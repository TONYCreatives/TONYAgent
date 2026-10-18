# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the installed TONYAgent.

**One executable, two processes.** The host and the core are the same program
run twice -- see `tonyagent.window.core.default_argv` -- so the bundle has to
carry both import graphs. The core is reached through ``--core``, which means
`tonyagent.headless.server` is imported inside an ``if`` that a static analyser
can see but a lazy one would miss, so it is named in ``hiddenimports`` rather
than left to chance.

**onedir, not onefile.** A onefile build unpacks to a temporary directory on
every launch, which is the wrong trade for an app whose whole interface is a
webview: the frontend is served from disk by the host's own HTTP server, and a
directory that is deleted at exit is a directory the webview may still be
reading. onedir also keeps the WebView2 runtime DLLs findable, which is how the
browser control loads at all.

**`app/dist` is data, not source.** The window reads the built frontend at
runtime (`default_dist`), so it is copied in whole rather than imported. The
icons and the logo come along for the same reason: the caption icon and the
shortcut icon are files the program opens.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

import os

#: A console build, for reading a startup traceback that a windowed build can
#: only show as a dialog. Set `TONYAGENT_DEBUG_CONSOLE=1` before PyInstaller.
DEBUG_CONSOLE = bool(os.environ.get("TONYAGENT_DEBUG_CONSOLE"))

#: The repository root, from this spec's own location. `SPECPATH` is set by
#: PyInstaller to the directory holding this file, which is what makes the build
#: work from any working directory.
ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller

datas = [
    # The built frontend, at the path `host.default_dist` looks for when frozen.
    (str(ROOT / "app" / "dist"), "app/dist"),
    (str(ROOT / "app" / "icons"), "app/icons"),
    (str(ROOT / "logo"), "logo"),
]

# pywebview ships its JavaScript and the WebView2 .NET assemblies as data, and
# the loader DLLs as binaries, none of which are found by importing the package.
datas += collect_data_files("webview", subdir="lib")
datas += collect_data_files("webview")
binaries = collect_dynamic_libs("webview")

# **The mypyc shared library, which nothing can find by reading imports.**
# `tomli_w` is distributed as a mypyc-compiled extension whose support module is
# a top-level file named `<hash>__mypyc` -- a name that appears in no `.py` file
# anywhere, because the import of it lives inside the compiled code. Static
# analysis therefore misses it, and the failure is at *runtime*: the frozen app
# opens its window and dies inside the first `import tomli_w`, with
# `ModuleNotFoundError: No module named '3c22db458360489351e4__mypyc'`.
#
# Globbing rather than naming it: the hash is a build artifact of whoever
# compiled the wheel, so a literal here would be wrong on the next release. It
# is placed at the bundle root because that is where a top-level module has to
# be for the import to resolve.
#
# The library sits *beside* the compiled package rather than inside it, so the
# search root is the directory holding both -- one level up from `tomli_w/`.
import tomli_w  # noqa: E402 - imported for its location, not its API

_PACKAGE = Path(tomli_w.__file__).resolve().parent
_SEARCH = _PACKAGE.parent if (_PACKAGE / "__init__.py").is_file() else _PACKAGE
binaries += [(str(path), ".") for path in _SEARCH.glob("*__mypyc*.pyd")]

hiddenimports = [
    # The core, reached through `--core`. See the module docstring.
    "tonyagent.headless.server",
    # pywebview picks a backend by name at runtime, so the module that carries
    # the WinForms form is never imported statically. Without it the frozen app
    # starts and answers "no supported platform".
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "webview.platforms.win32",
    # pythonnet's loader, imported by name from `clr`.
    "clr_loader",
    "pythonnet",
    # Keyring's Windows backend: a provider of a plugin registry, not an import
    # anything in this tree makes.
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.chainer",
]

# Everything the app does not touch. The declared dependencies still list the
# vendor SDKs the single-dialect rewrite removed, and freezing them would put
# tens of megabytes of never-imported code in the installer.
excludes = [
    "anthropic",
    "openai",
    "ollama",
    "google.generativeai",
    "playwright",
    "markdown2",
    "pygments",
    "tkinter",
    "unittest",
    "pydoc_data",
    "IPython",
    "matplotlib",
    "numpy",
    "pandas",
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TONYAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=DEBUG_CONSOLE,
    disable_windowed_traceback=DEBUG_CONSOLE,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # The caption icon and the taskbar icon. `pywebview` hands this to the form,
    # and the same file is the shortcut's icon in the installer.
    #
    # `logo/tonyagent-logo.ico` and not `app/icons/icon.ico`: the app wears the
    # mark on black everywhere now -- see `host.app_icon`, which reads the same
    # file at runtime -- so the icon baked into the executable and the icon the
    # window asks for cannot be two different drawings.
    icon=str(ROOT / "logo" / "tonyagent-logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TONYAgent",
)
