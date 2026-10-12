"""Run every TONYAgent check in parallel and print one verdict.

Replaces the serial compile -> pytest -> verify_gui -> launch dance with a
single fan-out, which is where most of the wall-clock time went while iterating
on the UI.

    python scripts/check_all.py            # everything
    python scripts/check_all.py --fast     # skip the GUI launch smoke test
    python scripts/check_all.py --no-docker  # skip tests that need a live container

Exit code is 0 only if every check passed.

NOTE: run the live-container e2e scripts (scripts/e2e_*.py) SEPARATELY from this
one - they share the fixed container name "tonyagent-sandbox" and will kill each
other's sandbox. Use --no-docker to keep this runner's pytest pass clear of it.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE_SECONDS = 12
# This console is cp949 on some machines, which crashes on non-ASCII output.
_ASCII = re.compile(r"[^\x20-\x7e]")


def _clean(text: str, limit: int = 6) -> list[str]:
    """ASCII-safe, non-empty tail lines for the summary."""
    lines = [_ASCII.sub("?", ln).rstrip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    return lines[-limit:]


def _run(name: str, argv: list[str], timeout: int = 300) -> dict:
    started = time.time()
    try:
        proc = subprocess.run(
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return {
            "name": name,
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "secs": time.time() - started,
            "tail": _clean(out),
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "ok": False,
            "code": "timeout",
            "secs": time.time() - started,
            "tail": [f"timed out after {timeout}s"],
        }
    except Exception as e:  # a missing interpreter should not abort the run
        return {
            "name": name,
            "ok": False,
            "code": "error",
            "secs": time.time() - started,
            "tail": [f"{type(e).__name__}: {e}"],
        }


def _smoke_launch() -> dict:
    """Start the app, confirm it survives startup, then shut it down.

    ``tonyagent.window`` and not ``tonyagent``: the package has no ``__main__``, so
    the shorter form exits with "cannot be directly executed" and this check was
    reporting that as a crash on startup. Measured -- and the README says the same
    thing in the section that used to name the working command.
    """
    started = time.time()
    argv = [sys.executable, "-m", "tonyagent.window"]
    try:
        proc = subprocess.Popen(
            argv,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as e:
        return {"name": "launch", "ok": False, "code": "error",
                "secs": 0.0, "tail": [f"{type(e).__name__}: {e}"]}

    time.sleep(SMOKE_SECONDS)
    crashed = proc.poll() is not None
    if crashed:
        try:
            out = proc.stdout.read() or ""
        except Exception:
            out = ""
        return {
            "name": "launch",
            "ok": False,
            "code": proc.returncode,
            "secs": time.time() - started,
            "tail": _clean(out) or ["exited during startup"],
        }

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    return {
        "name": "launch",
        "ok": True,
        "code": 0,
        "secs": time.time() - started,
        "tail": [f"survived {SMOKE_SECONDS}s startup, terminated cleanly"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run all TONYAgent checks in parallel.")
    ap.add_argument("--fast", action="store_true", help="skip the GUI launch test")
    ap.add_argument("--no-docker", action="store_true",
                    help="deselect tests that need a live Docker container")
    args = ap.parse_args()

    py = sys.executable
    checks = [
        ("compile", [py, "-m", "compileall", "-q", "src/tonyagent"], 120),
        ("pytest", [py, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"], 300),
    ]
    if args.no_docker:
        checks[1] = ("pytest", checks[1][1] + ["-m", "not docker"], 300)

    launch = None if args.fast else _smoke_launch
    total = len(checks) + (0 if launch is None else 1)
    print(f"Running {total} checks (launch runs last)...")
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, len(checks))) as pool:
        futures = [pool.submit(_run, n, a, t) for n, a, t in checks]
        results = [f.result() for f in futures]
    if launch is not None:
        results.append(launch())

    print()
    failed = 0
    for r in sorted(results, key=lambda x: x["name"]):
        mark = "PASS" if r["ok"] else "FAIL"
        if not r["ok"]:
            failed += 1
        print(f"[{mark}] {r['name']:<11} {r['secs']:>5.1f}s  (exit {r['code']})")
        for line in r["tail"]:
            print(f"         | {line}")

    total = time.time() - started
    print()
    if failed:
        print(f"{failed} of {len(results)} checks FAILED in {total:.1f}s")
    else:
        print(f"All {len(results)} checks passed in {total:.1f}s (was ~45s serially)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
