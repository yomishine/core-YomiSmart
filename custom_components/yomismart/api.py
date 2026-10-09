"""Async client for the YomiSmart cloud API."""

import asyncio
from dataclasses import dataclass, field
import ipaddress
import logging
import re
import socket
from typing import Any, Callable

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import API_BASE_URL


_LOGGER = logging.getLogger(__name__)


class YomiSmartApiError(Exception):
    """Base API error."""


class YomiSmartAuthError(YomiSmartApiError):
    """The saved credential is no longer valid."""


class YomiSmartInvalidCode(YomiSmartApiError):
    """The one-time authorization code is invalid."""


@dataclass(slots=True)
class YomiSmartDevice:
    """Device snapshot returned by the app API."""

    sn: str
    name: str
    device_type: str
    role: str
    permissions: dict[str, bool] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "YomiSmartDevice":
        return cls(
            sn=str(value.get("sn", "")),
            name=str(value.get("name") or "Washing Machine"),
            device_type=str(value.get("deviceType", "")),
            role=str(value.get("role", "")),
            permissions=dict(value.get("permissions") or {}),
            state=dict(value.get("state") or {}),
        )


class YomiSmartAPI:
    """YomiSmart authorization and device API."""

    def __init__(
        self,
        session: ClientSession,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_updated: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._session = session
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._token_updated = token_updated

    @classmethod
    async def exchange_auth_code(
        cls, session: ClientSession, auth_code: str
    ) -> dict[str, Any]:
        normalized_code = cls._normalize_auth_code(auth_code)
        if normalized_code is None:
            raise YomiSmartInvalidCode
        try:
            async with session.post(
                f"{API_BASE_URL}/auth/home-assistant/token",
                json={"authCode": normalized_code},
            ) as response:
                if response.status in (400, 401, 404):
                    raise YomiSmartInvalidCode
                if response.status >= 500:
                    _LOGGER.warning(
                        "YomiSmart token endpoint unavailable: status=%s",
                        response.status,
                    )
                    raise YomiSmartApiError("Service unavailable")
                response.raise_for_status()
                try:
                    payload = await response.json()
                except (ClientError, ValueError) as err:
                    _LOGGER.warning(
                        "YomiSmart token response is not readable JSON: "
                        "status=%s content_type=%s error_type=%s",
                        response.status,
                        response.content_type,
                        type(err).__name__,
                    )
                    raise YomiSmartApiError("Invalid token response") from err
                return cls._normalize_token_response(payload)
        except ClientError as err:
            _LOGGER.warning(
                "YomiSmart token request failed: error_type=%s message=%s",
                type(err).__name__,
                str(err),
            )
            raise YomiSmartApiError(str(err)) from err

    @staticmethod
    def _normalize_auth_code(auth_code: str) -> str | None:
        """Normalize a copied six-digit authorization code to 123-456."""
        if not isinstance(auth_code, str):
            return None
        normalized = re.sub(r"\s+", "", auth_code).replace("–", "-").replace(
            "—", "-"
        )
        if re.fullmatch(r"[0-9]{6}", normalized):
            return f"{normalized[:3]}-{normalized[3:]}"
        if re.fullmatch(r"[0-9]{3}-[0-9]{3}", normalized):
            return normalized
        return None

    async def devices(self) -> dict[str, YomiSmartDevice]:
        payload = await self._request("GET", "/app/devices")
        values = payload.get("data", payload)
        if isinstance(values, dict):
            values = values.get("devices", [])
        devices = [YomiSmartDevice.from_json(item) for item in (values or [])]
        result = {
            device.sn: device
            for device in devices
            if device.sn and device.device_type in {"washing_machine", "power_cut"}
        }
        washer_devices = {
            sn: device
            for sn, device in result.items()
            if device.device_type == "washing_machine"
        }
        curves = await asyncio.gather(
            *(self.current_power(sn) for sn in washer_devices), return_exceptions=True
        )
        for device, curve in zip(washer_devices.values(), curves):
            if isinstance(curve, YomiSmartAuthError):
                raise curve
            if isinstance(curve, dict):
                device.state["currentPowerW"] = curve.get("currentPowerW")
                device.state["peakPowerW"] = curve.get("peakPowerW")
        return result

    async def refresh_local_state(
        self, devices: dict[str, YomiSmartDevice]
    ) -> dict[str, YomiSmartDevice]:
        """Refresh local readings without requiring a cloud connection."""
        washer_devices = {
            sn: device
            for sn, device in devices.items()
            if device.device_type == "washing_machine"
        }
        local_washer_powers = await asyncio.gather(
            *(self.local_washer_power(device.sn) for device in washer_devices.values()),
            return_exceptions=True,
        )
        for device, local_power in zip(
            washer_devices.values(), local_washer_powers
        ):
            if isinstance(local_power, (int, float)) and not isinstance(
                local_power, bool
            ):
                device.state["currentPowerW"] = local_power
                device.state["localCurrentPowerAvailable"] = True
            else:
                device.state["localCurrentPowerAvailable"] = False
        local_washer_states = await asyncio.gather(
            *(self.local_washer_state(device.sn) for device in washer_devices.values()),
            return_exceptions=True,
        )
        local_washer_alarms = await asyncio.gather(
            *(
                self.local_alarm_active(device.sn, device.device_type)
                for device in washer_devices.values()
            ),
            return_exceptions=True,
        )
        valid_washer_states = {"idle", "running", "ending", "completed"}
        for device, local_state in zip(
            washer_devices.values(), local_washer_states
        ):
            if isinstance(local_state, str) and local_state in valid_washer_states:
                device.state["washerState"] = local_state
                device.state["localWasherStateAvailable"] = True
            else:
                device.state["localWasherStateAvailable"] = False
        for device, local_alarm in zip(washer_devices.values(), local_washer_alarms):
            if isinstance(local_alarm, bool):
                device.state["alarmActive"] = local_alarm
                device.state["localAlarmAvailable"] = True
            else:
                device.state["localAlarmAvailable"] = False
        power_cut_devices = [
            device for device in devices.values() if device.device_type == "power_cut"
        ]
        local_power_statuses = await asyncio.gather(
            *(self.local_power_status(device.sn) for device in power_cut_devices),
            return_exceptions=True,
        )
        for device, local_status in zip(power_cut_devices, local_power_statuses):
            if local_status in {"on", "off"}:
                device.state["localPowerStatus"] = local_status
                device.state["localPowerStatusAvailable"] = True
            else:
                device.state["localPowerStatusAvailable"] = False
        local_power_alarms = await asyncio.gather(
            *(
                self.local_alarm_active(device.sn, device.device_type)
                for device in power_cut_devices
            ),
            return_exceptions=True,
        )
        for device, local_alarm in zip(power_cut_devices, local_power_alarms):
            if isinstance(local_alarm, bool):
                device.state["alarmActive"] = local_alarm
                device.state["localAlarmAvailable"] = True
            else:
                device.state["localAlarmAvailable"] = False
        return devices

    async def local_alarm_active(self, sn: str, device_type: str) -> bool | None:
        """Read the active alarm state from a same-LAN device."""
        hostname = self._local_hostname(sn, device_type)
        if hostname is None:
            return None
        address = await self._local_device_address(sn, hostname)
        if address is None:
            return None
        try:
            async with self._session.get(
                f"http://{address}/info",
                headers={"Connection": "close"},
                timeout=ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
        except (asyncio.TimeoutError, ClientError, ValueError):
            return None
        alarm_active = payload.get("alarmActive") if isinstance(payload, dict) else None
        return (
            alarm_active
            if isinstance(payload, dict)
            and str(payload.get("sn", "")) == sn
            and isinstance(alarm_active, bool)
            else None
        )

    async def local_cancel_alarm(self, sn: str, device_type: str) -> bool:
        """Cancel an alarm directly on a same-LAN device."""
        hostname = self._local_hostname(sn, device_type)
        if hostname is None:
            return False
        address = await self._local_device_address(sn, hostname)
        if address is None:
            return False
        try:
            async with self._session.post(
                f"http://{address}/alarm/cancel",
                headers={"Connection": "close"},
                timeout=ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    return False
                payload = await response.json()
        except (asyncio.TimeoutError, ClientError, ValueError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("code") == 200
            and payload.get("alarmActive") is False
        )

    @staticmethod
    def _local_hostname(sn: str, device_type: str) -> str | None:
        if device_type == "washing_machine":
            return f"laundry-{sn[-4:]}.local"
        if device_type == "power_cut":
            return f"powerdetector-{sn[-4:]}.local"
        return None

    async def local_power_status(self, sn: str) -> str | None:
        """Read the power status directly from a same-LAN power detector."""
        hostname = f"powerdetector-{sn[-4:]}.local"
        address = await self._local_device_address(sn, hostname)
        if address is None:
            return None
        try:
            async with self._session.get(
                f"http://{address}/info",
                headers={"Connection": "close"},
                timeout=ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
        except (asyncio.TimeoutError, ClientError, ValueError):
            return None
        if not isinstance(payload, dict) or str(payload.get("sn", "")) != sn:
            return None
        status = payload.get("powerStatus")
        return status if status in {"on", "off"} else None

    async def local_washer_power(self, sn: str) -> float | None:
        """Read current watts directly from a same-LAN washer monitor."""
        hostname = f"laundry-{sn[-4:]}.local"
        address = await self._local_device_address(sn, hostname)
        if address is None:
            return None
        try:
            async with self._session.get(
                f"http://{address}/info",
                headers={"Connection": "close"},
                timeout=ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
        except (asyncio.TimeoutError, ClientError, ValueError):
            return None
        if not isinstance(payload, dict) or str(payload.get("sn", "")) != sn:
            return None
        power = payload.get("currentPowerW")
        if isinstance(power, bool) or not isinstance(power, (int, float)):
            return None
        if power < 0 or power > 3000:
            return None
        return float(power)

    async def local_washer_state(self, sn: str) -> str | None:
        """Read the washer state directly from a same-LAN device."""
        hostname = f"laundry-{sn[-4:]}.local"
        address = await self._local_device_address(sn, hostname)
        if address is None:
            return None
        try:
            async with self._session.get(
                f"http://{address}/info",
                headers={"Connection": "close"},
                timeout=ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
        except (asyncio.TimeoutError, ClientError, ValueError):
            return None
        if not isinstance(payload, dict) or str(payload.get("sn", "")) != sn:
            return None
        state = payload.get("washerState")
        return (
            state
            if isinstance(state, str)
            and state in {"idle", "running", "ending", "completed"}
            else None
        )

    @classmethod
    async def _local_device_address(cls, sn: str, hostname: str) -> str | None:
        """Resolve a device to a real RFC1918 address without trusting hijacked DNS."""
        address = await asyncio.to_thread(cls._address_from_arp, sn)
        if address is not None:
            return address
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                hostname,
                80,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
            )
        except OSError:
            return None
        for info in infos:
            candidate = info[4][0]
            if cls._is_rfc1918(candidate):
                return candidate
        return None

    @staticmethod
    def _address_from_arp(sn: str) -> str | None:
        """Find the current device IPv4 address from the Linux neighbor cache."""
        if not re.fullmatch(r"[0-9A-Fa-f]{12}", sn):
            return None
        expected_mac = ":".join(
            sn[index : index + 2].lower() for index in range(0, 12, 2)
        )
        try:
            with open("/proc/net/arp", encoding="ascii") as arp_file:
                lines = arp_file.readlines()[1:]
        except OSError:
            return None
        for line in lines:
            columns = line.split()
            if len(columns) >= 6 and columns[3].lower() == expected_mac:
                candidate = columns[0]
                if YomiSmartAPI._is_rfc1918(candidate):
                    return candidate
        return None

    @staticmethod
    def _is_rfc1918(address: str) -> bool:
        """Allow only ordinary private IPv4 LAN ranges."""
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not isinstance(ip, ipaddress.IPv4Address):
            return False
        return (
            ip in ipaddress.ip_network("10.0.0.0/8")
            or ip in ipaddress.ip_network("172.16.0.0/12")
            or ip in ipaddress.ip_network("192.168.0.0/16")
        )

    async def current_power(self, sn: str) -> dict[str, Any]:
        """Read the current washer-cycle power summary."""
        payload = await self._request("GET", f"/app/devices/{sn}/power-curve/current")
        value = payload.get("data", payload)
        return value if isinstance(value, dict) else {}

    async def cancel_alarm(self, sn: str) -> None:
        """Queue an alarm cancellation command for a washer."""
        await self._request(
            "POST",
            f"/app/devices/{sn}/commands",
            json={"command": "alarm.cancel", "target": "device", "params": {}},
        )

    async def cancel_alarm_for_device(self, device: YomiSmartDevice) -> None:
        """Prefer the same-LAN cancel endpoint, then fall back to cloud."""
        if await self.local_cancel_alarm(device.sn, device.device_type):
            device.state["alarmActive"] = False
            device.state["localAlarmAvailable"] = True
            return
        await self.cancel_alarm(device.sn)

    async def send_command(
        self, sn: str, command: str, params: dict[str, Any]
    ) -> None:
        """Queue a device command after the server checks account permissions."""
        await self._request(
            "POST",
            f"/app/devices/{sn}/commands",
            json={"command": command, "target": "device", "params": params},
        )

    async def unlink(self) -> None:
        """Revoke this Home Assistant integration session."""
        await self._request("POST", "/app/integrations/home-assistant/unlink")

    async def refresh_access_token(self) -> None:
        if not self.refresh_token:
            raise YomiSmartAuthError
        try:
            async with self._session.post(
                f"{API_BASE_URL}/auth/home-assistant/token",
                json={
                    "grantType": "refresh_token",
                    "refreshToken": self.refresh_token,
                },
            ) as response:
                if response.status in (400, 401):
                    raise YomiSmartAuthError
                response.raise_for_status()
                token = self._normalize_token_response(await response.json())
        except ClientError as err:
            raise YomiSmartApiError(str(err)) from err
        self.access_token = token["access_token"]
        self.refresh_token = token["refresh_token"]
        if self._token_updated:
            self._token_updated(token)

    @staticmethod
    def _normalize_token_response(payload: Any) -> dict[str, Any]:
        """Accept both current and historical YomiSmart token field names."""
        top_level_keys = (
            sorted(str(key) for key in payload) if isinstance(payload, dict) else []
        )
        data_keys = (
            sorted(str(key) for key in payload["data"])
            if isinstance(payload, dict) and isinstance(payload.get("data"), dict)
            else []
        )
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        if not isinstance(payload, dict):
            _LOGGER.warning(
                "YomiSmart token response has invalid payload type=%s",
                type(payload).__name__,
            )
            raise YomiSmartApiError("Invalid token response")

        token = {
            "access_token": payload.get("access_token", payload.get("accessToken")),
            "refresh_token": payload.get(
                "refresh_token", payload.get("refreshToken")
            ),
            "expires_in": payload.get("expires_in", payload.get("expiresIn")),
            "account_id": payload.get("account_id", payload.get("accountId")),
        }
        missing_fields = [
            name for name, value in token.items() if value is None or value == ""
        ]
        if missing_fields:
            _LOGGER.warning(
                "YomiSmart token response missing fields=%s top_level_keys=%s "
                "data_keys=%s",
                missing_fields,
                top_level_keys,
                data_keys,
            )
            raise YomiSmartApiError("Incomplete token response")
        return token

    async def _request(
        self,
        method: str,
        path: str,
        allow_refresh: bool = True,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with self._session.request(
                method, f"{API_BASE_URL}{path}", headers=headers, json=json
            ) as response:
                if response.status == 401 and allow_refresh and self.refresh_token:
                    await self.refresh_access_token()
                    return await self._request(
                        method, path, allow_refresh=False, json=json
                    )
                if response.status == 401:
                    raise YomiSmartAuthError
                response.raise_for_status()
                return await response.json()
        except ClientError as err:
            raise YomiSmartApiError(str(err)) from err
