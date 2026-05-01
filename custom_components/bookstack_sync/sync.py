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
    PAGE_KIND_BLUETOOTH,
    PAGE_KIND_DEVICE,
    PAGE_KIND_ENERGY,
    PAGE_KIND_HELPERS,
    PAGE_KIND_INTEGRATIONS,
    PAGE_KIND_MQTT,
    PAGE_KIND_NETWORK,
    PAGE_KIND_OVERVIEW,
    PAGE_KIND_RECORDER,
    PAGE_KIND_SCENES,
    PAGE_KIND_SCRIPTS,
    PAGE_KIND_SERVICES,
    TAG_NAME,
    TAG_VALUE_MANAGED,
    TAG_VALUE_ORPHANED,
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
    render_bluetooth_auto_block,
    render_device_auto_block,
    render_energy_auto_block,
    render_helpers_auto_block,
    render_integrations_auto_block,
    render_mqtt_auto_block,
    render_network_auto_block,
    render_overview_auto_block,
    render_recorder_auto_block,
    render_scenes_auto_block,
    render_scripts_auto_block,
    render_services_auto_block,
    render_tombstone_auto_block,
)
from .store import PageMapping


def _managed_tags() -> list[dict[str, str]]:
    """Tag set applied to a healthy page on every write."""
    return [{"name": TAG_NAME, "value": TAG_VALUE_MANAGED}]


def _orphaned_tags() -> list[dict[str, str]]:
    """Tag set applied to a tombstoned page (overwrites the managed tag)."""
    return [{"name": TAG_NAME, "value": TAG_VALUE_ORPHANED}]


