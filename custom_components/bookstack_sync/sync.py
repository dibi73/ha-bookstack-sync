"""Sync orchestrator: snapshot HA -> render -> merge -> push to BookStack."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .api import BookStackApiAuthError, BookStackApiError
from .const import (
    LOGGER,
    PAGE_KIND_ADDONS,
    PAGE_KIND_AREA,
    PAGE_KIND_DEVICE,
    PAGE_KIND_OVERVIEW,
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
    render_device_auto_block,
    render_overview_auto_block,
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
    skipped_conflict: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def as_dict(self) -> dict[str, list[str] | bool | int]:
        """Plain-dict view for logging from the preview service."""
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped_conflict": self.skipped_conflict,
            "errors": self.errors,
            "dry_run": self.dry_run,
            "total_pages": (
                len(self.created)
                + len(self.updated)
                + len(self.unchanged)
                + len(self.skipped_conflict)
            ),
        }


@dataclass
class _PlannedPage:
    key: str
    title: str
    auto_body: str


def _device_page(device: DeviceSnapshot, now: datetime) -> _PlannedPage:
    return _PlannedPage(
        key=f"{PAGE_KIND_DEVICE}:{device.device_id}",
        title=f"Gerät: {device.name}",
        auto_body=render_device_auto_block(device, now),
    )


def _plan_pages(snapshot: HASnapshot, now: datetime) -> list[_PlannedPage]:
    planned: list[_PlannedPage] = [
        _PlannedPage(
            key=f"{PAGE_KIND_OVERVIEW}:_",
            title="Home Assistant – Übersicht",
            auto_body=render_overview_auto_block(snapshot, now),
        ),
    ]
    if snapshot.addons:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_ADDONS}:_",
                title="Home Assistant – Add-ons",
                auto_body=render_addons_auto_block(snapshot.addons, now),
            ),
        )
    for area in snapshot.areas:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_AREA}:{area.area_id}",
                title=f"Raum: {area.name}",
                auto_body=render_area_auto_block(area, now),
            ),
        )
        planned.extend(_device_page(d, now) for d in area.devices)
    planned.extend(_device_page(d, now) for d in snapshot.unassigned_devices)
    return planned


async def run_sync(  # noqa: PLR0913 - cohesive entry point
    hass: HomeAssistant,
    client: BookStackApiClient,
    store: BookStackSyncStore,
    book_id: int,
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
    planned = _plan_pages(snapshot, now)

    await store.async_load()

    for page in planned:
        try:
            await _sync_one(client, store, book_id, page, report, dry_run=dry_run)
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

    if not dry_run:
        await store.async_save()

    LOGGER.info(
        "BookStack sync complete: %d created, %d updated, %d unchanged, "
        "%d conflicts, %d errors%s",
        len(report.created),
        len(report.updated),
        len(report.unchanged),
        len(report.skipped_conflict),
        len(report.errors),
        " (dry-run)" if dry_run else "",
    )
    return report


async def _sync_one(  # noqa: PLR0913 - cohesive sync step, splitting hurts clarity
    client: BookStackApiClient,
    store: BookStackSyncStore,
    book_id: int,
    page: _PlannedPage,
    report: SyncReport,
    *,
    dry_run: bool,
) -> None:
    new_hash = hash_auto_block(page.auto_body)
    mapping = store.get(page.key)

    if mapping is None:
        if dry_run:
            report.created.append(page.title)
            return
        body = build_page_body(page.auto_body, "")
        created = await client.create_page(book_id, page.title, body)
        store.set(
            page.key,
            PageMapping(
                page_id=int(created["id"]),
                auto_block_hash=new_hash,
                last_seen=datetime.now(tz=UTC).isoformat(),
            ),
        )
        report.created.append(page.title)
        return

    existing = await client.get_page(mapping.page_id)
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
        return

    if existing_auto_hash == new_hash:
        report.unchanged.append(page.title)
        mapping.last_seen = datetime.now(tz=UTC).isoformat()
        store.set(page.key, mapping)
        return

    if dry_run:
        report.updated.append(page.title)
        return

    await client.update_page(mapping.page_id, page.title, merged.body)
    store.set(
        page.key,
        PageMapping(
            page_id=mapping.page_id,
            auto_block_hash=merged.auto_hash,
            last_seen=datetime.now(tz=UTC).isoformat(),
        ),
    )
    report.updated.append(page.title)
