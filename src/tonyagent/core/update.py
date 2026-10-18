"""Is there a newer TONYAgent than this one? Ask GitHub, and say what happened.

**A read, and only a read.** This module fetches one JSON document, compares two
version numbers, and answers. It downloads nothing, installs nothing and writes
nothing outside its own cache file. Applying an update is the window's job --
see `window/update.py` -- because launching an installer is an OS action and the
core is the process that would be replaced.

**Why the core owns the question.** It already owns every other fetch the app
makes (`models.list`, the usage ledger), it has the HTTP client, and putting this
behind the JSONL protocol means the desktop window, the CLI and the TUI all get
updates from one implementation rather than three that disagree about what
"newer" means.

**The honest answer matters more than the answer.** Every failure -- offline, a
rate limit, a repository that cannot be seen, a release with no asset -- is
reported as *its own reason* rather than as "up to date". A check that cannot
reach GitHub has not learned that you are current, and saying so would be a
claim it is not entitled to make. `models.list` draws the same line between
"no models" and "could not ask".

**One request per day, and the second one is free.** GitHub's unauthenticated
limit is 60 requests an hour per address, which is not much for an app that
might ship. Measured: a conditional request that answers `304 Not Modified`
does not consume quota, so the cached `ETag` is sent on every check and a check
that finds nothing new costs nothing. The cache is one small JSON file beside
`config.toml`.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from tonyagent import __version__

#: The repository the releases live in. Public, because a shipped installer
#: cannot read a private one without carrying a credential, and a credential
#: inside an installer is a published credential.
REPO = "TONYCreatives/TONYAgent"

#: The one endpoint this module reads. `releases/latest` rather than the full
#: list: GitHub resolves "latest" itself, excluding drafts and prereleases, so
#: the app does not have to reimplement that rule and get it subtly wrong.
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

#: The page a person goes to when they want the update. Derived from the API's
#: own `html_url` when there is one, and this is the fallback for the releases
#: index rather than a guess at a tag.
RELEASES_PAGE = f"https://github.com/{REPO}/releases"

#: GitHub answers 403 with a rate-limit body rather than a 429.
RATE_LIMIT_STATUS = 403

#: How long a cached answer stands before it is asked again. A day, because a
#: release is not an emergency and every check is a request against a shared
#: 60/hour allowance. The cache is also what makes the app work offline: the
#: last known answer is still shown, marked as old.
CACHE_SECONDS = 24 * 60 * 60

#: How long to wait on GitHub. Short: this runs while the window is coming up,
#: and a check that blocks a launch is worse than one that gives up.
TIMEOUT = 10.0

#: `v1.2.3`, `1.2.3`, `1.2.3-beta.1` -- the leading `v` is optional because
#: GitHub tags are written both ways and the app should not care.
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)")


def parse_version(text: str) -> tuple[int, ...] | None:
    """A tag or version string as comparable numbers, or None.

    **None, not an empty tuple, for anything unparseable.** An empty tuple would
    compare as older than everything, so a repository that started tagging its
    releases `release-2026-10` would quietly report every one of them as an
    update. "I do not understand this" has to be distinguishable from "this is
    old", which is the same distinction the rest of this module keeps making.
    """
    match = _VERSION.match((text or "").strip())
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:  # pragma: no cover - the regex only admits digits
        return None


def is_newer(candidate: str, current: str) -> bool:
    """Whether `candidate` is a later version than `current`.

    Compared field by field with the shorter one padded, so `0.2` is newer than
    `0.1.9` and `1.0.0` equals `1.0`. Unparseable either side is not newer:
    the app will not offer an update it cannot explain.
    """
    left, right = parse_version(candidate), parse_version(current)
    if left is None or right is None:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


@dataclass
class UpdateInfo:
    """What a check found, including the ways it can find nothing."""

    current: str = ""
    latest: str = ""
    #: The tag as GitHub spells it, for display: `v0.2.0` reads as a release.
    tag: str = ""
    available: bool = False
    prerelease: bool = False
    notes: str = ""
    published_at: str = ""
    url: str = RELEASES_PAGE
    asset: dict[str, Any] | None = None
    #: When this answer was obtained, in epoch seconds. A cached answer keeps
    #: the time it was fetched rather than the time it was shown, so "checked
    #: 3 days ago" stays true.
    checked_at: float = 0.0
    #: True when this came from the cache rather than from GitHub.
    cached: bool = False
    #: "" when the question was answered. Otherwise why it was not, as one of
    #: `offline`, `rate_limited`, `not_found`, `server`, `malformed`, and the
    #: frontend turns it into a sentence.
    reason: str = ""

    @property
    def understood(self) -> bool:
        """Whether the question was actually answered."""
        return not self.reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "latest": self.latest,
            "tag": self.tag,
            "available": self.available,
            "prerelease": self.prerelease,
            "notes": self.notes,
            "published_at": self.published_at,
            "url": self.url,
            "asset": self.asset,
            "checked_at": self.checked_at,
            "cached": self.cached,
            "reason": self.reason,
        }


@dataclass
class _Cache:
    """The last answer and the ETag that came with it."""

    etag: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def cache_path() -> Path:
    """Where the last answer lives. Beside `config.toml`, like the ledger."""
    from tonyagent.config.settings import settings

    return settings.get_config_dir() / "update.json"


def _read_cache(path: Path) -> _Cache:
    """The stored cache, or an empty one. A broken file is not an error."""
    try:
        if not path.is_file():
            return _Cache()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _Cache()
        payload = data.get("payload")
        return _Cache(
            etag=str(data.get("etag") or ""),
            payload=payload if isinstance(payload, dict) else {},
        )
    except Exception as exc:  # noqa: BLE001 - a cache is never worth a refusal
        logger.debug(f"Could not read the update cache: {exc}")
        return _Cache()


def _write_cache(path: Path, cache: _Cache) -> None:
    """Store the answer. Failing to is logged and otherwise ignored."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"etag": cache.etag, "payload": cache.payload}),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.debug(f"Could not write the update cache: {exc}")


