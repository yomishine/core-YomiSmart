"""Buttons for YomiSmart washing-machine alarms."""

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
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
    """Create alarm buttons for washing machines with control permission."""
    coordinator = entry.runtime_data
    known_sns: set[str] = set()

    def add_new_entities() -> None:
        new_sns = set(coordinator.data) - known_sns
        entities = [
            YomiSmartCancelAlarmButton(coordinator, coordinator.data[sn])
            for sn in new_sns
            if coordinator.data[sn].device_type in {"washing_machine", "power_cut"}
            and coordinator.data[sn].permissions.get("alarmControl", False)
        ]
        known_sns.update(new_sns)
        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class YomiSmartCancelAlarmButton(
    CoordinatorEntity[YomiSmartUpdateCoordinator], ButtonEntity
):
    """Cancel the active washing-machine alarm."""

    _attr_has_entity_name = True
    _attr_name = "Cancel alarm"

    def __init__(self, coordinator: YomiSmartUpdateCoordinator, device: YomiSmartDevice) -> None:
        super().__init__(coordinator)
        self._sn = device.sn
        self._attr_unique_id = f"{device.sn}_cancel_alarm"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.sn)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=model_for_device(device.device_type),
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._sn in self.coordinator.data

    async def async_press(self) -> None:
        device = self.coordinator.data.get(self._sn)
        if device is not None:
            await self.coordinator.api_client.cancel_alarm_for_device(device)
            device.state["alarmActive"] = False
            if device.device_type == "washing_machine":
                device.state["washerState"] = "idle"
            self.coordinator.async_set_updated_data(dict(self.coordinator.data))
