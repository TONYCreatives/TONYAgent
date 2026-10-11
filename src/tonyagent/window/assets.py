"""Serve the built frontend to the window, from a directory, on loopback.

The page cannot be loaded from ``file://``. Vite emits ES modules, and Chromium
refuses to load a module over ``file://`` -- it is a request with no origin to
match -- so a build opened as a file renders a blank window with the reason only
in the webview's own console. Every alternative is worse: inlining the bundle
gives up code splitting, and loosening the webview's flags changes the security
posture of the whole app to solve a loading problem.

So the host runs a real HTTP server: on ``127.0.0.1``, on a port the OS picks.
Bound to loopback and never to ``0.0.0.0``, which is what keeps this from being
a service on the network; and ephemeral rather than fixed, so a second window --
or anything else already holding 8000 -- cannot make the app fail to start.

Three details that are not decoration:

* ``.woff2`` is mapped by hand. Windows' ``mimetypes`` does not know it, and a
  font served as ``application/octet-stream`` is a font the page refuses to
  use -- which is the entire typography of this app, silently falling back.
* ``Cache-Control: no-store``. The host serves whatever ``app/dist`` holds when
  the window opens, so a rebuild between two launches must not be answered from
  the previous launch's cache.
* the directory is checked at start. A missing ``app/dist`` is the one failure
  a user can actually fix, and "the window opened and is blank" is not a
  message that helps them find ``npm run build``.
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from loguru import logger


class MissingFrontendError(RuntimeError):
    """``app/dist`` is not there, so there is nothing to put in the window."""


class _Handler(SimpleHTTPRequestHandler):
    """``SimpleHTTPRequestHandler`` with the two fixes above and no logging.

    ``extensions_map`` is the class attribute Python's own ``guess_type``
    consults, so extending it is the supported way to teach this server a MIME
    type -- and it is a copy, because the base mapping is shared process-wide
    and mutating it would change every other server in the interpreter.
    """

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".woff2": "font/woff2",
        ".woff": "font/woff",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".json": "application/json",
    }

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        # The default writes a line to stderr for every asset, which buries the
        # core's own output -- the channel the log strip reads. Kept at debug so
        # a missing asset is still findable when someone goes looking.
        logger.debug(f"assets: {format % args}")


class AssetServer:
    """The built frontend, on loopback, for as long as the window is open.

    A thread per request, because a page load is a dozen of them at once and a
    single-threaded server serialises them behind whichever font is slowest.
    """

    def __init__(self, directory: Path | str) -> None:
        self._directory = Path(directory)

    def start(self) -> str:
        """Serve the directory and return the origin to load the page from."""
        index = self._directory / "index.html"
        if not index.is_file():
            raise MissingFrontendError(
                f"{index} is missing. Build the frontend first: npm run build in app/"
            )
        handler = partial(_Handler, directory=str(self._directory))
        # Port 0 is the OS choosing one. `daemon_threads` so a request still in
        # flight cannot hold the process open after the window has closed.
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        self._server = server
        thread = threading.Thread(
            target=server.serve_forever, name="tonyagent-assets", daemon=True
        )
        thread.start()
        self._thread = thread
        host, port = server.server_address[:2]
        origin = f"http://{host}:{port}"
        logger.info(f"Serving the frontend from {self._directory} at {origin}")
        return origin

    def stop(self) -> None:
        server = getattr(self, "_server", None)
        if server is None:
            return
        self._server = None
        server.shutdown()
        server.server_close()

    @property
    def url(self) -> str:
        """Where the page is, once ``start`` has returned."""
        server = getattr(self, "_server", None)
        if server is None:
            raise RuntimeError("the asset server is not running")
        host, port = server.server_address[:2]
        return f"http://{host}:{port}/index.html"
