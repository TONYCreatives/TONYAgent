"""``python -m tonyagent.cli`` -- the same entry point the window uses.

`pyproject.toml` also installs this as the `tony` console script, so an
installed copy is `tony` on PATH. This module exists so the CLI runs from a
source checkout with no install at all, which is how it is developed.
"""

from tonyagent.cli.repl import main

if __name__ == "__main__":
    raise SystemExit(main())
