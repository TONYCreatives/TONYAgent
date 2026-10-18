"""The installed build's entry point: one executable, two jobs.

PyInstaller needs a script rather than a ``-m`` module, and this is the one
line of it that matters -- the same dispatch ``tonyagent.window.__main__``
performs, reached the same way. It is a copy of two imports on purpose
instead of an indirection into the package: a frozen build's entry point is
the one file whose import graph decides what gets bundled, so pointing it at
the package's own ``__main__`` keeps PyInstaller following the same modules
the from-source launcher follows.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":
    if "--core" in sys.argv[1:]:
        from tonyagent.headless.server import main as core_main

        raise SystemExit(core_main())

    from tonyagent.window.host import main

    raise SystemExit(main())
