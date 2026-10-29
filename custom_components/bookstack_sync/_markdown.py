"""Markdown helpers shared by the renderer and the automation describer."""

from __future__ import annotations


def _md_escape(value: object) -> str:
    """
    Escape characters that would break a markdown table or inject HTML.

    BookStack renders markdown safely by default but we don't want a device
    named ``Living Room | <script>`` to either break the table layout or end
    up as an inline HTML tag if a user enables raw-HTML in BookStack.

    ``[`` / ``]`` are escaped to defuse a name like
    ``Lampe](javascript:alert(1))`` from breaking out of a markdown link
    label and injecting a clickable ``javascript:`` URL. BookStack's own
    sanitiser strips ``javascript:`` schemes on render, but treating that
    as defence-in-depth lets us not depend on it.
    """
    # Device registry fields such as sw_version can arrive as ints.
    text = "" if value is None else str(value)
    if not text:
        return text
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", " ")
    )
