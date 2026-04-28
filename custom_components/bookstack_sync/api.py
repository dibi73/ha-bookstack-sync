"""BookStack API client."""

from __future__ import annotations

import asyncio
import socket
from http import HTTPStatus
from typing import Any

import aiohttp

from .const import LOGGER

REQUEST_TIMEOUT = 15
PAGE_SIZE = 500
MAX_REQUEST_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 0.5

# Connection-level errors that BookStack's reverse proxy or aiohttp's
# keep-alive pool can hand us mid-flight on long sync runs. They are
# safe to retry: the request either never reached BookStack or BookStack
# itself dropped the connection before responding.
_TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
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


def _raise_for_status(response: aiohttp.ClientResponse) -> None:
    if response.status in (401, 403):
        msg = f"BookStack rejected the API token (HTTP {response.status})"
        raise BookStackApiAuthError(msg)
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

    async def create_page(
        self,
        name: str,
        markdown: str,
        *,
        book_id: int | None = None,
        chapter_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Create a markdown page either at book-level or inside a chapter.

        Exactly one of ``book_id`` and ``chapter_id`` must be provided.
        """
        if (book_id is None) == (chapter_id is None):
            msg = "create_page needs exactly one of book_id or chapter_id"
            raise BookStackApiError(msg)
        body: dict[str, Any] = {"name": name, "markdown": markdown}
        if chapter_id is not None:
            body["chapter_id"] = chapter_id
        else:
            body["book_id"] = book_id
        return await self._request("post", "/api/pages", json=body)

    async def update_page(
        self,
        page_id: int,
        name: str,
        markdown: str,
        *,
        chapter_id: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing markdown page; optionally move it to a chapter."""
        body: dict[str, Any] = {"name": name, "markdown": markdown}
        if chapter_id is not None:
            body["chapter_id"] = chapter_id
        return await self._request("put", f"/api/pages/{page_id}", json=body)

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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Token {self._token_id}:{self._token_secret}",
            "Accept": "application/json",
        }
        last_err: Exception | None = None
        for attempt in range(MAX_REQUEST_ATTEMPTS):
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    response = await self._session.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json,
                        headers=headers,
                    )
                    _raise_for_status(response)
                    if response.status == HTTPStatus.NO_CONTENT:
                        return {}
                    # Don't gate on Content-Length: BookStack uses chunked
                    # transfer encoding, so content_length is None even when
                    # there is a JSON body to parse.
                    return await response.json()
            except BookStackApiError:
                raise
            except (TimeoutError, *_TRANSIENT_ERRORS) as err:
                last_err = err
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
                        err,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                msg = (
                    f"BookStack request failed after {MAX_REQUEST_ATTEMPTS} "
                    f"attempts: {err}"
                )
                raise BookStackApiCommunicationError(msg) from err
            except (aiohttp.ClientError, socket.gaierror) as err:
                msg = f"BookStack request failed: {err}"
                raise BookStackApiCommunicationError(msg) from err
        # The retry loop above either returns, raises, or reaches its final
        # iteration which always raises. This line is purely a safety net.
        msg = f"BookStack request retry loop exited unexpectedly: {last_err}"
        raise BookStackApiCommunicationError(msg)
