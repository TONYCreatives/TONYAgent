"""Re-introduce the pass B bugs and confirm the new tests notice.

A test that passes against both the fix and the defect it was written for is not
a test. This puts each defect back the way it was and asserts that at least one
test goes red, then restores the file. It is the only honest check on a
regression test, and it is the reason `scripts/` holds a script rather than a
note saying "please check these fail without the fix".

Run:  python scripts/mutate_pass_b.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

# (file, good, bad, what the mutation represents)
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "src/useDismiss.ts","""      const node = surface?.current;
      if (node && event.target instanceof Node && node.contains(event.target)) {
        return;
      }
      onClose();""",
        """      const node = surface?.current;
      if (node && event.target instanceof Node && false) {
        return;
      }
      onClose();""",
        "the unguarded capture-phase pointerdown all three surfaces grew",
    ),
    (
        "src/styles.css",
        """.rail.rail-expanded .rail-toggle {
  align-self: stretch;
}""",
        """.rail-toggle {
  align-self: flex-start;
}""",
        "the collapsed sidebar's reopen button hanging against the window edge",
    ),
    (
        "src/TopBar.tsx",
        '<header className="topbar" data-tauri-drag-region="deep">',
        '<header className="topbar">',
        "an undecorated window with no drag handle at all",
    ),
    (
        "src/ToolBudgetControl.tsx",
        """    if ("reason" in parsed) {
      setProblem(parsed.reason);
      return;
    }""",
        """    if ("reason" in parsed) {
      onChange(1);
      setProblem(parsed.reason);
      return;
    }""",
        "a refused budget clamped to 1 instead of refused",
    ),
]


def run(command: list[str]) -> tuple[int, str]:
    """Run a command, decoding as UTF-8 whatever the console hands back.

    `npm` is a `npm.cmd` shim on Windows, and `subprocess` will not find it
    without one, so the command is handed to the shell -- which is also how a
    developer would run it by hand.
    """
    done = subprocess.run(
        " ".join(command), cwd=APP, capture_output=True, shell=True
    )
    return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")


def failing_tests(output: str) -> list[str]:
    return [
        line[2:].split(" (")[0].strip()
        for line in output.replace("\r", "").splitlines()
        if line.startswith("✖ ") and line.strip() != "✖ failing tests:"
    ]


def main() -> int:
    problems: list[str] = []

    for relative, good, bad, description in MUTATIONS:
        path = APP / relative
        original = path.read_bytes()
        text = original.decode("utf-8")
        newline = "\r\n" if "\r\n" in text else "\n"
        flat = text.replace("\r\n", "\n")

        if flat.count(good) != 1:
            print(f"SKIP {relative}: the good anchor was not found exactly once")
            problems.append(f"{relative}: anchor not found, mutation not attempted")
            continue

        print(f"\n=== {relative}: {description}")
        try:
            mutated = flat.replace(good, bad)
            path.write_bytes(
                (mutated.replace("\n", newline) if newline != "\n" else mutated).encode(
                    "utf-8"
                )
            )
            code, output = run(["npm", "test"])
            names = failing_tests(output)
            if "error TS" in output:
                # A mutation that does not compile proves nothing: the suite
                # never ran. Reporting that as "not detected" would be a check
                # that agrees with whatever it is shown.
                print("  NOT EVALUABLE -- the mutation does not compile:")
                for line in output.splitlines():
                    if "error TS" in line:
                        print(f"      {line.strip()}")
                problems.append(f"{relative}: the mutation does not compile")
            elif code == 0 or not names:
                print("  NOT DETECTED -- the suite stayed green")
                problems.append(f"{relative}: {description} was not detected")
            else:
                for name in names:
                    print(f"  caught by: {name}")
        finally:
            path.write_bytes(original)
            print("  restored")

    print()
    if problems:
        print(f"{len(problems)} mutation(s) survived:")
        for problem in problems:
            print(f"  ! {problem}")
        return 1
    print("every mutation was caught by at least one test")
    return 0


if __name__ == "__main__":
    sys.exit(main())