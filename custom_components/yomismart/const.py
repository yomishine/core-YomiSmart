"""YomiSmart integration constants."""

DOMAIN = "yomismart"
MANUFACTURER = "YomiSmart"
MODEL_WASHING_MACHINE = "Washing Machine Monitor"
MODEL_POWER_CUT = "Power Cut Monitor"


def model_for_device(device_type: str) -> str:
    """Return the user-facing model for a supported device type."""
    return MODEL_POWER_CUT if device_type == "power_cut" else MODEL_WASHING_MACHINE
API_BASE_URL = "https://iot01.yomishine.com"
DEFAULT_POLL_INTERVAL = 60
# A full refresh includes the device list and parallel power-curve reads.
REQUEST_TIMEOUT = 20

CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
CONF_ACCOUNT_ID = "account_id"
SERVICE_CANCEL_ALARM = "cancel_alarm"
SERVICE_SET_VOLUME = "set_volume"
