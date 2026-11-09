"""P008: the installed app uses verified local models, supervises its model server and ships a pinned runtime.

Static checks run everywhere. Building, signing and notarizing the disk image need a Mac
(installer/build.sh, which runs its own self-checks inside the bundle before and after signing).
"""
import json
import os
import re
import subprocess
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.companion import load_llm_settings
from app.local_models import installed_models
from app.voice import MlxVoiceEngine, use_bundled_espeak

ROOT = Path(__file__).parent
INSTALLER = ROOT / "installer"
CONFIG = json.loads((ROOT / "config" / "models.json").read_text())


def fake_install(data: Path, roles=("llm", "stt", "tts")) -> dict:
    models = data / "models"
    out = {}
    entries = {}
    for role in roles:
        rel = "snapshots/synthetic-org--%s--%s" % (role, "3" * 40)
        (models / rel).mkdir(parents=True)
        entries[role] = {"id": role, "path": rel, "profile": "balanced" if role == "llm" else None}
        out[role] = str((models / rel).resolve())
    (models / "installed.json").write_text(json.dumps({"schema": 2, "roles": entries}))
    return out


class LocalModelWiringTests(unittest.TestCase):
    def test_installed_app_uses_verified_local_folders(self):
        with TemporaryDirectory() as d:
            paths = fake_install(Path(d))
            self.assertEqual({k: v["path"] for k, v in installed_models(Path(d)).items()}, paths)
            settings = load_llm_settings(ROOT, Path(d))
            self.assertEqual(settings.model, paths["llm"])             # the exact --model given to mlx_lm.server
            self.assertEqual(settings.base_url, CONFIG["endpoint"])
            engine = MlxVoiceEngine(data_dir=Path(d))                  # constructing does not import MLX
            self.assertEqual(engine.config["stt"]["mlx"], paths["stt"])
            self.assertEqual(engine.config["tts"]["mlx"], paths["tts"])

    def test_developer_tree_keeps_hub_names(self):
        with TemporaryDirectory() as d:
            self.assertEqual(installed_models(Path(d)), {})
            self.assertEqual(installed_models(None), {})
            engine = MlxVoiceEngine(data_dir=Path(d))
            self.assertEqual(engine.config["stt"]["mlx"], CONFIG["stt"]["mlx"])
            self.assertIn(load_llm_settings(ROOT, Path(d)).model, {p["mlx"] for p in CONFIG["profiles"].values()})

    def test_partial_install_only_overrides_what_is_complete(self):
        with TemporaryDirectory() as d:
            paths = fake_install(Path(d), roles=("tts",))
            engine = MlxVoiceEngine(data_dir=Path(d))
            self.assertEqual(engine.config["tts"]["mlx"], paths["tts"])
            self.assertEqual(engine.config["stt"]["mlx"], CONFIG["stt"]["mlx"])

    def test_bundled_espeak_is_used_unless_overridden(self):
        saved = {k: os.environ.pop(k, None) for k in ("PHONEMIZER_ESPEAK_LIBRARY", "PHONEMIZER_ESPEAK_DATA_PATH")}
        with TemporaryDirectory() as d:
            lib = Path(d) / "libespeak-ng.dylib"
            lib.write_bytes(b"synthetic")
            sys.modules["espeakng_loader"] = types.SimpleNamespace(get_library_path=lambda: str(lib), get_data_path=lambda: d)
            try:
                self.assertTrue(use_bundled_espeak())
                self.assertEqual(os.environ["PHONEMIZER_ESPEAK_LIBRARY"], str(lib))
                self.assertFalse(use_bundled_espeak())                 # an explicit setting wins
            finally:
                sys.modules.pop("espeakng_loader", None)
                for key in ("PHONEMIZER_ESPEAK_LIBRARY", "PHONEMIZER_ESPEAK_DATA_PATH"):
                    os.environ.pop(key, None)
                for key, value in saved.items():
                    if value is not None:
                        os.environ[key] = value

    def test_companion_process_never_imports_the_downloader(self):
        for path in (ROOT / "app").glob("*.py"):
            text = path.read_text()
            self.assertNotRegex(text, r"(?m)^\s*(from tools\b|import tools\b|from \S*model_manager|import \S*model_manager)", path.name)
            self.assertNotRegex(text, r"snapshot_download\(|hf_hub_download\(", path.name)


