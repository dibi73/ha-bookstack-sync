"""BookStack API client."""

from __future__ import annotations

import asyncio
import socket
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import aiohttp

from .const import LOGGER

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

REQUEST_TIMEOUT = 15
PAGE_SIZE = 500
MAX_REQUEST_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 0.5

# #236: BookStack renders and stores the HTML of every page write
# server-side, so a multi-MB page can take far longer than a read of the
# same page. Writes get a timeout that grows with the body size instead
# of the flat REQUEST_TIMEOUT.
WRITE_TIMEOUT_BASE = 30.0
WRITE_TIMEOUT_PER_MB = 15.0
WRITE_TIMEOUT_MAX = 180.0

# Connection-level errors that BookStack's reverse proxy or aiohttp's
# keep-alive pool can hand us mid-flight on long sync runs. They are
# safe to retry: the request either never reached BookStack or BookStack
# itself dropped the connection before responding.
_TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    TimeoutError,
    aiohttp.ServerDisconnectedError,
    aiohttp.ClientConnectorError,
    aiohttp.ServerTimeoutError,
)


class BookStackApiError(Exception):
    """Generic BookStack API error."""


class BookStackApiAuthError(BookStackApiError):
    """Raised on 401/403 from BookStack."""


class BookStackApiCommunicationError(BookStackApiError):
    """Raised on network/timeout problems."""


class BookStackApiNotFoundError(BookStackApiCommunicationError):
    """
    Raised on 404 from BookStack.

    Subclass of ``BookStackApiCommunicationError`` so existing
    catch-all handlers keep working, but lets the sync orchestrator
    treat ``page deleted in BookStack`` as a recoverable-state
    instead of a hard failure: drop the stale mapping entry, recreate
    the page if the underlying HA object still exists.
    """


def _parse_retry_after(value: str | None) -> float | None:
    """
    Parse a ``Retry-After`` header (seconds only; no HTTP-date form).

    BookStack never sends the HTTP-date form. Returns ``None`` on
    anything unparseable so the caller falls back to its own
    exponential backoff.
    """
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _write_timeout(markdown: str) -> float:
    """Return the client-side timeout for writing a page of this size (#236)."""
    size_mb = len(markdown.encode()) / 1_000_000
    return min(WRITE_TIMEOUT_BASE + WRITE_TIMEOUT_PER_MB * size_mb, WRITE_TIMEOUT_MAX)


def _raise_for_status(response: aiohttp.ClientResponse) -> None:
    if response.status in (401, 403):
        msg = f"BookStack rejected the API token (HTTP {response.status})"
        raise BookStackApiAuthError(msg)
    if response.status == HTTPStatus.NOT_FOUND:
        # 404 = the resource we asked for is gone. Most common cause:
        # the user deleted a managed page directly in BookStack. The
        # sync layer recovers by dropping the mapping entry and
        # recreating the page on the next pass.
        msg = f"BookStack resource not found ({response.url.path})"
        raise BookStackApiNotFoundError(msg)
    response.raise_for_status()


