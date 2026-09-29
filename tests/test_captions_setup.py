"""Where the transcriber's packages live, and how they get there.

The point of these: `--transcribe` has to work on a machine nobody has set up by hand, and
what decides that is which interpreter runs, which environment it falls back to, and what
`--install` puts in it.
"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location(
    "captions", os.path.join(HERE, "..", "player", "tools", "captions.py"))
captions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(captions)


class WhereThePackagesLive(unittest.TestCase):
    def test_named_by_the_environment_wins(self):
        self.assertEqual(captions.venv_dir({"REFRACT_CAPTIONS_VENV": "/opt/whisper"}), "/opt/whisper")
        self.assertTrue(captions.venv_dir({"REFRACT_CAPTIONS_VENV": "~/w"}).endswith("/w"),
                        "a ~ is expanded")

    def test_a_cache_directory_otherwise(self):
        where = captions.venv_dir({"HOME": "/Users/x"})
        self.assertTrue(where.startswith("/Users/x/"), "under the user's own home")
        self.assertTrue(where.endswith("captions-venv"))
        self.assertIn("Cache" if sys.platform == "darwin" else ".cache", where)

    def test_the_interpreter_inside_one(self):
        self.assertEqual(captions.venv_python("/opt/w"),
                         "/opt/w/Scripts/python.exe" if sys.platform == "win32" else "/opt/w/bin/python3")


class WhatIsMissing(unittest.TestCase):
    def test_both_steps_are_asked_about(self):
        none = captions.missing(finder=lambda name: None)
        self.assertEqual(len(none), 2, "a transcriber and an aligner")
        self.assertIn("whisperx (the aligner)", none)
        # find_spec raises for some names rather than returning None; that is "not there".
        def angry(name):
            raise ValueError(name)
        self.assertEqual(len(captions.missing(finder=angry)), 2)

    def test_either_transcriber_will_do(self):
        self.assertEqual(captions.missing(finder=lambda n: object() if n in ("whisper", "whisperx") else None), [])
        self.assertEqual(captions.missing(finder=lambda n: object() if n in ("faster_whisper", "whisperx") else None), [])
        self.assertEqual(captions.missing(finder=lambda n: object() if n == "whisper" else None),
                         ["whisperx (the aligner)"], "a transcriber alone is not enough")


class Installing(unittest.TestCase):
    def test_the_commands_build_then_fill_the_environment(self):
        commands = captions.install_commands("/tmp/v", python="/usr/bin/python3.12")
        self.assertEqual(commands[0], ["/usr/bin/python3.12", "-m", "venv", "/tmp/v"])
        for command in commands[1:]:
            self.assertEqual(command[0], captions.venv_python("/tmp/v"),
                             "everything after it runs inside the environment")
        self.assertIn("whisperx", commands[-1], "one package brings both steps")
        self.assertNotIn("--upgrade", commands[-1])
        self.assertIn("--upgrade", captions.install_commands("/tmp/v", upgrade=True)[-1])

    def test_the_environment_is_built_with_a_python_new_enough(self):
        # This interpreter, when it is new enough — which is the usual case.
        if sys.version_info >= (3, 10):
            self.assertEqual(captions.installer_python(), sys.executable)
        # Apple's 3.9 is what `python3` means on a Mac nobody has set up: look for another.
        old = (3, 9, 6)
        real = sys.version_info
        try:
            sys.version_info = old            # type: ignore[assignment]
            found = captions.installer_python(which=lambda n: "/opt/bin/" + n if n == "python3.12" else None)
            self.assertEqual(found, "/opt/bin/python3.12")
            self.assertIsNone(captions.installer_python(which=lambda n: None),
                              "and say so when there is none")
        finally:
            sys.version_info = real           # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
