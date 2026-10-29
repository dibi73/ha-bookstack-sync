"""
Readable summaries of automation and script configs (issue #44).

Turns an automation's ``raw_config`` into nested Markdown bullet points
("State of Sofa (`light.sofa`) changes to `on`") instead of embedding the
raw YAML. The YAML itself is backup material (HA's backup already holds
it) and is mostly noise for a RAG built on these pages; a sentence per
trigger / condition / action is what answers "what turns on the sofa
light at night?".

Only values that are safe and meaningful are shown. Action data in
particular can hold secrets resolved from ``!secret`` (tokens in URLs,
passwords), so only the keys in ``_SAFE_DATA_KEYS`` show their value;
every other key is listed by name only. Webhook IDs are never shown.

``refs`` maps raw references (entity IDs, entity registry UUIDs used by
device triggers/actions, device IDs, area IDs) to an already escaped
display label, built by the extractor. Anything without a ref falls back
to a code span of the raw value.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from ._markdown import _md_escape

if TYPE_CHECKING:
    from .extractor import BlueprintInfo

# Nesting deeper than this is cut off with "…" — a choose inside a repeat
# inside an if is already hard to follow as prose.
_MAX_DEPTH = 5
_MAX_VALUE_LEN = 100

# Action data keys whose values are shown. Everything else is listed by
# key only: values may come from ``!secret`` and cannot be told apart.
_SAFE_DATA_KEYS = frozenset(
    {
        "brightness",
        "brightness_pct",
        "brightness_step_pct",
        "color_name",
        "color_temp_kelvin",
        "fan_mode",
        "hvac_mode",
        "kelvin",
        "language",
        "message",
        "mode",
        "option",
        "percentage",
        "position",
        "preset_mode",
        "source",
        "target_temp_high",
        "target_temp_low",
        "temperature",
        "tilt_position",
        "title",
        "transition",
        "value",
        "volume_level",
    },
)

_TARGET_KEYS = ("entity_id", "device_id", "area_id", "floor_id", "label_id")

# Blueprint inputs are free-form; hide the value of any input whose key
# suggests a credential (#50).
_SECRET_INPUT_RE = re.compile(r"secret|token|passw|api_?key|webhook|url", re.IGNORECASE)


def _code(value: object) -> str:
    """Return ``value`` as a single-line, length-capped code span."""
    if isinstance(value, (dict, list)) and not isinstance(value, str):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > _MAX_VALUE_LEN:
        text = text[: _MAX_VALUE_LEN - 1] + "…"
    fence = "``" if "`" in text else "`"
    pad = " " if fence == "``" else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _duration(value: Any) -> str:
    """Render a HA duration (``"00:05:00"``, seconds or a dict) as code."""
    if isinstance(value, dict):
        parts = {k: int(value.get(k, 0) or 0) for k in ("hours", "minutes", "seconds")}
        if set(value) <= {"hours", "minutes", "seconds", "milliseconds"}:
            return _code(
                f"{parts['hours']:02d}:{parts['minutes']:02d}:{parts['seconds']:02d}"
            )
    return _code(value)


class _Describer:
    """Render one config tree with fixed strings + refs."""

    def __init__(self, strings: dict[str, str], refs: dict[str, str]) -> None:
        self.s = strings
        self.refs = refs

    # -- references ---------------------------------------------------------

    def ref(self, value: Any) -> str:
        if isinstance(value, str) and value in self.refs:
            return self.refs[value]
        return _code(value)

    def device_ref(self, value: Any) -> str:
        """Like ``ref`` but flags a device ID HA doesn't know (any more)."""
        if isinstance(value, str) and value not in self.refs:
            return self.s["desc_unknown_device"].format(value=_code(value))
        return self.ref(value)

    def refs_of(self, value: Any) -> str:
        return ", ".join(self.ref(v) for v in _as_list(value))

    def target(self, item: dict[str, Any]) -> str:
        """Join entity/device/area references of an item and its ``target``."""
        parts: list[str] = []
        sources = [item]
        if isinstance(item.get("target"), dict):
            sources.append(item["target"])
        for source in sources:
            for key in _TARGET_KEYS:
                if key in source:
                    to_label = self.device_ref if key == "device_id" else self.ref
                    parts.extend(to_label(v) for v in _as_list(source[key]))
        return ", ".join(parts)

    def with_target(self, text: str, item: dict[str, Any]) -> str:
        what = self.target(item)
        return f"{text} {self.s['desc_for'].format(what=what)}" if what else text

    def device(self, item: dict[str, Any]) -> str:
        """Describe a device trigger/condition/action."""
        kind = item.get("type") or item.get("domain") or "?"
        device_id = item.get("device_id")
        template = "desc_device" if device_id in self.refs else "desc_device_unknown"
        text = self.s[template].format(device=self.ref(device_id), type=_code(kind))
        if item.get("subtype"):
            text += f" {_code(item['subtype'])}"
        if item.get("entity_id"):
            text += f" ({self.refs_of(item['entity_id'])})"
        return text

    # -- triggers -----------------------------------------------------------

    def trigger(self, item: Any) -> str:  # noqa: PLR0912 - flat dispatch over trigger types
        if not isinstance(item, dict):
            return _code(item)
        s = self.s
        kind = str(item.get("trigger") or item.get("platform") or "?")
        what = self.refs_of(item.get("entity_id"))
        if kind == "state":
            if item.get("attribute"):
                what = s["desc_attribute"].format(
                    attribute=_code(item["attribute"]), what=what
                )
            text = s["desc_t_state"].format(what=what)
            text += self._from_to(item)
        elif kind == "numeric_state":
            text = what + self._above_below(item)
            if item.get("for"):
                text += " " + s["desc_for_duration"].format(
                    value=_duration(item["for"])
                )
        elif kind == "time":
            text = s["desc_t_time"].format(value=self.refs_of(item.get("at")))
        elif kind == "time_pattern":
            pattern = ", ".join(
                f"{key} {_code(item[key])}"
                for key in ("hours", "minutes", "seconds")
                if key in item
            )
            text = s["desc_t_time_pattern"].format(value=pattern)
        elif kind == "sun":
            text = s["desc_t_sun"].format(value=_code(item.get("event")))
            if item.get("offset"):
                text += " " + s["desc_offset"].format(value=_code(item["offset"]))
        elif kind == "homeassistant":
            text = s["desc_t_homeassistant"].format(value=_code(item.get("event")))
        elif kind == "event":
            text = s["desc_t_event"].format(value=self.refs_of(item.get("event_type")))
        elif kind == "mqtt":
            text = s["desc_t_mqtt"].format(value=_code(item.get("topic")))
            if "payload" in item:
                text += " " + s["desc_payload"].format(value=_code(item["payload"]))
        elif kind == "template":
            text = s["desc_t_template"].format(value=_code(item.get("value_template")))
        elif kind == "zone":
            verb = (
                s["desc_zone_leave"]
                if item.get("event") == "leave"
                else s["desc_zone_enter"]
            )
            text = s["desc_t_zone"].format(
                what=what, verb=verb, zone=self.ref(item.get("zone"))
            )
        elif kind == "device":
            text = self.device(item)
        elif kind == "webhook":
            # Never show the webhook ID: it is the only secret a webhook has.
            text = s["desc_t_webhook"]
        elif kind == "conversation":
            text = s["desc_t_conversation"].format(
                value=", ".join(_code(c) for c in _as_list(item.get("command")))
            )
        else:
            text = self.with_target(_code(kind), item)
        if item.get("for") and kind == "state":
            text += " " + s["desc_for_duration"].format(value=_duration(item["for"]))
        return text + self._disabled(item)

    def _from_to(self, item: dict[str, Any]) -> str:
        text = ""
        if "from" in item and item["from"] is not None:
            text += " " + self.s["desc_from"].format(value=self.refs_of(item["from"]))
        if "to" in item and item["to"] is not None:
            text += " " + self.s["desc_to"].format(value=self.refs_of(item["to"]))
        return text

    def _above_below(self, item: dict[str, Any]) -> str:
        text = ""
        if item.get("attribute"):
            text += " " + self.s["desc_attribute_short"].format(
                attribute=_code(item["attribute"])
            )
        if "above" in item:
            text += " " + self.s["desc_above"].format(value=self.ref(item["above"]))
        if "below" in item:
            text += " " + self.s["desc_below"].format(value=self.ref(item["below"]))
        return text

    def _disabled(self, item: dict[str, Any]) -> str:
        return f" {self.s['desc_disabled']}" if item.get("enabled") is False else ""

    # -- conditions ---------------------------------------------------------

    def condition(self, item: Any, depth: int) -> list[str]:  # noqa: PLR0912 - flat dispatch over condition types
        s = self.s
        if isinstance(item, str):
            return [s["desc_c_template"].format(value=_code(item))]
        if not isinstance(item, dict):
            return [_code(item)]
        kind = str(item.get("condition") or "?")
        what = self.refs_of(item.get("entity_id"))
        if kind in ("and", "or", "not"):
            head = s[f"desc_c_{kind}"] + self._disabled(item)
            return [
                head,
                *self._nested(self.conditions(item.get("conditions"), depth + 1)),
            ]
        if kind == "state":
            if item.get("attribute"):
                what = s["desc_attribute"].format(
                    attribute=_code(item["attribute"]), what=what
                )
            text = s["desc_c_state"].format(
                what=what, value=self.refs_of(item.get("state"))
            )
            if item.get("for"):
                text += " " + s["desc_for_duration"].format(
                    value=_duration(item["for"])
                )
        elif kind == "numeric_state":
            text = what + self._above_below(item)
        elif kind == "time":
            parts = []
            if item.get("after"):
                parts.append(s["desc_after"].format(value=self.ref(item["after"])))
            if item.get("before"):
                parts.append(s["desc_before"].format(value=self.ref(item["before"])))
            if item.get("weekday"):
                days = ", ".join(_code(d) for d in _as_list(item["weekday"]))
                parts.append(s["desc_weekday"].format(value=days))
            text = s["desc_c_time"].format(value=" ".join(parts))
        elif kind == "sun":
            parts = [
                s[f"desc_{key}"].format(value=_code(item[key]))
                for key in ("after", "before")
                if item.get(key)
            ]
            text = s["desc_c_sun"].format(value=" ".join(parts))
        elif kind == "template":
            text = s["desc_c_template"].format(value=_code(item.get("value_template")))
        elif kind == "trigger":
            text = s["desc_c_trigger"].format(value=self.refs_of(item.get("id")))
        elif kind == "zone":
            text = s["desc_c_zone"].format(
                what=what, zone=self.refs_of(item.get("zone"))
            )
        elif kind == "device":
            text = self.device(item)
        else:
            text = self.with_target(_code(kind), item)
        return [text + self._disabled(item)]

    def conditions(self, items: Any, depth: int) -> list[str]:
        if depth > _MAX_DEPTH:
            return ["- …"]
        lines: list[str] = []
        for item in _as_list(items):
            first, *rest = self.condition(item, depth)
            lines.append(f"- {first}")
            lines.extend(rest)
        return lines

    # -- actions ------------------------------------------------------------

    def action(self, item: Any, depth: int) -> list[str]:  # noqa: PLR0911, PLR0912 - flat dispatch over action types
        s = self.s
        if not isinstance(item, dict):
            return [_code(item)]
        dis = self._disabled(item)
        if "action" in item or "service" in item:
            return [self._call(item) + dis]
        if "delay" in item:
            return [s["desc_a_delay"].format(value=_duration(item["delay"])) + dis]
        if "wait_template" in item:
            text = s["desc_a_wait_template"].format(value=_code(item["wait_template"]))
            return [text + self._timeout(item) + dis]
        if "wait_for_trigger" in item:
            return [
                s["desc_a_wait_trigger"] + self._timeout(item) + dis,
                *self._nested(
                    [f"- {self.trigger(t)}" for t in _as_list(item["wait_for_trigger"])]
                ),
            ]
        if "choose" in item:
            lines = [s["desc_a_choose"] + dis]
            for option in _as_list(item["choose"]):
                if not isinstance(option, dict):
                    continue
                lines.extend(
                    self._nested(
                        [
                            f"- {s['desc_if']}",
                            *self._nested(
                                self.conditions(option.get("conditions"), depth + 1)
                            ),
                            f"- {s['desc_then']}",
                            *self._nested(
                                self.actions(option.get("sequence"), depth + 1)
                            ),
                        ]
                    )
                )
            if item.get("default"):
                lines.extend(
                    self._nested(
                        [
                            f"- {s['desc_else']}",
                            *self._nested(self.actions(item["default"], depth + 1)),
                        ]
                    )
                )
            return lines
        if "if" in item:
            lines = [
                s["desc_if"] + dis,
                *self._nested(self.conditions(item["if"], depth + 1)),
                f"\x00{s['desc_then']}",
                *self._nested(self.actions(item.get("then"), depth + 1)),
            ]
            if item.get("else"):
                lines.append(f"\x00{s['desc_else']}")
                lines.extend(self._nested(self.actions(item["else"], depth + 1)))
            return lines
        if "repeat" in item:
            return self._repeat(item["repeat"], depth, dis)
        if "parallel" in item:
            return [
                s["desc_a_parallel"] + dis,
                *self._nested(self.actions(item["parallel"], depth + 1)),
            ]
        if "sequence" in item:
            return [
                s["desc_a_sequence"] + dis,
                *self._nested(self.actions(item["sequence"], depth + 1)),
            ]
        if "condition" in item:
            return [
                s["desc_a_condition"] + dis,
                *self._nested(self.conditions([item], depth + 1)),
            ]
        if "scene" in item:
            return [s["desc_a_scene"].format(value=self.ref(item["scene"])) + dis]
        if "event" in item:
            text = s["desc_a_event"].format(value=_code(item["event"]))
            if item.get("event_data"):
                text += " " + self._data(item["event_data"])
            return [text + dis]
        if "variables" in item:
            names = ", ".join(_code(k) for k in item["variables"])
            return [s["desc_a_variables"].format(value=names) + dis]
        if "stop" in item:
            return [s["desc_a_stop"].format(value=_code(item["stop"])) + dis]
        if "device_id" in item:
            return [self.device(item) + dis]
        if "set_conversation_response" in item:
            return [s["desc_a_response"] + dis]
        return [_code(next(iter(item), "?")) + dis]

    def _call(self, item: dict[str, Any]) -> str:
        service = item.get("action") or item.get("service")
        text = self.with_target(_code(service), item)
        data = item.get("data") or item.get("data_template")
        if isinstance(data, dict) and data:
            text += " " + self._data(data)
        return text

    def _data(self, data: Any) -> str:
        if not isinstance(data, dict):
            return f"({_code(data)})"
        shown = [
            f"{key}: {_code(value)}"
            for key, value in data.items()
            if key in _SAFE_DATA_KEYS
        ]
        hidden = [_code(key) for key in data if key not in _SAFE_DATA_KEYS]
        if hidden:
            shown.append(self.s["desc_more_data"].format(value=", ".join(hidden)))
        return f"({'; '.join(shown)})"

    def _timeout(self, item: dict[str, Any]) -> str:
        if not item.get("timeout"):
            return ""
        return " " + self.s["desc_timeout"].format(value=_duration(item["timeout"]))

    def _repeat(self, repeat: Any, depth: int, dis: str) -> list[str]:
        s = self.s
        if not isinstance(repeat, dict):
            return [s["desc_a_repeat"] + dis]
        head = s["desc_a_repeat"]
        cond_lines: list[str] = []
        if "count" in repeat:
            head += " " + s["desc_times"].format(value=_code(repeat["count"]))
        elif "for_each" in repeat:
            head += " " + s["desc_for_each"].format(value=_code(repeat["for_each"]))
        elif "while" in repeat:
            head += " " + s["desc_while"]
            cond_lines = self.conditions(repeat["while"], depth + 1)
        elif "until" in repeat:
            head += " " + s["desc_until"]
            cond_lines = self.conditions(repeat["until"], depth + 1)
        body = self._nested(self.actions(repeat.get("sequence"), depth + 1))
        if not cond_lines:
            return [head + dis, *body]
        return [
            head + dis,
            *self._nested(cond_lines),
            f"\x00{s['desc_each_time']}",
            *body,
        ]

    def actions(self, items: Any, depth: int) -> list[str]:
        if depth > _MAX_DEPTH:
            return ["- …"]
        lines: list[str] = []
        for item in _as_list(items):
            first, *rest = self.action(item, depth)
            lines.append(f"- {first}")
            for line in rest:
                # "\x00" marks a sibling heading (then / else) that belongs
                # at the same list level as the action's own bullet.
                if line.startswith("\x00"):
                    lines.append(f"- {line[1:]}")
                else:
                    lines.append(line)
        return lines

    @staticmethod
    def _nested(lines: list[str]) -> list[str]:
        return [f"  {line}" for line in lines]


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"**{title}**", "", *lines, ""] if lines else []


