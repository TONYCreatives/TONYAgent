"""The update check: comparison, caching, and the ways it can find nothing.

The interesting half of this module is not "is 0.2.0 newer than 0.1.0". It is
that a check which cannot reach GitHub must not answer "you are up to date" --
the app would be claiming a fact it did not learn. So most of what is asserted
here is the *reason* a check produced, and that a cached answer survives the
network going away while still admitting it is old.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from tonyagent.core import update as update_module
from tonyagent.core.update import UpdateInfo, is_newer, parse_version


# --- comparing versions ------------------------------------------------------
def test_a_leading_v_is_optional():
    """GitHub tags are written both ways and the app should not care."""
    assert parse_version("v0.2.0") == (0, 2, 0)
    assert parse_version("0.2.0") == (0, 2, 0)
    assert parse_version("  v1.2.3  ") == (1, 2, 3)


def test_an_unparseable_tag_is_not_older_it_is_unknown():
    """**None and () are different, and the difference is a wrong update.

    An empty tuple compares as older than everything, so a repository that
    switched to date tags would report every release as an update -- forever,
    with no way for the user to make it stop.
    """
    assert parse_version("release-2026-10") is None
    assert parse_version("") is None
    assert parse_version("latest") is None
    assert is_newer("release-2026-10", "0.1.0") is False
    assert is_newer("0.2.0", "not-a-version") is False


def test_versions_compare_field_by_field():
    assert is_newer("0.2.0", "0.1.0") is True
    assert is_newer("v0.1.0", "0.1.0") is False
    assert is_newer("0.2", "0.1.9") is True, "a shorter version is not an older one"
    assert is_newer("1.0.0", "1.0") is False, "1.0 and 1.0.0 are the same version"
    assert is_newer("0.10.0", "0.9.0") is True, "string order would say otherwise"


# --- the release payload -----------------------------------------------------
def test_the_msi_asset_is_the_one_kept():
    """The installer is what an update would run, so it is what is recorded.

    Chosen by extension rather than by position: a release also carries a
    checksum file, and taking `assets[0]` would hand the updater a text file.
    """
    payload = update_module._release_payload(
        {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/x/y/releases/tag/v0.2.0",
            "assets": [
                {"name": "SHA256SUMS.txt", "size": 10, "browser_download_url": "u0"},
                {
                    "name": "TONYAgent-0.2.0.msi",
                    "size": 30000000,
                    "digest": "sha256:abc",
                    "browser_download_url": "u1",
                },
            ],
        }
    )
    assert payload["asset"] == {
        "name": "TONYAgent-0.2.0.msi",
        "size": 30000000,
        "digest": "sha256:abc",
        "url": "u1",
    }


def test_a_release_with_no_installer_is_still_a_release():
    """Reported, not refused: the notes and the page are worth showing even
    when there is nothing to download."""
    payload = update_module._release_payload({"tag_name": "v0.2.0", "assets": []})
    assert payload["asset"] is None
    assert payload["tag_name"] == "v0.2.0"


# --- the check ---------------------------------------------------------------
@pytest.fixture
def cache(tmp_path: Path, monkeypatch) -> Path:
    """Point the cache at a temp file so no test touches the real one."""
    path = tmp_path / "update.json"
    monkeypatch.setattr(update_module, "cache_path", lambda: path)
    return path


def _client(status: int, body: str = "", headers: dict | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, headers=headers or {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


RELEASE = {
    "tag_name": "v0.2.0",
    "prerelease": False,
    "body": "Fixes the pet.",
    "published_at": "2026-10-18T00:00:00Z",
    "html_url": "https://github.com/TONYCreatives/TONYAgent/releases/tag/v0.2.0",
    "assets": [
        {
            "name": "TONYAgent-0.2.0.msi",
            "size": 1,
            "digest": "sha256:deadbeef",
            "browser_download_url": "https://example.test/a.msi",
        }
    ],
}


async def test_a_newer_release_is_reported_with_its_notes(cache):
    async with _client(200, json.dumps(RELEASE), {"ETag": 'W/"x"'}) as http:
        info = await update_module.check(current="0.1.0", client=http)

    assert info.available is True
    assert info.latest == "v0.2.0"
    assert info.notes == "Fixes the pet."
    assert info.asset and info.asset["name"] == "TONYAgent-0.2.0.msi"
    assert info.asset["digest"] == "sha256:deadbeef"
    assert info.reason == ""
    assert info.cached is False
    assert cache.is_file(), "the answer was not cached, so the next launch asks again"


async def test_the_same_version_is_not_an_update(cache):
    same = dict(RELEASE, tag_name="v0.1.0")
    async with _client(200, json.dumps(same)) as http:
        info = await update_module.check(current="0.1.0", client=http)
    assert info.available is False
    assert info.reason == ""


async def test_offline_says_offline_and_not_up_to_date(cache):
    """**The whole point of `reason`.** A check that could not run has not
    learned that the app is current, and "up to date" would be a claim it
    cannot make."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        info = await update_module.check(current="0.1.0", client=http)

    assert info.reason == "offline"
    assert info.available is False
    assert info.understood is False


