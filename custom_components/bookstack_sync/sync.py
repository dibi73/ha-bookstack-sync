"""
Sync orchestrator: snapshot HA -> render -> merge -> push to BookStack.

Flow per run:
1. ``ensure_chapters`` makes sure ``Räume`` / ``Geräte`` / ``Labels``
   chapters exist (titles + descriptions come from the active output
   language).
2. Pass 1 syncs all device / bundle pages and collects their page IDs.
3. Pass 2 renders area pages (device URLs now known) and syncs them.
4. Pass 3 renders label pages (device + area URLs now known, issue #22)
   and syncs them.
5. Pass 4 renders the orphaned-pages overview (#166) from the store's
   currently-tombstoned mappings and writes it.
6. Pass 5 renders the overview with markdown links to the IDs from the
   earlier passes (including pass 4's) and writes it.
7. Pages whose HA object has vanished get a one-time tombstone block.
8. Mapping store is persisted and a persistent notification is posted.

The active output language is passed in via ``strings`` — see
``_strings.get_strings``. Default in coordinator is ``hass.config.language``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
)

from .api import (
    BookStackApiAuthError,
    BookStackApiError,
    BookStackApiNotFoundError,
)
from .const import (
    CHAPTER_KEY_AREAS,
    CHAPTER_KEY_DEVICES,
    CHAPTER_KEY_LABELS,
    LOGGER,
    PAGE_KIND_ADDONS,
    PAGE_KIND_AREA,
    PAGE_KIND_AUTOMATIONS,
    PAGE_KIND_BACKUP,
    PAGE_KIND_BLUETOOTH,
    PAGE_KIND_DEVICE,
    PAGE_KIND_ENERGY,
    PAGE_KIND_HELPERS,
    PAGE_KIND_INTEGRATIONS,
    PAGE_KIND_LABEL,
    PAGE_KIND_MQTT,
    PAGE_KIND_NETWORK,
    PAGE_KIND_ORPHANED,
    PAGE_KIND_OVERVIEW,
    PAGE_KIND_RECORDER,
    PAGE_KIND_SCENES,
    PAGE_KIND_SCRIPTS,
    PAGE_KIND_SERVICES,
    TAG_NAME,
    TAG_VALUE_MANAGED,
    TAG_VALUE_ORPHANED,
)
from .extractor import (
    ReverseUsageEntry,
    async_extract_addons,
    async_extract_backup_status,
    async_extract_energy_config,
    extract_snapshot,
)
from .merge import (
    build_page_body,
    extract_auto_block,
    hash_auto_block,
    merge_page,
)
from .renderer import (
    OrphanedPageEntry,
    render_addons_auto_block,
    render_area_auto_block,
    render_automations_auto_block,
    render_backup_auto_block,
    render_bluetooth_auto_block,
    render_device_auto_block,
    render_energy_auto_block,
    render_helpers_auto_block,
    render_integrations_auto_block,
    render_label_auto_block,
    render_mqtt_auto_block,
    render_network_auto_block,
    render_orphaned_auto_block,
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
    response: dict[str, Any],
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
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

    from .api import BookStackApiClient
    from .extractor import DeviceSnapshot, HASnapshot, LabelSnapshot
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
    # Absolute BookStack URLs paired with the keys above (issue #189) —
    # "" when unresolvable (see _build_absolute_page_url). Lets the
    # repair-issue description link straight to the affected page.
    tampered_page_urls: list[str] = field(default_factory=list)
    # Page keys + titles of pages where the marker comments are gone
    # (typical cause: WYSIWYG-editor toggle). Same shape as the tampered
    # lists so the coordinator can reconcile a separate repair issue.
    markers_missing_page_keys: list[str] = field(default_factory=list)
    markers_missing_page_titles: list[str] = field(default_factory=list)
    markers_missing_page_urls: list[str] = field(default_factory=list)
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
    # 1-based sidebar position within chapter_key (issue #185). None = don't
    # touch BookStack's priority - deliberately left unset for book-level
    # pages (chapter_key=None): that root-level ordering isn't in scope, see
    # the issue discussion.
    priority: int | None = None


def _device_page(  # noqa: PLR0913 - cohesive planner, mirrors _label_page's params
    device: DeviceSnapshot,
    now: datetime,
    strings: dict[str, str],
    reverse_usage: dict[str, list[ReverseUsageEntry]] | None = None,
    ha_url: str = "",
    priority: int | None = None,
) -> _PlannedPage:
    return _PlannedPage(
        key=f"{PAGE_KIND_DEVICE}:{device.device_id}",
        title=strings["title_device_template"].format(name=device.name),
        auto_body=render_device_auto_block(
            device,
            now,
            strings,
            reverse_usage=reverse_usage,
            ha_url=ha_url,
        ),
        chapter_key=CHAPTER_KEY_DEVICES,
        priority=priority,
    )


def _plan_pages(
    snapshot: HASnapshot,
    now: datetime,
    strings: dict[str, str],
    ha_url: str = "",
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
                ha_url=ha_url,
            ),
        ),
        _PlannedPage(
            key=f"{PAGE_KIND_AUTOMATIONS}:_",
            title=strings["title_automations"],
            auto_body=render_automations_auto_block(
                snapshot.automations,
                now,
                strings,
                ha_url=ha_url,
            ),
        ),
        _PlannedPage(
            key=f"{PAGE_KIND_SCRIPTS}:_",
            title=strings["title_scripts"],
            auto_body=render_scripts_auto_block(
                snapshot.scripts,
                now,
                strings,
                ha_url=ha_url,
            ),
        ),
        _PlannedPage(
            key=f"{PAGE_KIND_SCENES}:_",
            title=strings["title_scenes"],
            auto_body=render_scenes_auto_block(
                snapshot.scenes,
                now,
                strings,
                ha_url=ha_url,
            ),
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
    if snapshot.bluetooth:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_BLUETOOTH}:_",
                title=strings["title_bluetooth"],
                auto_body=render_bluetooth_auto_block(
                    snapshot.bluetooth,
                    now,
                    strings,
                    ha_url=ha_url,
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
    if snapshot.backup_status is not None:
        planned.append(
            _PlannedPage(
                key=f"{PAGE_KIND_BACKUP}:_",
                title=strings["title_backup"],
                auto_body=render_backup_auto_block(
                    snapshot.backup_status,
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
                    ha_url=ha_url,
                ),
            ),
        )
    # Areas are rendered in a SECOND pass so they can carry cross-page
    # Markdown links to the device pages (v0.14.0/v0.14.4). Pass 1 only
    # contains bundle pages + every device — we collect their page IDs
    # first, then ``_plan_area_pages`` renders each area on top of those.
    #
    # Priority (issue #185): every device page shares one chapter
    # ("Geräte") regardless of area, so the sidebar order needs one
    # counter across the whole flattened area+unassigned list below -
    # numbering per-area would just reproduce area grouping, not the
    # alphabetical-per-device order the sidebar shows.
    all_devices = [d for area in snapshot.areas for d in area.devices]
    all_devices.extend(snapshot.unassigned_devices)
    planned.extend(
        _device_page(
            d,
            now,
            strings,
            snapshot.reverse_usage,
            ha_url=ha_url,
            priority=idx + 1,
        )
        for idx, d in enumerate(all_devices)
    )
    return planned


def _build_page_url(book_slug: str, page_slug: str) -> str | None:
    """
    Construct a BookStack cross-link for a page, relative to BookStack's own origin.

    Deliberately root-relative (``/books/<book>/page/<page>``), NOT
    ``{base_url}/books/...`` (pre-v0.15.1 behaviour). ``base_url`` is the
    address bookstack-sync itself uses to reach BookStack's API — often a
    LAN-only address (e.g. ``http://192.168.0.16:2665``) that has nothing
    to do with how a *person* is viewing BookStack in their browser, which
    could be a different LAN address, a reverse-proxy hostname, or a
    public domain if BookStack is exposed externally. A root-relative
    href resolves against whatever origin the browser is already on, so
    the same link works no matter which of those the reader used to open
    the page — unlike the HA-deep-link case (v0.14.5), there's no
    external/internal choice to make here at all, relative just always
    wins.

    Returns ``None`` when any component is missing — caller falls back
    to a bold-name label rather than rendering a broken link. Empty
    ``book_slug`` typically means the post-v0.14.4 first sync hasn't
    finished caching the slug yet; empty ``page_slug`` means the
    mapping was migrated from a pre-v0.14.4 store and we haven't
    re-fetched the page since.
    """
    if not book_slug or not page_slug:
        return None
    return f"/books/{book_slug}/page/{page_slug}"


def _build_absolute_page_url(
    base_url: str,
    book_slug: str,
    page_slug: str,
) -> str | None:
    """
    Construct a full, clickable BookStack page URL (issue #189).

    Unlike ``_build_page_url`` above, this one IS meant to be resolved
    against ``base_url`` — used only for links rendered in Home
    Assistant's own UI (repair issues), which has no BookStack page to
    resolve a root-relative href against. Carries the same caveat
    ``_build_page_url`` avoids: ``base_url`` is whatever address
    bookstack-sync itself uses to reach BookStack's API (e.g. a
    LAN-only address), which could differ from how a person actually
    browses to BookStack (reverse-proxy hostname, public domain) — the
    link may not be clickable from outside that network. Still far more
    useful than no link at all for the common case where they match.
    """
    relative = _build_page_url(book_slug, page_slug)
    if relative is None or not base_url:
        return None
    return f"{base_url.rstrip('/')}{relative}"


def _plan_area_pages(
    snapshot: HASnapshot,
    now: datetime,
    strings: dict[str, str],
    page_links: dict[str, str],
    ha_url: str = "",
) -> list[_PlannedPage]:
    """Render area pages with cross-page Markdown links to device pages."""
    return [
        _PlannedPage(
            key=f"{PAGE_KIND_AREA}:{area.area_id}",
            title=strings["title_area_template"].format(name=area.name),
            auto_body=render_area_auto_block(
                area,
                now,
                strings,
                page_links=page_links,
                ha_url=ha_url,
            ),
            chapter_key=CHAPTER_KEY_AREAS,
            priority=idx + 1,
        )
        for idx, area in enumerate(snapshot.areas)
    ]


def _label_page(  # noqa: PLR0913 - cohesive planner, mirrors _device_page's params + area_names
    label: LabelSnapshot,
    now: datetime,
    strings: dict[str, str],
    page_links: dict[str, str],
    area_names: dict[str, str],
    ha_url: str = "",
    priority: int | None = None,
) -> _PlannedPage:
    """
    Plan one label page (issue #22).

    Title carries the label's MDI icon name in parentheses when set
    (maintainer decision on the issue — color is ignored, not worth the
    complexity). Needs ``page_links``/``area_names`` from a pass after
    devices AND areas have been synced, same reason area pages do
    (cross-page Markdown links to device/area pages).
    """
    title = strings["title_label_template"].format(name=label.name)
    if label.icon:
        title = f"{title} ({label.icon})"
    return _PlannedPage(
        key=f"{PAGE_KIND_LABEL}:{label.label_id}",
        title=title,
        auto_body=render_label_auto_block(
            label,
            now,
            strings,
            page_links=page_links,
            area_names=area_names,
            ha_url=ha_url,
        ),
        chapter_key=CHAPTER_KEY_LABELS,
        priority=priority,
    )


def _plan_label_pages(
    snapshot: HASnapshot,
    now: datetime,
    strings: dict[str, str],
    page_links: dict[str, str],
    ha_url: str = "",
) -> list[_PlannedPage]:
    """Plan every label page. Empty when no label has a device (issue #22)."""
    area_names = {area.area_id: area.name for area in snapshot.areas}
    return [
        _label_page(
            label,
            now,
            strings,
            page_links,
            area_names,
            ha_url=ha_url,
            priority=idx + 1,
        )
        for idx, label in enumerate(snapshot.labels)
    ]


async def _ensure_chapters(
    client: BookStackApiClient,
    store: BookStackSyncStore,
    book_id: int,
    strings: dict[str, str],
) -> dict[str, int]:
    """Make sure the area + device + labels chapters exist; return their IDs."""
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
        (
            CHAPTER_KEY_LABELS,
            strings["chapter_labels_title"],
            strings["chapter_labels_description"],
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


async def run_sync(  # noqa: C901, PLR0912, PLR0913, PLR0915 - cohesive 3-pass entry point
    hass: HomeAssistant,
    client: BookStackApiClient,
    store: BookStackSyncStore,
    book_id: int,
    strings: dict[str, str],
    *,
    dry_run: bool = False,
    force: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
    external_base_url: str | None = None,
) -> SyncReport:
    """
    Execute one full sync cycle and return a report.

    ``external_base_url`` (issue #202) overrides ``client.base_url`` only
    for the absolute links embedded in repair-issue descriptions - those
    render in HA's own UI, which may be reachable from outside the LAN
    even when ``client.base_url`` (how bookstack-sync itself reaches the
    BookStack API) isn't. ``None`` keeps the previous behaviour of using
    ``client.base_url`` for both.
    """
    report = SyncReport(dry_run=dry_run)
    now = datetime.now(tz=UTC)

    # Registries are pure in-memory dict lookups and must run on the event
    # loop thread - never wrap them in async_add_executor_job. The
    # Energy-Dashboard config however is read from ``.storage/energy``,
    # so we fetch it here on the executor (v0.14.10) and inject it into
    # the otherwise-sync snapshot pipeline.
    # Loaded before the snapshot (not after, like every other read here)
    # so ``known_device_pages`` can make merged-device primary selection
    # sticky — see ``extract_snapshot``'s docstring / ``_primary_priority``.
    # ``async_load`` is a no-op on a second call, so this doesn't change
    # anything for callers that already loaded the store themselves.
    await store.async_load()
    known_device_pages = {
        key.split(":", 1)[1]: mapping.tombstoned_at is not None
        for key, mapping in store.all().items()
        if key.startswith(f"{PAGE_KIND_DEVICE}:")
    }

    energy_config = await async_extract_energy_config(hass)
    backup_status = await async_extract_backup_status(hass)
    addons = await async_extract_addons(hass)
    snapshot = extract_snapshot(
        hass,
        energy_config=energy_config,
        backup_status=backup_status,
        addons=addons,
        known_device_pages=known_device_pages,
    )
    # v0.14.5: HA-frontend deep-links use this base. ``external_url``
    # wins over ``internal_url`` because the same Markdown lands in
    # exported .md files that the optional RAG add-on serves to the
    # household — internal-only URLs would 404 from a phone browser
    # outside the LAN. When neither is configured, renderers degrade
    # silently to plain code-spans / bold labels — never broken hrefs.
    ha_url = (hass.config.external_url or hass.config.internal_url or "").rstrip("/")
    planned = _plan_pages(snapshot, now, strings, ha_url=ha_url)

    chapters = (
        {} if dry_run else await _ensure_chapters(client, store, book_id, strings)
    )

    # v0.14.4: capture (and persist) the BookStack book slug so we can
    # build proper Markdown links of the form
    # ``/books/{book_slug}/page/{page_slug}`` (root-relative since
    # v0.15.1, see ``_build_page_url``) instead of the ``{{@<id>}}``
    # syntax we used through v0.14.3 — which BookStack interprets as
    # INCLUDE/transclusion (it inlines the linked page's whole content),
    # not as a cross-link.
    book_slug = store.get_book_slug()
    if not book_slug:
        try:
            for book in await client.list_books():
                if int(book.get("id", 0)) == book_id:
                    book_slug = str(book.get("slug") or "")
                    break
        except BookStackApiError as err:
            LOGGER.warning(
                "Could not fetch book slug for URL construction: %s. "
                "Falling back to bold-name labels in cross-references.",
                err,
            )
        if book_slug:
            store.set_book_slug(book_slug)

    # Pass 1: sync devices + bundles. Build URL map so areas + overview can
    # render proper Markdown links to them.
    page_links: dict[str, str] = {}

    def _refresh_url(page_key: str) -> None:
        """Look up the current slug in the store and add the URL to page_links."""
        m = store.get(page_key)
        if m and m.slug:
            url = _build_page_url(book_slug, m.slug)
            if url:
                page_links[page_key] = url

    area_planned = _plan_area_pages(snapshot, now, strings, page_links, ha_url=ha_url)
    label_planned = _plan_label_pages(snapshot, now, strings, page_links, ha_url=ha_url)
    total_steps = (
        len(planned) + len(area_planned) + len(label_planned) + 2
    )  # +1 overview, +1 orphaned-pages overview (#166)
    step = 0

    def _emit_progress() -> None:
        """Tell the coordinator (and via it, the status sensor) where we are."""
        if progress_callback is not None:
            progress_callback(step, total_steps)

    _emit_progress()
    for page in planned:
        step += 1
        try:
            page_id = await _sync_one(
                client,
                store,
                book_id,
                page,
                chapters,
                report,
                strings,
                index=step,
                total=total_steps,
                dry_run=dry_run,
                force=force,
                book_slug=book_slug,
                external_base_url=external_base_url,
            )
            if page_id is not None:
                _refresh_url(page.key)
        except BookStackApiAuthError:
            raise
        except BookStackApiError as err:
            LOGGER.exception("BookStack sync failed for %s", page.key)
            report.errors.append(f"{page.key}: {err}")
        except Exception as err:  # noqa: BLE001 - report and continue
            LOGGER.exception("Unexpected error syncing %s", page.key)
            report.errors.append(f"{page.key}: {err}")
        _emit_progress()
        if not dry_run:
            # #127: persist after every page, not just once at the end of
            # the whole multi-pass run - an interrupted run (HA restart,
            # BookStack outage) then only loses the one in-flight page's
            # state instead of every page already written this run.
            await store.async_save()
            await asyncio.sleep(WRITE_PAUSE_SECONDS)

    # Pass 2: render area pages (now that device URLs exist) and sync them.
    # Re-plan with the populated page_links so each area's auto-body
    # contains real cross-page Markdown links instead of bold-name fallbacks.
    area_planned = _plan_area_pages(snapshot, now, strings, page_links, ha_url=ha_url)
    for page in area_planned:
        step += 1
        try:
            page_id = await _sync_one(
                client,
                store,
                book_id,
                page,
                chapters,
                report,
                strings,
                index=step,
                total=total_steps,
                dry_run=dry_run,
                force=force,
                book_slug=book_slug,
                external_base_url=external_base_url,
            )
            if page_id is not None:
                _refresh_url(page.key)
        except BookStackApiAuthError:
            raise
        except BookStackApiError as err:
            LOGGER.exception("BookStack sync failed for %s", page.key)
            report.errors.append(f"{page.key}: {err}")
        except Exception as err:  # noqa: BLE001 - report and continue
            LOGGER.exception("Unexpected error syncing %s", page.key)
            report.errors.append(f"{page.key}: {err}")
        _emit_progress()
        if not dry_run:
            await store.async_save()  # #127: incremental persistence
            await asyncio.sleep(WRITE_PAUSE_SECONDS)

    # Pass 3: render label pages (now that device + area URLs exist) and
    # sync them. Same re-plan-with-populated-links reasoning as pass 2.
    label_planned = _plan_label_pages(snapshot, now, strings, page_links, ha_url=ha_url)
    for page in label_planned:
        step += 1
        try:
            page_id = await _sync_one(
                client,
                store,
                book_id,
                page,
                chapters,
                report,
                strings,
                index=step,
                total=total_steps,
                dry_run=dry_run,
                force=force,
                book_slug=book_slug,
                external_base_url=external_base_url,
            )
            if page_id is not None:
                _refresh_url(page.key)
        except BookStackApiAuthError:
            raise
        except BookStackApiError as err:
            LOGGER.exception("BookStack sync failed for %s", page.key)
            report.errors.append(f"{page.key}: {err}")
        except Exception as err:  # noqa: BLE001 - report and continue
            LOGGER.exception("Unexpected error syncing %s", page.key)
            report.errors.append(f"{page.key}: {err}")
        _emit_progress()
        if not dry_run:
            await store.async_save()  # #127: incremental persistence
            await asyncio.sleep(WRITE_PAUSE_SECONDS)

    # Pass 4: orphaned-pages overview (#166). Built from the store's
    # CURRENT tombstoned mappings — i.e. as of before this run's own
    # tombstoning below, same one-sync-cycle lag the overview/area/label
    # pages already have relative to each other. Synced (and its URL
    # captured via ``_refresh_url``) BEFORE the main overview below, for
    # two reasons: (1) its own key must exist in ``all_planned`` before
    # ``_tombstone_orphans`` runs, else this bundle page itself would
    # look like a vanished HA object and get wrongly tombstoned every
    # run; (2) the main overview's "Other pages" list can then link to
    # it directly instead of always rendering bold, unlinked text.
    orphaned_entries = await _gather_orphaned_entries(client, store, book_slug)
    orphaned_page = _PlannedPage(
        key=f"{PAGE_KIND_ORPHANED}:_",
        title=strings["title_orphaned"],
        auto_body=render_orphaned_auto_block(orphaned_entries, now, strings),
    )
    step += 1
    try:
        orphaned_page_id = await _sync_one(
            client,
            store,
            book_id,
            orphaned_page,
            chapters,
            report,
            strings,
            index=step,
            total=total_steps,
            dry_run=dry_run,
            force=force,
            book_slug=book_slug,
            external_base_url=external_base_url,
        )
        if orphaned_page_id is not None:
            _refresh_url(orphaned_page.key)
    except BookStackApiAuthError:
        raise
    except BookStackApiError as err:
        LOGGER.exception("BookStack sync failed for orphaned-pages overview")
        report.errors.append(f"{orphaned_page.key}: {err}")
    _emit_progress()
    if not dry_run:
        await store.async_save()  # #127: incremental persistence

    # Pass 5: render overview with the full URL map + sync it.
    overview = _PlannedPage(
        key=f"{PAGE_KIND_OVERVIEW}:_",
        title=strings["title_overview"],
        auto_body=render_overview_auto_block(
            snapshot,
            now,
            strings,
            page_links=page_links,
        ),
    )
    step += 1
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
            force=force,
            book_slug=book_slug,
            external_base_url=external_base_url,
        )
    except BookStackApiAuthError:
        raise
    except BookStackApiError as err:
        LOGGER.exception("BookStack sync failed for overview")
        report.errors.append(f"{overview.key}: {err}")
    _emit_progress()
    if not dry_run:
        await store.async_save()  # #127: incremental persistence

    all_planned = [overview, orphaned_page, *area_planned, *label_planned, *planned]
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


async def resync_single_page(  # noqa: PLR0913 - mirrors run_sync's core params + page_key
    hass: HomeAssistant,
    client: BookStackApiClient,
    store: BookStackSyncStore,
    book_id: int,
    page_key: str,
    strings: dict[str, str],
    external_base_url: str | None = None,
) -> bool:
    """
    Force-resync exactly one page's AUTO block (#190 repair-issue Fix flow).

    Unlike ``run_sync(force=True)``, which force-overwrites every page,
    this only touches the one page identified by ``page_key`` - so
    clicking "Fix" on a single tampered/markers-missing repair issue
    doesn't also churn every unrelated page's revision history in
    BookStack.

    ``external_base_url`` (#202) is threaded through to ``_sync_one``
    for consistency, though it's currently a no-op here: ``force=True``
    never reaches the skip branches that build a repair-issue URL.

    Cross-page Markdown links use the slugs already recorded in
    ``store`` from previous full syncs, rather than a fresh write pass
    over every other page - safe because a repair issue can only exist
    for a page that has already been through at least one full sync.

    Returns ``False`` if no planned page currently matches ``page_key``
    (the underlying device/area/label was removed from HA between the
    issue being raised and the fix being confirmed) - caller should
    treat that as "nothing left to fix", not an error.
    """
    await store.async_load()
    known_device_pages = {
        key.split(":", 1)[1]: mapping.tombstoned_at is not None
        for key, mapping in store.all().items()
        if key.startswith(f"{PAGE_KIND_DEVICE}:")
    }
    energy_config = await async_extract_energy_config(hass)
    backup_status = await async_extract_backup_status(hass)
    addons = await async_extract_addons(hass)
    snapshot = extract_snapshot(
        hass,
        energy_config=energy_config,
        backup_status=backup_status,
        addons=addons,
        known_device_pages=known_device_pages,
    )
    now = datetime.now(tz=UTC)
    ha_url = (hass.config.external_url or hass.config.internal_url or "").rstrip("/")
    book_slug = store.get_book_slug() or ""

    page_links: dict[str, str] = {}
    for key, mapping in store.all().items():
        if mapping.slug:
            url = _build_page_url(book_slug, mapping.slug)
            if url:
                page_links[key] = url

    all_planned = [
        *_plan_pages(snapshot, now, strings, ha_url=ha_url),
        *_plan_area_pages(snapshot, now, strings, page_links, ha_url=ha_url),
        *_plan_label_pages(snapshot, now, strings, page_links, ha_url=ha_url),
    ]
    page = next((p for p in all_planned if p.key == page_key), None)
    if page is None:
        return False

    chapters = await _ensure_chapters(client, store, book_id, strings)
    report = SyncReport()
    await _sync_one(
        client,
        store,
        book_id,
        page,
        chapters,
        report,
        strings,
        index=1,
        total=1,
        dry_run=False,
        force=True,
        book_slug=book_slug,
        external_base_url=external_base_url,
    )
    await store.async_save()
    return True


def _post_sync_notification(
    hass: HomeAssistant,
    report: SyncReport,
    strings: dict[str, str],
) -> None:
    """
    Surface a persistent notification only when something needs attention.

    Successful runs are silent — the status sensor + integration card already
    show "ok", and a green-bell-every-night spam is more noise than value.
    Errors and tampering-related skips do warrant a notification, because
    those are exactly the cases the user has to act on.
    """
    has_errors = bool(report.errors)
    has_skipped = bool(report.skipped_conflict)
    if not has_errors and not has_skipped:
        return
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


async def _sync_one(  # noqa: PLR0911, PLR0913, PLR0915 - cohesive sync step, splitting hurts clarity
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
    force: bool = False,
    book_slug: str = "",
    external_base_url: str | None = None,
) -> int | None:
    """Sync one page; return the BookStack page id (or None on dry-run create)."""
    # #202: repair-issue links use whichever base URL a person would
    # actually be able to open from wherever they're reading HA's
    # notifications - falls back to client.base_url (the address
    # bookstack-sync itself uses) when nothing more specific is set.
    repair_link_base_url = external_base_url or client.base_url
    chapter_id = chapters.get(page.chapter_key) if page.chapter_key else None
    new_hash = hash_auto_block(page.auto_body)
    mapping = store.get(page.key)

    LOGGER.debug(
        "BookStack sync %d/%d: %s",
        index,
        total,
        page.title,
    )

    async def _create_fresh() -> int | None:
        """Create the BookStack page from scratch (no usable mapping)."""
        if dry_run:
            report.created.append(page.title)
            return None
        manual_heading = strings.get("heading_manual")
        initial_manual = f"# {manual_heading}" if manual_heading else ""
        body = build_page_body(page.auto_body, initial_manual)
        if chapter_id is not None:
            created = await client.create_page(
                page.title,
                body,
                chapter_id=chapter_id,
                tags=_managed_tags(),
                priority=page.priority,
            )
        else:
            created = await client.create_page(
                page.title,
                body,
                book_id=book_id,
                tags=_managed_tags(),
                priority=page.priority,
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
                slug=str(created.get("slug") or ""),
            ),
        )
        report.created.append(page.title)
        return page_id

    if mapping is None:
        return await _create_fresh()

    try:
        existing = await client.get_page(mapping.page_id)
    except BookStackApiNotFoundError:
        # v0.14.10: page was deleted directly in BookStack between
        # syncs. Pre-fix this raised BookStackApiCommunicationError
        # which aborted the whole area's sync; now we drop the stale
        # mapping and recreate the page so the user's HA object stays
        # documented.
        LOGGER.warning(
            "BookStack page %s was tracked under id=%s but is gone "
            "from BookStack — dropping stale mapping and recreating.",
            page.title,
            mapping.page_id,
        )
        store.discard(page.key)
        return await _create_fresh()
    needs_move = _needs_move(existing, chapter_id, page.key)

    existing_markdown = existing.get("markdown") or existing.get("raw_html") or ""
    existing_auto = extract_auto_block(existing_markdown)
    existing_auto_hash = hash_auto_block(existing_auto) if existing_auto else None

    merged = merge_page(
        new_auto_body=page.auto_body,
        existing_markdown=existing_markdown,
        last_known_auto_hash=mapping.auto_block_hash or None,
        default_manual_body=strings.get("default_manual_body"),
        manual_heading=strings.get("heading_manual"),
    )

    if merged.markers_missing and not force:
        # WYSIWYG-toggle damage: page exists, has content, was previously
        # written with both marker blocks, but at least one marker is
        # gone. Most common cause is the user toggling BookStack's
        # WYSIWYG editor on the page (TinyMCE round-trip drops the
        # ``<!-- BEGIN ... -->`` comments). Refuse to overwrite — we'd
        # otherwise blow away whatever the user typed in the WYSIWYG
        # session — and surface a repair issue so the user can either
        # restore the markers manually in the markdown editor or call
        # run_now with force=true to accept a fresh AUTO+MANUAL pair.
        LOGGER.warning(
            "BookStack page %s (id=%s): marker comments are missing "
            "(WYSIWYG editor toggled?) - skipping to avoid clobbering "
            "user content. Reset the page in the markdown editor or "
            "re-run with force=true.",
            page.title,
            mapping.page_id,
        )
        report.skipped_conflict.append(page.title)
        report.markers_missing_page_keys.append(page.key)
        report.markers_missing_page_titles.append(page.title)
        report.markers_missing_page_urls.append(
            _build_absolute_page_url(repair_link_base_url, book_slug, mapping.slug)
            or "",
        )
        return mapping.page_id

    if merged.manual_block_tampered:
        if not merged.auto_block_changed:
            # Hash drift, not tampering (issue follow-up to #58):
            # BookStack's current AUTO content matches what HA would
            # render right now, but the hash we stored after our last
            # write has drifted from it. That means BookStack
            # normalised the markdown sometime between the immediate
            # create/update response (which we hashed) and the
            # subsequent read — so the user did NOT edit the page,
            # the storage just lost track. Re-hash silently against
            # what BookStack actually has now and continue.
            LOGGER.info(
                "BookStack page %s (id=%s): stored hash drifted from "
                "BookStack content, but content still matches HA's "
                "current render — re-hashing silently (no tampering).",
                page.title,
                mapping.page_id,
            )
            mapping = PageMapping(
                page_id=mapping.page_id,
                auto_block_hash=existing_auto_hash or "",
                last_seen=mapping.last_seen,
                tombstoned_at=mapping.tombstoned_at,
                hash_origin="bookstack",
                slug=str(existing.get("slug") or "") or mapping.slug,
            )
            store.set(page.key, mapping)
        elif mapping.hash_origin != "bookstack":
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
        elif force:
            # User explicitly opted in to overwrite via the
            # ``force=true`` service parameter. Used after a major
            # version bump that reshapes the AUTO block format and
            # leaves dozens of pages stuck on a residual hash drift
            # the v0.13.3 normaliser can't catch (real situation
            # after the v0.14.0 area-page refactor).
            #
            # MANUAL block stays preserved (merge_page already kept
            # it), only the AUTO block is overwritten with the fresh
            # render.
            LOGGER.warning(
                "BookStack page %s (id=%s): force=True — overriding "
                "tamper check, AUTO block will be overwritten. MANUAL "
                "block stays preserved.",
                page.title,
                mapping.page_id,
            )
        else:
            LOGGER.warning(
                "BookStack page %s (id=%s): AUTO block was edited outside "
                "of Home Assistant - skipping to avoid clobbering manual "
                "changes. Re-run with force=true to override.",
                page.title,
                mapping.page_id,
            )
            report.skipped_conflict.append(page.title)
            report.tampered_page_keys.append(page.key)
            report.tampered_page_titles.append(page.title)
            report.tampered_page_urls.append(
                _build_absolute_page_url(repair_link_base_url, book_slug, mapping.slug)
                or "",
            )
            return mapping.page_id

    # #185: a page's own content can stay untouched for months while a
    # newly-inserted sibling shifts where it belongs in the sidebar - so
    # priority drift has to force a write even when nothing else did,
    # otherwise it would only ever get fixed the next time that page's
    # content happens to change too.
    priority_drifted = (
        page.priority is not None and _existing_priority(existing) != page.priority
    )

    if (
        existing_auto_hash == new_hash
        and not needs_move
        and mapping.hash_origin == "bookstack"
        and not merged.manual_heading_added
        and not priority_drifted
    ):
        # Skip-on-unchanged needs a trustworthy stored hash — only
        # safe when origin is ``bookstack``. Legacy ``write`` mappings
        # always re-write once to settle into the new regime.
        # ``manual_heading_added`` also forces a write: the one-time
        # ``# {heading_manual}`` migration (see merge.py) would never
        # actually reach BookStack for a page whose AUTO content never
        # changes again otherwise.
        report.unchanged.append(page.title)
        mapping.last_seen = datetime.now(tz=UTC).isoformat()
        # v0.14.4: refresh slug from BookStack — handles the case where
        # a user renamed the page in BookStack and BookStack regenerated
        # the slug. Without this update, our cross-page links would 404.
        live_slug = str(existing.get("slug") or "")
        if live_slug:
            mapping.slug = live_slug
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
        priority=page.priority,
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
            slug=str(saved.get("slug") or "") or mapping.slug,
        ),
    )
    report.updated.append(page.title)
    return mapping.page_id


