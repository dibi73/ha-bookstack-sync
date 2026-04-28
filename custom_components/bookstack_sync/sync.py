"""
Sync orchestrator: snapshot HA -> render -> merge -> push to BookStack.

Flow per run:
1. ``ensure_chapters`` makes sure ``Räume`` + ``Geräte`` chapters exist
   (titles + descriptions come from the active output language).
2. Pass 1 syncs all area / device / bundle pages and collects their page IDs.
3. Pass 2 renders the overview with markdown links to the IDs from pass 1
   and writes it.
4. Pages whose HA object has vanished get a one-time tombstone block.
5. Mapping store is persisted and a persistent notification is posted.

The active output language is passed in via ``strings`` — see
``_strings.get_strings``. Default in coordinator is ``hass.config.language``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
)

from .api import BookStackApiAuthError, BookStackApiError
from .const import (
    CHAPTER_KEY_AREAS,
    CHAPTER_KEY_DEVICES,
    LOGGER,
    PAGE_KIND_ADDONS,
    PAGE_KIND_AREA,
    PAGE_KIND_AUTOMATIONS,
    PAGE_KIND_DEVICE,
    PAGE_KIND_INTEGRATIONS,
    PAGE_KIND_OVERVIEW,
    PAGE_KIND_SCENES,
    PAGE_KIND_SCRIPTS,
)
from .extractor import extract_snapshot
from .merge import (
    build_page_body,
    extract_auto_block,
    hash_auto_block,
    merge_page,
)
from .renderer import (
    render_addons_auto_block,
    render_area_auto_block,
    render_automations_auto_block,
    render_device_auto_block,
    render_integrations_auto_block,
    render_overview_auto_block,
    render_scenes_auto_block,
    render_scripts_auto_block,
    render_tombstone_auto_block,
)
from .store import PageMapping

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant

    from .api import BookStackApiClient
    from .extractor import DeviceSnapshot, HASnapshot
    from .store import BookStackSyncStore


# BookStack's API rate limit defaults to 180 req/min - we batch with a small
# pause between page writes to stay well below that even on big setups.
WRITE_PAUSE_SECONDS = 0.2


@dataclass
class SyncReport:
    """Summary of one sync run, returned to services for logging."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    tombstoned: list[str] = field(default_factory=list)
    skipped_conflict: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def as_dict(self) -> dict[str, list[str] | bool | int]:
        """Plain-dict view for logging from the preview service."""
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "tombstoned": self.tombstoned,
            "skipped_conflict": self.skipped_conflict,
            "errors": self.errors,
            "dry_run": self.dry_run,
            "total_pages": (
                len(self.created)
                + len(self.updated)
                + len(self.unchanged)
                + len(self.tombstoned)
                + len(self.skipped_conflict)
            ),
        }


@dataclass
class _PlannedPage:
    """One page we want to ensure exists / is up to date."""

    key: str
    title: str
    auto_body: str
    chapter_key: str | None = None  # None = page lives at book level


def _device_page(
    device: DeviceSnapshot,
    now: datetime,
    strings: dict[str, str],
) -> _PlannedPage:
    return _PlannedPage(
        key=f"{PAGE_KIND_DEVICE}:{device.device_id}",
        title=strings["title_device_template"].format(name=device.name),
        auto_body=render_device_auto_block(device, now, strings),
        chapter_key=CHAPTER_KEY_DEVICES,
    )


