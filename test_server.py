import re
import collections
import unittest
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.main import create_app


ROOT = Path(__file__).parent


def node_executable():
    discovered = shutil.which("node")
    if discovered:
        return discovered
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node")
    return str(bundled) if bundled.is_file() else None


def browser_acceptance_available():
    playwright = Path("/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/playwright")
    brave = Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
    return bool(node_executable() and playwright.is_dir() and brave.is_file())


class HearthServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.client = TestClient(create_app(
            password_hash=PasswordHasher().hash("synthetic-static-test"),
            cookie_secure=False,
            db_path=Path(cls.temp.name) / "static.sqlite3",
            dev_tools=True,
            llm_enabled=False,
            voice_engine=None,
        ), base_url="http://localhost")
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp.cleanup()

    def test_health_is_explicitly_non_production(self):
        data = self.client.get("/healthz").json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["build_id"], "1.3.0-rc1+p009")
        self.assertEqual(data["patch_level"], 9)
        self.assertFalse(data["personal_use_ready"])
        self.assertEqual(data["local_ai"], "disabled")
        self.assertEqual(data["persistence"], "sqlite-synthetic")

    def test_security_headers(self):
        response = self.client.get("/")
        headers = response.headers
        body = response.text
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("Hearth and Workshop", body)

    def test_script_csp_has_no_unsafe_inline_and_hashes_the_inline_script(self):
        import base64, hashlib
        csp = self.client.get("/").headers["Content-Security-Policy"]
        script_src = [part for part in csp.split(";") if part.strip().startswith("script-src")][0]
        self.assertNotIn("unsafe-inline", script_src)
        html = (ROOT / "dist" / "index.html").read_text(encoding="utf-8")
        bodies = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
        self.assertGreaterEqual(len(bodies), 1)
        for body in bodies:
            digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
            self.assertIn("'sha256-" + digest + "'", script_src)

    def test_no_remote_runtime_assets(self):
        html = (ROOT / "dist" / "index.html").read_text(encoding="utf-8")
        remote_asset = re.compile(r'''(?:src|href)=["']https?://''', re.IGNORECASE)
        self.assertIsNone(remote_asset.search(html))
        self.assertNotIn("@font-face", html)
        self.assertNotIn("fonts.css", html)
        self.assertNotIn("localStorage", html)
        self.assertNotIn("sessionStorage", html)
        self.assertNotIn("indexedDB", html)

    def test_static_document_has_no_duplicate_literal_ids(self):
        html = (ROOT / "dist" / "index.html").read_text(encoding="utf-8")
        literal_ids = re.findall(r'\bid="([A-Za-z][A-Za-z0-9_-]*)"', html)
        duplicates = [key for key, count in collections.Counter(literal_ids).items() if count > 1]
        self.assertEqual(duplicates, [])

    def test_orb_is_runtime_selected_and_shell_is_modular(self):
        selector = self.client.get("/orb/active-renderer.json")
        self.assertEqual(selector.status_code, 200)
        self.assertEqual(selector.json()["renderer"], "filament-v1@1")
        self.assertEqual(self.client.get("/shell/realtime.js").status_code, 200)
        self.assertEqual(self.client.get("/shell/audio-bands.js").status_code, 200)
        html = (ROOT / "dist" / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="/shell/bootstrap.js"', html)
        self.assertIn('src="/shell/audio-bootstrap.js"', html)
        self.assertIn('src="/orb/bootstrap.js"', html)

    def test_release_manifest_cannot_claim_personal_readiness(self):
        manifest = self.client.get("/release.json").json()
        self.assertEqual(manifest["version"], "1.3.0-rc1")
        self.assertFalse(manifest["personal_use_ready"])
        self.assertIn("reviewed-safety-policy", manifest["blocking_gates"])

    def test_unmeasured_privacy_claims_are_hidden(self):
        html = (ROOT / "dist" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="egressRow" hidden', html)
        self.assertIn('id="backupRow" hidden', html)

    def test_untrusted_subtitle_and_memory_text_are_not_inserted_as_html(self):
        html = (ROOT / "dist" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("'+m.text+'", html)
        self.assertNotIn("capEl.innerHTML=shown", html)
        self.assertIn("s.textContent=w", html)

    def test_unknown_api_is_not_silently_accepted(self):
        self.assertEqual(self.client.get("/api/memories").status_code, 404)

    @unittest.skipUnless(node_executable(), "Node is required for the JavaScript contract suites")
    def test_javascript_contract_suites(self):
        result = subprocess.run(
            [node_executable(), "--test", "tests/orb_contract.test.mjs", "tests/shell_contract.test.mjs"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(browser_acceptance_available(), "Bundled Playwright and Brave are required")
    def test_browser_acceptance(self):
        result = subprocess.run(
            [node_executable(), "tests/browser_acceptance.mjs"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

