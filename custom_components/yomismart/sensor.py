"""Sensors for YomiSmart washing-machine and power-cut monitors."""

from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import YomiSmartDevice
from .const import DOMAIN, MANUFACTURER, model_for_device
from .coordinator import YomiSmartConfigEntry, YomiSmartUpdateCoordinator

WASHER_STATES = ["idle", "running", "ending", "completed"]
POWER_STATES = ["Power cut", "Power restored"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YomiSmartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create state and configuration sensors."""
    coordinator = entry.runtime_data
    known_sns: set[str] = set()

    def add_new_entities() -> None:
        known_sns.intersection_update(coordinator.data)
        new_sns = set(coordinator.data) - known_sns
        entities: list[SensorEntity] = []
        for sn in new_sns:
            device = coordinator.data[sn]
            if device.device_type == "power_cut":
                entity_registry = er.async_get(coordinator.hass)
                old_volume = entity_registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{sn}_volume"
                )
                if old_volume:
                    entity_registry.async_remove(old_volume)
                entities.append(
                    YomiSmartPowerStatusSensor(coordinator, device)
                )
            else:
                entities.extend(
                    (
                        YomiSmartWasherStateSensor(coordinator, device),
                        YomiSmartValueSensor(
                            coordinator, device, "volume", "Volume", "volumeLevel"
                        ),
                    YomiSmartValueSensor(
                        coordinator,
                        device,
                        "alarm_delay",
                        "Alarm delay",
                        "alarmDelayMinutes",
                        UnitOfTime.MINUTES,
                    ),
                    YomiSmartPowerSensor(
                        coordinator,
                        device,
                        "current_power",
                        "Current power",
                        "currentPowerW",
                    ),
                        YomiSmartPowerSensor(
                            coordinator,
                            device,
                            "peak_power",
                            "Peak power",
                            "peakPowerW",
                        ),
                    )
                )
        known_sns.update(new_sns)
        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class YomiSmartBaseSensor(
    CoordinatorEntity[YomiSmartUpdateCoordinator], SensorEntity
):
    """Base sensor bound to a device SN."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: YomiSmartUpdateCoordinator,
        device: YomiSmartDevice,
        suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._sn = device.sn
        self._attr_unique_id = f"{device.sn}_{suffix}"
        self._attr_name = name
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


class YomiSmartWasherStateSensor(YomiSmartBaseSensor):
    """Current washer state."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = WASHER_STATES

    def __init__(
        self, coordinator: YomiSmartUpdateCoordinator, device: YomiSmartDevice
    ) -> None:
        super().__init__(coordinator, device, "washer_state", "Washer state")

    @property
    @override
    def native_value(self) -> str:
        value = str(self.device.state.get("washerState", "idle")) if self.device else "idle"
        return value if value in WASHER_STATES else "idle"


class YomiSmartPowerStatusSensor(YomiSmartBaseSensor):
    """Current mains state with explicit user-facing Chinese labels."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = POWER_STATES

    def __init__(
        self, coordinator: YomiSmartUpdateCoordinator, device: YomiSmartDevice
    ) -> None:
        super().__init__(coordinator, device, "power_status", "Power status")

    @property
    @override
    def native_value(self) -> str:
        state = self.device.state if self.device else {}
        status = state.get(
            "localPowerStatus", state.get("powerStatus", state.get("power_status"))
        )
        if status is None:
            status = state.get("power")
        return "Power restored" if status in ("restored", "on", 1, True) else "Power cut"

    @property
    @override
    def extra_state_attributes(self) -> dict[str, str | bool]:
        state = self.device.state if self.device else {}
        local_available = bool(state.get("localPowerStatusAvailable"))
        return {
            "data_source": "local" if local_available else "cloud",
            "local_available": local_available,
        }


class YomiSmartValueSensor(YomiSmartBaseSensor):
    """Read a numeric value from the latest state."""

    def __init__(
        self,
        coordinator: YomiSmartUpdateCoordinator,
        device: YomiSmartDevice,
        suffix: str,
        name: str,
        field_name: str,
        unit: str | None = None,
    ) -> None:
        super().__init__(coordinator, device, suffix, name)
        self._field_name = field_name
        self._attr_native_unit_of_measurement = unit

    @property
    @override
    def native_value(self) -> Any:
        return self.device.state.get(self._field_name) if self.device else None


class YomiSmartPowerSensor(YomiSmartValueSensor):
    """Power reading from the active washer cycle."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: YomiSmartUpdateCoordinator,
        device: YomiSmartDevice,
        suffix: str,
        name: str,
        field_name: str,
    ) -> None:
        super().__init__(coordinator, device, suffix, name, field_name, UnitOfPower.WATT)
        self._field_name = field_name

    @property
    @override
    def extra_state_attributes(self) -> dict[str, str | bool] | None:
        if self._field_name != "currentPowerW":
            return None
        state = self.device.state if self.device else {}
        local_available = bool(state.get("localCurrentPowerAvailable"))
        return {
            "data_source": "local" if local_available else "cloud",
            "local_available": local_available,
        }
