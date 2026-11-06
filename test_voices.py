import unittest
from app.voices import available_voices, resolve_voice


class VoiceTests(unittest.TestCase):
    def test_default_is_heart_nicole_blend(self):
        v = resolve_voice(None)
        self.assertEqual(v["kokoro_voice"], "af_heart,af_nicole")
        self.assertEqual(v["lang_code"], "a")

    def test_unknown_falls_back_to_default(self):
        self.assertEqual(resolve_voice("ember")["id"], "willow")

    def test_george_is_selectable(self):
        v = resolve_voice("moss")
        self.assertEqual((v["kokoro_voice"], v["lang_code"]), ("bm_george", "b"))

    def test_listing(self):
        self.assertEqual([x["id"] for x in available_voices()], ["willow", "moss"])


if __name__ == "__main__":
    unittest.main()
