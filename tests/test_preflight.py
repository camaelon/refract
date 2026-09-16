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


class Json2rc(unittest.TestCase):
    """The compiler *and* the jars it runs from.

    This is here because of a real failure: .gitignore's `lib/` rule — meant for a
    virtualenv — also matched prebuilt/json2rc/lib, so a fresh clone got the launcher script
    and none of the six jars. json2rc started a JVM and died with "Could not find or load
    main class", which names neither json2rc nor the missing files, and `--check` said it was
    fine because it had only looked for the script.
    """

    def test_the_classpath_is_read_out_of_the_launcher(self):
        launcher = os.path.join(REPO, "prebuilt", "json2rc", "bin", "json2rc")
        jars = preflight.json2rc_classpath(launcher)
        self.assertTrue(jars, "no CLASSPATH line found in the launcher")
        self.assertTrue(any(j.endswith("json2rc.jar") for j in jars),
                        "the launcher's classpath does not mention json2rc.jar")
        for jar in jars:
            self.assertTrue(os.path.isabs(jar), f"{jar} is not an absolute path")

    def test_every_jar_the_launcher_names_is_here(self):
        launcher = os.path.join(REPO, "prebuilt", "json2rc", "bin", "json2rc")
        missing = [j for j in preflight.json2rc_classpath(launcher) if not os.path.isfile(j)]
        self.assertEqual(missing, [], "json2rc would fail to start")

    def test_the_jars_are_not_ignored_by_git(self):
        # The actual bug: present on the machine that built them, absent from every clone.
        jars = preflight.json2rc_classpath(
            os.path.join(REPO, "prebuilt", "json2rc", "bin", "json2rc"))
        if not jars:
            self.skipTest("no launcher to read")
        p = subprocess.run(["git", "check-ignore", *jars], cwd=REPO,
                           capture_output=True, text=True)
        self.assertEqual(p.stdout.strip(), "",
                         "git ignores jars json2rc needs; a clone would not get them")

    def test_a_launcher_with_no_jars_is_reported_as_missing(self):
        fake = tempfile.mkdtemp()
        os.makedirs(os.path.join(fake, "prebuilt", "json2rc", "bin"))
        launcher = os.path.join(fake, "prebuilt", "json2rc", "bin", "json2rc")
        with open(launcher, "w") as f:
            f.write("#!/bin/sh\nCLASSPATH=$APP_HOME/lib/json2rc.jar:$APP_HOME/lib/other.jar\n")
        os.chmod(launcher, 0o755)
        check = preflight.json2rc_check(fake)
        self.assertFalse(check.ok, "a launcher with no jars behind it is not usable")
        self.assertIn("jars", check.detail)
        self.assertIn("json2rc.jar", check.detail)


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
