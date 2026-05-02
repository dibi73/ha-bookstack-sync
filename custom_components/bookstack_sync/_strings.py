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
        "title_network": "Netzwerk",
        "title_bluetooth": "Bluetooth",
        "title_services": "Notify- und TTS-Services",
        "title_recorder": "Recorder-Konfiguration",
        "title_mqtt": "MQTT-Topics",
        "title_energy": "Energie-Dashboard",
        "title_helpers": "Helpers",
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
        "section_automations_in_area_template": "Automatisierungen in {name}",
        "section_scripts_in_area_template": "Skripte in {name}",
        "section_scenes_in_area_template": "Szenen in {name}",
        "section_orphan_entities": "Entities ohne Geräte-Zuordnung",
        "toc_label": "Inhalt",
        "section_network": "Netzwerk",
        "field_ip": "IP",
        "field_mac": "MAC",
        "field_hostname": "Hostname",
        "field_connection": "Verbindung",
        "field_vlan": "VLAN",
        "field_ssid": "SSID",
        "field_last_seen": "Letzter Kontakt",
        "connection_wired": "LAN",
        "connection_wireless": "WLAN",
        "connection_unknown": "unbekannt",
        "network_also_template": "auch: {values}",
        "section_master_data": "Stammdaten",
        "section_entities": "Entities",
        "section_addons_count_template": "Add-ons ({count})",
        "section_automations_count_template": "Automatisierungen ({count})",
        "section_scripts_count_template": "Skripte ({count})",
        "section_scenes_count_template": "Szenen ({count})",
        "section_integrations_count_template": "Integrationen ({count})",
        "section_network_count_template": "Geräte mit Netzwerkdaten ({count})",
        "section_dhcp_export": "DHCP-Reservierungen (zum Übernehmen in Router)",
        "section_unknown_clients_template": "Unbekannte Clients ({count})",
        "section_unknown_clients_intro": (
            "Geräte, die UniFi sieht aber HA nicht als Device führt — "
            "gut zum Aufräumen:"
        ),
        "section_topology": "Topologie",
        "topology_unsorted_label": "Nicht via UniFi getrackt",
        "section_notify_count_template": "Notify-Services ({count})",
        "section_tts_count_template": "TTS-Services ({count})",
        "section_recorder_basic": "Datenbank + Aufbewahrung",
        "section_recorder_excluded_domains": "Ausgeschlossene Domains",
        "section_recorder_excluded_entities": "Ausgeschlossene Entities",
        "section_recorder_included_domains": "Eingeschlossene Domains",
        "section_recorder_included_entities": "Eingeschlossene Entities",
        "recorder_field_engine": "DB-Engine",
        "recorder_field_url": "DB-URL",
        "recorder_field_keep_days": "Aufbewahrung (Tage)",
        "section_mqtt_count_template": "MQTT-Topics ({count} Entities)",
        "section_energy_sources": "Konfigurierte Energiequellen",
        "section_energy_devices": "Einzeln getrackte Verbraucher",
        "empty_helpers": "_Keine Helpers konfiguriert._",
        "section_used_by": "Verwendet in",
        "used_by_automations": "Automatisierungen",
        "used_by_scripts": "Skripte",
        "used_by_scenes": "Szenen",
        "used_by_via_group_template": " *(über Gruppe `{group}`)*",
        "network_col_hostname": "Hostname",
        "network_col_mac": "MAC",
        "network_col_ip": "IP",
        "network_col_connection": "Verbindung",
        "network_col_vlan": "SSID/VLAN",
        "network_col_last_seen": "Letzter Kontakt",
        "network_col_ap_switch": "AP / Switch-Port",
        "network_col_oui": "Hersteller (OUI)",
        "empty_network": "_Keine Geräte mit Netzwerkdaten gefunden._",
        "section_bluetooth_count_template": "Bluetooth-Scanner ({count})",
        "bt_local_label": "HA-Host (lokaler BT-Adapter)",
        "bt_proxy_label_template": "ESPHome-Proxy: {name}",
        "empty_bluetooth": "_Keine Bluetooth-Scanner / -Proxies gefunden._",
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
        "bundle_network": "Netzwerk",
        "bundle_bluetooth": "Bluetooth",
        "bundle_services": "Services (Notify/TTS)",
        "bundle_recorder": "Recorder",
        "bundle_mqtt": "MQTT",
        "bundle_energy": "Energie",
        "bundle_helpers": "Helpers",
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
        "integration_col_docs": "Doku",
        "integration_docs_link_label": "Doku",
        # Entity-line bits
        "entity_state_label": "State",
        "entity_topic_label": "Topic",
        "entity_disabled_marker": "_[disabled]_",
        "entity_stats_marker": "📊",
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
        "title_network": "Network",
        "title_bluetooth": "Bluetooth",
        "title_services": "Notify and TTS services",
        "title_recorder": "Recorder configuration",
        "title_mqtt": "MQTT topics",
        "title_energy": "Energy dashboard",
        "title_helpers": "Helpers",
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
        "section_automations_in_area_template": "Automations in {name}",
        "section_scripts_in_area_template": "Scripts in {name}",
        "section_scenes_in_area_template": "Scenes in {name}",
        "section_orphan_entities": "Entities without a device",
        "toc_label": "Contents",
        "section_network": "Network",
        "field_ip": "IP",
        "field_mac": "MAC",
        "field_hostname": "Hostname",
        "field_connection": "Connection",
        "field_vlan": "VLAN",
        "field_ssid": "SSID",
        "field_last_seen": "Last seen",
        "connection_wired": "Wired",
        "connection_wireless": "Wireless",
        "connection_unknown": "unknown",
        "network_also_template": "also: {values}",
        "section_master_data": "Master data",
        "section_entities": "Entities",
        "section_addons_count_template": "Add-ons ({count})",
        "section_automations_count_template": "Automations ({count})",
        "section_scripts_count_template": "Scripts ({count})",
        "section_scenes_count_template": "Scenes ({count})",
        "section_integrations_count_template": "Integrations ({count})",
        "section_network_count_template": "Devices with network data ({count})",
        "section_dhcp_export": "DHCP reservations (paste into your router)",
        "section_unknown_clients_template": "Unknown clients ({count})",
        "section_unknown_clients_intro": (
            "Devices UniFi sees but HA does not have as a registered "
            "device — useful for cleanup:"
        ),
        "section_topology": "Topology",
        "topology_unsorted_label": "Not tracked via UniFi",
        "section_notify_count_template": "Notify services ({count})",
        "section_tts_count_template": "TTS services ({count})",
        "section_recorder_basic": "Database + retention",
        "section_recorder_excluded_domains": "Excluded domains",
        "section_recorder_excluded_entities": "Excluded entities",
        "section_recorder_included_domains": "Included domains",
        "section_recorder_included_entities": "Included entities",
        "recorder_field_engine": "DB engine",
        "recorder_field_url": "DB URL",
        "recorder_field_keep_days": "Retention (days)",
        "section_mqtt_count_template": "MQTT topics ({count} entities)",
        "section_energy_sources": "Configured energy sources",
        "section_energy_devices": "Individually tracked devices",
        "empty_helpers": "_No helpers configured._",
        "section_used_by": "Used by",
        "used_by_automations": "Automations",
        "used_by_scripts": "Scripts",
        "used_by_scenes": "Scenes",
        "used_by_via_group_template": " *(via group `{group}`)*",
        "network_col_hostname": "Hostname",
        "network_col_mac": "MAC",
        "network_col_ip": "IP",
        "network_col_connection": "Connection",
        "network_col_vlan": "SSID/VLAN",
        "network_col_last_seen": "Last seen",
        "network_col_ap_switch": "AP / Switch port",
        "network_col_oui": "Manufacturer (OUI)",
        "empty_network": "_No devices with network data found._",
        "section_bluetooth_count_template": "Bluetooth scanners ({count})",
        "bt_local_label": "HA host (local BT adapter)",
        "bt_proxy_label_template": "ESPHome proxy: {name}",
        "empty_bluetooth": "_No Bluetooth scanners / proxies found._",
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
        "bundle_network": "Network",
        "bundle_bluetooth": "Bluetooth",
        "bundle_services": "Services (Notify/TTS)",
        "bundle_recorder": "Recorder",
        "bundle_mqtt": "MQTT",
        "bundle_energy": "Energy",
        "bundle_helpers": "Helpers",
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
        "integration_col_docs": "Docs",
        "integration_docs_link_label": "Docs",
        "entity_state_label": "State",
        "entity_topic_label": "Topic",
        "entity_disabled_marker": "_[disabled]_",
        "entity_stats_marker": "📊",
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
