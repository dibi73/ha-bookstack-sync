"""Tests for integration-lifecycle hooks in __init__.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bookstack_sync import async_remove_entry
from custom_components.bookstack_sync.const import (
    DOMAIN,
    REPAIR_ISSUE_TAMPERED,
    REPAIR_ISSUE_UNREACHABLE,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_async_remove_entry_deletes_only_this_entrys_issues(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """
    #186: removing a config entry must clean up its own repair issues.

    Repair issue IDs embed ``entry.entry_id`` but nothing previously told
    the issue registry those issues are orphaned once the entry is gone —
    confirmed live to leave hundreds of stale issues behind forever.
    Issues belonging to a DIFFERENT entry must survive untouched.
    """
    other_entry = MockConfigEntry(domain=DOMAIN, title="Other BookStack")
    config_entry.add_to_hass(hass)
    other_entry.add_to_hass(hass)

    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{REPAIR_ISSUE_TAMPERED}_{config_entry.entry_id}_device:abc",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=REPAIR_ISSUE_TAMPERED,
        translation_placeholders={"page_title": "removed-entry-page"},
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{REPAIR_ISSUE_UNREACHABLE}_{config_entry.entry_id}",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=REPAIR_ISSUE_UNREACHABLE,
        translation_placeholders={"count": "3"},
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{REPAIR_ISSUE_TAMPERED}_{other_entry.entry_id}_device:xyz",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=REPAIR_ISSUE_TAMPERED,
        translation_placeholders={"page_title": "surviving-entry-page"},
    )

    await async_remove_entry(hass, config_entry)

    issue_reg = ir.async_get(hass)
    remaining = {
        issue_id for (domain, issue_id) in issue_reg.issues if domain == DOMAIN
    }
    assert remaining == {
        f"{REPAIR_ISSUE_TAMPERED}_{other_entry.entry_id}_device:xyz",
    }
