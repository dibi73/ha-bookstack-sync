"""End-to-end tests for the sync orchestrator.

We mock the BookStackApiClient (not the lower aiohttp layer) so these
tests focus on the orchestration: chapter creation, two-pass overview
rendering, tombstoning, page mapping persistence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers import (
    area_registry as ar,
)

from custom_components.bookstack_sync._strings import get_strings
from custom_components.bookstack_sync.const import (
    CHAPTER_KEY_AREAS,
    CHAPTER_KEY_DEVICES,
)
from custom_components.bookstack_sync.store import BookStackSyncStore
from custom_components.bookstack_sync.sync import run_sync

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _fake_client_with_state(state: dict[str, Any]) -> MagicMock:
    """A MagicMock that mimics BookStackApiClient and tracks created pages.

    state['next_id'] is incremented on every page/chapter create so we
    hand out unique IDs without colliding.
    """
    state.setdefault("pages", {})  # id -> {markdown, chapter_id, name}
    state.setdefault("chapters", {})  # id -> name
    state.setdefault("next_id", 100)
    state.setdefault("books", [{"id": 1, "name": "Book", "slug": "book"}])

    client = MagicMock()
    client.base_url = "http://bookstack.local"

    async def list_books() -> list[dict[str, Any]]:
        return list(state["books"])

    async def list_chapters(book_id: int) -> list[dict[str, Any]]:
        return [{"id": cid, "name": name} for cid, name in state["chapters"].items()]

    async def create_chapter(
        book_id: int,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        cid = state["next_id"]
        state["next_id"] += 1
        state["chapters"][cid] = name
        return {"id": cid, "name": name}

    async def create_page(
        name: str,
        markdown: str,
        *,
        book_id: int | None = None,
        chapter_id: int | None = None,
        tags: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        pid = state["next_id"]
        state["next_id"] += 1
        state["pages"][pid] = {
            "id": pid,
            "name": name,
            "slug": f"slug-{pid}",
            "markdown": markdown,
            "chapter_id": chapter_id,
            "book_id": book_id,
            "tags": tags,
        }
        return state["pages"][pid]

    async def get_page(page_id: int) -> dict[str, Any]:
        return state["pages"][page_id]

    async def update_page(
        page_id: int,
        name: str,
        markdown: str,
        *,
        chapter_id: int | None = None,
        tags: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        state["pages"][page_id]["name"] = name
        state["pages"][page_id]["markdown"] = markdown
        if chapter_id is not None:
            state["pages"][page_id]["chapter_id"] = chapter_id
        if tags is not None:
            state["pages"][page_id]["tags"] = tags
        return state["pages"][page_id]

    client.list_books = AsyncMock(side_effect=list_books)
    client.list_chapters = AsyncMock(side_effect=list_chapters)
    client.create_chapter = AsyncMock(side_effect=create_chapter)
    client.create_page = AsyncMock(side_effect=create_page)
    client.get_page = AsyncMock(side_effect=get_page)
    client.update_page = AsyncMock(side_effect=update_page)
    return client


@pytest.fixture
async def store(hass: HomeAssistant) -> BookStackSyncStore:
    s = BookStackSyncStore(hass, entry_id="testentry")
    await s.async_load()
    return s


@pytest.fixture
def strings() -> dict[str, str]:
    """Default to German strings for sync tests (tests our home-base output)."""
    return get_strings("de")


async def test_first_sync_creates_chapters_and_pages(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)

    # Seed minimal HA state
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    report = await run_sync(hass, client, store, 1, strings)

    # Both chapters auto-created (titles come from the active language).
    assert strings["chapter_areas_title"] in state["chapters"].values()
    assert strings["chapter_devices_title"] in state["chapters"].values()
    assert store.get_chapter(CHAPTER_KEY_AREAS) is not None
    assert store.get_chapter(CHAPTER_KEY_DEVICES) is not None

    # At least the overview + the four bundle pages + the area page were created
    assert len(report.created) >= 6
    assert report.errors == []


async def test_first_sync_tags_pages_as_managed(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """Every newly-created page carries the bookstack_sync=managed tag."""
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    await run_sync(hass, client, store, 1, strings)

    # Inspect every kwargs the fake client received during create_page.
    create_calls = client.create_page.call_args_list
    assert create_calls, "first sync must have created at least one page"
    for call in create_calls:
        tags = call.kwargs.get("tags")
        assert tags == [{"name": "bookstack_sync", "value": "managed"}], (
            f"expected managed tag on every create_page, got {tags!r}"
        )


async def test_second_sync_with_unchanged_data_makes_no_changes(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    # First sync: creates everything
    await run_sync(hass, client, store, 1, strings)

    # Second sync should be all-unchanged (this is the regression hot spot
    # we just fixed in v0.2.1: false-positive tampering after first write).
    report2 = await run_sync(hass, client, store, 1, strings)
    assert report2.created == []
    assert report2.skipped_conflict == []  # NO false positives
    assert report2.errors == []


async def test_dry_run_does_not_call_writes(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)

    report = await run_sync(hass, client, store, 1, strings, dry_run=True)
    assert report.dry_run is True
    client.create_page.assert_not_called()
    client.update_page.assert_not_called()
    client.create_chapter.assert_not_called()


async def test_chapter_reused_when_already_present(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    state: dict[str, Any] = {
        "chapters": {500: strings["chapter_areas_title"]},
        "next_id": 600,
    }
    client = _fake_client_with_state(state)

    await run_sync(hass, client, store, 1, strings)

    # We must NOT have created a duplicate area chapter - only the device
    # chapter was missing.
    chapter_titles = list(state["chapters"].values())
    assert chapter_titles.count(strings["chapter_areas_title"]) == 1
    assert chapter_titles.count(strings["chapter_devices_title"]) == 1
    assert store.get_chapter(CHAPTER_KEY_AREAS) == 500


async def test_english_run_creates_english_titled_chapters(
    hass: HomeAssistant,
    store: BookStackSyncStore,
) -> None:
    """v0.4.0 regression: chapter titles follow the strings dict."""
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    en = get_strings("en")

    await run_sync(hass, client, store, 1, en)

    chapter_titles = list(state["chapters"].values())
    assert "Areas" in chapter_titles
    assert "Devices" in chapter_titles
    # And no German leftovers.
    assert "Räume" not in chapter_titles
    assert "Geräte" not in chapter_titles


async def test_clean_sync_emits_no_notification(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """
    Regression: a healthy sync run is silent.

    Users explicitly asked for no green-bell after every successful sync.
    The status sensor + integration card already show "ok"; another
    persistent notification is just noise.
    """
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    with patch(
        "custom_components.bookstack_sync.sync.async_create_notification",
    ) as notify:
        report = await run_sync(hass, client, store, 1, strings)

    assert report.errors == []
    assert report.skipped_conflict == []
    notify.assert_not_called()


async def test_sync_with_errors_emits_notification(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """A sync that hit at least one error still surfaces a notification."""
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    # Force every page write to fail so the run produces errors.
    from custom_components.bookstack_sync.api import BookStackApiError  # noqa: PLC0415

    client.create_page = AsyncMock(side_effect=BookStackApiError("boom"))

    with patch(
        "custom_components.bookstack_sync.sync.async_create_notification",
    ) as notify:
        report = await run_sync(hass, client, store, 1, strings)

    assert report.errors  # the run did record at least one error
    notify.assert_called_once()


async def test_sync_with_skipped_conflict_emits_notification(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """Tampering-detected skips also warrant a notification."""
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    # First run creates the pages cleanly.
    await run_sync(hass, client, store, 1, strings)

    # Mutate one stored page's auto block in BookStack to simulate the user
    # editing inside the AUTO marker. The next sync must detect tampering
    # and skip — and now the run should emit a notification.
    page_id, page = next(iter(state["pages"].items()))
    state["pages"][page_id] = {
        **page,
        "markdown": page["markdown"].replace(
            "Auto-generated",
            "Auto-generated [HACKED]",
        ),
    }

    with patch(
        "custom_components.bookstack_sync.sync.async_create_notification",
    ) as notify:
        report = await run_sync(hass, client, store, 1, strings)

    if report.skipped_conflict:
        notify.assert_called_once()
    else:
        # Marker-block layout changed → no skip happened. In that case the
        # test is degenerate; surface it loudly so a future refactor doesn't
        # silently mask the regression we care about.
        pytest.fail(
            "Expected tamper detection to produce skipped_conflict; got none",
        )


async def test_drifted_stored_hash_does_not_trigger_tampering(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """
    Regression for the v0.13.1 false-positive on Acurite-Rain-25:

    BookStack normalises markdown sometime between the immediate
    create/update response (which we hashed) and the subsequent read
    on the next sync. The hash drifts, the previous tampering check
    fired even though the user did NOT edit the page in BookStack.
    Fix: when the AUTO content still matches HA's current render,
    treat it as drift, re-hash silently, no notification, no skip.
    """
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    # First sync: creates everything, stores hashes from BookStack
    # response.
    await run_sync(hass, client, store, 1, strings)

    # Simulate hash drift: corrupt every stored mapping's
    # ``auto_block_hash`` while leaving ``hash_origin = "bookstack"``.
    # The BookStack content is untouched (so ``existing_auto_hash``
    # still equals the new render).
    from custom_components.bookstack_sync.store import PageMapping  # noqa: PLC0415

    for key, mapping in store.all().items():
        store.set(
            key,
            PageMapping(
                page_id=mapping.page_id,
                auto_block_hash="cafebabe" * 8,  # not the real hash
                last_seen=mapping.last_seen,
                tombstoned_at=mapping.tombstoned_at,
                hash_origin="bookstack",
            ),
        )

    # Second sync should NOT raise tampering — content matches.
    report2 = await run_sync(hass, client, store, 1, strings)
    assert report2.skipped_conflict == []
    assert report2.tampered_page_keys == []
    assert report2.errors == []


async def test_force_overwrites_tampered_pages(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """
    v0.14.3: ``force=True`` bypasses the tamper-skip path.

    Real-world trigger: after a major upgrade that reshapes the AUTO
    block format (e.g. v0.14.0's area-page refactor), residual hash
    drift the v0.13.3 normaliser can't catch combines with the
    legitimate content change to make pages look tampered. ``force``
    is the user-facing escape hatch: overwrite anyway, MANUAL block
    stays preserved by the merge logic.
    """
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    # First run creates pages cleanly.
    await run_sync(hass, client, store, 1, strings)

    # Simulate hash drift + content change combo: corrupt the stored
    # hash AND mutate the BookStack-side AUTO content so the next
    # sync sees the page as legitimately-changed AND tampered.
    from custom_components.bookstack_sync.store import PageMapping  # noqa: PLC0415

    for key, mapping in store.all().items():
        store.set(
            key,
            PageMapping(
                page_id=mapping.page_id,
                auto_block_hash="cafebabe" * 8,
                last_seen=mapping.last_seen,
                tombstoned_at=mapping.tombstoned_at,
                hash_origin="bookstack",
            ),
        )
    page_id, page = next(iter(state["pages"].items()))
    state["pages"][page_id] = {
        **page,
        "markdown": page["markdown"].replace(
            "Auto-generated",
            "Auto-generated [drifted]",
        ),
    }

    # Without force: the page is skipped.
    report_skip = await run_sync(hass, client, store, 1, strings)
    assert report_skip.skipped_conflict, "expected tamper-skip without force"

    # With force=True: overwritten, no skip.
    report_force = await run_sync(hass, client, store, 1, strings, force=True)
    assert report_force.skipped_conflict == [], (
        f"force=True should bypass skip, got {report_force.skipped_conflict!r}"
    )
    assert report_force.tampered_page_keys == []


async def test_markers_missing_skips_page_and_records_repair_keys(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """
    v0.14.9: WYSIWYG-toggle round-trip strips the ``<!-- BEGIN ... -->``
    marker comments. Sync must refuse to overwrite the resulting page
    (would clobber whatever the user typed) and surface a separate
    repair issue so it doesn't get conflated with normal tampering.
    """
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    # Populate state by running a clean sync first.
    await run_sync(hass, client, store, 1, strings)

    # Simulate WYSIWYG-toggle damage on one page: replace its markdown
    # with a plausible TinyMCE round-trip (no marker comments anywhere,
    # whitespace-flattened — same shape Pandoc-style HTML→Markdown
    # conversion produces).
    page_id, page = next(iter(state["pages"].items()))
    state["pages"][page_id] = {
        **page,
        "markdown": ("Living Room\n\nuser typed some notes here in WYSIWYG mode\n"),
    }

    report = await run_sync(hass, client, store, 1, strings)

    # The damaged page is in skipped_conflict AND in markers_missing —
    # not in tampered (the lists are mutually exclusive by construction).
    assert report.skipped_conflict, (
        "expected the markers-missing page to land in skipped_conflict"
    )
    assert report.markers_missing_page_keys, (
        "expected at least one markers_missing_page_keys entry"
    )
    assert report.tampered_page_keys == [], (
        "markers-missing must NOT also raise tamper — it's a distinct cause"
    )


async def test_markers_missing_force_overwrites(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """User escape hatch: ``force=True`` accepts the page recreation."""
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    await run_sync(hass, client, store, 1, strings)
    page_id, page = next(iter(state["pages"].items()))
    state["pages"][page_id] = {
        **page,
        "markdown": "WYSIWYG-flattened content with no markers anywhere\n",
    }

    report = await run_sync(hass, client, store, 1, strings, force=True)
    assert report.markers_missing_page_keys == [], (
        f"force=True must skip markers_missing detection, got "
        f"{report.markers_missing_page_keys!r}"
    )


async def test_force_default_false_preserves_safety(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """
    v0.14.3 invariant: when ``force`` is NOT explicitly passed, the
    tamper-skip protection MUST still fire. The escape hatch is
    user-opt-in only — no silent regressions on the schedule path.
    """
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    await run_sync(hass, client, store, 1, strings)

    # Tamper a single page.
    page_id, page = next(iter(state["pages"].items()))
    state["pages"][page_id] = {
        **page,
        "markdown": page["markdown"].replace(
            "Auto-generated",
            "Auto-generated [tampered]",
        ),
    }

    # Default (no force kwarg): the page must be skipped.
    report = await run_sync(hass, client, store, 1, strings)
    assert report.skipped_conflict, (
        "default run_sync (no force) must keep the tamper-skip protection"
    )


async def test_progress_callback_is_called_with_step_and_total(
    hass: HomeAssistant,
    store: BookStackSyncStore,
    strings: dict[str, str],
) -> None:
    """v0.14.6: each managed page emits a (step, total) progress tick."""
    state: dict[str, Any] = {}
    client = _fake_client_with_state(state)
    area_reg = ar.async_get(hass)
    area_reg.async_create("Living Room")

    progress: list[tuple[int, int]] = []

    def record(step: int, total: int) -> None:
        progress.append((step, total))

    await run_sync(
        hass,
        client,
        store,
        1,
        strings,
        progress_callback=record,
    )

    assert progress, "progress_callback was never invoked"
    # Total stays constant for every tick within a run.
    totals = {total for _, total in progress}
    assert len(totals) == 1, f"total should be stable, got {totals!r}"
    total = next(iter(totals))
    assert total >= 6, f"expected at least 6 pages, got {total}"
    # First emitted tick is the (0, total) seed before any page is written.
    assert progress[0] == (0, total)
    # Steps are monotonically non-decreasing and the final tick reaches total.
    steps = [step for step, _ in progress]
    assert steps == sorted(steps), f"step counter regressed: {steps!r}"
    assert steps[-1] == total, (
        f"final tick must show step==total, got {steps[-1]}/{total}"
    )
