"""Switch entities for YomiSmart power-cut devices."""

from typing import override

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .api import YomiSmartDevice, YomiSmartApiError
from .const import DOMAIN, MANUFACTURER, model_for_device
from .coordinator import YomiSmartConfigEntry, YomiSmartUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YomiSmartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known_sns: set[str] = set()

    def add_new_entities() -> None:
        new_sns = set(coordinator.data) - known_sns
        entities = [
            YomiSmartStatusLightSwitch(coordinator, coordinator.data[sn])
            for sn in new_sns
            if coordinator.data[sn].device_type == "power_cut"
            and coordinator.data[sn].permissions.get("control", False)
        ]
        known_sns.update(new_sns)
        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class YomiSmartStatusLightSwitch(
    CoordinatorEntity[YomiSmartUpdateCoordinator], SwitchEntity
):
    _attr_has_entity_name = True
    _attr_name = "Status light"

    def __init__(self, coordinator: YomiSmartUpdateCoordinator, device: YomiSmartDevice) -> None:
        super().__init__(coordinator)
        self._sn = device.sn
        self._optimistic_enabled: bool | None = None
        self._attr_unique_id = f"{device.sn}_status_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.sn)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=model_for_device(device.device_type),
        )

    @property
    def device(self) -> YomiSmartDevice | None:
        return self.coordinator.data.get(self._sn)

    @property
    @override
    def is_on(self) -> bool:
        if self._optimistic_enabled is not None:
            return self._optimistic_enabled
        return bool(self.device and self.device.state.get("statusLightEnabled"))

    @override
    def _handle_coordinator_update(self) -> None:
        self._optimistic_enabled = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.api_client.send_command(
            self._sn, "device.setConfig", {"statusLightEnabled": True}
        )
        self._optimistic_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.api_client.send_command(
            self._sn, "device.setConfig", {"statusLightEnabled": False}
        )
        self._optimistic_enabled = False
        self.async_write_ha_state()
