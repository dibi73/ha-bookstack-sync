"""Tests for the repair-issue Fix flow (#190).

``_SinglePageFixFlow`` is exercised directly (constructed + populated
the same way the real ``RepairsFlowManager`` does: attributes set
after construction, not via a custom ``__init__``) rather than through
the full HA repairs UI machinery - same "test the orchestration, not
the framework" style as ``test_sync.py``/``test_coordinator.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from homeassistant.data_entry_flow import FlowResultType

from custom_components.bookstack_sync.api import BookStackApiError
from custom_components.bookstack_sync.const import DOMAIN
from custom_components.bookstack_sync.repairs import (
    _SinglePageFixFlow,
    async_create_fix_flow,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_async_create_fix_flow_parses_entry_id_and_page_key(
    hass: HomeAssistant,
) -> None:
    flow = await async_create_fix_flow(
        hass,
        "page_tampered_entry1_device:abc",
        {"entry_id": "entry1", "page_key": "device:abc"},
    )
    assert isinstance(flow, _SinglePageFixFlow)
    assert flow._entry_id == "entry1"
    assert flow._page_key == "device:abc"


async def test_async_create_fix_flow_defaults_when_data_missing(
    hass: HomeAssistant,
) -> None:
    """No ``data`` (e.g. a stale pre-#190 issue) -> empty strings, not a crash."""
    flow = await async_create_fix_flow(hass, "page_tampered_entry1_device:abc", None)
    assert flow._entry_id == ""
    assert flow._page_key == ""


async def test_confirm_step_shows_form_first(hass: HomeAssistant) -> None:
    """No ``user_input`` yet -> a form, not an immediate action."""
    flow = _SinglePageFixFlow(entry_id="entry1", page_key="device:abc")
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = "page_tampered_entry1_device:abc"

    result = await flow.async_step_confirm(None)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"


async def test_confirm_step_success_resyncs_and_creates_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    fix_page = AsyncMock(return_value=True)
    config_entry.runtime_data = type(
        "RD",
        (),
        {"coordinator": type("Coord", (), {"async_fix_single_page": fix_page})()},
    )()

    flow = _SinglePageFixFlow(entry_id=config_entry.entry_id, page_key="device:abc")
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = f"page_tampered_{config_entry.entry_id}_device:abc"

    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    fix_page.assert_awaited_once_with("device:abc")


async def test_confirm_step_aborts_when_entry_removed(hass: HomeAssistant) -> None:
    """The config entry vanished between the issue firing and the Fix click."""
    flow = _SinglePageFixFlow(entry_id="does-not-exist", page_key="device:abc")
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = "page_tampered_does-not-exist_device:abc"

    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"


async def test_confirm_step_aborts_when_page_gone(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """The device/area/label itself vanished from HA too -> nothing to fix."""
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = type(
        "RD",
        (),
        {
            "coordinator": type(
                "Coord",
                (),
                {"async_fix_single_page": AsyncMock(return_value=False)},
            )(),
        },
    )()

    flow = _SinglePageFixFlow(entry_id=config_entry.entry_id, page_key="device:gone")
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = f"page_tampered_{config_entry.entry_id}_device:gone"

    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "page_not_found"


async def test_confirm_step_aborts_when_resync_fails(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = type(
        "RD",
        (),
        {
            "coordinator": type(
                "Coord",
                (),
                {
                    "async_fix_single_page": AsyncMock(
                        side_effect=BookStackApiError("unreachable"),
                    ),
                },
            )(),
        },
    )()

    flow = _SinglePageFixFlow(entry_id=config_entry.entry_id, page_key="device:abc")
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = f"page_tampered_{config_entry.entry_id}_device:abc"

    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "resync_failed"