class BookStackApiClient:
    """
    Minimal async BookStack REST client.

    BookStack auth header format: ``Authorization: Token <id>:<secret>``.
    See https://demo.bookstackapp.com/api/docs.
    """

    def __init__(
        self,
        base_url: str,
        token_id: str,
        token_secret: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Store credentials and the shared aiohttp session."""
        self._base_url = base_url.rstrip("/")
        self._token_id = token_id
        self._token_secret = token_secret
        self._session = session

    @property
    def base_url(self) -> str:
        """Return the BookStack base URL without trailing slash."""
        return self._base_url

    def _scrub(self, err: Exception) -> str:
        """
        Return a stringified ``err`` with the BookStack URL / hostname masked.

        Why: aiohttp's ``ClientResponseError`` includes the full request URL
        in its repr; ``socket.gaierror`` includes the hostname. Both end up
        in ``home-assistant.log`` via ``LOGGER.exception`` and via
        ``UpdateFailed(str(err))`` rendered in HA's notifications. The token
        itself never travels via URL (it's in the ``Authorization`` header),
        but the hostname is potentially private and has no place leaking
        into logs the user might paste into a forum.
        """
        text = str(err)
        text = text.replace(self._base_url, "<bookstack>")
        host = urlparse(self._base_url).hostname
        if host:
            text = text.replace(host, "<bookstack>")
        return text

    def _describe(self, err: Exception, timeout: float) -> str:
        """
        Return a scrubbed, never-empty description of a transient error.

        ``TimeoutError`` stringifies to ``""``, which left the retry
        warnings reading ``transient error (attempt 1/3): ;`` (#236).
        """
        if isinstance(err, TimeoutError) and not str(err):
            return f"no response within {timeout:.0f}s"
        return self._scrub(err) or type(err).__name__

    async def _verify_write(
        self,
        method: str,
        path: str,
        verify: Callable[[], Awaitable[dict[str, Any] | None]],
    ) -> dict[str, Any] | None:
        """Run a post-timeout write check; ``None`` if unconfirmed (#236)."""
        try:
            written = await verify()
        except BookStackApiError as err:
            LOGGER.warning(
                "BookStack %s %s timed out and the follow-up check failed "
                "too (%s); treating the write as not applied",
                method.upper(),
                path,
                err,
            )
            return None
        if written is not None:
            LOGGER.info(
                "BookStack %s %s timed out on the client side, but BookStack "
                "had already applied the write; not retrying",
                method.upper(),
                path,
            )
        return written

    async def list_books(self) -> list[dict[str, Any]]:
        """Return all books visible to the configured token."""
        return await self._list_paginated("/api/books")

    async def list_book_pages(self, book_id: int) -> list[dict[str, Any]]:
        """Return all pages in the given book."""
        return await self._list_paginated(
            "/api/pages",
            params={"filter[book_id]": str(book_id)},
        )

    async def list_chapters(self, book_id: int) -> list[dict[str, Any]]:
        """Return all chapters in the given book."""
        return await self._list_paginated(
            "/api/chapters",
            params={"filter[book_id]": str(book_id)},
        )

    async def create_chapter(
        self,
        book_id: int,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new chapter inside the given book."""
        body: dict[str, Any] = {"book_id": book_id, "name": name}
        if description:
            body["description"] = description
        return await self._request("post", "/api/chapters", json=body)

    async def get_page(self, page_id: int) -> dict[str, Any]:
        """Fetch a single page including markdown body."""
        return await self._request("get", f"/api/pages/{page_id}")

    async def create_page(  # noqa: PLR0913 - all keyword-only, one per BookStack field
        self,
        name: str,
        markdown: str,
        *,
        book_id: int | None = None,
        chapter_id: int | None = None,
        tags: list[dict[str, str]] | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """
        Create a markdown page either at book-level or inside a chapter.

        Exactly one of ``book_id`` and ``chapter_id`` must be provided.
        ``tags`` is forwarded as BookStack's tag array
        (``[{"name": "...", "value": "..."}]``). ``priority`` sets the
        page's sidebar position within its parent (#185); omitted when
        ``None`` so callers that don't manage ordering leave BookStack's
        default (append-at-end) behaviour untouched.
        """
        if (book_id is None) == (chapter_id is None):
            msg = "create_page needs exactly one of book_id or chapter_id"
            raise BookStackApiError(msg)
        # ``editor: "markdown"`` is sent defensively (v0.14.9): newer
        # BookStack versions honour it as a per-page editor pin so the
        # WYSIWYG toggle in the UI either disappears or warns the user;
        # older versions silently ignore unknown fields, so this never
        # breaks. The TinyMCE HTML round-trip drops our ``<!-- BEGIN -->``
        # marker comments; pinning the editor is the cleanest way to
        # prevent the corruption upfront. The ``markers_missing`` repair
        # issue and the manual-block placeholder both still warn the
        # user explicitly because BookStack's per-page editor pin is
        # advisory, not enforced.
        body: dict[str, Any] = {
            "name": name,
            "markdown": markdown,
            "editor": "markdown",
        }
        if chapter_id is not None:
            body["chapter_id"] = chapter_id
        else:
            body["book_id"] = book_id
        if tags is not None:
            body["tags"] = tags
        if priority is not None:
            body["priority"] = priority

        async def _find_created_page() -> dict[str, Any] | None:
            # #236: a timed-out POST may still have created the page.
            # Retrying blindly would create a duplicate, so look for a
            # page with the same name and body in the same parent first.
            # Matching on content rather than timestamps keeps this
            # independent of clock skew between HA and BookStack.
            parent = (
                {"filter[chapter_id]": str(chapter_id)}
                if chapter_id is not None
                else {"filter[book_id]": str(book_id)}
            )
            candidates = await self._list_paginated(
                "/api/pages",
                params={"filter[name]": name, **parent},
            )
            for candidate in sorted(candidates, key=lambda p: p["id"], reverse=True):
                page = await self.get_page(candidate["id"])
                if page.get("markdown") == markdown:
                    return page
            return None

        return await self._request(
            "post",
            "/api/pages",
            json=body,
            request_timeout=_write_timeout(markdown),
            verify_after_timeout=_find_created_page,
        )

    async def update_page(  # noqa: PLR0913 - all keyword-only, one per BookStack field
        self,
        page_id: int,
        name: str,
        markdown: str,
        *,
        chapter_id: int | None = None,
        tags: list[dict[str, str]] | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """
        Update an existing markdown page; optionally move it to a chapter.

        ``tags`` is forwarded as BookStack's tag array
        (``[{"name": "...", "value": "..."}]``); BookStack overwrites the
        full tag set on update, so passing the full intended list each
        write keeps things idempotent. ``priority`` is likewise sent
        whenever the caller manages ordering for this page (#185).

        ``editor: "markdown"`` is repeated on every update so a page
        that was switched to WYSIWYG between syncs gets pulled back to
        the markdown editor on the next write — see ``create_page`` for
        the rationale.
        """
        body: dict[str, Any] = {
            "name": name,
            "markdown": markdown,
            "editor": "markdown",
        }
        if chapter_id is not None:
            body["chapter_id"] = chapter_id
        if tags is not None:
            body["tags"] = tags
        if priority is not None:
            body["priority"] = priority

        async def _page_already_written() -> dict[str, Any] | None:
            # #236: BookStack usually finishes a timed-out PUT anyway. If
            # the page already holds what we sent, the write went through
            # and re-sending the full body would only add another revision.
            page = await self.get_page(page_id)
            if page.get("name") == name and page.get("markdown") == markdown:
                return page
            return None

        return await self._request(
            "put",
            f"/api/pages/{page_id}",
            json=body,
            request_timeout=_write_timeout(markdown),
            verify_after_timeout=_page_already_written,
        )

    async def _list_paginated(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page_params = {"count": str(PAGE_SIZE), "offset": str(offset)}
            if params:
                page_params.update(params)
            payload = await self._request("get", path, params=page_params)
            data = payload.get("data", [])
            items.extend(data)
            if len(data) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        return items

    async def _request(  # noqa: PLR0913 - keyword-only request options
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        request_timeout: float = REQUEST_TIMEOUT,
        verify_after_timeout: Callable[[], Awaitable[dict[str, Any] | None]]
        | None = None,
    ) -> dict[str, Any]:
        """
        Send one request, retrying transient errors with backoff.

        ``verify_after_timeout`` (#236) is for writes: after a timeout it
        checks whether BookStack applied the write anyway and returns the
        resulting page if so, which then counts as success instead of a
        retry. Returning ``None`` means the write did not happen and the
        normal retry continues.
        """
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Token {self._token_id}:{self._token_secret}",
            "Accept": "application/json",
        }
        last_err: Exception | None = None
        for attempt in range(MAX_REQUEST_ATTEMPTS):
            try:
                async with asyncio.timeout(request_timeout):
                    response = await self._session.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json,
                        headers=headers,
                    )
                    if response.status == HTTPStatus.TOO_MANY_REQUESTS:
                        # #210: parallel sync workers can occasionally brush
                        # against BookStack's default 180 req/min limit even
                        # with the shared rate limiter's own headroom -
                        # honour Retry-After when BookStack sends one,
                        # otherwise fall back to the same exponential
                        # backoff as a transient network error.
                        remaining = MAX_REQUEST_ATTEMPTS - attempt - 1
                        if remaining > 0:
                            retry_after = _parse_retry_after(
                                response.headers.get("Retry-After"),
                            )
                            backoff = (
                                retry_after
                                if retry_after is not None
                                else RETRY_BACKOFF_BASE * (2**attempt)
                            )
                            LOGGER.warning(
                                "BookStack %s %s rate-limited (attempt %d/%d); "
                                "retrying in %.1fs",
                                method.upper(),
                                path,
                                attempt + 1,
                                MAX_REQUEST_ATTEMPTS,
                                backoff,
                            )
                            await asyncio.sleep(backoff)
                            continue
                        msg = (
                            f"BookStack rate-limited the request after "
                            f"{MAX_REQUEST_ATTEMPTS} attempts"
                        )
                        raise BookStackApiCommunicationError(msg)
                    _raise_for_status(response)
                    if response.status == HTTPStatus.NO_CONTENT:
                        return {}
                    # Don't gate on Content-Length: BookStack uses chunked
                    # transfer encoding, so content_length is None even when
                    # there is a JSON body to parse.
                    payload: dict[str, Any] = await response.json()
                    return payload
            except BookStackApiError:
                raise
            except _TRANSIENT_ERRORS as err:
                last_err = err
                reason = self._describe(err, request_timeout)
                if isinstance(err, TimeoutError) and verify_after_timeout:
                    written = await self._verify_write(
                        method, path, verify_after_timeout
                    )
                    if written is not None:
                        return written
                remaining = MAX_REQUEST_ATTEMPTS - attempt - 1
                if remaining > 0:
                    backoff = RETRY_BACKOFF_BASE * (2**attempt)
                    LOGGER.warning(
                        "BookStack %s %s transient error (attempt %d/%d): %s; "
                        "retrying in %.1fs",
                        method.upper(),
                        path,
                        attempt + 1,
                        MAX_REQUEST_ATTEMPTS,
                        reason,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                msg = (
                    f"BookStack request failed after {MAX_REQUEST_ATTEMPTS} "
                    f"attempts: {reason}"
                )
                raise BookStackApiCommunicationError(msg) from err
            except (aiohttp.ClientError, socket.gaierror) as err:
                msg = f"BookStack request failed: {self._scrub(err)}"
                raise BookStackApiCommunicationError(msg) from err
        # The retry loop above either returns, raises, or reaches its final
        # iteration which always raises. This line is purely a safety net.
        scrubbed = self._scrub(last_err) if last_err else "no error captured"
        msg = f"BookStack request retry loop exited unexpectedly: {scrubbed}"
        raise BookStackApiCommunicationError(msg)