def _existing_priority(existing: dict[str, Any]) -> int | None:
    """
    Parse BookStack's current ``priority`` for a page, defensively (#185).

    Same "coerce, never crash" contract as ``_needs_move`` below for
    ``chapter_id`` — an unparsable value just means "unknown", which
    ``priority_drifted`` treats as needing a write to reassert ours.
    """
    raw = existing.get("priority")
    if raw is None:
        return None
    try:
        return int(raw)
    except TypeError, ValueError:
        return None


def _needs_move(
    existing: dict[str, Any],
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
    if raw is None:
        return expected_chapter_id != 0
    try:
        actual = int(raw)
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


async def _gather_orphaned_entries(
    client: BookStackApiClient,
    store: BookStackSyncStore,
    book_slug: str,
) -> list[OrphanedPageEntry]:
    """
    Build the row list for the orphaned-pages overview page (#166).

    Re-fetches each tombstoned page from BookStack rather than trusting
    the mapping's own cached ``slug`` (which the tombstone step doesn't
    carry forward) — same one-GET-per-page cost the markdown export
    already pays for the same set of pages. A page that 404s was deleted
    directly in BookStack since it was tombstoned; the stale mapping is
    dropped so it stops being re-checked on every future sync.
    """
    entries: list[OrphanedPageEntry] = []
    for key, mapping in sorted(store.all().items()):
        if mapping.tombstoned_at is None:
            continue
        try:
            page = await client.get_page(mapping.page_id)
        except BookStackApiNotFoundError:
            LOGGER.info(
                "Orphaned-pages overview: page id=%s (%s) already gone from "
                "BookStack — dropping stale mapping.",
                mapping.page_id,
                key,
            )
            store.discard(key)
            continue
        except BookStackApiError as err:
            LOGGER.warning(
                "Orphaned-pages overview: could not refresh %s: %s",
                key,
                err,
            )
            continue
        name = str(page.get("name") or key)
        slug = str(page.get("slug") or "")
        url = _build_page_url(book_slug, slug) if slug else None
        entries.append(
            OrphanedPageEntry(
                name=name,
                url=url,
                orphaned_since=mapping.tombstoned_at,
            ),
        )
    return entries


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
            await store.async_save()  # #127: incremental persistence
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

    try:
        existing = await client.get_page(mapping.page_id)
    except BookStackApiNotFoundError:
        # v0.14.10: page is gone from BookStack already — the user
        # deleted it directly. Nothing left to tombstone; just clear
        # the stale mapping entry so future runs don't re-trigger
        # this path.
        LOGGER.info(
            "BookStack page id=%s (%s) already gone — clearing tombstone mapping.",
            mapping.page_id,
            key,
        )
        store.discard(key)
        return
    existing_markdown = existing.get("markdown") or existing.get("raw_html") or ""

    merged = merge_page(
        new_auto_body=auto_body,
        existing_markdown=existing_markdown,
        last_known_auto_hash=mapping.auto_block_hash or None,
        default_manual_body=strings.get("default_manual_body"),
        manual_heading=strings.get("heading_manual"),
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
