"""TONYAgent - A local AI agent for automating programming tasks."""

#: **The one place the version is written down.**
#:
#: It used to be spelled twice, here and in `pyproject.toml`, and the two were
#: read by different consumers: the package metadata by pip, and this by the
#: app's User-Agent and its CLIs. The installer read the *third* copy out of
#: `pyproject.toml`. Three readers, one number, and nothing comparing them --
#: so an update check built on the app's value could have been comparing a
#: number no release was ever tagged with.
#:
#: `pyproject.toml` now declares the version dynamic and reads it from here, and
#: the installer build does the same. The direction is deliberate: this module
#: is inside the frozen bundle, so the installed app can always answer "what am
#: I", while `pyproject.toml` is not shipped anywhere and a frozen build could
#: not read it if it were.
#:
#: Keep it a bare literal. setuptools reads it by parsing rather than importing
#: (it cannot import a package whose dependencies are not installed yet), so an
#: expression here is a build failure rather than a clever version string.
__version__ = "0.3.1"
__author__ = "Tony Lee"