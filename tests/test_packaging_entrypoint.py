"""The packaged executable must actually start.

## What this guards

v0.1.0 and v0.2.0 both shipped an executable that died on its very first
import:

    ImportError: attempted relative import with no known parent package

The cause was in `build.py`, not in the package: PyInstaller was pointed at
`src/ordertune_bridge_ibkr/main.py`. That makes the module the `__main__`
script, and a `__main__` script has no parent package, so `from . import
__version__` cannot resolve.

Nothing caught it. The existing suite imports the package the normal way,
where relative imports are correct and work; and no step ever launched the
built artifact. A defect in how the program is *started* is invisible to every
test that starts it a different way.

These tests therefore reproduce PyInstaller's execution model directly: run a
file as a script, in a subprocess, and look at what comes out.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _run(script: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a file as `__main__`, with `src` importable — as PyInstaller does.

    T1-101: `cwd` is now a parameter, and the caller that asserts on a MISSING
    `bridge.env` passes a scratch directory. Running in the repository root
    made the test depend on whether the developer happens to keep a real
    `bridge.env` there — and on the owner's machine they do. It then found a
    valid configuration, walked past the check it was written for, and failed
    on the next step. A test whose result depends on an ignored file in the
    working tree does not test the program; it tests the machine.


    The environment is INHERITED and only `PYTHONPATH` is overridden. Handing
    `subprocess` a hand-built environment instead broke the release build on
    Windows: without `SYSTEMROOT` the interpreter cannot reach the OS random
    source and dies before running anything —

        Fatal Python error: _Py_HashRandomization_Init: failed to get random
        numbers to initialize Python

    Both tests then saw that message instead of the import behaviour they
    assert on, and reported a packaging fault that did not exist. A test
    harness that strips the environment does not test a stricter case; it
    tests a different program.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(cwd or ROOT),
        env=env,
    )


def test_launcher_starts_and_reaches_configuration(tmp_path) -> None:
    """The launcher must get past its imports and into `main()`.

    With no `bridge.env` present, `main()` is expected to reject the
    configuration and exit 1. That is a SUCCESSFUL start for our purposes: it
    proves every import resolved and the program's own error handling ran.
    """
    result = _run(ROOT / "launcher.py", cwd=tmp_path)

    combined = result.stdout + result.stderr
    assert "ImportError" not in combined, (
        "the launcher died during import — the executable would not start:\n"
        f"{combined}"
    )
    assert "attempted relative import" not in combined
    # T1-101 A-1/A-2: the wording changed from `bridge.env invalid: <exception>`
    # to a framed block with a stable reference code. The code is what this
    # test anchors on -- it is the part meant to survive rewording.
    assert "Reference: env_missing" in combined, (
        "expected the configuration check to run and complain; got:\n"
        f"{combined}"
    )
    assert result.returncode == 1


def test_the_launcher_does_not_wait_for_input_when_run_from_source(tmp_path) -> None:
    """T1-101 A-1 — der Halt gilt der gepackten EXE, nicht jedem Aufruf.

    `_run` gibt keinen Eingabekanal mit. Bliebe der Halt auch ausserhalb einer
    gepackten EXE stehen, liefe dieser Aufruf in eine Wartestellung statt in
    einen Rueckgabewert — und mit ihm jede geplante Aufgabe und jeder
    CI-Durchlauf.
    """
    result = _run(ROOT / "launcher.py", cwd=tmp_path)

    assert result.returncode == 1
    assert "Press Enter" not in result.stdout + result.stderr


def test_package_module_is_not_a_launch_script() -> None:
    """`main.py` run as a script must fail — and that is correct.

    This is not a bug to fix in the package. Its relative imports are right;
    they are how a module inside a package refers to its siblings. The test
    pins the reason the launcher exists: if someone ever "fixes" this by
    rewriting the package's imports to absolute ones, the launcher would look
    redundant and the next person would delete it.
    """
    result = _run(SRC / "ordertune_bridge_ibkr" / "main.py")

    combined = result.stdout + result.stderr
    assert "attempted relative import" in combined, (
        "main.py started as a script — then the launcher may have been made "
        "redundant by absolute imports. Re-check build.py before removing it:\n"
        f"{combined}"
    )


def test_build_targets_the_launcher() -> None:
    """`build.py` must package the launcher, not a module inside the package.

    The failure this pins is a one-line edit away and produces an executable
    that is broken in exactly one place: startup. Cheap to assert, expensive
    to discover in the field.
    """
    build_source = (ROOT / "build.py").read_text(encoding="utf-8")

    assert "launcher.py" in build_source
    assert "--paths" in build_source, (
        "without --paths the launcher cannot import the package by name"
    )
    assert (
        '"ordertune_bridge_ibkr" / "main.py"' not in build_source
        and "ordertune_bridge_ibkr\" / \"main.py\"" not in build_source
    ), "build.py points at a module inside the package again"
