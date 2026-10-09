"""The YomiSmart integration."""

import time

import voluptuous as vol

from homeassistant.const import CONF_ACCESS_TOKEN, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr

from .api import YomiSmartAPI, YomiSmartApiError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    SERVICE_CANCEL_ALARM,
    SERVICE_SET_VOLUME,
)
from .coordinator import YomiSmartConfigEntry, YomiSmartUpdateCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]


def _clear_legacy_serial_numbers(
    hass: HomeAssistant, entry: YomiSmartConfigEntry
) -> None:
    """Remove production identifiers exposed by earlier integration versions."""
    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if device.serial_number:
            device_registry.async_update_device(device.id, serial_number=None)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register account-independent YomiSmart services."""
    hass.data.setdefault(DOMAIN, {})

    async def cancel_alarm(call: ServiceCall) -> None:
        sn = call.data["sn"].strip()
        for coordinator in hass.data[DOMAIN].values():
            device = (coordinator.data or {}).get(sn)
            if device is None:
                continue
            if not device.permissions.get("alarmControl", False):
                raise HomeAssistantError("This account cannot control the device alarm")
            try:
                await coordinator.api_client.cancel_alarm_for_device(device)
                device.state["alarmActive"] = False
                coordinator.async_set_updated_data(dict(coordinator.data))
            except YomiSmartApiError as err:
                raise HomeAssistantError(
                    "YomiSmart rejected the alarm cancellation"
                ) from err
            return
        raise HomeAssistantError("The device is not available to a configured account")

    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_ALARM,
        cancel_alarm,
        schema=vol.Schema({vol.Required("sn"): str}),
    )

    async def set_volume(call: ServiceCall) -> None:
        sn = call.data["sn"].strip()
        level = int(call.data["level"])
        for coordinator in hass.data[DOMAIN].values():
            device = (coordinator.data or {}).get(sn)
            if device is None:
                continue
            if not device.permissions.get("control", False):
                raise HomeAssistantError("This account cannot control the device")
            try:
                await coordinator.api_client.send_command(sn, "volume.set", {"level": level})
            except YomiSmartApiError as err:
                raise HomeAssistantError("YomiSmart rejected the volume change") from err
            return
        raise HomeAssistantError("The device is not available to a configured account")

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_VOLUME,
        set_volume,
        schema=vol.Schema({
            vol.Required("sn"): str,
            vol.Required("level"): vol.All(vol.Coerce(int), vol.Range(min=0, max=3)),
        }),
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: YomiSmartConfigEntry
) -> bool:
    """Set up YomiSmart from a config entry."""
    def token_updated(token: dict) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: token["access_token"],
                CONF_REFRESH_TOKEN: token["refresh_token"],
                CONF_EXPIRES_AT: int(time.time()) + int(token["expires_in"]),
                CONF_ACCOUNT_ID: token.get("account_id", entry.data[CONF_ACCOUNT_ID]),
            },
        )

    api_client = YomiSmartAPI(
        async_get_clientsession(hass),
        entry.data[CONF_ACCESS_TOKEN],
        entry.data.get(CONF_REFRESH_TOKEN),
        token_updated,
    )
    coordinator = YomiSmartUpdateCoordinator(hass, entry, api_client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    _clear_legacy_serial_numbers(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: YomiSmartConfigEntry
) -> bool:
    """Unload a YomiSmart config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(
    hass: HomeAssistant, entry: YomiSmartConfigEntry
) -> None:
    """Best-effort revocation when the integration is removed from Home Assistant."""
    api_client = YomiSmartAPI(
        async_get_clientsession(hass),
        entry.data[CONF_ACCESS_TOKEN],
        entry.data.get(CONF_REFRESH_TOKEN),
    )
    try:
        await api_client.unlink()
    except YomiSmartApiError:
        # Local removal must still succeed while the cloud is unavailable.
        return
