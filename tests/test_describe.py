"""Tests for the readable automation/script summaries (issue #44)."""

from __future__ import annotations

from custom_components.bookstack_sync._strings import get_strings
from custom_components.bookstack_sync.describe import (
    describe_automation,
    describe_script,
)
from custom_components.bookstack_sync.extractor import BlueprintInfo

DE = get_strings("de")
EN = get_strings("en")
REFS = {
    "light.sofa": "Sofa (`light.sofa`)",
    "dev1": "Fernbedienung",
    "0123456789abcdef0123456789abcdef": "Decke (`light.decke`)",
}


def _text(lines: list[str]) -> str:
    return "\n".join(lines)


def test_triggers_conditions_actions_sections() -> None:
    config = {
        "triggers": [
            {
                "trigger": "state",
                "entity_id": "light.sofa",
                "to": "on",
                "for": {"minutes": 5},
            },
        ],
        "conditions": [{"condition": "time", "after": "22:00:00"}],
        "actions": [
            {"action": "light.turn_off", "target": {"entity_id": "light.sofa"}},
        ],
    }
    out = _text(describe_automation(config, DE, REFS))

    assert (
        "**Auslöser**\n\n"
        "- Sofa (`light.sofa`) wechselt zu `on` seit mindestens `00:05:00`" in out
    )
    assert "**Bedingungen**\n\n- Zeit nach `22:00:00`" in out
    assert "**Aktionen**\n\n- `light.turn_off` für Sofa (`light.sofa`)" in out


def test_legacy_singular_keys_and_single_items() -> None:
    """Old-style ``trigger``/``platform``/``service`` and non-list values."""
    config = {
        "trigger": {"platform": "sun", "event": "sunset", "offset": "-00:30:00"},
        "action": {"service": "scene.turn_on", "entity_id": "scene.abend"},
    }
    out = _text(describe_automation(config, EN, {}))

    assert "- Sun: `sunset` (offset `-00:30:00`)" in out
    assert "- `scene.turn_on` for `scene.abend`" in out
    assert "**Conditions**" not in out


def test_device_trigger_and_action_use_resolved_names() -> None:
    config = {
        "triggers": [
            {
                "trigger": "device",
                "device_id": "dev1",
                "domain": "zha",
                "type": "remote_button_short_press",
                "subtype": "turn_on",
            },
        ],
        "actions": [
            {
                "device_id": "dev1",
                "domain": "light",
                "entity_id": "0123456789abcdef0123456789abcdef",
                "type": "turn_on",
            },
        ],
    }
    out = _text(describe_automation(config, DE, REFS))

    assert "- Gerät Fernbedienung: `remote_button_short_press` `turn_on`" in out
    assert "- Gerät Fernbedienung: `turn_on` (Decke (`light.decke`))" in out
    assert "0123456789abcdef" not in out


def test_nested_choose_if_and_logic_conditions() -> None:
    config = {
        "conditions": [
            {
                "condition": "or",
                "conditions": [
                    {"condition": "state", "entity_id": "light.sofa", "state": "off"},
                    "{{ is_state('sun.sun', 'below_horizon') }}",
                ],
            },
        ],
        "actions": [
            {
                "choose": [
                    {
                        "conditions": [{"condition": "trigger", "id": "nacht"}],
                        "sequence": [
                            {
                                "if": [
                                    {
                                        "condition": "state",
                                        "entity_id": "light.sofa",
                                        "state": "on",
                                    }
                                ],
                                "then": [{"delay": "00:00:05"}],
                                "else": [{"stop": "fertig"}],
                            },
                        ],
                    },
                ],
                "default": [{"action": "notify.mobile", "data": {"message": "Hallo"}}],
            },
        ],
    }
    out = _text(describe_automation(config, DE, REFS))

    assert (
        "- Mindestens eine davon:\n"
        "  - Sofa (`light.sofa`) ist `off`\n"
        "  - Template ist wahr: `{{ is_state('sun.sun', 'below_horizon') }}`"
    ) in out
    assert (
        "- Auswahl:\n"
        "  - Wenn:\n"
        "    - Ausgelöst durch Auslöser `nacht`\n"
        "  - Dann:\n"
        "    - Wenn:\n"
        "      - Sofa (`light.sofa`) ist `on`\n"
        "    - Dann:\n"
        "      - Warten `00:00:05`\n"
        "    - Sonst:\n"
        "      - Stopp: `fertig`\n"
        "  - Sonst:\n"
        "    - `notify.mobile` (message: `Hallo`)"
    ) in out


def test_only_safe_data_values_are_shown() -> None:
    """Values that may come from ``!secret`` are listed by key only."""
    config = {
        "actions": [
            {
                "action": "rest_command.call",
                "data": {
                    "url": "https://x/?token=SECRET",
                    "password": "hunter2",
                    "message": "ok",
                },
            },
        ],
    }
    out = _text(describe_automation(config, EN, {}))

    assert "SECRET" not in out
    assert "hunter2" not in out
    assert "message: `ok`" in out
    assert "more data: `url`, `password`" in out


