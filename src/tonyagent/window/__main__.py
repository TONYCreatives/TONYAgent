"""``python -m tonyagent.window``, which is how the app is started.

A separate file from ``__init__.py`` because that is the rule and not a choice:
``-m package`` looks for ``package.__main__`` and nothing else, so a package
whose ``__init__`` exports ``main`` is a package that *cannot* be run that way.
The failure is loud but easy to miss in the wrong place --

    No module named tonyagent.window.__main__;
    'tonyagent.window' is a package and cannot be directly executed

-- and it is worth a note here because this file did not exist at first. Every
harness in ``scripts/`` calls ``host.main()`` directly, so the one entry point
the launcher, the docs and every instruction in this repository actually name
was the one path nothing exercised. The launcher found it in a second.

**``--core`` is the installed build's second half.** A frozen executable has no
``python -m`` to spawn: ``sys.executable`` is the app itself, so the core is
reached by re-running that same file with this flag and dispatching here.
Everything below the argument is the ordinary host.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":
    if "--core" in sys.argv[1:]:
        from tonyagent.headless.server import main as core_main

        raise SystemExit(core_main())

    from tonyagent.window.host import main

    raise SystemExit(main())
