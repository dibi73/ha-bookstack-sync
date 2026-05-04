"""Tests for the BookStack REST client.

Two real bugs we shipped to users hide here as regression tests:

* v0.1.2 — chunked-transfer responses without ``Content-Length`` were
  short-circuited to ``{}`` instead of being parsed.
* v0.2.2 — transient ``ServerDisconnectedError`` on long sync runs was
  treated as a hard failure instead of being retried.
"""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.bookstack_sync.api import (
    MAX_REQUEST_ATTEMPTS,
    BookStackApiAuthError,
    BookStackApiClient,
    BookStackApiCommunicationError,
    BookStackApiError,
)


@pytest.fixture
async def client() -> Any:
    """A client backed by a real (but unused-by-network) aiohttp session."""
    async with aiohttp.ClientSession() as session:
        yield BookStackApiClient(
            base_url="http://bookstack.local:6875",
            token_id="tid",
            token_secret="tsec",
            session=session,
        )


class TestBaseUrl:
    """URL handling."""

    def test_base_url_strips_trailing_slash(self) -> None:
        # Constructor does no IO, so a None session is enough to exercise it.
        client = BookStackApiClient(
            base_url="http://bookstack.local:6875/",
            token_id="x",
            token_secret="y",
            session=None,  # type: ignore[arg-type]
        )
        assert client.base_url == "http://bookstack.local:6875"


class TestAuth:
    """Authorization header format must match BookStack's expected `Token id:secret`."""

    async def test_auth_header_passed(self, client: BookStackApiClient) -> None:
        with aioresponses() as mocked:
            mocked.get(
                "http://bookstack.local:6875/api/books?count=500&offset=0",
                payload={"data": [], "total": 0},
            )
            await client.list_books()
            # aioresponses captures the requests for inspection
            request_history = mocked.requests
            (((_, _), call_list),) = list(request_history.items())
            assert call_list
            kwargs = call_list[0].kwargs
            headers = kwargs["headers"]
            assert headers["Authorization"] == "Token tid:tsec"
            assert headers["Accept"] == "application/json"

    async def test_401_raises_auth_error(self, client: BookStackApiClient) -> None:
        with aioresponses() as mocked:
            mocked.get(
                "http://bookstack.local:6875/api/books?count=500&offset=0",
                status=401,
                payload={"error": {"message": "Invalid token"}},
            )
            with pytest.raises(BookStackApiAuthError):
                await client.list_books()

    async def test_403_raises_auth_error(self, client: BookStackApiClient) -> None:
        with aioresponses() as mocked:
            mocked.get(
                "http://bookstack.local:6875/api/books?count=500&offset=0",
                status=403,
            )
            with pytest.raises(BookStackApiAuthError):
                await client.list_books()


class TestJsonParsing:
    """v0.1.2 regression: chunked responses must be parsed."""

    async def test_chunked_response_body_parsed(
        self,
        client: BookStackApiClient,
    ) -> None:
        # Regression: previously we returned {} when content_length was None
        # (which is the case for chunked encoding).
        with aioresponses() as mocked:
            mocked.get(
                "http://bookstack.local:6875/api/pages/42",
                payload={"id": 42, "name": "X", "markdown": "body"},
            )
            page = await client.get_page(42)
            assert page["id"] == 42
            assert page["markdown"] == "body"

    async def test_204_no_content_returns_empty_dict(
        self,
        client: BookStackApiClient,
    ) -> None:
        with aioresponses() as mocked:
            mocked.get(
                "http://bookstack.local:6875/api/pages/42",
                status=204,
            )
            assert await client.get_page(42) == {}


class TestPagination:
    """`_list_paginated` walks until BookStack returns < PAGE_SIZE items."""

    async def test_single_page_response(self, client: BookStackApiClient) -> None:
        with aioresponses() as mocked:
            mocked.get(
                "http://bookstack.local:6875/api/books?count=500&offset=0",
                payload={"data": [{"id": 1, "name": "A"}], "total": 1},
            )
            books = await client.list_books()
            assert [b["id"] for b in books] == [1]

    async def test_filter_param_passed_through(
        self,
        client: BookStackApiClient,
    ) -> None:
        with aioresponses() as mocked:
            mocked.get(
                "http://bookstack.local:6875/api/pages?count=500&offset=0&filter%5Bbook_id%5D=42",
                payload={"data": [], "total": 0},
            )
            await client.list_book_pages(42)