def _from_payload(payload: dict[str, Any], current: str, *, cached: bool) -> UpdateInfo:
    """Turn a stored or freshly-fetched release object into an answer."""
    tag = str(payload.get("tag_name") or "")
    latest = str(payload.get("version") or "") or (parse_version(tag) and tag) or ""
    asset = payload.get("asset")
    return UpdateInfo(
        current=current,
        latest=latest,
        tag=tag,
        available=is_newer(tag or latest, current),
        prerelease=bool(payload.get("prerelease")),
        notes=str(payload.get("notes") or ""),
        published_at=str(payload.get("published_at") or ""),
        url=str(payload.get("url") or RELEASES_PAGE),
        asset=asset if isinstance(asset, dict) else None,
        checked_at=float(payload.get("checked_at") or 0.0),
        cached=cached,
    )


def _release_payload(release: dict[str, Any]) -> dict[str, Any]:
    """The parts of a GitHub release this app keeps.

    Narrowed on purpose. The raw release object is tens of kilobytes -- every
    asset, every uploader, a dozen URLs -- and none of it belongs in a cache
    file that is read on every launch.

    **The installer is the first `.msi` asset, and this project publishes
    exactly one.** That is a real assumption rather than a general rule: a
    release carrying several (per-architecture, say) would need a naming rule
    here, because "first" is a coin toss between them. `release.ps1` attaches
    one file, so there is nothing to choose between today.
    """
    installer = ""
    for entry in release.get("assets") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        if name.lower().endswith(".msi"):
            installer = name
            break
    chosen = next(
        (
            entry
            for entry in (release.get("assets") or [])
            if isinstance(entry, dict) and str(entry.get("name") or "") == installer
        ),
        None,
    )
    return {
        "tag_name": str(release.get("tag_name") or ""),
        "prerelease": bool(release.get("prerelease")),
        "notes": str(release.get("body") or ""),
        "published_at": str(release.get("published_at") or ""),
        "url": str(release.get("html_url") or RELEASES_PAGE),
        "checked_at": time.time(),
        "asset": (
            {
                "name": str(chosen.get("name") or ""),
                "size": int(chosen.get("size") or 0),
                "digest": str(chosen.get("digest") or ""),
                "url": str(chosen.get("browser_download_url") or ""),
            }
            if chosen
            else None
        ),
    }


async def check(
    current: str = "",
    *,
    force: bool = False,
    client: httpx.AsyncClient | None = None,
) -> UpdateInfo:
    """Ask whether there is a newer version. Never raises.

    `force` skips the freshness window but still sends the `ETag`, so a manual
    "check now" costs quota only when something has actually changed.
    """
    current = current or __version__
    path = cache_path()
    cache = _read_cache(path)
    now = time.time()

    if not force and cache.payload:
        age = now - float(cache.payload.get("checked_at") or 0.0)
        if 0 <= age < CACHE_SECONDS:
            return _from_payload(cache.payload, current, cached=True)

    headers = {
        # GitHub refuses a request with no User-Agent, and this one names the
        # app rather than the HTTP library, which is the same rule the LLM
        # client follows for gateways that care.
        "User-Agent": f"TONYAgent/{current}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if cache.etag:
        headers["If-None-Match"] = cache.etag

    owned = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)
    try:
        response = await http.get(RELEASES_URL, headers=headers)
    except Exception as exc:  # noqa: BLE001 - offline is an answer, not a crash
        logger.debug(f"The update check could not reach GitHub: {exc}")
        return _stale_or(cache, current, "offline")
    finally:
        if owned:
            await http.aclose()

    # **304: nothing has changed, and this cost no quota.** The cached answer is
    # still the current one; `checked_at` is refreshed so the next launch does
    # not ask again, which is what keeps a daily check at one real request.
    if response.status_code == 304 and cache.payload:
        cache.payload["checked_at"] = now
        _write_cache(path, cache)
        return _from_payload(cache.payload, current, cached=True)

    if response.status_code == RATE_LIMIT_STATUS:
        return _stale_or(cache, current, "rate_limited")
    if response.status_code == 404:
        # The repository is private, renamed, or gone. Distinguishable from
        # offline, and worth saying differently: one fixes itself, the other
        # needs somebody to change a setting.
        return _stale_or(cache, current, "not_found")
    if response.status_code >= 400:
        return _stale_or(cache, current, "server")

    try:
        release = response.json()
    except Exception as exc:  # noqa: BLE001 - a body that is not JSON
        logger.debug(f"The update check got a body it could not read: {exc}")
        return _stale_or(cache, current, "malformed")
    if not isinstance(release, dict) or not release.get("tag_name"):
        return _stale_or(cache, current, "malformed")

    payload = _release_payload(release)
    _write_cache(path, _Cache(etag=str(response.headers.get("ETag") or ""), payload=payload))
    return _from_payload(payload, current, cached=False)