def test_webhook_id_is_never_shown() -> None:
    config = {"triggers": [{"trigger": "webhook", "webhook_id": "very-secret-id"}]}
    out = _text(describe_automation(config, EN, {}))

    assert "- Webhook call" in out
    assert "very-secret-id" not in out


def test_new_style_target_trigger_and_disabled_marker() -> None:
    config = {
        "triggers": [
            {
                "trigger": "motion.detected",
                "target": {"entity_id": ["light.sofa"]},
                "enabled": False,
            },
        ],
    }
    out = _text(describe_automation(config, DE, REFS))

    assert "- `motion.detected` für Sofa (`light.sofa`) (deaktiviert)" in out


def test_long_values_are_capped_and_backticks_survive() -> None:
    template = "{{ " + "x" * 200 + " }}"
    config = {"triggers": [{"trigger": "template", "value_template": template}]}
    out = _text(describe_automation(config, EN, {}))
    assert "…`" in out
    assert len(out.splitlines()[2]) < 160

    config = {"triggers": [{"trigger": "template", "value_template": "{{ `a` }}"}]}
    assert "`` {{ `a` }} ``" in _text(describe_automation(config, EN, {}))


def test_script_fields_and_sequence() -> None:
    config = {
        "fields": {"raum": {"name": "Raum", "description": "Welcher Raum"}},
        "sequence": [{"repeat": {"count": 3, "sequence": [{"delay": 1}]}}],
    }
    out = _text(describe_script(config, DE, {}))

    assert "**Eingabefelder**\n\n- `raum` – Raum" in out
    assert "**Ablauf**\n\n- Wiederholen `3` Mal\n  - Warten `1`" in out


def test_repeat_while_lists_conditions_then_body() -> None:
    config = {
        "sequence": [
            {
                "repeat": {
                    "while": [
                        {"condition": "state", "entity_id": "light.sofa", "state": "on"}
                    ],
                    "sequence": [{"delay": "00:01:00"}],
                },
            },
        ],
    }
    out = _text(describe_script(config, DE, REFS))

    assert (
        "- Wiederholen solange:\n"
        "  - Sofa (`light.sofa`) ist `on`\n"
        "- Jedes Mal:\n"
        "  - Warten `00:01:00`"
    ) in out


def test_no_config_renders_nothing() -> None:
    assert describe_automation(None, DE, {}) == []
    assert describe_script(None, DE, {}) == []


def test_blueprint_automation_lists_blueprint_and_inputs() -> None:
    """#50: blueprint-based automations show the blueprint and its inputs."""
    blueprint = BlueprintInfo(
        domain="automation",
        path="homeassistant/motion_light.yaml",
        name="Motion-activated Light",
        inputs={"motion_entity": "Motion Sensor", "light_target": "Light"},
    )
    config = {
        "use_blueprint": {
            "path": "homeassistant/motion_light.yaml",
            "input": {
                "motion_entity": "light.sofa",
                "light_target": {"entity_id": ["light.sofa"]},
                "no_motion_wait": 120,
                "notify_url": "https://x/?token=SECRET",
            },
        },
    }
    out = _text(describe_automation(config, DE, REFS, blueprint))

    assert (
        "**Blueprint**\n\n- Motion-activated Light (`homeassistant/motion_light.yaml`)"
        in out
    )
    assert "- Motion Sensor: Sofa (`light.sofa`)" in out
    assert "- Light: Sofa (`light.sofa`)" in out
    assert "- no_motion_wait: `120`" in out
    assert "- notify_url: *(verborgen)*" in out
    assert "SECRET" not in out
    assert "**Auslöser**" not in out


def test_blueprint_use_is_followed_by_the_substituted_summary() -> None:
    """#50: HA hands over the substituted config next to use_blueprint."""
    config = {
        "use_blueprint": {"path": "x/motion.yaml", "input": {}},
        "triggers": [{"trigger": "state", "entity_id": "light.sofa", "to": "on"}],
    }
    out = _text(describe_automation(config, DE, REFS))

    assert out.index("**Blueprint**") < out.index("**Auslöser**")
    assert "- Sofa (`light.sofa`) wechselt zu `on`" in out


def test_blueprint_not_loadable_shows_path_only() -> None:
    config = {"use_blueprint": {"path": "gone/missing.yaml", "input": {}}}
    out = _text(describe_script(config, EN, {}))

    assert "**Blueprint**\n\n- `gone/missing.yaml`" in out
    assert "**Inputs**" not in out


def test_unknown_device_is_flagged() -> None:
    """A device ID HA no longer knows (deleted device) is called out."""
    config = {
        "triggers": [{"trigger": "device", "device_id": "gone", "type": "turned_on"}],
        "actions": [
            {"action": "music_assistant.play_media", "target": {"device_id": "gone"}},
        ],
    }
    out = _text(describe_automation(config, DE, REFS))

    assert "- Unbekanntes Gerät `gone`: `turned_on`" in out
    assert "- `music_assistant.play_media` für unbekanntes Gerät `gone`" in out