class TestCreatePage:
    """`create_page` enforces book_id XOR chapter_id."""

    async def test_book_only(self, client: BookStackApiClient) -> None:
        with aioresponses() as mocked:
            mocked.post(
                "http://bookstack.local:6875/api/pages",
                payload={"id": 11, "name": "P"},
            )
            res = await client.create_page("P", "body", book_id=5)
            assert res["id"] == 11

    async def test_chapter_only(self, client: BookStackApiClient) -> None:
        with aioresponses() as mocked:
            mocked.post(
                "http://bookstack.local:6875/api/pages",
                payload={"id": 12, "name": "P"},
            )
            res = await client.create_page("P", "body", chapter_id=8)
            assert res["id"] == 12

    async def test_both_raises(self, client: BookStackApiClient) -> None:
        with pytest.raises(BookStackApiError):
            await client.create_page("P", "body", book_id=5, chapter_id=8)

    async def test_neither_raises(self, client: BookStackApiClient) -> None:
        with pytest.raises(BookStackApiError):
            await client.create_page("P", "body")

    async def test_pins_markdown_editor(self, client: BookStackApiClient) -> None:
        # v0.14.9: every create call sends `editor: "markdown"` so newer
        # BookStack versions hide / disable the WYSIWYG toggle on the
        # resulting page. Older versions silently ignore the field.
        with aioresponses() as mocked:
            mocked.post(
                "http://bookstack.local:6875/api/pages",
                payload={"id": 11, "name": "P"},
            )
            await client.create_page("P", "body", book_id=5)
            request_kwargs = next(iter(mocked.requests.values()))[0].kwargs
            assert request_kwargs["json"]["editor"] == "markdown"
            assert request_kwargs["json"]["markdown"] == "body"


class TestUpdatePage:
    """`update_page` optionally moves the page via chapter_id."""

    async def test_update_without_move(self, client: BookStackApiClient) -> None:
        with aioresponses() as mocked:
            mocked.put(
                "http://bookstack.local:6875/api/pages/42",
                payload={"id": 42, "name": "P"},
            )
            await client.update_page(42, "P", "body")

    async def test_update_with_chapter_move(
        self,
        client: BookStackApiClient,
    ) -> None:
        with aioresponses() as mocked:
            mocked.put(
                "http://bookstack.local:6875/api/pages/42",
                payload={"id": 42, "name": "P"},
            )
            await client.update_page(42, "P", "body", chapter_id=99)

    async def test_pins_markdown_editor(
        self,
        client: BookStackApiClient,
    ) -> None:
        # v0.14.9: every update call sends `editor: "markdown"` so a page
        # that was switched to WYSIWYG between syncs gets pinned back.
        with aioresponses() as mocked:
            mocked.put(
                "http://bookstack.local:6875/api/pages/42",
                payload={"id": 42, "name": "P"},
            )
            await client.update_page(42, "P", "body")
            request_kwargs = next(iter(mocked.requests.values()))[0].kwargs
            assert request_kwargs["json"]["editor"] == "markdown"


class TestRetryOnTransientErrors:
    """v0.2.2 regression: transient errors must be retried."""

    async def test_server_disconnect_then_success(
        self,
        client: BookStackApiClient,
    ) -> None:
        with aioresponses() as mocked:
            # First attempt: BookStack drops the connection mid-flight.
            mocked.get(
                "http://bookstack.local:6875/api/pages/42",
                exception=aiohttp.ServerDisconnectedError(),
            )
            # Second attempt: clean response.
            mocked.get(
                "http://bookstack.local:6875/api/pages/42",
                payload={"id": 42, "name": "P"},
            )
            page = await client.get_page(42)
            assert page["id"] == 42

    async def test_persistent_disconnect_eventually_raises(
        self,
        client: BookStackApiClient,
    ) -> None:
        with aioresponses() as mocked:
            for _ in range(MAX_REQUEST_ATTEMPTS):
                mocked.get(
                    "http://bookstack.local:6875/api/pages/42",
                    exception=aiohttp.ServerDisconnectedError(),
                )
            with pytest.raises(BookStackApiCommunicationError):
                await client.get_page(42)

    async def test_500_does_not_retry(self, client: BookStackApiClient) -> None:
        # 500 is an aiohttp.ClientResponseError, NOT a transient error -
        # it indicates a real server-side problem we shouldn't retry blindly.
        with aioresponses() as mocked:
            mocked.get(
                "http://bookstack.local:6875/api/pages/42",
                status=500,
            )
            with pytest.raises(BookStackApiCommunicationError):
                await client.get_page(42)


class TestUrlScrubbing:
    """The BookStack URL/hostname must not leak into raised error messages."""

    async def test_500_error_message_does_not_contain_url_or_host(
        self,
        client: BookStackApiClient,
    ) -> None:
        with aioresponses() as mocked:
            mocked.get(
                "http://bookstack.local:6875/api/pages/42",
                status=500,
            )
            with pytest.raises(BookStackApiCommunicationError) as excinfo:
                await client.get_page(42)
            text = str(excinfo.value)
            assert "bookstack.local" not in text
            assert "http://bookstack.local:6875" not in text
            # Sanity: scrubbed placeholder is in there instead.
            assert "<bookstack>" in text

    async def test_persistent_disconnect_message_does_not_leak_host(
        self,
        client: BookStackApiClient,
    ) -> None:
        with aioresponses() as mocked:
            for _ in range(MAX_REQUEST_ATTEMPTS):
                mocked.get(
                    "http://bookstack.local:6875/api/pages/42",
                    exception=aiohttp.ServerDisconnectedError(),
                )
            with pytest.raises(BookStackApiCommunicationError) as excinfo:
                await client.get_page(42)
            assert "bookstack.local" not in str(excinfo.value)