def _hash_from_response(
    response: dict,
    fallback_auto_body: str,
) -> tuple[str, str]:
    """
    Return (hash, origin) for a create/update response.

    BookStack normalises the markdown when saving (whitespace, line
    endings). If we hash what we *sent*, the next read produces a
    different hash and we mistakenly flag it as tampered (issue #58).
    Solution: hash what BookStack actually stored — extract the AUTO
    block from the response's ``markdown`` field. If that field is
    missing (older BookStack), fall back to write-side hash and mark
    origin so the migration path takes over on the next sync.
    """
    saved_markdown = response.get("markdown") or ""
    if saved_markdown:
        saved_auto = extract_auto_block(saved_markdown)
        if saved_auto is not None:
            return hash_auto_block(saved_auto), "bookstack"
    return hash_auto_block(fallback_auto_body), "write"


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
    # Stable page keys (e.g. ``device:UUID``) of pages whose AUTO block
    # was tampered with this run. Used by the coordinator to drive HA
    # repair-issues without having to re-derive keys from titles.
    tampered_page_keys: list[str] = field(default_factory=list)
    # Human-readable titles paired with the keys above (same length,
    # same order). Lets repair-issue translations show the page name.
    tampered_page_titles: list[str] = field(default_factory=list)
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
    reverse_usage: dict[str, list] | None = None,
) -> _PlannedPage:
    return _PlannedPage(
        key=f"{PAGE_KIND_DEVICE}:{device.device_id}",
        title=strings["title_device_template"].format(name=device.name),
        auto_body=render_device_auto_block(
            device,
            now,
            strings,
            reverse_usage=reverse_usage,
        ),
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
    network_devices = _devices_with_network(snapshot)
    has_topology = bool(snapshot.unifi_topology and snapshot.unifi_topology.nodes)
    if network_devices or snapshot.unknown_unifi_clients or has_topology:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_NETWORK}:_",
                title=strings["title_network"],
                auto_body=render_network_auto_block(
                    network_devices,
                    now,
                    strings,
                    unknown_clients=snapshot.unknown_unifi_clients,
                    topology=snapshot.unifi_topology,
                    snapshot=snapshot,
                ),
            ),
        )
    if snapshot.bluetooth and snapshot.bluetooth.scanners:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_BLUETOOTH}:_",
                title=strings["title_bluetooth"],
                auto_body=render_bluetooth_auto_block(
                    snapshot.bluetooth,
                    now,
                    strings,
                ),
            ),
        )
    if snapshot.notify_services or snapshot.tts_services:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_SERVICES}:_",
                title=strings["title_services"],
                auto_body=render_services_auto_block(
                    snapshot.notify_services,
                    snapshot.tts_services,
                    now,
                    strings,
                ),
            ),
        )
    if snapshot.recorder is not None:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_RECORDER}:_",
                title=strings["title_recorder"],
                auto_body=render_recorder_auto_block(
                    snapshot.recorder,
                    now,
                    strings,
                ),
            ),
        )
    if snapshot.mqtt_tree is not None:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_MQTT}:_",
                title=strings["title_mqtt"],
                auto_body=render_mqtt_auto_block(
                    snapshot.mqtt_tree,
                    now,
                    strings,
                ),
            ),
        )
    if snapshot.energy is not None:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_ENERGY}:_",
                title=strings["title_energy"],
                auto_body=render_energy_auto_block(
                    snapshot.energy,
                    now,
                    strings,
                ),
            ),
        )
    if snapshot.helpers:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_HELPERS}:_",
                title=strings["title_helpers"],
                auto_body=render_helpers_auto_block(
                    snapshot.helpers,
                    now,
                    strings,
                ),
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
        planned.extend(
            _device_page(d, now, strings, snapshot.reverse_usage) for d in area.devices
        )
    planned.extend(
        _device_page(d, now, strings, snapshot.reverse_usage)
        for d in snapshot.unassigned_devices
    )
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
                strings,
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
            strings,
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
    strings: dict[str, str],
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
                tags=_managed_tags(),
            )
        else:
            created = await client.create_page(
                page.title,
                body,
                book_id=book_id,
                tags=_managed_tags(),
            )
        page_id = int(created["id"])
        # Hash what BookStack actually stored, not what we sent (#58).
        saved_hash, hash_origin = _hash_from_response(created, page.auto_body)
        store.set(
            page.key,
            PageMapping(
                page_id=page_id,
                auto_block_hash=saved_hash,
                last_seen=datetime.now(tz=UTC).isoformat(),
                hash_origin=hash_origin,
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
        default_manual_body=strings.get("default_manual_body"),
    )

    if merged.manual_block_tampered:
        if mapping.hash_origin != "bookstack":
            # Migration path (#58): legacy ``write``-origin hashes can't
            # reliably detect tampering against BookStack's normalised
            # storage. Trust the user, fall through to a fresh write
            # which will store a correct ``bookstack``-origin hash.
            LOGGER.info(
                "BookStack page %s (id=%s): write-origin hash from "
                "pre-v0.11 — suppressing tampering check on this run, "
                "migrating to bookstack-origin hash.",
                page.title,
                mapping.page_id,
            )
        else:
            LOGGER.warning(
                "BookStack page %s (id=%s): AUTO block was edited outside "
                "of Home Assistant - skipping to avoid clobbering manual "
                "changes.",
                page.title,
                mapping.page_id,
            )
            report.skipped_conflict.append(page.title)
            report.tampered_page_keys.append(page.key)
            report.tampered_page_titles.append(page.title)
            return mapping.page_id

    if (
        existing_auto_hash == new_hash
        and not needs_move
        and mapping.hash_origin == "bookstack"
    ):
        # Skip-on-unchanged needs a trustworthy stored hash — only
        # safe when origin is ``bookstack``. Legacy ``write`` mappings
        # always re-write once to settle into the new regime.
        report.unchanged.append(page.title)
        mapping.last_seen = datetime.now(tz=UTC).isoformat()
        store.set(page.key, mapping)
        return mapping.page_id

    if dry_run:
        report.updated.append(page.title)
        return mapping.page_id

    saved = await client.update_page(
        mapping.page_id,
        page.title,
        merged.body,
        chapter_id=chapter_id if needs_move else None,
        tags=_managed_tags(),
    )
    saved_hash, hash_origin = _hash_from_response(saved, page.auto_body)
    store.set(
        page.key,
        PageMapping(
            page_id=mapping.page_id,
            auto_block_hash=saved_hash,
            last_seen=datetime.now(tz=UTC).isoformat(),
            tombstoned_at=None,  # device is back; clear any prior tombstone
            hash_origin=hash_origin,
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

    existing = await client.get_page(mapping.page_id)
    existing_markdown = existing.get("markdown") or existing.get("raw_html") or ""

    merged = merge_page(
        new_auto_body=auto_body,
        existing_markdown=existing_markdown,
        last_known_auto_hash=mapping.auto_block_hash or None,
        default_manual_body=strings.get("default_manual_body"),
    )

    if merged.manual_block_tampered:
        if mapping.hash_origin != "bookstack":
            # Migration path (#58): legacy write-origin hash, suppress.
            LOGGER.info(
                "BookStack page id=%s (%s): write-origin hash, "
                "tombstoning anyway (migration to bookstack-origin).",
                mapping.page_id,
                key,
            )
        else:
            LOGGER.warning(
                "BookStack page id=%s (%s): AUTO block was edited manually "
                "- skipping tombstone to preserve manual changes.",
                mapping.page_id,
                key,
            )
            report.skipped_conflict.append(f"{key} (tombstone)")
            return

    existing_name = existing.get("name") or key

    if dry_run:
        report.tombstoned.append(existing_name)
        return

    saved = await client.update_page(
        mapping.page_id,
        existing_name,
        merged.body,
        tags=_orphaned_tags(),
    )
    saved_hash, hash_origin = _hash_from_response(saved, auto_body)
    store.set(
        key,
        PageMapping(
            page_id=mapping.page_id,
            auto_block_hash=saved_hash,
            last_seen=mapping.last_seen,
            tombstoned_at=now.isoformat(),
            hash_origin=hash_origin,
        ),
    )
    report.tombstoned.append(existing_name)


def _devices_with_network(snapshot: HASnapshot) -> list[DeviceSnapshot]:
    """
    Return devices that have a primary NetworkInfo, sorted for the table.

    Sorted by VLAN (alphabetic) then IP (numeric octet-by-octet) so the
    output is byte-identical between runs and matches typical DHCP-lease
    listings.
    """
    devices: list[DeviceSnapshot] = []
    for area in snapshot.areas:
        devices.extend(d for d in area.devices if d.network is not None)
    devices.extend(d for d in snapshot.unassigned_devices if d.network is not None)

    placeholder_ip = "0.0.0.0"  # noqa: S104 - sort placeholder, not a bind addr

    def ip_key(d: DeviceSnapshot) -> tuple[int, ...]:
        ip = d.network.ip if d.network and d.network.ip else placeholder_ip
        try:
            parts = tuple(int(o) for o in ip.split(".")[:4])
        except ValueError:
            return (0, 0, 0, 0)
        return parts + (0,) * (4 - len(parts))

    def vlan_key(d: DeviceSnapshot) -> str:
        return (d.network.vlan or "") if d.network else ""

    devices.sort(key=lambda d: (vlan_key(d), ip_key(d), d.name.lower()))
    return devices