def _blueprint_lines(
    config: dict[str, Any],
    d: _Describer,
    blueprint: BlueprintInfo | None,
) -> list[str]:
    """Describe ``use_blueprint``: which blueprint, with which inputs (#50)."""
    use = config.get("use_blueprint")
    if not isinstance(use, dict):
        return []
    path = _code(use.get("path"))
    head = f"- {_md_escape(blueprint.name)} ({path})" if blueprint else f"- {path}"
    labels = blueprint.inputs if blueprint else {}
    inputs: list[str] = []
    for key, value in (use.get("input") or {}).items():
        label = _md_escape(labels.get(key, key))
        if _SECRET_INPUT_RE.search(str(key)):
            shown = d.s["desc_hidden"]
        elif isinstance(value, dict) and any(k in value for k in _TARGET_KEYS):
            shown = d.target(value)
        elif isinstance(value, (str, list)):
            shown = d.refs_of(value)
        else:
            shown = _code(value)
        inputs.append(f"- {label}: {shown}")
    return [
        *_section(d.s["desc_blueprint"], [head]),
        *_section(d.s["desc_inputs"], inputs),
    ]


def describe_automation(
    config: dict[str, Any] | None,
    strings: dict[str, str],
    refs: dict[str, str],
    blueprint: BlueprintInfo | None = None,
) -> list[str]:
    """Return Markdown lines describing triggers, conditions and actions."""
    if not isinstance(config, dict):
        return []
    d = _Describer(strings, refs)
    # A blueprint-based entry carries both ``use_blueprint`` and, from HA,
    # the substituted triggers/actions (#50): show the blueprint first,
    # then what the result does.
    head = _blueprint_lines(config, d, blueprint)
    triggers = config.get("triggers", config.get("trigger"))
    conditions = config.get("conditions", config.get("condition"))
    actions = config.get("actions", config.get("action"))
    return [
        *head,
        *_section(
            strings["desc_triggers"],
            [f"- {d.trigger(t)}" for t in _as_list(triggers)],
        ),
        *_section(strings["desc_conditions"], d.conditions(conditions, 0)),
        *_section(strings["desc_actions"], d.actions(actions, 0)),
    ]


def describe_script(
    config: dict[str, Any] | None,
    strings: dict[str, str],
    refs: dict[str, str],
    blueprint: BlueprintInfo | None = None,
) -> list[str]:
    """Return Markdown lines describing a script's fields and sequence."""
    if not isinstance(config, dict):
        return []
    d = _Describer(strings, refs)
    # A blueprint-based entry carries both ``use_blueprint`` and, from HA,
    # the substituted triggers/actions (#50): show the blueprint first,
    # then what the result does.
    head = _blueprint_lines(config, d, blueprint)
    fields = config.get("fields")
    field_lines = (
        [
            f"- {_code(name)}"
            + (
                f" – {_md_escape(spec.get('name') or spec.get('description'))}"
                if isinstance(spec, dict)
                and (spec.get("name") or spec.get("description"))
                else ""
            )
            for name, spec in fields.items()
        ]
        if isinstance(fields, dict)
        else []
    )
    return [
        *head,
        *_section(strings["desc_fields"], field_lines),
        *_section(strings["desc_sequence"], d.actions(config.get("sequence"), 0)),
    ]
