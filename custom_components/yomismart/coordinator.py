"""Data coordinator for YomiSmart devices."""

import asyncio
from datetime import timedelta
import logging
from typing import TypeAlias, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .api import (
    YomiSmartAPI,
    YomiSmartApiError,
    YomiSmartAuthError,
    YomiSmartDevice,
)
from .const import DEFAULT_POLL_INTERVAL, DOMAIN, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

YomiSmartConfigEntry: TypeAlias = ConfigEntry["YomiSmartUpdateCoordinator"]


class YomiSmartUpdateCoordinator(
    DataUpdateCoordinator[dict[str, YomiSmartDevice]]
):
    """Fetch device snapshots and notify entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api_client: YomiSmartAPI,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )
        self.api_client = api_client

    @override
    async def _async_update_data(self) -> dict[str, YomiSmartDevice]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                devices = await self.api_client.devices()
        except YomiSmartAuthError as err:
            raise ConfigEntryAuthFailed from err
        except YomiSmartApiError as err:
            if self.data:
                _LOGGER.warning(
                    "YomiSmart cloud is unavailable; refreshing cached devices locally: %s",
                    err,
                )
                devices = dict(self.data)
            else:
                raise UpdateFailed(
                    f"Error communicating with YomiSmart: {err}"
                ) from err
        else:
            previous_sns = set(self.data or {})
            removed_sns = previous_sns - set(devices)
            if removed_sns:
                self._remove_devices(removed_sns)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                return await self.api_client.refresh_local_state(devices)
        except YomiSmartAuthError as err:
            raise ConfigEntryAuthFailed from err
        except YomiSmartApiError as err:
            raise UpdateFailed(f"Error communicating with YomiSmart: {err}") from err

    def _remove_devices(self, removed_sns: set[str]) -> None:
        """Remove entities and device registry entries no longer authorized."""
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        for sn in removed_sns:
            for platform, suffixes in (
                (
                    "sensor",
                    (
                        "washer_state",
                        "volume",
                        "alarm_delay",
                        "current_power",
                        "peak_power",
                    ),
                ),
                ("binary_sensor", ("completion_alarm", "connectivity")),
                ("sensor", ("power_status",)),
                ("switch", ("status_light",)),
                ("button", ("cancel_alarm",)),
            ):
                for suffix in suffixes:
                    entity_id = entity_registry.async_get_entity_id(
                        platform, DOMAIN, f"{sn}_{suffix}"
                    )
                    if entity_id:
                        entity_registry.async_remove(entity_id)
            device = device_registry.async_get_device(identifiers={(DOMAIN, sn)})
            if device:
                device_registry.async_remove_device(device.id)
