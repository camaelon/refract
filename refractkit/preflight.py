"""What this machine needs to build and play a deck, and what it is missing.

Everything refract needs is either in the repository or is one install away, but the failures
are spread out and none of them says the whole truth: a missing JVM surfaces as a message
from Apple's `java` stub, an old Python as an ImportError three imports deep, an unbuilt
player as a fallback to a different exporter. So they are all asked in one place, and
``refract.py --check`` prints the answer.

Nothing here fixes anything. It reports, with the command that would.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


# Python 3.11 is where ``tomllib`` arrived, and settings.toml is read with it. Apple ships
# 3.9, so this is the one requirement a stock Mac does not already meet.
MIN_PYTHON = (3, 11)
# The class files in json2rc.jar are major version 65.
MIN_JAVA = 21


class Check:
    """One question about the machine, and what to do when the answer is no."""

    def __init__(self, name: str, ok: bool, detail: str, fix: str = "", needed: bool = True):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.fix = fix
        self.needed = needed      # False for something only some decks use

    def __repr__(self) -> str:                     # pragma: no cover - debugging only
        return f"<Check {self.name} {'ok' if self.ok else 'missing'}>"


def _version_of(python: str) -> tuple:
    """(major, minor) that interpreter reports, or () when it will not run."""
    try:
        out = subprocess.run([python, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                             capture_output=True, text=True, timeout=20)
        parts = out.stdout.split()
        return (int(parts[0]), int(parts[1])) if len(parts) == 2 else ()
    except (OSError, ValueError, subprocess.SubprocessError):
        return ()


def python_check() -> Check:
    """The running interpreter, and the `python3` on PATH.

    Two answers, because two things ask: refract.py runs under whatever started it, and the
    player looks up `python3` on PATH for its own tools. A checkout where those differ works
    from the terminal and quietly fails inside the editor, which is a confusing way to find
    out.
    """
    have = sys.version_info[:2]
    detail = f"{have[0]}.{have[1]} at {sys.executable}"
    ok = have >= MIN_PYTHON

    onpath = shutil.which("python3")
    if onpath and os.path.realpath(onpath) != os.path.realpath(sys.executable):
        theirs = _version_of(onpath)
        shown = f"{theirs[0]}.{theirs[1]}" if theirs else "will not run"
        detail += f";  `python3` on PATH is {shown} at {onpath}"
        if not theirs or theirs < MIN_PYTHON:
            ok = False
    return Check(
        "python", ok, detail,
        f"refract needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer (tomllib, for settings.toml), "
        f"and the player runs `python3` from PATH for its editing tools. macOS ships 3.9 — "
        f"`brew install python` gives a current one; put it ahead of /usr/bin on PATH.")


def bundled_jre(repo_root: str) -> str:
    """A JRE shipped in the repository, if somebody put one there. Empty otherwise.

    Optional on purpose: it is 45MB, which is a real thing to add to a checkout, and a
    machine with a JDK already does not need it.
    """
    path = os.path.join(repo_root, "prebuilt", "jre")
    return path if os.path.isfile(os.path.join(path, "bin", "java")) else ""


def java_version(java: str) -> int:
    """The major version `java` reports, or 0 when it will not run at all."""
    try:
        out = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return 0
    text = (out.stderr or "") + (out.stdout or "")
    for token in text.replace('"', " ").split():
        head = token.split(".")[0]
        if head.isdigit():
            return int(head)
    return 0


def java_check(repo_root: str) -> Check:
    bundled = bundled_jre(repo_root)
    java = os.path.join(bundled, "bin", "java") if bundled else shutil.which("java")
    where = "prebuilt/jre" if bundled else (java or "")
    if not java:
        return Check("java", False, "not found",
                     f"json2rc compiles a slide to .rc and needs a JVM {MIN_JAVA}+. "
                     f"`brew install openjdk@{MIN_JAVA}` — or put a JRE in prebuilt/jre.")
    version = java_version(java)
    if version == 0:
        return Check("java", False, f"{where} will not run",
                     "macOS ships a `java` stub that only reports a missing runtime. "
                     f"`brew install openjdk@{MIN_JAVA}`.")
    ok = version >= MIN_JAVA
    return Check("java", ok, f"{version} at {where}",
                 f"json2rc needs {MIN_JAVA} or newer. `brew install openjdk@{MIN_JAVA}`.")


def json2rc_check(repo_root: str) -> Check:
    launcher = os.path.join(repo_root, "prebuilt", "json2rc", "bin", "json2rc")
    ok = os.path.isfile(launcher) and os.access(launcher, os.X_OK)
    return Check("json2rc", ok, launcher if ok else "not in prebuilt/",
                 "The compiler that turns a slide's JSON into .rc. Build it with "
                 "`(cd json2rc && ./gradlew installDist)`.")


def player_check(repo_root: str) -> Check:
    player = os.path.join(repo_root, "prebuilt", "refractplayer")
    if not (os.path.isfile(player) and os.access(player, os.X_OK)):
        return Check("refractplayer", False, "not in prebuilt/",
                     "Build it with `player/build.sh`, or use `--json-only` and a viewer.",
                     needed=False)
    try:
        out = subprocess.run([player, "--help"], capture_output=True, text=True, timeout=20)
        ok = out.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        return Check("refractplayer", False, f"will not run: {e}",
                     "The shipped binary is arm64 and needs macOS 11 or newer.", needed=False)
    return Check("refractplayer", ok, player if ok else "will not run",
                 "The shipped binary is arm64 and needs macOS 11 or newer.", needed=False)


def graphviz_check() -> Check:
    dot = shutil.which("dot")
    return Check("graphviz", bool(dot), dot or "not found",
                 "Only for `graph` slides. `brew install graphviz`.", needed=False)


def check(repo_root: str) -> list[Check]:
    """Every question, in the order somebody hits them."""
    return [
        python_check(),
        json2rc_check(repo_root),
        java_check(repo_root),
        player_check(repo_root),
        graphviz_check(),
    ]


def report(checks: list[Check]) -> str:
    """The answers, as something to read. Ends with what to do about the ones that failed."""
    width = max(len(c.name) for c in checks)
    lines = []
    for c in checks:
        mark = "ok  " if c.ok else ("MISSING" if c.needed else "absent ")
        lines.append(f"  {mark:8}{c.name.ljust(width)}  {c.detail}")
    missing = [c for c in checks if not c.ok]
    if missing:
        lines.append("")
        for c in missing:
            lines.append(f"  {c.name}: {c.fix}")
    return "\n".join(lines)


def blocking(checks: list[Check]) -> list[Check]:
    """The failures that stop a deck being built at all."""
    return [c for c in checks if c.needed and not c.ok]
