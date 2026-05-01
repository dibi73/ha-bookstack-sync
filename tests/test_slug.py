"""Unit tests for the slug helpers (issue #61, A5)."""

from __future__ import annotations

import pytest

from custom_components.bookstack_sync.slug import make_unique_slug, slugify


class TestSlugify:
    """Verify the rules listed in slug.slugify's docstring."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Wohnzimmer", "wohnzimmer"),
            ("Büro", "buero"),
            ("Straße", "strasse"),
            ("Fön", "foen"),
            ("Übersicht", "uebersicht"),
            ("Bewegungsmelder Gang", "bewegungsmelder-gang"),
            ("Light", "light"),
            ("Light 2", "light-2"),
            ("Smart-Home/Devices", "smart-home-devices"),
            ("  spaces  ", "spaces"),
            ("multi   internal   spaces", "multi-internal-spaces"),
            ("---leading---trailing---", "leading-trailing"),
            ("123 numeric", "123-numeric"),
            ("Café au lait", "cafe-au-lait"),
        ],
    )
    def test_typical_inputs(self, name: str, expected: str) -> None:
        """The common cases produce the documented slugs."""
        assert slugify(name) == expected

    def test_empty_string_falls_back_to_untitled(self) -> None:
        """An entirely-stripped input must still produce a usable slug."""
        assert slugify("") == "untitled"

    def test_only_special_chars_falls_back_to_untitled(self) -> None:
        """Input with no ASCII alphanumerics produces ``untitled``."""
        assert slugify("???") == "untitled"
        assert slugify("---") == "untitled"

    def test_emoji_input_drops_to_untitled(self) -> None:
        """Pure emoji input drops to ``untitled`` rather than a tofu slug."""
        assert slugify("🏠💡") == "untitled"

    def test_mixed_emoji_and_text_keeps_text(self) -> None:
        """Text wins, emojis are silently dropped."""
        assert slugify("Light 💡 Living Room") == "light-living-room"

    def test_long_input_truncated_to_80_chars(self) -> None:
        """Long titles are capped — filesystem-friendly."""
        long_name = "very-" + "long-" * 30 + "name"
        result = slugify(long_name)
        assert len(result) <= 80
        assert not result.endswith("-")  # trailing dash trimmed after truncate

    def test_idempotent(self) -> None:
        """Running slugify on its own output returns the same value."""
        for sample in ("Wohnzimmer", "Büro", "Light 2", "Smart-Home/Devices"):
            assert slugify(slugify(sample)) == slugify(sample)


class TestMakeUniqueSlug:
    """Verify the collision-suffix counter."""

    def test_unique_base_returned_unchanged(self) -> None:
        """When the slug isn't taken, no suffix is added."""
        assert make_unique_slug("light", set()) == "light"

    def test_first_collision_appends_2(self) -> None:
        """The first conflict produces ``-2``, not ``-1``."""
        assert make_unique_slug("light", {"light"}) == "light-2"

    def test_second_collision_appends_3(self) -> None:
        """Multiple collisions count up sequentially."""
        assert make_unique_slug("light", {"light", "light-2"}) == "light-3"

    def test_holes_in_taken_set_filled(self) -> None:
        """``light-3`` is preferred over ``light-7`` if 3 is free."""
        assert make_unique_slug("light", {"light", "light-2", "light-7"}) == "light-3"

    def test_stable_across_runs(self) -> None:
        """Same input set → same output, run after run."""
        taken = {"light"}
        first = make_unique_slug("light", taken)
        # Simulate a second sync with the same starting state.
        second = make_unique_slug("light", taken)
        assert first == second == "light-2"
