"""BookStack API client."""

from __future__ import annotations

import asyncio
import socket
from http import HTTPStatus
from typing import Any

import aiohttp

REQUEST_TIMEOUT = 15
PAGE_SIZE = 500


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

    async def get_page(self, page_id: int) -> dict[str, Any]:
        """Fetch a single page including markdown body."""
        return await self._request("get", f"/api/pages/{page_id}")

    async def create_page(
        self,
        book_id: int,
        name: str,
        markdown: str,
    ) -> dict[str, Any]:
        """Create a markdown page inside the given book."""
        return await self._request(
            "post",
            "/api/pages",
            json={"book_id": book_id, "name": name, "markdown": markdown},
        )

    async def update_page(
        self,
        page_id: int,
        name: str,
        markdown: str,
    ) -> dict[str, Any]:
        """Update an existing markdown page."""
        return await self._request(
            "put",
            f"/api/pages/{page_id}",
            json={"name": name, "markdown": markdown},
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
        except TimeoutError as err:
            msg = f"BookStack request timed out: {err}"
            raise BookStackApiCommunicationError(msg) from err
        except (aiohttp.ClientError, socket.gaierror) as err:
            msg = f"BookStack request failed: {err}"
            raise BookStackApiCommunicationError(msg) from err