def _plan_pages(
    snapshot: HASnapshot,
    now: datetime,
    strings: dict[str, str],
) -> list[_PlannedPage]:
    """Plan all pages EXCEPT the overview (rendered in a second pass)."""
    planned: list[_PlannedPage] = [
        _PlannedPage(
            key=f"{PAGE_KIND_INTEGRATIONS}:_",
            title=strings["title_integrations"],
            auto_body=render_integrations_auto_block(
                snapshot.integrations,
                now,
                strings,
            ),
        ),
        _PlannedPage(
            key=f"{PAGE_KIND_AUTOMATIONS}:_",
            title=strings["title_automations"],
            auto_body=render_automations_auto_block(
                snapshot.automations,
                now,
                strings,
            ),
        ),
        _PlannedPage(
            key=f"{PAGE_KIND_SCRIPTS}:_",
            title=strings["title_scripts"],
            auto_body=render_scripts_auto_block(snapshot.scripts, now, strings),
        ),
        _PlannedPage(
            key=f"{PAGE_KIND_SCENES}:_",
            title=strings["title_scenes"],
            auto_body=render_scenes_auto_block(snapshot.scenes, now, strings),
        ),
    ]
    if snapshot.addons:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_ADDONS}:_",
                title=strings["title_addons"],
                auto_body=render_addons_auto_block(snapshot.addons, now, strings),
            ),
        )
    for area in snapshot.areas:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_AREA}:{area.area_id}",
                title=strings["title_area_template"].format(name=area.name),
                auto_body=render_area_auto_block(area, now, strings),
                chapter_key=CHAPTER_KEY_AREAS,
            ),
        )
        planned.extend(_device_page(d, now, strings) for d in area.devices)
    planned.extend(_device_page(d, now, strings) for d in snapshot.unassigned_devices)
    return planned


async def _ensure_chapters(
    client: BookStackApiClient,
    store: BookStackSyncStore,
    book_id: int,
    strings: dict[str, str],
) -> dict[str, int]:
    """Make sure the area + device chapters exist; return their IDs."""
    desired = (
        (
            CHAPTER_KEY_AREAS,
            strings["chapter_areas_title"],
            strings["chapter_areas_description"],
        ),
        (
            CHAPTER_KEY_DEVICES,
            strings["chapter_devices_title"],
            strings["chapter_devices_description"],
        ),
    )
    existing_chapters = await client.list_chapters(book_id)
    existing_ids = {int(ch["id"]) for ch in existing_chapters}
    by_name = {ch["name"]: int(ch["id"]) for ch in existing_chapters}

    chapters: dict[str, int] = {}
    for key, title, description in desired:
        stored_id = store.get_chapter(key)
        if stored_id and stored_id in existing_ids:
            chapters[key] = stored_id
            continue
        if title in by_name:
            chapters[key] = by_name[title]
            continue
        created = await client.create_chapter(book_id, title, description=description)
        chapters[key] = int(created["id"])

    for key, chapter_id in chapters.items():
        store.set_chapter(key, chapter_id)
    return chapters


async def run_sync(  # noqa: PLR0913 - cohesive entry point
    hass: HomeAssistant,
    client: BookStackApiClient,
    store: BookStackSyncStore,
    book_id: int,
    strings: dict[str, str],
    *,
    dry_run: bool = False,
    excluded_area_ids: Iterable[str] = (),
) -> SyncReport:
    """Execute one full sync cycle and return a report."""
    report = SyncReport(dry_run=dry_run)
    now = datetime.now(tz=UTC)

    # Registries are pure in-memory dict lookups and must run on the event
    # loop thread - never wrap them in async_add_executor_job.
    snapshot = extract_snapshot(hass, excluded_area_ids=excluded_area_ids)
    planned = _plan_pages(snapshot, now, strings)

    await store.async_load()
    chapters = (
        {} if dry_run else await _ensure_chapters(client, store, book_id, strings)
    )

    # Pass 1: sync all non-overview pages, collect their IDs for the overview.
    page_ids: dict[str, int] = {}
    total_steps = len(planned) + 1  # +1 for the overview pass
    for index, page in enumerate(planned, start=1):
        try:
            page_id = await _sync_one(
                client,
                store,
                book_id,
                page,
                chapters,
                report,
                index=index,
                total=total_steps,
                dry_run=dry_run,
            )
            if page_id is not None:
                page_ids[page.key] = page_id
        except BookStackApiAuthError:
            raise
        except BookStackApiError as err:
            LOGGER.exception("BookStack sync failed for %s", page.key)
            report.errors.append(f"{page.key}: {err}")
        except Exception as err:  # noqa: BLE001 - report and continue
            LOGGER.exception("Unexpected error syncing %s", page.key)
            report.errors.append(f"{page.key}: {err}")
        if not dry_run:
            await asyncio.sleep(WRITE_PAUSE_SECONDS)

    # Pass 2: render overview with page links + sync it.
    overview = _PlannedPage(
        key=f"{PAGE_KIND_OVERVIEW}:_",
        title=strings["title_overview"],
        auto_body=render_overview_auto_block(
            snapshot,
            now,
            strings,
            page_links=page_ids,
        ),
    )
    try:
        await _sync_one(
            client,
            store,
            book_id,
            overview,
            chapters,
            report,
            index=total_steps,
            total=total_steps,
            dry_run=dry_run,
        )
    except BookStackApiAuthError:
        raise
    except BookStackApiError as err:
        LOGGER.exception("BookStack sync failed for overview")
        report.errors.append(f"{overview.key}: {err}")

    all_planned = [overview, *planned]
    await _tombstone_orphans(
        client,
        store,
        all_planned,
        report,
        now,
        strings,
        dry_run=dry_run,
    )

    if not dry_run:
        await store.async_save()

    LOGGER.info(
        "BookStack sync complete: %d created, %d updated, %d unchanged, "
        "%d tombstoned, %d conflicts, %d errors%s",
        len(report.created),
        len(report.updated),
        len(report.unchanged),
        len(report.tombstoned),
        len(report.skipped_conflict),
        len(report.errors),
        " (dry-run)" if dry_run else "",
    )
    if not dry_run:
        _post_sync_notification(hass, report, strings)
    return report


