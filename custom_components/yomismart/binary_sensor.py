"""Binary sensors for YomiSmart washing-machine monitors."""

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import YomiSmartDevice
from .const import DOMAIN, MANUFACTURER, model_for_device
from .coordinator import YomiSmartConfigEntry, YomiSmartUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YomiSmartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create washing-machine alarm and connectivity sensors."""
    coordinator = entry.runtime_data
    entity_registry = er.async_get(hass)
    for sn, device in coordinator.data.items():
        if device.device_type == "power_cut":
            entity_id = entity_registry.async_get_entity_id(
                "binary_sensor", DOMAIN, f"{sn}_power_cut"
            )
            if entity_id:
                entity_registry.async_remove(entity_id)
    known_sns: set[str] = set()

    def add_new_entities() -> None:
        known_sns.intersection_update(coordinator.data)
        new_sns = set(coordinator.data) - known_sns
        entities: list[BinarySensorEntity] = []
        for sn in new_sns:
            device = coordinator.data[sn]
            if device.device_type == "power_cut":
                entities.append(YomiSmartConnectivitySensor(coordinator, device))
            else:
                entities.extend(
                    (
                        YomiSmartAlarmSensor(coordinator, device),
                        YomiSmartConnectivitySensor(coordinator, device),
                    )
                )
        known_sns.update(new_sns)
        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class YomiSmartBinarySensor(
    CoordinatorEntity[YomiSmartUpdateCoordinator], BinarySensorEntity
):
    """Base binary sensor bound to a device SN."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: YomiSmartUpdateCoordinator,
        device: YomiSmartDevice,
        suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._sn = device.sn
        self._attr_unique_id = f"{device.sn}_{suffix}"
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
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.device is not None


class YomiSmartAlarmSensor(YomiSmartBinarySensor):
    """Whether the local laundry-complete alarm is active."""

    _attr_name = "Completion alarm"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: YomiSmartUpdateCoordinator, device: YomiSmartDevice
    ) -> None:
        super().__init__(coordinator, device, "completion_alarm")

    @property
    @override
    def is_on(self) -> bool:
        return bool(self.device and self.device.state.get("alarmActive"))


class YomiSmartConnectivitySensor(YomiSmartBinarySensor):
    """Whether the device is online."""

    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: YomiSmartUpdateCoordinator, device: YomiSmartDevice
    ) -> None:
        super().__init__(coordinator, device, "connectivity")

    @property
    @override
    def is_on(self) -> bool:
        return bool(self.device and self.device.state.get("online"))
