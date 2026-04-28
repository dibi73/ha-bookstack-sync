"""
Localised strings for the BookStack output (page content + notifications).

This is intentionally a separate translation system from HA's own
``translations/*.json`` files: those localise the integration's UI
(config flow, sensor names, service descriptions). The strings in this
module localise what the integration *writes* into BookStack — page
titles, section headings, table column labels, the tombstone banner,
the persistent-notification body — so that an English-speaking user
on an English HA does not end up with a German-only wiki.

Add a new language by adding a fully-populated entry to ``_STRINGS``.
Falling back to English keeps every renderer call safe even on
unsupported locales.
"""

from __future__ import annotations

LANG_DE = "de"
LANG_EN = "en"
LANG_DEFAULT = LANG_EN

SUPPORTED_LANGUAGES: tuple[str, ...] = (LANG_DE, LANG_EN)


_STRINGS: dict[str, dict[str, str]] = {
    LANG_DE: {
        # Attribution + tombstone
        "attribution_template": ("_{attribution} – Stand {timestamp} UTC._"),
        "tombstone_attribution_template": (
            "_{attribution} – letzter Sync {timestamp} UTC._"
        ),
        "tombstone_warning": "⚠️ **Diese Seite ist verwaist.**",
        "tombstone_explanation_template": (
            "Das zugehörige Objekt existiert seit {date} nicht mehr in Home Assistant."
        ),
        "tombstone_manual_hint": (
            "Der manuelle Block unten bleibt unangetastet. Wenn die "
            "Notizen dort nicht mehr relevant sind, kannst du diese "
            "Seite manuell löschen."
        ),
        # Default manual-block placeholder
        "default_manual_body": (
            "_Notizen, die du hier zwischen den Markern einträgst, "
            "bleiben beim Sync erhalten._"
        ),
        # Page titles
        "title_overview": "Übersicht",
        "title_integrations": "Integrationen",
        "title_automations": "Automatisierungen",
        "title_scripts": "Skripte",
        "title_scenes": "Szenen",
        "title_addons": "Add-ons",
        "title_area_template": "Raum: {name}",
        "title_device_template": "Gerät: {name}",
        # Chapter titles + descriptions
        "chapter_areas_title": "Räume",
        "chapter_areas_description": (
            "Pro Raum eine Page mit den dort angesiedelten Geräten und Entities."
        ),
        "chapter_devices_title": "Geräte",
        "chapter_devices_description": (
            "Pro Gerät eine Page mit Stammdaten und allen zugehörigen Entities."
        ),
        # Section headings
        "section_statistics": "Statistik",
        "section_areas": "Räume",
        "section_categories": "Bereiche",
        "section_unassigned_devices": "Geräte ohne Raum-Zuordnung",
        "section_devices_in_area_template": "Geräte in {name}",
        "section_orphan_entities": "Entities ohne Geräte-Zuordnung",
        "section_master_data": "Stammdaten",
        "section_entities": "Entities",
        "section_addons_count_template": "Add-ons ({count})",
        "section_automations_count_template": "Automatisierungen ({count})",
        "section_scripts_count_template": "Skripte ({count})",
        "section_scenes_count_template": "Szenen ({count})",
        "section_integrations_count_template": "Integrationen ({count})",
        # Stats list labels (Übersicht)
        "stat_areas": "Areas",
        "stat_devices": "Geräte",
        "stat_entities": "Entities",
        "stat_integrations": "Integrationen",
        "stat_automations": "Automatisierungen",
        "stat_scripts": "Skripte",
        "stat_scenes": "Szenen",
        "stat_addons": "Add-ons",
        # Bundle-link labels (Übersicht "Bereiche" list)
        "bundle_integrations": "Integrationen",
        "bundle_automations": "Automatisierungen",
        "bundle_scripts": "Skripte",
        "bundle_scenes": "Szenen",
        "bundle_addons": "Add-ons",
        # Empty-state messages
        "empty_areas": "_Keine Areas konfiguriert._",
        "empty_devices_in_room": "_Keine Geräte in diesem Raum._",
        "empty_entities_in_device": "_Keine Entities zu diesem Gerät._",
        "empty_automations": "_Keine Automatisierungen vorhanden._",
        "empty_scripts": "_Keine Skripte vorhanden._",
        "empty_scenes": "_Keine Szenen vorhanden._",
        "empty_integrations": "_Keine Integrationen geladen._",
        "empty_addons": ("_Kein Supervisor verfügbar oder keine Add-ons installiert._"),
        # Device facts table
        "field_manufacturer": "Hersteller",
        "field_model": "Modell",
        "field_firmware": "Firmware",
        "field_hardware": "Hardware",
        "field_integrations": "Integrationen",
        "field_device_id": "Device-ID",
        "table_field_header": "Feld",
        "table_value_header": "Wert",
        # Addon table
        "addon_col_name": "Add-on",
        "addon_col_slug": "Slug",
        "addon_col_version": "Version",
        "addon_col_state": "Status",
        "addon_col_update": "Update",
        "addon_update_yes": "Ja",
        "addon_update_no": "nein",
        # Integration table
        "integration_col_name": "Integration",
        "integration_col_title": "Titel",
        "integration_col_state": "Status",
        "integration_col_source": "Quelle",
        "integration_col_devices": "Geräte",
        "integration_col_entities": "Entities",
        # Entity-line bits
        "entity_state_label": "State",
        "entity_topic_label": "Topic",
        "entity_disabled_marker": "_[disabled]_",
        # Automation/Script details
        "field_entity": "Entity",
        "field_status": "Status",
        "field_mode": "Modus",
        "field_last_triggered": "Letzter Trigger",
        # Bold / heading prefixes
        "label_entities": "Entities",
        # Notification
        "notification_title": "BookStack Sync",
        "notification_body_template": (
            "BookStack-Sync abgeschlossen:\n\n"
            "- {created} angelegt\n"
            "- {updated} aktualisiert\n"
            "- {unchanged} unverändert\n"
            "- {tombstoned} verwaist (Tombstone)\n"
            "- {skipped} mit Konflikt übersprungen\n"
            "- {errors} Fehler"
        ),
    },
    LANG_EN: {
        "attribution_template": ("_{attribution} – synced at {timestamp} UTC._"),
        "tombstone_attribution_template": (
            "_{attribution} – last sync {timestamp} UTC._"
        ),
        "tombstone_warning": "⚠️ **This page is orphaned.**",
        "tombstone_explanation_template": (
            "The associated object no longer exists in Home Assistant since {date}."
        ),
        "tombstone_manual_hint": (
            "The manual block below stays untouched. If the notes "
            "there are no longer relevant you can delete this page "
            "manually."
        ),
        "default_manual_body": (
            "_Notes you put between the markers here are preserved across syncs._"
        ),
        "title_overview": "Overview",
        "title_integrations": "Integrations",
        "title_automations": "Automations",
        "title_scripts": "Scripts",
        "title_scenes": "Scenes",
        "title_addons": "Add-ons",
        "title_area_template": "Area: {name}",
        "title_device_template": "Device: {name}",
        "chapter_areas_title": "Areas",
        "chapter_areas_description": (
            "One page per area with all the devices and entities located there."
        ),
        "chapter_devices_title": "Devices",
        "chapter_devices_description": (
            "One page per device with master data and all its entities."
        ),
        "section_statistics": "Statistics",
        "section_areas": "Areas",
        "section_categories": "Sections",
        "section_unassigned_devices": "Devices without area",
        "section_devices_in_area_template": "Devices in {name}",
        "section_orphan_entities": "Entities without a device",
        "section_master_data": "Master data",
        "section_entities": "Entities",
        "section_addons_count_template": "Add-ons ({count})",
        "section_automations_count_template": "Automations ({count})",
        "section_scripts_count_template": "Scripts ({count})",
        "section_scenes_count_template": "Scenes ({count})",
        "section_integrations_count_template": "Integrations ({count})",
        "stat_areas": "Areas",
        "stat_devices": "Devices",
        "stat_entities": "Entities",
        "stat_integrations": "Integrations",
        "stat_automations": "Automations",
        "stat_scripts": "Scripts",
        "stat_scenes": "Scenes",
        "stat_addons": "Add-ons",
        "bundle_integrations": "Integrations",
        "bundle_automations": "Automations",
        "bundle_scripts": "Scripts",
        "bundle_scenes": "Scenes",
        "bundle_addons": "Add-ons",
        "empty_areas": "_No areas configured._",
        "empty_devices_in_room": "_No devices in this area._",
        "empty_entities_in_device": "_No entities on this device._",
        "empty_automations": "_No automations defined._",
        "empty_scripts": "_No scripts defined._",
        "empty_scenes": "_No scenes defined._",
        "empty_integrations": "_No integrations loaded._",
        "empty_addons": ("_No Supervisor available or no add-ons installed._"),
        "field_manufacturer": "Manufacturer",
        "field_model": "Model",
        "field_firmware": "Firmware",
        "field_hardware": "Hardware",
        "field_integrations": "Integrations",
        "field_device_id": "Device ID",
        "table_field_header": "Field",
        "table_value_header": "Value",
        "addon_col_name": "Add-on",
        "addon_col_slug": "Slug",
        "addon_col_version": "Version",
        "addon_col_state": "State",
        "addon_col_update": "Update",
        "addon_update_yes": "Yes",
        "addon_update_no": "no",
        "integration_col_name": "Integration",
        "integration_col_title": "Title",
        "integration_col_state": "State",
        "integration_col_source": "Source",
        "integration_col_devices": "Devices",
        "integration_col_entities": "Entities",
        "entity_state_label": "State",
        "entity_topic_label": "Topic",
        "entity_disabled_marker": "_[disabled]_",
        "field_entity": "Entity",
        "field_status": "State",
        "field_mode": "Mode",
        "field_last_triggered": "Last triggered",
        "label_entities": "Entities",
        "notification_title": "BookStack Sync",
        "notification_body_template": (
            "BookStack sync complete:\n\n"
            "- {created} created\n"
            "- {updated} updated\n"
            "- {unchanged} unchanged\n"
            "- {tombstoned} tombstoned\n"
            "- {skipped} skipped (conflict)\n"
            "- {errors} errors"
        ),
    },
}


def get_strings(lang: str | None) -> dict[str, str]:
    """
    Return the translation dict for ``lang``, falling back to English.

    Accepts the bare two-letter code (``"de"``) or longer locale strings
    (``"de-AT"``, ``"en_GB"``); only the leading two letters are used.
    """
    if lang:
        short = lang.split("-")[0].split("_")[0].lower()
        if short in _STRINGS:
            return _STRINGS[short]
    return _STRINGS[LANG_DEFAULT]


def normalise_language(lang: str | None) -> str:
    """Return the canonical two-letter code we'd resolve ``lang`` to."""
    if lang:
        short = lang.split("-")[0].split("_")[0].lower()
        if short in _STRINGS:
            return short
    return LANG_DEFAULT
