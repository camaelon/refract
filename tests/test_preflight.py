"""What the machine needs, and whether it says so usefully.

This is the code somebody meets when nothing works yet, so what is tested is the reporting:
that a missing thing is reported as missing, that an optional thing does not read as a
failure, and that every failure carries something to type.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from refractkit import preflight


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Checks(unittest.TestCase):
    def test_this_checkout_is_usable(self):
        # The repository under test has its tools; if this fails, the report says why.
        checks = preflight.check(REPO)
        self.assertEqual(preflight.blocking(checks), [],
                         "\n" + preflight.report(checks))

    def test_every_failure_says_what_to_do(self):
        # An empty directory has none of it — every check should fail with a fix.
        empty = tempfile.mkdtemp()
        for c in preflight.check(empty):
            if not c.ok:
                self.assertTrue(c.fix, f"{c.name} fails with nothing to try")

    def test_a_checkout_with_no_tools(self):
        empty = tempfile.mkdtemp()
        names = {c.name: c for c in preflight.check(empty)}
        self.assertFalse(names["json2rc"].ok, "no json2rc in an empty directory")
        self.assertFalse(names["refractplayer"].ok, "and no player")
        # ...but the player is not what stops a build: `--json-only` needs neither.
        self.assertNotIn("refractplayer", [c.name for c in preflight.blocking(names.values())])

    def test_optional_things_do_not_block(self):
        for c in preflight.check(REPO):
            if c.name in ("graphviz", "refractplayer"):
                self.assertFalse(c.needed, f"{c.name} should not be required")

    def test_the_report_names_everything(self):
        text = preflight.report(preflight.check(REPO))
        for name in ("python", "json2rc", "java", "refractplayer", "graphviz"):
            self.assertIn(name, text)


class Java(unittest.TestCase):
    def test_a_missing_runtime_is_zero_not_a_crash(self):
        self.assertEqual(preflight.java_version("/nonexistent/java"), 0)

    def test_the_version_is_read_from_what_java_prints(self):
        java = shutil.which("java")
        if not java:
            self.skipTest("no java on this machine")
        self.assertGreaterEqual(preflight.java_version(java), 8)

    def test_a_bundled_jre_is_found_when_there_is_one(self):
        root = tempfile.mkdtemp()
        self.assertEqual(preflight.bundled_jre(root), "")
        binary = os.path.join(root, "prebuilt", "jre", "bin")
        os.makedirs(binary)
        open(os.path.join(binary, "java"), "w").close()
        self.assertEqual(preflight.bundled_jre(root),
                         os.path.join(root, "prebuilt", "jre"))


class ThroughTheCli(unittest.TestCase):
    def test_check_reports_and_exits_zero_here(self):
        p = subprocess.run([sys.executable, os.path.join(REPO, "refract.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("python", p.stdout)
        self.assertIn("json2rc", p.stdout)


if __name__ == "__main__":
    unittest.main()