def _stale_or(cache: _Cache, current: str, reason: str) -> UpdateInfo:
    """The reason, plus whatever was known before it.

    A cached answer is carried along and marked `cached`, so a window that is
    offline still says "0.2.0 is available" rather than nothing -- the fact did
    not stop being true because the network went away. What it will not do is
    claim the check succeeded: `reason` stays set.
    """
    if not cache.payload:
        return UpdateInfo(current=current, reason=reason)
    info = _from_payload(cache.payload, current, cached=True)
    info.reason = reason
    return info


#: Where a downloaded installer waits. One fixed directory, because the window
#: is only ever allowed to run an MSI it finds here -- see `window/update.py`.
UPDATE_DIRNAME = "update"


def download_dir() -> Path:
    """The one directory an installer may be run from. Beside `config.toml`."""
    from tonyagent.config.settings import settings

    return settings.get_config_dir() / UPDATE_DIRNAME


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_digest(value: str) -> str:
    """The hex part of a GitHub `digest` field, lowercased.

    GitHub spells it `sha256:abc...`. Anything that is not that shape comes
    back empty, which the caller treats as "no digest" and refuses -- see
    `download`.
    """
    text = (value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    return text if len(text) == 64 and all(c in "0123456789abcdef" for c in text) else ""


async def download(
    info: UpdateInfo | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Fetch the installer for `info` and prove it is the one that was published.

    **A release with no `sha256` digest is refused, not run.** GitHub publishes
    the digest beside the asset, so an installer arriving without one is either
    a release built wrong or a download that has been tampered with, and the two
    are indistinguishable from here. Refusing is the only answer that cannot end
    in running somebody else's executable.

    The check is done by `check()` first, so this never trusts a URL from the
    page: the address and the digest both come from GitHub's own reply, in this
    process, a moment earlier.
    """
    info = info or await check(force=False)
    if info.reason:
        return {"ok": False, "reason": info.reason, "path": "", "name": "", "size": 0}
    if not info.available:
        return {"ok": False, "reason": "current", "path": "", "name": "", "size": 0}
    asset = info.asset or {}
    url = str(asset.get("url") or "")
    name = str(asset.get("name") or "")
    if not url or not name.lower().endswith(".msi"):
        return {"ok": False, "reason": "no_installer", "path": "", "name": "", "size": 0}

    wanted = expected_digest(str(asset.get("digest") or ""))
    if not wanted:
        logger.warning("The release carries no sha256 digest, so nothing was downloaded.")
        return {"ok": False, "reason": "no_digest", "path": "", "name": name, "size": 0}

    # The name comes from GitHub, so it is not a path -- only its final segment
    # is kept. A release named `../../windows/system32/x.msi` would otherwise
    # write outside the directory the window is allowed to run from.
    safe = Path(name).name
    target = download_dir() / safe
    part = target.with_suffix(target.suffix + ".part")

    owned = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        async with http.stream("GET", url) as response:
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "reason": "server",
                    "path": "",
                    "name": safe,
                    "size": 0,
                }
            with part.open("wb") as handle:
                async for block in response.aiter_bytes(1024 * 1024):
                    handle.write(block)
    except Exception as exc:  # noqa: BLE001 - offline is an answer, not a crash
        logger.debug(f"Could not download the update: {exc}")
        part.unlink(missing_ok=True)
        return {"ok": False, "reason": "offline", "path": "", "name": safe, "size": 0}
    finally:
        if owned:
            await http.aclose()

    got = _sha256(part)
    if got != wanted:
        # Deleted rather than kept: a file that failed verification must not be
        # sitting in the one directory the window will run an installer from.
        part.unlink(missing_ok=True)
        logger.warning("The downloaded installer did not match the published digest.")
        return {"ok": False, "reason": "digest", "path": "", "name": safe, "size": 0}

    part.replace(target)
    return {
        "ok": True,
        "reason": "",
        "path": str(target),
        "name": safe,
        "size": target.stat().st_size,
        "version": info.latest,
    }