def _post_sync_notification(
    hass: HomeAssistant,
    report: SyncReport,
    strings: dict[str, str],
) -> None:
    body = strings["notification_body_template"].format(
        created=len(report.created),
        updated=len(report.updated),
        unchanged=len(report.unchanged),
        tombstoned=len(report.tombstoned),
        skipped=len(report.skipped_conflict),
        errors=len(report.errors),
    )
    async_create_notification(
        hass,
        body,
        title=strings["notification_title"],
        notification_id="bookstack_sync_last_run",
    )


async def _sync_one(  # noqa: PLR0913 - cohesive sync step, splitting hurts clarity
    client: BookStackApiClient,
    store: BookStackSyncStore,
    book_id: int,
    page: _PlannedPage,
    chapters: dict[str, int],
    report: SyncReport,
    *,
    index: int,
    total: int,
    dry_run: bool,
) -> int | None:
    """Sync one page; return the BookStack page id (or None on dry-run create)."""
    chapter_id = chapters.get(page.chapter_key) if page.chapter_key else None
    new_hash = hash_auto_block(page.auto_body)
    mapping = store.get(page.key)

    LOGGER.debug(
        "BookStack sync %d/%d: %s",
        index,
        total,
        page.title,
    )

    if mapping is None:
        if dry_run:
            report.created.append(page.title)
            return None
        body = build_page_body(page.auto_body, "")
        if chapter_id is not None:
            created = await client.create_page(
                page.title,
                body,
                chapter_id=chapter_id,
            )
        else:
            created = await client.create_page(
                page.title,
                body,
                book_id=book_id,
            )
        page_id = int(created["id"])
        store.set(
            page.key,
            PageMapping(
                page_id=page_id,
                auto_block_hash=new_hash,
                last_seen=datetime.now(tz=UTC).isoformat(),
            ),
        )
        report.created.append(page.title)
        return page_id

    existing = await client.get_page(mapping.page_id)
    needs_move = _needs_move(existing, chapter_id, page.key)

    existing_markdown = existing.get("markdown") or existing.get("raw_html") or ""
    existing_auto = extract_auto_block(existing_markdown)
    existing_auto_hash = hash_auto_block(existing_auto) if existing_auto else None

    merged = merge_page(
        new_auto_body=page.auto_body,
        existing_markdown=existing_markdown,
        last_known_auto_hash=mapping.auto_block_hash or None,
    )

    if merged.manual_block_tampered:
        LOGGER.warning(
            "BookStack page %s (id=%s): AUTO block was edited outside of "
            "Home Assistant - skipping to avoid clobbering manual changes.",
            page.title,
            mapping.page_id,
        )
        report.skipped_conflict.append(page.title)
        return mapping.page_id

    if existing_auto_hash == new_hash and not needs_move:
        report.unchanged.append(page.title)
        mapping.last_seen = datetime.now(tz=UTC).isoformat()
        store.set(page.key, mapping)
        return mapping.page_id

    if dry_run:
        report.updated.append(page.title)
        return mapping.page_id

    await client.update_page(
        mapping.page_id,
        page.title,
        merged.body,
        chapter_id=chapter_id if needs_move else None,
    )
    store.set(
        page.key,
        PageMapping(
            page_id=mapping.page_id,
            auto_block_hash=merged.auto_hash,
            last_seen=datetime.now(tz=UTC).isoformat(),
            tombstoned_at=None,  # device is back; clear any prior tombstone
        ),
    )
    report.updated.append(page.title)
    return mapping.page_id


