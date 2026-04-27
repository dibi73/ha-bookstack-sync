"""Config flow for BookStack Sync."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import (
    BookStackApiAuthError,
    BookStackApiClient,
    BookStackApiCommunicationError,
    BookStackApiError,
)
from .const import (
    CONF_BASE_URL,
    CONF_BOOK_ID,
    CONF_SYNC_INTERVAL,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    DEFAULT_INTERVAL,
    DOMAIN,
    INTERVAL_DAILY,
    INTERVAL_HOURLY,
    INTERVAL_MANUAL,
    LOGGER,
)


def _interval_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="sync_interval",
            options=[INTERVAL_HOURLY, INTERVAL_DAILY, INTERVAL_MANUAL],
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
        client = BookStackApiClient(
            base_url=user_input[CONF_BASE_URL],
            token_id=user_input[CONF_TOKEN_ID],
            token_secret=user_input[CONF_TOKEN_SECRET],
            session=async_create_clientsession(self.hass),
        )
        return await client.list_books()

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
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_BOOK_ID: int(user_input[CONF_BOOK_ID]),
                    CONF_SYNC_INTERVAL: user_input[CONF_SYNC_INTERVAL],
                },
            )

        client = BookStackApiClient(
            base_url=self.config_entry.data[CONF_BASE_URL],
            token_id=self.config_entry.data[CONF_TOKEN_ID],
            token_secret=self.config_entry.data[CONF_TOKEN_SECRET],
            session=async_create_clientsession(self.hass),
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
                },
            ),
        )
