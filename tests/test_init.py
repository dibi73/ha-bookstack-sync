"""Tests for integration-lifecycle hooks in __init__.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bookstack_sync import (
    _migrate_external_base_url_to_data,
    async_remove_entry,
)
from custom_components.bookstack_sync.const import (
    CONF_EXTERNAL_BASE_URL,
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


async def test_migrate_external_base_url_moves_options_value_to_data(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """#214: a pre-#214 entry's options value moves to data exactly once."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            **config_entry.options,
            CONF_EXTERNAL_BASE_URL: "https://bookstack.example.com",
        },
    )

    _migrate_external_base_url_to_data(hass, config_entry)

    assert config_entry.data[CONF_EXTERNAL_BASE_URL] == "https://bookstack.example.com"
    assert CONF_EXTERNAL_BASE_URL not in config_entry.options


async def test_migrate_external_base_url_no_op_when_nothing_to_migrate(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """An entry that never used options.external_base_url is left untouched."""
    config_entry.add_to_hass(hass)

    _migrate_external_base_url_to_data(hass, config_entry)

    assert CONF_EXTERNAL_BASE_URL not in config_entry.data
    assert CONF_EXTERNAL_BASE_URL not in config_entry.options


async def test_migrate_external_base_url_does_not_overwrite_existing_data(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """An entry already migrated (or set via reconfigure) keeps its data value."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_EXTERNAL_BASE_URL: "https://already-migrated.example.com",
        },
        options={
            **config_entry.options,
            CONF_EXTERNAL_BASE_URL: "https://stale.example.com",
        },
    )

    _migrate_external_base_url_to_data(hass, config_entry)

    assert (
        config_entry.data[CONF_EXTERNAL_BASE_URL]
        == "https://already-migrated.example.com"
    )
