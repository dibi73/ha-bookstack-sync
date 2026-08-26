"""Shared fixtures for the bookstack_sync test suite."""

from __future__ import annotations

import functools
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bookstack_sync._strings import get_strings
from custom_components.bookstack_sync.const import (
    CONF_BASE_URL,
    CONF_BOOK_ID,
    CONF_SYNC_INTERVAL,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_VERIFY_SSL,
    DOMAIN,
    INTERVAL_DAILY,
)

if TYPE_CHECKING:
    from collections.abc import Generator


# aioresponses 0.7.9 (latest on PyPI) still constructs aiohttp.ClientResponse
# without the ``stream_writer`` keyword that aiohttp made required in the
# version HA 2026.8.3 pulls in (aiohttp>=3.14) — upstream hasn't caught up
# yet. ClientResponse.__init__ also reads ``stream_writer.output_size`` when
# ``writer`` (the real request-writer task) is None, which is always the
# case for a mocked response, so a plain ``None`` default isn't enough — a
# minimal stand-in with that one attribute is. The mocked responses in this
# test suite never touch real streaming beyond that.
# Safe to remove once aioresponses ships a fix for this.
class _FakeStreamWriter:
    output_size = 0


_orig_client_response_init = aiohttp.ClientResponse.__init__


@functools.wraps(_orig_client_response_init)
def _client_response_init_with_stream_writer_default(
    self: aiohttp.ClientResponse, *args: object, **kwargs: object
) -> None:
    kwargs.setdefault("stream_writer", _FakeStreamWriter())
    _orig_client_response_init(self, *args, **kwargs)


aiohttp.ClientResponse.__init__ = _client_response_init_with_stream_writer_default


@pytest.fixture
def fixed_now() -> datetime:
    """A stable timestamp so renderer output is byte-identical across runs."""
    return datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def strings_de() -> dict[str, str]:
    """German output strings used across renderer tests."""
    return get_strings("de")


@pytest.fixture
def strings_en() -> dict[str, str]:
    """English output strings used across renderer tests."""
    return get_strings("en")


# Allow this custom integration to be loaded by pytest-homeassistant-custom-component.
# Without this autouse fixture HA refuses to load custom_components/* in tests.
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: object,
) -> Generator[None]:
    """Enable custom integration loading for every test in this suite."""
    return


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A minimally populated MockConfigEntry that mirrors a real setup."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="BookStack: Hausdokumentation",
        unique_id="http://bookstack.local:6875",
        data={
            CONF_BASE_URL: "http://bookstack.local:6875",
            CONF_TOKEN_ID: "tid",
            CONF_TOKEN_SECRET: "tsec",
            CONF_BOOK_ID: 1,
            CONF_VERIFY_SSL: True,
        },
        options={
            CONF_SYNC_INTERVAL: INTERVAL_DAILY,
        },
    )