def _needs_move(
    existing: dict,
    expected_chapter_id: int | None,
    page_key: str,
) -> bool:
    """
    Return whether the existing page needs to be moved into ``expected_chapter_id``.

    Defensively coerces BookStack's response: ``chapter_id`` can come back as
    int, str, None or missing. Anything that doesn't parse to the expected
    target is treated as "needs move" rather than crashing — this is what
    finally clears the V0.1.x findlings stuck at book level on long-running
    setups.
    """
    if expected_chapter_id is None:
        return False
    raw = existing.get("chapter_id")
    try:
        actual = int(raw) if raw is not None else 0
    except TypeError, ValueError:
        LOGGER.warning(
            "BookStack returned non-numeric chapter_id %r for %s "
            "(page id=%s); treating as needs-move",
            raw,
            page_key,
            existing.get("id"),
        )
        return True
    return actual != expected_chapter_id


async def _tombstone_orphans(  # noqa: PLR0913 - cohesive sync step
    client: BookStackApiClient,
    store: BookStackSyncStore,
    planned: list[_PlannedPage],
    report: SyncReport,
    now: datetime,
    strings: dict[str, str],
    *,
    dry_run: bool,
) -> None:
    """Mark pages whose HA object vanished as orphaned (one-time, not on repeat)."""
    planned_keys = {p.key for p in planned}
    # Sorted iteration keeps the report and BookStack revision stream stable.
    for key, mapping in sorted(store.all().items()):
        if key in planned_keys:
            continue
        if mapping.tombstoned_at is not None:
            continue
        try:
            await _tombstone_one(
                client,
                store,
                key,
                mapping,
                report,
                now,
                strings,
                dry_run=dry_run,
            )
        except BookStackApiAuthError:
            raise
        except BookStackApiError as err:
            LOGGER.exception("Tombstone failed for %s", key)
            report.errors.append(f"{key} (tombstone): {err}")
        except Exception as err:  # noqa: BLE001 - report and continue
            LOGGER.exception("Unexpected error tombstoning %s", key)
            report.errors.append(f"{key} (tombstone): {err}")
        if not dry_run:
            await asyncio.sleep(WRITE_PAUSE_SECONDS)


async def _tombstone_one(  # noqa: PLR0913 - cohesive sync step
    client: BookStackApiClient,
    store: BookStackSyncStore,
    key: str,
    mapping: PageMapping,
    report: SyncReport,
    now: datetime,
    strings: dict[str, str],
    *,
    dry_run: bool,
) -> None:
    auto_body = render_tombstone_auto_block(strings, now)
    new_hash = hash_auto_block(auto_body)

    existing = await client.get_page(mapping.page_id)
    existing_markdown = existing.get("markdown") or existing.get("raw_html") or ""

    merged = merge_page(
        new_auto_body=auto_body,
        existing_markdown=existing_markdown,
        last_known_auto_hash=mapping.auto_block_hash or None,
    )

    if merged.manual_block_tampered:
        LOGGER.warning(
            "BookStack page id=%s (%s): AUTO block was edited manually - "
            "skipping tombstone to preserve manual changes.",
            mapping.page_id,
            key,
        )
        report.skipped_conflict.append(f"{key} (tombstone)")
        return

    existing_name = existing.get("name") or key

    if dry_run:
        report.tombstoned.append(existing_name)
        return

    await client.update_page(mapping.page_id, existing_name, merged.body)
    store.set(
        key,
        PageMapping(
            page_id=mapping.page_id,
            auto_block_hash=new_hash,
            last_seen=mapping.last_seen,
            tombstoned_at=now.isoformat(),
        ),
    )
    report.tombstoned.append(existing_name)
