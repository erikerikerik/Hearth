"""Tests for the installer-facing pieces: data dir, first-run password, swappable look layer, model downloader."""

import hashlib
import http.server
import json
import os
import stat
import threading
import urllib.parse
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


class _HubHandler(http.server.BaseHTTPRequestHandler):
    """Serves /<org>/<name>/resolve/<rev>/<path> from an in-memory dict; honours Range unless told not to."""
    files = {}
    ignore_range = False
    redirect_to = None
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).requests.append(self.path)
        if type(self).redirect_to:
            self.send_response(302)
            self.send_header("Location", type(self).redirect_to)
            self.end_headers()
            return
        key = self.path.split("/resolve/", 1)[-1].split("/", 1)[-1]
        data = type(self).files.get(urllib.parse.unquote(key))
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
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


def git_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


REV1 = "1" * 40
REV2 = "2" * 40


class ModelManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HubHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.hub = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.weights = os.urandom(300_000)
        self.config = b'{"synthetic": true}'
        _HubHandler.files = {"weights.safetensors": self.weights, "config.json": self.config,
                             "voices/af_test.safetensors": b"v" * 1000}
        _HubHandler.ignore_range = False
        _HubHandler.redirect_to = None
        _HubHandler.requests = []

    def tearDown(self):
        self.temp.cleanup()

    def snap(self, **over):
        base = {"id": "tts", "role": "tts", "repo": "synthetic-org/Kokoro-82M-test", "revision": REV1, "min_ram_gb": 8,
                "files": [
                    {"path": "config.json", "size": len(self.config), "git_sha1": git_sha1(self.config)},
                    {"path": "voices/af_test.safetensors", "size": 1000, "sha256": hashlib.sha256(b"v" * 1000).hexdigest()},
                    {"path": "weights.safetensors", "size": len(self.weights), "sha256": hashlib.sha256(self.weights).hexdigest()},
                ]}
        base.update(over)
        return base

    def manifest(self, snaps, default="balanced"):
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"schema": 2, "hub": self.hub, "default_profile": default, "snapshots": snaps}))
        return path

    def llm(self, profile, ram):
        return self.snap(id="llm-" + profile, role="llm", profile=profile, min_ram_gb=ram, repo="synthetic-org/llm-" + profile)

    def test_snapshot_downloads_verifies_and_records(self):
        done = model_manager.ensure(self.manifest([self.snap()]), self.data, accept=True, ram_gb=16)
        self.assertEqual(done, ["tts"])
        folder = model_manager.installed_path(self.data / "models", "tts")
        self.assertEqual((folder / "weights.safetensors").read_bytes(), self.weights)
        self.assertEqual((folder / "voices" / "af_test.safetensors").read_bytes(), b"v" * 1000)
        # The folder name keeps the repo name: mlx-audio infers Kokoro from it (its config has no model_type).
        self.assertIn("kokoro", folder.name.lower().split("-"))
        self.assertFalse(list((self.data / "models").rglob("*.part")))
        self.assertFalse(list((self.data / "models").rglob("*.partial")))
        self.assertEqual(stat.S_IMODE(os.stat(self.data / "models").st_mode), 0o700)
        self.assertEqual(json.loads((self.data / "models" / "progress.json").read_text())["state"], "done")
        self.assertTrue(all("/resolve/%s/" % REV1 in r for r in _HubHandler.requests))

    def test_interrupted_download_resumes(self):
        snap = self.snap()
        staging = model_manager._staging(self.data / "models", snap)
        staging.mkdir(parents=True)
        (staging / "weights.safetensors.part").write_bytes(self.weights[:100_000])
        model_manager.install_snapshot(self.hub, snap, self.data / "models")
        self.assertEqual((model_manager.snapshot_dir(self.data / "models", snap) / "weights.safetensors").read_bytes(), self.weights)
        self.assertTrue(any(r.endswith("weights.safetensors") for r in _HubHandler.requests))

    def test_server_ignoring_range_restarts_cleanly(self):
        _HubHandler.ignore_range = True
        snap = self.snap()
        staging = model_manager._staging(self.data / "models", snap)
        staging.mkdir(parents=True)
        (staging / "weights.safetensors.part").write_bytes(b"junk" * 1000)
        model_manager.install_snapshot(self.hub, snap, self.data / "models")
        self.assertEqual((model_manager.snapshot_dir(self.data / "models", snap) / "weights.safetensors").read_bytes(), self.weights)

    def test_sha256_mismatch_discards_and_nothing_is_installed(self):
        snap = self.snap()
        snap["files"][2]["sha256"] = "a" * 64
        with self.assertRaises(model_manager.ModelError):
            model_manager.ensure(self.manifest([snap]), self.data, accept=True, ram_gb=16)
        models = self.data / "models"
        self.assertFalse(model_manager.snapshot_dir(models, snap).exists())
        self.assertFalse(list(models.rglob("weights.safetensors*")))
        self.assertIsNone(model_manager.installed_path(models, "tts"))
        self.assertEqual(json.loads((models / "progress.json").read_text())["state"], "error")

    def test_small_files_are_checked_by_git_blob_hash(self):
        _HubHandler.files["config.json"] = b'{"synthetic": fals}'   # same length, different bytes
        with self.assertRaises(model_manager.ModelError):
            model_manager.ensure(self.manifest([self.snap()]), self.data, accept=True, ram_gb=16)

    def test_unpinned_and_unconsented_downloads_are_refused(self):
        with self.assertRaises(model_manager.ModelError):
            model_manager.ensure(self.manifest([self.snap(revision="main")]), self.data, accept=True, ram_gb=16)
        with self.assertRaises(model_manager.ModelError):
            model_manager.ensure(self.manifest([self.snap()]), self.data, accept=False, ram_gb=16)
        self.assertFalse((self.data / "models").exists())
        self.assertEqual(_HubHandler.requests, [])

    def test_remote_http_and_downgrading_redirects_are_refused(self):
        with self.assertRaises(model_manager.ModelError):
            model_manager.install_snapshot("http://example.com", self.snap(), self.data / "models")
        _HubHandler.redirect_to = "http://example.com/weights.safetensors"
        with self.assertRaises(model_manager.ModelError):
            model_manager.install_snapshot(self.hub, self.snap(), self.data / "models")

    def test_profile_follows_ram_like_install_models_sh(self):
        manifest = json.loads(self.manifest([self.llm("fast", 16), self.llm("balanced", 24), self.llm("large", 32), self.snap()]).read_text())
        pick = lambda ram, profile="": model_manager.choose(manifest, "llm", ram, profile)["id"]
        self.assertEqual(pick(18), "llm-fast")
        self.assertEqual(pick(24), "llm-balanced")
        self.assertEqual(pick(36), "llm-balanced")      # default profile is the cap below 48 GB
        self.assertEqual(pick(64), "llm-large")
        self.assertEqual(pick(18, "balanced"), "llm-balanced")
        with self.assertRaises(model_manager.ModelError):
            pick(8)
        self.assertEqual([s["id"] for s in model_manager.selection(manifest, 24)], ["llm-balanced", "tts"])

    def test_unsafe_manifests_are_rejected(self):
        for bad in ("../evil", "/etc/passwd", ".hidden/x", "a/../../b", "a\\b"):
            snap = self.snap()
            snap["files"][0]["path"] = bad
            with self.assertRaises(model_manager.ModelError, msg=bad):
                model_manager.load_manifest(self.manifest([snap]))
        for repo in ("../x", "org/name/extra", "org"):
            with self.assertRaises(model_manager.ModelError, msg=repo):
                model_manager.load_manifest(self.manifest([self.snap(repo=repo)]))
        snap = self.snap()
        snap["files"][0]["sha256"] = "b" * 64            # both hashes present
        with self.assertRaises(model_manager.ModelError):
            model_manager.load_manifest(self.manifest([snap]))
        path = self.root / "old.json"
        path.write_text(json.dumps({"models": []}))
        with self.assertRaises(model_manager.ModelError):
            model_manager.load_manifest(path)

    def test_pending_counts_missing_bytes_minus_partial_progress(self):
        path = self.manifest([self.snap()])
        total = len(self.config) + 1000 + len(self.weights)
        self.assertEqual(model_manager.pending_bytes(path, self.data, 16), total)
        staging = model_manager._staging(self.data / "models", self.snap())
        staging.mkdir(parents=True)
        (staging / "weights.safetensors.part").write_bytes(self.weights[:1000])
        self.assertEqual(model_manager.pending_bytes(path, self.data, 16), total - 1000)
        model_manager.ensure(path, self.data, accept=True, ram_gb=16)
        self.assertEqual(model_manager.pending_bytes(path, self.data, 16), 0)

    def test_new_revision_replaces_and_prunes_the_old_one(self):
        model_manager.ensure(self.manifest([self.snap()]), self.data, accept=True, ram_gb=16)
        old = model_manager.installed_path(self.data / "models", "tts")
        model_manager.ensure(self.manifest([self.snap(revision=REV2)]), self.data, accept=True, ram_gb=16)
        new = model_manager.installed_path(self.data / "models", "tts")
        self.assertNotEqual(old, new)
        self.assertFalse(old.exists())
        self.assertTrue(new.name.endswith(REV2))

    def test_verify_detects_tampering(self):
        path = self.manifest([self.snap()])
        model_manager.ensure(path, self.data, accept=True, ram_gb=16)
        self.assertEqual(model_manager.verify(path, self.data), [])
        target = model_manager.installed_path(self.data / "models", "tts") / "weights.safetensors"
        data = bytearray(target.read_bytes())
        data[10] ^= 1
        target.write_bytes(bytes(data))
        self.assertEqual(len(model_manager.verify(path, self.data)), 1)

    def test_installed_path_cannot_escape_the_snapshots_folder(self):
        models = self.data / "models"
        (models / "snapshots").mkdir(parents=True)
        (self.root / "elsewhere").mkdir()
        (models / "installed.json").write_text(json.dumps(
            {"schema": 2, "roles": {"llm": {"path": "../../elsewhere"}, "tts": {"path": "snapshots/x.partial"}}}))
        (models / "snapshots" / "x.partial").mkdir()
        self.assertIsNone(model_manager.installed_path(models, "llm"))
        self.assertIsNone(model_manager.installed_path(models, "tts"))
        from app.local_models import installed_models
        self.assertEqual(installed_models(self.data), {})

    def test_only_one_download_at_a_time(self):
        import fcntl
        models = self.data / "models"
        models.mkdir(parents=True)
        self.assertFalse(model_manager.download_running(models))
        with open(models / ".lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertTrue(model_manager.download_running(models))
            with self.assertRaises(model_manager.ModelError):
                model_manager.ensure(self.manifest([self.snap()]), self.data, accept=True, ram_gb=16)
        self.assertFalse(model_manager.download_running(models))


class ShippedManifestTests(unittest.TestCase):
    """The manifest that build.sh ships: fully pinned and consistent with config/models.json."""

    def setUp(self):
        root = Path(__file__).parent
        self.manifest = model_manager.load_manifest(root / "models" / "manifest.json")
        self.config = json.loads((root / "config" / "models.json").read_text())
        self.by_id = {s["id"]: s for s in self.manifest["snapshots"]}

    def test_every_snapshot_is_pinned_with_real_files(self):
        self.assertTrue(self.manifest["hub"].startswith("https://"))
        for snap in self.manifest["snapshots"]:
            self.assertTrue(model_manager.is_pinned(snap), snap["id"])
            paths = {f["path"] for f in snap["files"]}
            self.assertIn("config.json", paths, snap["id"])
            self.assertTrue(any(p.endswith(".safetensors") for p in paths), snap["id"])
            self.assertFalse(any(p.endswith((".md", ".pt", ".wav")) for p in paths), snap["id"])

    def test_manifest_matches_config(self):
        self.assertEqual(self.manifest["default_profile"], self.config["default_profile"])
        for name, profile in self.config["profiles"].items():
            snap = self.by_id["llm-" + name]
            self.assertEqual((snap["repo"], snap["min_ram_gb"], snap["profile"]), (profile["mlx"], profile["min_ram_gb"], name))
        self.assertEqual(self.by_id["stt"]["repo"], self.config["stt"]["mlx"])
        self.assertEqual(self.by_id["tts"]["repo"], self.config["tts"]["mlx"])

    def test_every_configured_voice_is_downloaded(self):
        paths = {f["path"] for f in self.by_id["tts"]["files"]}
        for option in self.config["voices"]["options"].values():
            for voice in option["kokoro_voice"].split(","):
                self.assertIn("voices/%s.safetensors" % voice, paths)


if __name__ == "__main__":
    unittest.main()
