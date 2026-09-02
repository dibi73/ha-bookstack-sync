"""Tests for the BookStack Sync config flow.

Covers the three big paths: happy path through both steps, auth error on
the URL/token step, no-books detection. Reauth is sketched too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.config_entries import SOURCE_REAUTH

from custom_components.bookstack_sync.api import (
    BookStackApiAuthError,
    BookStackApiCommunicationError,
)
from custom_components.bookstack_sync.const import (
    CONF_BASE_URL,
    CONF_BOOK_ID,
    CONF_EXPORT_ENABLED,
    CONF_EXTERNAL_BASE_URL,
    CONF_OUTPUT_LANGUAGE,
    CONF_SYNC_INTERVAL,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_VERIFY_SSL,
    DOMAIN,
    INTERVAL_DAILY,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_user_step_happy_path_to_book_step(hass: HomeAssistant) -> None:
    """Valid credentials advance to the book picker step."""
    with patch(
        "custom_components.bookstack_sync.config_flow.BookStackApiClient.list_books",
        new=AsyncMock(return_value=[{"id": 1, "name": "Hausdokumentation"}]),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_BASE_URL: "http://bookstack.local:6875",
                CONF_TOKEN_ID: "tid",
                CONF_TOKEN_SECRET: "tsec",
                CONF_VERIFY_SSL: True,
            },
        )
    assert result2["type"] == data_entry_flow.FlowResultType.FORM
    assert result2["step_id"] == "book"


async def test_user_step_auth_error_shows_form_with_error(
    hass: HomeAssistant,
) -> None:
    with patch(
        "custom_components.bookstack_sync.config_flow.BookStackApiClient.list_books",
        new=AsyncMock(side_effect=BookStackApiAuthError("nope")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_BASE_URL: "http://bookstack.local:6875",
                CONF_TOKEN_ID: "tid",
                CONF_TOKEN_SECRET: "wrong",
                CONF_VERIFY_SSL: True,
            },
        )
    assert result2["type"] == data_entry_flow.FlowResultType.FORM
    assert result2["errors"] == {"base": "auth"}


async def test_user_step_connection_error_shows_form_with_error(
    hass: HomeAssistant,
) -> None:
    with patch(
        "custom_components.bookstack_sync.config_flow.BookStackApiClient.list_books",
        new=AsyncMock(side_effect=BookStackApiCommunicationError("down")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_BASE_URL: "http://bookstack.local:6875",
                CONF_TOKEN_ID: "tid",
                CONF_TOKEN_SECRET: "tsec",
                CONF_VERIFY_SSL: True,
            },
        )
    assert result2["errors"] == {"base": "connection"}


async def test_user_step_no_books_shows_dedicated_error(
    hass: HomeAssistant,
) -> None:
    with patch(
        "custom_components.bookstack_sync.config_flow.BookStackApiClient.list_books",
        new=AsyncMock(return_value=[]),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_BASE_URL: "http://bookstack.local:6875",
                CONF_TOKEN_ID: "tid",
                CONF_TOKEN_SECRET: "tsec",
                CONF_VERIFY_SSL: True,
            },
        )
    assert result2["errors"] == {"base": "no_books"}


async def test_book_step_creates_entry(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.bookstack_sync.config_flow.BookStackApiClient.list_books",
        new=AsyncMock(return_value=[{"id": 7, "name": "Hausdokumentation"}]),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_BASE_URL: "http://bookstack.local:6875",
                CONF_TOKEN_ID: "tid",
                CONF_TOKEN_SECRET: "tsec",
                CONF_VERIFY_SSL: True,
            },
        )
        # Async setup of the entry will run; we don't care about its
        # success here, only that the flow finishes with CREATE_ENTRY.
        with patch(
            "custom_components.bookstack_sync.async_setup_entry",
            new=AsyncMock(return_value=True),
        ):
            result3 = await hass.config_entries.flow.async_configure(
                result2["flow_id"],
                user_input={
                    CONF_BOOK_ID: "7",
                    CONF_SYNC_INTERVAL: INTERVAL_DAILY,
                },
            )
    assert result3["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result3["title"].startswith("BookStack")
    assert result3["data"][CONF_BOOK_ID] == 7
    assert result3["options"][CONF_SYNC_INTERVAL] == INTERVAL_DAILY


async def test_reauth_flow_updates_token(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Reauth replaces just the token credentials; URL stays."""
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.bookstack_sync.config_flow.BookStackApiClient.list_books",
        new=AsyncMock(return_value=[{"id": 1, "name": "Hausdokumentation"}]),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": SOURCE_REAUTH,
                "entry_id": config_entry.entry_id,
            },
            data=config_entry.data,
        )
        assert result["step_id"] == "reauth_confirm"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_TOKEN_ID: "newid",
                CONF_TOKEN_SECRET: "newsecret",
            },
        )

    assert result2["type"] == data_entry_flow.FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKEN_ID] == "newid"
    assert config_entry.data[CONF_TOKEN_SECRET] == "newsecret"


def _options_submission(**overrides: object) -> dict[str, object]:
    """Minimal valid options-flow submission; export disabled to skip its checks."""
    base: dict[str, object] = {
        CONF_BOOK_ID: "1",
        CONF_SYNC_INTERVAL: INTERVAL_DAILY,
        CONF_OUTPUT_LANGUAGE: "de",
        CONF_EXPORT_ENABLED: False,
    }
    base.update(overrides)
    return base


async def test_options_flow_saves_external_base_url(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """#202: a valid external URL is persisted as-is."""
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.bookstack_sync.config_flow.BookStackApiClient.list_books",
        new=AsyncMock(return_value=[{"id": 1, "name": "Hausdokumentation"}]),
    ):
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input=_options_submission(
                **{CONF_EXTERNAL_BASE_URL: "https://bookstack.example.com"},
            ),
        )

    assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_EXTERNAL_BASE_URL] == "https://bookstack.example.com"


async def test_options_flow_external_base_url_optional(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """#202: leaving it blank keeps the previous client.base_url-only behaviour."""
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.bookstack_sync.config_flow.BookStackApiClient.list_books",
        new=AsyncMock(return_value=[{"id": 1, "name": "Hausdokumentation"}]),
    ):
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input=_options_submission(),
        )

    assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_EXTERNAL_BASE_URL] == ""


async def test_options_flow_rejects_invalid_external_base_url(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """#202: a scheme-less value is rejected the same way CONF_BASE_URL is."""
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.bookstack_sync.config_flow.BookStackApiClient.list_books",
        new=AsyncMock(return_value=[{"id": 1, "name": "Hausdokumentation"}]),
    ):
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input=_options_submission(
                **{CONF_EXTERNAL_BASE_URL: "not-a-url"},
            ),
        )

    assert result2["type"] == data_entry_flow.FlowResultType.FORM
    assert result2["errors"][CONF_EXTERNAL_BASE_URL] == "base_url_invalid_scheme"
