"""Tests for the installer-facing pieces: data dir, first-run password, swappable look layer, model downloader."""

import hashlib
import http.server
import json
import os
import stat
import threading
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.main import configured_password_hash, create_app
from tools import model_manager, set_password, ui_manager

PASSWORD = "synthetic-test-passphrase"


def make_bundle(path: Path, name="warm", version="2.0.0", contract="1.0", index="<title>NEWLOOK</title>", extra=None):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("ui.json", json.dumps({"name": name, "version": version, "contract": contract}))
        zf.writestr("index.html", index)
        for key, value in (extra or {}).items():
            zf.writestr(key, value)
    return path


class FirstRunPasswordTests(unittest.TestCase):
    def test_auth_file_is_private_and_used(self):
        with TemporaryDirectory() as d:
            target = set_password.write_auth(Path(d) / "data", PASSWORD)
            self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(target.parent).st_mode), 0o700)
            self.assertNotIn(PASSWORD, target.read_text())
            hashed = configured_password_hash(Path(d) / "data")
            self.assertTrue(PasswordHasher().verify(hashed, PASSWORD))

    def test_short_password_and_overwrite_are_refused(self):
        with TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                set_password.write_auth(Path(d), "short")
            set_password.write_auth(Path(d), PASSWORD)
            with self.assertRaises(SystemExit):
                set_password.write_auth(Path(d), "another-long-password")
            set_password.write_auth(Path(d), "another-long-password", force=True)

    def test_missing_password_fails_closed(self):
        with TemporaryDirectory() as d:
            saved = {k: os.environ.pop(k, None) for k in ("HEARTH_PASSWORD_HASH", "HEARTH_DEV_PASSWORD")}
            try:
                with self.assertRaises(RuntimeError):
                    configured_password_hash(Path(d))
            finally:
                for key, value in saved.items():
                    if value is not None:
                        os.environ[key] = value


class LookLayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.data = Path(self.temp.name) / "data"
        set_password.write_auth(self.data, PASSWORD)
        self.client = TestClient(create_app(cookie_secure=False, data_dir=self.data, dev_tools=False, voice_engine=None), base_url="http://localhost")
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self):
        return self.client.post("/api/auth/login", json={"password": PASSWORD}).json()["csrf_token"]

    def test_default_is_bundled_look(self):
        self.assertEqual(self.client.get("/healthz").json()["ui"]["source"], "bundled")
        self.assertIn("Hearth", self.client.get("/").text)

    def test_look_update_swaps_ui_but_keeps_history_and_needs_no_restart(self):
        csrf = self.login()
        note = self.client.post("/api/notes", json={"text": "HISTORY_SENTINEL", "author": "E"}, headers={"X-CSRF-Token": csrf}).json()
        bundle = make_bundle(Path(self.temp.name) / "warm.zip")
        ui_manager.install(self.data, str(bundle))
        page = self.client.get("/")
        self.assertIn("NEWLOOK", page.text)
        self.assertEqual(page.headers["cache-control"], "no-cache")
        health = self.client.get("/healthz").json()["ui"]
        self.assertEqual((health["source"], health["name"], health["version"]), ("installed", "warm", "2.0.0"))
        notes = self.client.get("/api/workshop").json()["notes"]
        self.assertIn(note["id"], [n["id"] for n in notes])
        self.assertIn("HISTORY_SENTINEL", json.dumps(notes))

    def test_rollback_and_reset_restore_previous_looks(self):
        ui_manager.install(self.data, str(make_bundle(Path(self.temp.name) / "a.zip", version="1.0.0", index="<title>LOOK_A</title>")))
        ui_manager.install(self.data, str(make_bundle(Path(self.temp.name) / "b.zip", version="2.0.0", index="<title>LOOK_B</title>")))
        self.assertIn("LOOK_B", self.client.get("/").text)
        ui_manager.rollback(self.data)
        self.assertIn("LOOK_A", self.client.get("/").text)
        ui_manager.reset(self.data)
        self.assertEqual(self.client.get("/healthz").json()["ui"]["source"], "bundled")

    def test_broken_installed_look_falls_back_to_bundled(self):
        ui_manager.install(self.data, str(make_bundle(Path(self.temp.name) / "a.zip")))
        (self.data / "ui" / "versions" / "warm-2.0.0" / "index.html").unlink()
        self.assertEqual(self.client.get("/healthz").json()["ui"]["source"], "bundled")
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_incompatible_or_malicious_bundles_are_rejected(self):
        with self.assertRaises(ui_manager.UiError):
            ui_manager.install(self.data, str(make_bundle(Path(self.temp.name) / "v2.zip", contract="2.0")))
        with self.assertRaises(ui_manager.UiError):
            ui_manager.install(self.data, str(make_bundle(Path(self.temp.name) / "slip.zip", extra={"../escape.txt": "x"})))
        with self.assertRaises(ui_manager.UiError):
            ui_manager.install(self.data, str(make_bundle(Path(self.temp.name) / "name.zip", name="../bad")))
        good = make_bundle(Path(self.temp.name) / "ok.zip")
        with self.assertRaises(ui_manager.UiError):
            ui_manager.install(self.data, str(good), sha256="0" * 64)
        self.assertEqual(ui_manager.status(self.data)["current"], "bundled-default")
        self.assertFalse((Path(self.temp.name) / "escape.txt").exists())

    def test_remote_bundles_need_https_and_checksum(self):
        with self.assertRaises(ui_manager.UiError):
            ui_manager.install(self.data, "http://example.com/look.zip", sha256="0" * 64)
        with self.assertRaises(ui_manager.UiError):
            ui_manager.install(self.data, "https://example.com/look.zip")

    def test_path_traversal_cannot_reach_data_files(self):
        self.assertEqual(self.client.get("/%2e%2e/auth.json").status_code, 404)
        self.assertEqual(self.client.get("/%2e%2e/%2e%2e/%2e%2e/etc/passwd").status_code, 404)
        self.assertNotIn("password_hash", self.client.get("/auth.json").text)


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    payload = b""

    def log_message(self, *args):
        pass

    def do_GET(self):
        data = type(self).payload
        start = 0
        header = self.headers.get("Range")
        if header and header.startswith("bytes=") and not type(self).ignore_range:
            start = int(header[6:].split("-")[0])
            self.send_response(206)
        else:
            self.send_response(200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    ignore_range = False


class ModelManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/model.bin" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = os.urandom(300_000)
        _RangeHandler.payload = self.payload
        _RangeHandler.ignore_range = False
        self.sha = hashlib.sha256(self.payload).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def item(self, **over):
        base = {"id": "m1", "role": "llm", "filename": "m1.bin", "url": self.url, "sha256": self.sha,
                "size_bytes": len(self.payload), "min_ram_gb": 8}
        base.update(over)
        return base

    def manifest(self, items):
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"models": items}))
        return path

    def test_download_verifies_and_records(self):
        path = self.manifest([self.item()])
        done = model_manager.ensure(path, self.root / "data", ["llm"], accept=True, ram_gb=16)
        self.assertEqual(done, ["m1"])
        self.assertEqual((self.root / "data" / "models" / "m1.bin").read_bytes(), self.payload)
        self.assertFalse((self.root / "data" / "models" / "m1.bin.part").exists())
        installed = json.loads((self.root / "data" / "models" / "installed.json").read_text())
        self.assertEqual(installed["llm"]["id"], "m1")

    def test_interrupted_download_resumes(self):
        models = self.root / "data" / "models"
        models.mkdir(parents=True)
        (models / "m1.bin.part").write_bytes(self.payload[:100_000])
        model_manager.download(self.item(), models)
        self.assertEqual((models / "m1.bin").read_bytes(), self.payload)

    def test_server_ignoring_range_restarts_cleanly(self):
        _RangeHandler.ignore_range = True
        models = self.root / "data" / "models"
        models.mkdir(parents=True)
        (models / "m1.bin.part").write_bytes(b"junk" * 1000)
        model_manager.download(self.item(), models)
        self.assertEqual((models / "m1.bin").read_bytes(), self.payload)

    def test_checksum_mismatch_discards_partial(self):
        models = self.root / "data" / "models"
        with self.assertRaises(model_manager.ModelError):
            model_manager.download(self.item(sha256="a" * 64), models)
        self.assertEqual(list(models.glob("m1.bin*")), [])

    def test_unpinned_and_unconsented_downloads_are_refused(self):
        path = self.manifest([self.item(sha256="PLACEHOLDER")])
        with self.assertRaises(model_manager.ModelError):
            model_manager.ensure(path, self.root / "data", ["llm"], accept=True, ram_gb=16)
        path = self.manifest([self.item()])
        with self.assertRaises(model_manager.ModelError):
            model_manager.ensure(path, self.root / "data", ["llm"], accept=False, ram_gb=16)
        self.assertFalse((self.root / "data" / "models").exists())

    def test_remote_http_is_refused(self):
        with self.assertRaises(model_manager.ModelError):
            model_manager.download(self.item(url="http://example.com/m.bin"), self.root / "models")

    def test_tier_follows_ram_and_largest_fit_wins(self):
        models = [self.item(id="fast", min_ram_gb=16), self.item(id="big", min_ram_gb=24, filename="big.bin"),
                  self.item(id="huge", min_ram_gb=64, filename="huge.bin")]
        self.assertEqual(model_manager.choose(models, "llm", 24)["id"], "big")
        self.assertEqual(model_manager.choose(models, "llm", 18)["id"], "fast")
        with self.assertRaises(model_manager.ModelError):
            model_manager.choose(models, "llm", 8)

    def test_unsafe_manifest_filename_is_rejected(self):
        with self.assertRaises(model_manager.ModelError):
            model_manager.load_manifest(self.manifest([self.item(filename="../evil")]))

    def test_pending_reports_only_missing_pinned_models(self):
        path = self.manifest([self.item(), self.item(id="placeholder", role="stt", filename="s.bin", sha256="PLACEHOLDER")])
        data = self.root / "data"
        self.assertEqual(model_manager.pending_bytes(path, data, 16), len(self.payload))
        model_manager.ensure(path, data, ["llm"], accept=True, ram_gb=16)
        self.assertEqual(model_manager.pending_bytes(path, data, 16), 0)

    def test_shipped_manifest_is_all_unpinned_until_filled_in(self):
        shipped = model_manager.load_manifest(Path(__file__).parent / "models" / "manifest.json")
        self.assertTrue(shipped and not any(model_manager.is_pinned(m) for m in shipped))


if __name__ == "__main__":
    unittest.main()
