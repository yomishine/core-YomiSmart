"""Config flow for YomiSmart."""

from collections.abc import Mapping
import time
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_CODE
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YomiSmartAPI, YomiSmartApiError, YomiSmartInvalidCode
from .const import CONF_ACCOUNT_ID, CONF_EXPIRES_AT, CONF_REFRESH_TOKEN, DOMAIN

CONFIG_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})


class YomiSmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a one-time authorization code."""

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_init(user_input)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="init", data_schema=CONFIG_SCHEMA)

        try:
            token = await YomiSmartAPI.exchange_auth_code(
                async_get_clientsession(self.hass), user_input[CONF_CODE]
            )
        except YomiSmartInvalidCode:
            errors = {CONF_CODE: "invalid_auth"}
        except YomiSmartApiError:
            errors = {"base": "cannot_connect"}
        else:
            account_id = str(token["account_id"])
            await self.async_set_unique_id(account_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="YomiSmart",
                data={
                    CONF_ACCESS_TOKEN: token["access_token"],
                    CONF_REFRESH_TOKEN: token["refresh_token"],
                    CONF_EXPIRES_AT: int(time.time()) + int(token["expires_in"]),
                    CONF_ACCOUNT_ID: account_id,
                },
            )

        return self.async_show_form(
            step_id="init", data_schema=CONFIG_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=CONFIG_SCHEMA
            )

        try:
            token = await YomiSmartAPI.exchange_auth_code(
                async_get_clientsession(self.hass), user_input[CONF_CODE]
            )
        except YomiSmartInvalidCode:
            errors = {CONF_CODE: "invalid_auth"}
        except YomiSmartApiError:
            errors = {"base": "cannot_connect"}
        else:
            entry = self._get_reauth_entry()
            if str(token["account_id"]) != str(entry.data[CONF_ACCOUNT_ID]):
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(
                entry,
                data_updates={
                    **entry.data,
                    CONF_ACCESS_TOKEN: token["access_token"],
                    CONF_REFRESH_TOKEN: token["refresh_token"],
                    CONF_EXPIRES_AT: int(time.time()) + int(token["expires_in"]),
                },
            )

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=CONFIG_SCHEMA, errors=errors
        )