class LaunchAgentTests(unittest.TestCase):
    def test_model_server_agent_is_loopback_offline_and_supervised(self):
        text = (INSTALLER / "launchd" / "com.hearth.llm.plist.template").read_text()
        args = re.findall(r"<string>([^<]*)</string>", text.split("<key>ProgramArguments</key>", 1)[1].split("</array>", 1)[0])
        self.assertEqual(args[1:3], ["-m", "mlx_lm.server"])
        self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
        self.assertEqual(args[args.index("--model") + 1], "@MODEL@")
        self.assertIn("<key>KeepAlive</key><true/>", text)
        for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            self.assertRegex(text, r"<key>%s</key><string>1</string>" % key)
        self.assertNotIn("0.0.0.0", text)

    def test_model_port_matches_the_companion_endpoint(self):
        launcher = (INSTALLER / "Hearth-launcher.sh").read_text()
        port = re.search(r"^LLM_PORT=(\d+)$", launcher, re.M).group(1)
        self.assertEqual(CONFIG["endpoint"], "http://127.0.0.1:%s/v1" % port)

    def test_companion_agent_enables_model_and_voice_offline(self):
        text = (INSTALLER / "launchd" / "com.hearth.local.plist.template").read_text()
        for key in ("HEARTH_LLM_ENABLED", "HEARTH_VOICE_ENABLED", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            self.assertRegex(text, r"<key>%s</key><string>1</string>" % key)

    def test_launcher_parses_and_keeps_its_boundaries(self):
        path = INSTALLER / "Hearth-launcher.sh"
        self.assertEqual(subprocess.run(["bash", "-n", str(path)]).returncode, 0)
        text = path.read_text()
        self.assertIn('mm path llm', text)                              # model server only after verification
        self.assertIn('mm ensure --accept', text)                       # downloads only after consent
        self.assertIn('"Download"', text)
        self.assertIn('remove_agent "$LLM_LABEL"', text)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", text)
        self.assertIn("<string>$APP_BUNDLE</string>", text)        # Dock gets Hearth.app, not Hearth.app/Contents
        self.assertNotRegex(text, r"(?i)google chrome|safari|firefox|0\.0\.0\.0")
        for script in ("uninstall.sh", "build.sh", "lock.sh", "scripts/postinstall"):
            self.assertEqual(subprocess.run(["bash", "-n", str(INSTALLER / script)]).returncode, 0, script)
        self.assertIn("com.hearth.llm", (INSTALLER / "uninstall.sh").read_text())


class BundledRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.build = (INSTALLER / "build.sh").read_text()
        self.lock = (INSTALLER / "requirements-app.lock").read_text()

    def test_python_runtime_is_pinned_by_hash(self):
        self.assertRegex(self.build, r'PBS_URL="https://github\.com/astral-sh/python-build-standalone/releases/download/\d+/cpython-3\.12\.')
        self.assertRegex(self.build, r'PBS_SHA256="[0-9a-f]{64}"')
        self.assertNotIn("releases/latest", self.build)

    def test_packages_come_only_from_the_hashed_lock(self):
        self.assertIn("--require-hashes --only-binary :all: --no-deps -r \"$HERE/requirements-app.lock\"", self.build)
        self.assertNotRegex(self.build, r"pip install [^\n]*requirements\.txt")
        blocks = [b for b in re.split(r"\n(?=[A-Za-z0-9])", self.lock) if b.strip() and not b.startswith("--")]
        self.assertGreater(len(blocks), 20)
        for block in blocks:
            self.assertRegex(block, r"--hash=sha256:[0-9a-f]{64}", block.splitlines()[0])

    def test_lock_matches_config_and_has_no_pytorch(self):
        for name, version in CONFIG["packages"].items():
            if name == "mlx-whisper":                       # developer benchmarks only; the app uses mlx-audio for speech
                continue
            self.assertIn("\n%s==%s " % (name, version), "\n" + self.lock)
        for pinned in re.findall(r"^([a-z0-9][a-z0-9._-]*)==([^\s]+)", (ROOT / "requirements.txt").read_text(), re.M):
            self.assertIn("\n%s==%s " % pinned, "\n" + self.lock)
        self.assertNotRegex(self.lock, r"(?m)^(torch|spacy-curated-transformers)\b")
        for needed in ("en-core-web-sm @ ", "espeakng-loader==", "misaki==", "spacy==", "mlx-metal=="):
            self.assertIn(needed, self.lock)

    def test_bundle_ships_config_both_agents_and_a_signed_self_check(self):
        self.assertIn('"$SRC/config"', self.build)
        self.assertIn("com.hearth.llm.plist.template", self.build)
        self.assertIn('pin_models.py" --check', self.build)
        self.assertIn('selfcheck "signed, hardened runtime"', self.build)
        self.assertIn("mx.metal.is_available()", self.build)
        self.assertIn('spacy.load("en_core_web_sm")', self.build)
        # bytecode is compiled before signing, so nothing writes into the sealed bundle later
        self.assertLess(self.build.index("compileall"), self.build.index('echo "==> Signing'))
        self.assertNotIn("scripts/pin_models.py\" \"$RES", self.build)   # developer tool is not shipped

    def test_minimum_macos_matches_mlx_wheels(self):
        plist = (INSTALLER / "Info.plist").read_text()
        self.assertIn("<key>LSMinimumSystemVersion</key><string>14.0</string>", plist)
        self.assertIn("MACOSX_DEPLOYMENT_TARGET=14.0", (INSTALLER / "lock.sh").read_text())


if __name__ == "__main__":
    unittest.main()