async def test_a_private_or_missing_repo_is_distinguishable_from_offline(cache):
    """One fixes itself when the network returns; the other needs somebody to
    change a repository setting. Collapsing them sends the user to check their
    wi-fi for a permissions problem."""
    async with _client(404, "{}") as http:
        info = await update_module.check(current="0.1.0", client=http)
    assert info.reason == "not_found"


async def test_a_rate_limit_is_reported_as_one(cache):
    """403 is GitHub's rate-limit status, and it is not the user's fault."""
    async with _client(403, "{}") as http:
        info = await update_module.check(current="0.1.0", client=http)
    assert info.reason == "rate_limited"


async def test_a_body_that_is_not_a_release_is_malformed(cache):
    async with _client(200, "<html>proxy</html>") as http:
        info = await update_module.check(current="0.1.0", client=http)
    assert info.reason == "malformed"

    async with _client(200, json.dumps({"message": "hi"})) as http:
        info = await update_module.check(current="0.1.0", client=http)
    assert info.reason == "malformed", "a JSON body with no tag is not a release"


async def test_a_second_check_within_the_day_does_not_ask_github(cache):
    """The cache is what keeps a daily check at one real request."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=json.dumps(RELEASE), headers={"ETag": 'W/"x"'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await update_module.check(current="0.1.0", client=http)
        again = await update_module.check(current="0.1.0", client=http)

    assert calls["n"] == 1, "the cached answer was not used"
    assert again.cached is True
    assert again.available is True


async def test_a_304_keeps_the_answer_and_costs_nothing(cache):
    """**Measured on the real API: a 304 does not consume the rate limit.**

    So the ETag is sent on every check and a check that finds nothing new is
    free. The stored answer must survive it, and `checked_at` must move so the
    next launch does not ask again.
    """
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers.get("if-none-match", ""))
        if request.headers.get("if-none-match"):
            return httpx.Response(304)
        return httpx.Response(200, text=json.dumps(RELEASE), headers={"ETag": 'W/"x"'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        first = await update_module.check(current="0.1.0", client=http)
        second = await update_module.check(current="0.1.0", force=True, client=http)

    assert sent[0] == "", "the first check has no ETag to send"
    assert sent[1] == 'W/"x"', "the ETag was not sent, so the 304 could never happen"
    assert second.available is True and second.latest == "v0.2.0"
    assert second.cached is True
    assert second.reason == "", "a 304 is a successful check, not a failure"


async def test_offline_keeps_the_last_known_answer_but_admits_it_is_stale(cache):
    """The fact did not stop being true because the network went away.

    So the cached release is carried along -- and `reason` stays set, because
    the app still does not know whether something newer was released since.
    """
    async with _client(200, json.dumps(RELEASE), {"ETag": 'W/"x"'}) as http:
        await update_module.check(current="0.1.0", client=http)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as http:
        info = await update_module.check(current="0.1.0", force=True, client=http)

    assert info.reason == "offline"
    assert info.available is True, "the known-newer release was thrown away"
    assert info.latest == "v0.2.0"
    assert info.cached is True


async def test_a_cache_that_cannot_be_parsed_is_not_an_error(cache):
    """A broken cache is a cache miss. Refusing to check would turn a stray
    byte in a scratch file into a broken feature."""
    cache.write_text("{not json", encoding="utf-8")
    async with _client(200, json.dumps(RELEASE)) as http:
        info = await update_module.check(current="0.1.0", client=http)
    assert info.available is True


async def test_a_stale_cache_is_asked_again(cache):
    """The freshness window has to expire, or the app never learns anything."""
    async with _client(200, json.dumps(RELEASE), {"ETag": 'W/"x"'}) as http:
        await update_module.check(current="0.1.0", client=http)

    stored = json.loads(cache.read_text(encoding="utf-8"))
    stored["payload"]["checked_at"] = time.time() - update_module.CACHE_SECONDS - 1
    cache.write_text(json.dumps(stored), encoding="utf-8")

    newer = dict(RELEASE, tag_name="v0.3.0")
    async with _client(200, json.dumps(newer), {"ETag": 'W/"y"'}) as http:
        info = await update_module.check(current="0.1.0", client=http)

    assert info.latest == "v0.3.0"
    assert info.cached is False


def test_the_default_answer_is_not_a_claim():
    """A bare `UpdateInfo` says nothing rather than saying "current"."""
    info = UpdateInfo()
    assert info.available is False
    assert info.understood is True, "no reason means the question was answered"
