import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
CORE = ROOT / "scripts" / "launch_testbed.sh"
WRAPPER = ROOT / "Launch-Hearth-Testbed.command"


class LocalLaptopLauncherTests(unittest.TestCase):
    def test_scripts_are_executable_and_parse_as_bash(self):
        self.assertTrue(os.access(CORE, os.X_OK))
        self.assertTrue(os.access(WRAPPER, os.X_OK))
        subprocess.run(["/bin/bash", "-n", str(CORE), str(WRAPPER)], check=True)

    def test_launcher_is_loopback_offline_and_brave_only(self):
        text = CORE.read_text()
        self.assertIn("http://127.0.0.1:4173", text)
        self.assertIn("http://127.0.0.1:8081", text)
        self.assertNotIn("0.0.0.0", text)
        self.assertIn("HF_HUB_OFFLINE=1", text)
        self.assertIn("TRANSFORMERS_OFFLINE=1", text)
        self.assertIn('open -a "Brave Browser"', text)
        self.assertNotIn('open -a "Google Chrome"', text)

    def test_password_is_read_silently_and_not_written(self):
        text = CORE.read_text()
        self.assertIn("read -r -s HEARTH_PASSWORD", text)
        self.assertIn("unset HEARTH_PASSWORD", text)
        self.assertNotIn("echo $HEARTH_PASSWORD", text)
        self.assertNotIn("HEARTH_PASSWORD >", text)

    def test_owned_processes_are_cleaned_up(self):
        text = CORE.read_text()
        self.assertIn("trap cleanup EXIT INT TERM HUP", text)
        self.assertIn('kill "$APP_PID"', text)
        self.assertIn('kill "$LLM_PID"', text)

    def test_launcher_check_mode_passes_on_build_machine(self):
        result = subprocess.run(
            ["/bin/bash", str(CORE), "--check"], cwd=ROOT, text=True,
            capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("prerequisites are present", result.stdout)


if __name__ == "__main__":
    unittest.main()
