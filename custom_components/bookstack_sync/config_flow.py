"""Config flow for BookStack Sync."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.loader import async_get_loaded_integration

if TYPE_CHECKING:
    from collections.abc import Mapping

from .api import (
    BookStackApiAuthError,
    BookStackApiClient,
    BookStackApiCommunicationError,
    BookStackApiError,
)
from .const import (
    CONF_BASE_URL,
    CONF_BOOK_ID,
    CONF_EXCLUDED_AREAS,
    CONF_EXPORT_ENABLED,
    CONF_EXPORT_PATH,
    CONF_OUTPUT_LANGUAGE,
    CONF_SYNC_INTERVAL,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_VERIFY_SSL,
    DEFAULT_EXPORT_ENABLED,
    DEFAULT_EXPORT_SUBDIR,
    DEFAULT_INTERVAL,
    DEFAULT_OUTPUT_LANGUAGE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    INTERVAL_DAILY,
    INTERVAL_HOURLY,
    INTERVAL_MANUAL,
    LOGGER,
    OUTPUT_LANGUAGE_AUTO,
)

_ERR_INVALID_SCHEME = "base_url_invalid_scheme"
_ERR_MISSING_HOST = "base_url_missing_host"
_ERR_PATH_INVALID = "path_invalid"
_ERR_EXPORT_ALREADY_ENABLED = "export_already_enabled_elsewhere"


def _validate_base_url(raw: str) -> str:
    """
    Reject schemes other than http/https; reject missing host.

    Why: aiohttp will happily dispatch ``file://``, ``gopher://`` etc. and
    we send a BookStack token in the Authorization header, so an
    accidentally-pasted ``file:///etc/passwd`` would otherwise leak the
    token to a logger or to whatever responds. We do *not* block private
    IP ranges - 99% of real users run BookStack on 192.168.x.x.
    """
    parsed = urlparse(raw.strip())
    if parsed.scheme not in {"http", "https"}:
        raise vol.Invalid(_ERR_INVALID_SCHEME)
    if not parsed.netloc:
        raise vol.Invalid(_ERR_MISSING_HOST)
    return raw.strip()


def _interval_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="sync_interval",
            options=[INTERVAL_HOURLY, INTERVAL_DAILY, INTERVAL_MANUAL],
        ),
    )


def _output_language_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="output_language",
            options=[OUTPUT_LANGUAGE_AUTO, "de", "en"],
        ),
    )


class BookStackSyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step flow: credentials, then book + interval picker."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the in-progress flow."""
        self._credentials: dict[str, Any] = {}
        self._books: list[dict[str, Any]] = []

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Collect BookStack URL + API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input[CONF_BASE_URL] = _validate_base_url(
                    user_input[CONF_BASE_URL],
                )
            except vol.Invalid as err:
                errors[CONF_BASE_URL] = str(err)

        if user_input is not None and not errors:
            try:
                books = await self._fetch_books(user_input)
            except BookStackApiAuthError as err:
                LOGGER.warning("BookStack auth failed: %s", err)
                errors["base"] = "auth"
            except BookStackApiCommunicationError as err:
                LOGGER.error("BookStack unreachable: %s", err)
                errors["base"] = "connection"
            except BookStackApiError:
                LOGGER.exception("Unexpected BookStack error during config flow")
                errors["base"] = "unknown"
            else:
                if not books:
                    errors["base"] = "no_books"
                else:
                    await self.async_set_unique_id(
                        user_input[CONF_BASE_URL].rstrip("/"),
                    )
                    self._abort_if_unique_id_configured()
                    self._credentials = user_input
                    self._books = books
                    return await self.async_step_book()

        integration = async_get_loaded_integration(self.hass, DOMAIN)
        return self.async_show_form(
            step_id="user",
            description_placeholders={
                "documentation_url": integration.documentation or "",
            },
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BASE_URL,
                        default=(user_input or {}).get(CONF_BASE_URL, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.URL,
                        ),
                    ),
                    vol.Required(CONF_TOKEN_ID): selector.TextSelector(),
                    vol.Required(CONF_TOKEN_SECRET): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                    vol.Required(
                        CONF_VERIFY_SSL,
                        default=(user_input or {}).get(
                            CONF_VERIFY_SSL,
                            DEFAULT_VERIFY_SSL,
                        ),
                    ): selector.BooleanSelector(),
                },
            ),
            errors=errors,
        )

    async def async_step_book(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Pick the target book and sync interval."""
        if user_input is not None:
            data = {**self._credentials, CONF_BOOK_ID: int(user_input[CONF_BOOK_ID])}
            options = {CONF_SYNC_INTERVAL: user_input[CONF_SYNC_INTERVAL]}
            title = self._title_for_book(int(user_input[CONF_BOOK_ID]))
            return self.async_create_entry(title=title, data=data, options=options)

        return self.async_show_form(
            step_id="book",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BOOK_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            options=[
                                selector.SelectOptionDict(
                                    value=str(book["id"]),
                                    label=book.get("name", f"Book {book['id']}"),
                                )
                                for book in self._books
                            ],
                        ),
                    ),
                    vol.Required(
                        CONF_SYNC_INTERVAL,
                        default=DEFAULT_INTERVAL,
                    ): _interval_selector(),
                },
            ),
        )

    async def _fetch_books(self, user_input: dict[str, Any]) -> list[dict[str, Any]]:
        verify_ssl = user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        client = BookStackApiClient(
            base_url=user_input[CONF_BASE_URL],
            token_id=user_input[CONF_TOKEN_ID],
            token_secret=user_input[CONF_TOKEN_SECRET],
            session=async_create_clientsession(self.hass, verify_ssl=verify_ssl),
        )
        return await client.list_books()

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Triggered by HA when the coordinator raises ConfigEntryAuthFailed."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show a form to enter a fresh API token (URL stays as configured)."""
        errors: dict[str, str] = {}
        existing = self._get_reauth_entry()

        if user_input is not None:
            try:
                await self._verify_token(
                    base_url=existing.data[CONF_BASE_URL],
                    token_id=user_input[CONF_TOKEN_ID],
                    token_secret=user_input[CONF_TOKEN_SECRET],
                    verify_ssl=existing.data.get(
                        CONF_VERIFY_SSL,
                        DEFAULT_VERIFY_SSL,
                    ),
                )
            except BookStackApiAuthError as err:
                LOGGER.warning("Reauth failed: %s", err)
                errors["base"] = "auth"
            except BookStackApiCommunicationError as err:
                LOGGER.error("BookStack unreachable during reauth: %s", err)
                errors["base"] = "connection"
            except BookStackApiError:
                LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    existing,
                    data={
                        **existing.data,
                        CONF_TOKEN_ID: user_input[CONF_TOKEN_ID],
                        CONF_TOKEN_SECRET: user_input[CONF_TOKEN_SECRET],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"base_url": existing.data[CONF_BASE_URL]},
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN_ID): selector.TextSelector(),
                    vol.Required(CONF_TOKEN_SECRET): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=errors,
        )

    async def _verify_token(
        self,
        base_url: str,
        token_id: str,
        token_secret: str,
        *,
        verify_ssl: bool = DEFAULT_VERIFY_SSL,
    ) -> None:
        """Hit /api/books once to confirm the token works (and is authorised)."""
        client = BookStackApiClient(
            base_url=base_url,
            token_id=token_id,
            token_secret=token_secret,
            session=async_create_clientsession(self.hass, verify_ssl=verify_ssl),
        )
        await client.list_books()

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """
        User-initiated reconfigure of URL / token / TLS settings.

        Triggered when the user clicks *Configure → Reconfigure* on the
        integration card. Unlike the options flow this rewrites the
        ``data`` half of the entry (credentials), not the ``options``.
        The book selection is preserved as-is.
        """
        errors: dict[str, str] = {}
        existing = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                user_input[CONF_BASE_URL] = _validate_base_url(
                    user_input[CONF_BASE_URL],
                )
            except vol.Invalid as err:
                errors[CONF_BASE_URL] = str(err)

        if user_input is not None and not errors:
            # Re-pin unique_id; abort if user pointed at a different instance.
            await self.async_set_unique_id(user_input[CONF_BASE_URL].rstrip("/"))
            self._abort_if_unique_id_mismatch(reason="url_mismatch")

            try:
                await self._verify_token(
                    base_url=user_input[CONF_BASE_URL],
                    token_id=user_input[CONF_TOKEN_ID],
                    token_secret=user_input[CONF_TOKEN_SECRET],
                    verify_ssl=user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                )
            except BookStackApiAuthError as err:
                LOGGER.warning("Reconfigure auth failed: %s", err)
                errors["base"] = "auth"
            except BookStackApiCommunicationError as err:
                LOGGER.error("BookStack unreachable during reconfigure: %s", err)
                errors["base"] = "connection"
            except BookStackApiError:
                LOGGER.exception("Unexpected error during reconfigure")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    existing,
                    data={
                        **existing.data,
                        CONF_BASE_URL: user_input[CONF_BASE_URL],
                        CONF_TOKEN_ID: user_input[CONF_TOKEN_ID],
                        CONF_TOKEN_SECRET: user_input[CONF_TOKEN_SECRET],
                        CONF_VERIFY_SSL: user_input.get(
                            CONF_VERIFY_SSL,
                            DEFAULT_VERIFY_SSL,
                        ),
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BASE_URL,
                        default=existing.data[CONF_BASE_URL],
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.URL,
                        ),
                    ),
                    vol.Required(
                        CONF_TOKEN_ID,
                        default=existing.data[CONF_TOKEN_ID],
                    ): selector.TextSelector(),
                    vol.Required(CONF_TOKEN_SECRET): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                    vol.Required(
                        CONF_VERIFY_SSL,
                        default=existing.data.get(
                            CONF_VERIFY_SSL,
                            DEFAULT_VERIFY_SSL,
                        ),
                    ): selector.BooleanSelector(),
                },
            ),
            errors=errors,
        )

    def _title_for_book(self, book_id: int) -> str:
        for book in self._books:
            if int(book["id"]) == book_id:
                return f"BookStack: {book.get('name', book_id)}"
        return f"BookStack Book {book_id}"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow for this integration."""
        del config_entry
        return BookStackSyncOptionsFlow()


class BookStackSyncOptionsFlow(OptionsFlow):
    """
    Lets the user change book + interval after setup.

    ``self.config_entry`` is populated automatically by HA core.
    """

    def __init__(self) -> None:
        """Initialise the options flow state."""
        self._books: list[dict[str, Any]] = []

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show the options form / persist the new options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            export_enabled = bool(
                user_input.get(CONF_EXPORT_ENABLED, DEFAULT_EXPORT_ENABLED),
            )
            export_path = (user_input.get(CONF_EXPORT_PATH) or "").strip()
            if export_enabled:
                if not export_path:
                    errors[CONF_EXPORT_PATH] = _ERR_PATH_INVALID
                else:
                    candidate = Path(export_path)
                    if not candidate.is_absolute() or not candidate.parent.exists():
                        errors[CONF_EXPORT_PATH] = _ERR_PATH_INVALID
                # Single-writer rule: only one config entry may have the
                # markdown export enabled at a time. Two entries running
                # the export — even at different paths — would still
                # write the same idempotency ledger key collisions and
                # confuse external indexers; refuse upfront with a clear
                # error pointing at the other entry.
                for other in self.hass.config_entries.async_entries(DOMAIN):
                    if other.entry_id == self.config_entry.entry_id:
                        continue
                    if other.options.get(
                        CONF_EXPORT_ENABLED,
                        DEFAULT_EXPORT_ENABLED,
                    ):
                        errors[CONF_EXPORT_ENABLED] = _ERR_EXPORT_ALREADY_ENABLED
                        break
            if not errors:
                new_book_id = int(user_input[CONF_BOOK_ID])
                # When the user picks a different book the integration title
                # (= visible name on the integration card and the device name)
                # would otherwise still show the old book — the OptionsFlow's
                # ``async_create_entry`` doesn't touch the title. Detect the
                # change here and propagate via ``async_update_entry`` so the
                # UI follows the user's choice.
                old_book_id_raw = self.config_entry.options.get(
                    CONF_BOOK_ID
                ) or self.config_entry.data.get(CONF_BOOK_ID)
                if old_book_id_raw is not None and int(old_book_id_raw) != new_book_id:
                    new_title = next(
                        (
                            f"BookStack: {book.get('name', new_book_id)}"
                            for book in self._books
                            if int(book["id"]) == new_book_id
                        ),
                        self.config_entry.title,
                    )
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        title=new_title,
                    )
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_BOOK_ID: new_book_id,
                        CONF_SYNC_INTERVAL: user_input[CONF_SYNC_INTERVAL],
                        CONF_EXCLUDED_AREAS: user_input.get(CONF_EXCLUDED_AREAS, []),
                        CONF_OUTPUT_LANGUAGE: user_input.get(
                            CONF_OUTPUT_LANGUAGE,
                            DEFAULT_OUTPUT_LANGUAGE,
                        ),
                        CONF_EXPORT_ENABLED: export_enabled,
                        CONF_EXPORT_PATH: export_path,
                    },
                )

        verify_ssl = self.config_entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        client = BookStackApiClient(
            base_url=self.config_entry.data[CONF_BASE_URL],
            token_id=self.config_entry.data[CONF_TOKEN_ID],
            token_secret=self.config_entry.data[CONF_TOKEN_SECRET],
            session=async_create_clientsession(self.hass, verify_ssl=verify_ssl),
        )
        try:
            self._books = await client.list_books()
        except BookStackApiError:
            self._books = []

        current_book = self.config_entry.options.get(
            CONF_BOOK_ID
        ) or self.config_entry.data.get(CONF_BOOK_ID)
        current_interval = self.config_entry.options.get(
            CONF_SYNC_INTERVAL,
            DEFAULT_INTERVAL,
        )
        current_excluded = self.config_entry.options.get(CONF_EXCLUDED_AREAS, [])
        current_language = self.config_entry.options.get(
            CONF_OUTPUT_LANGUAGE,
            DEFAULT_OUTPUT_LANGUAGE,
        )
        current_export_enabled = self.config_entry.options.get(
            CONF_EXPORT_ENABLED,
            DEFAULT_EXPORT_ENABLED,
        )
        # Default path: <config>/bookstack_export — surfaced as a real
        # absolute path so the user immediately sees where files would land.
        current_export_path = self.config_entry.options.get(
            CONF_EXPORT_PATH,
            self.hass.config.path(DEFAULT_EXPORT_SUBDIR),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BOOK_ID,
                        default=str(current_book) if current_book else vol.UNDEFINED,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            options=[
                                selector.SelectOptionDict(
                                    value=str(book["id"]),
                                    label=book.get("name", f"Book {book['id']}"),
                                )
                                for book in self._books
                            ],
                        ),
                    ),
                    vol.Required(
                        CONF_SYNC_INTERVAL,
                        default=current_interval,
                    ): _interval_selector(),
                    vol.Optional(
                        CONF_EXCLUDED_AREAS,
                        default=current_excluded,
                    ): selector.AreaSelector(
                        selector.AreaSelectorConfig(multiple=True),
                    ),
                    vol.Required(
                        CONF_OUTPUT_LANGUAGE,
                        default=current_language,
                    ): _output_language_selector(),
                    # Markdown back-export. Off by default — costs disk
                    # space and CPU, so the user must consciously enable it.
                    vol.Required(
                        CONF_EXPORT_ENABLED,
                        default=current_export_enabled,
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_EXPORT_PATH,
                        default=current_export_path,
                    ): selector.TextSelector(),
                },
            ),
            errors=errors,
        )
