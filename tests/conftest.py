"""Shared fixtures for the bookstack_sync test suite."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

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


@pytest.fixture
def fixed_now() -> datetime:
    """A stable timestamp so renderer output is byte-identical across runs."""
    return datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)


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
