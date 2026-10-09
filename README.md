# YomiSmart for Home Assistant

Monitor your YomiSmart laundry and power devices in Home Assistant. After you link your YomiSmart account, Home Assistant automatically discovers the supported devices associated with that account and keeps their status up to date.

## Installation

### Install with HACS

1. Open **HACS** in Home Assistant.
2. Select **Integrations**.
3. Open the menu in the top-right corner and select **Custom repositories**.
4. Enter this repository's GitHub URL and select **Integration** as the category.
5. Select **Add**, find **YomiSmart**, and select **Download**.
6. Restart Home Assistant.

Until this integration is included in the default HACS repository, it must be added as a custom repository.

### Manual installation

Copy the `custom_components/yomismart` directory from this repository to:


```text
<Home Assistant configuration directory>/custom_components/yomismart/
```

Restart Home Assistant after installing or updating the integration.

## Before you begin

Make sure that:

- Home Assistant is running and the YomiSmart integration has been installed.
- Your YomiSmart device is already set up and visible in the YomiSmart app.
- Your phone can access the YomiSmart app and your Home Assistant instance.

## Generate an authorization code

The integration uses a one-time authorization code to link Home Assistant to your YomiSmart account.

1. Open the YomiSmart app.
2. Open the **Home Assistant** page.
3. Generate a six-digit authorization code.
4. Keep this page open or copy the code. The code is shown in the format `123-456`.

<!-- IMAGE PLACEHOLDER: YomiSmart app Home Assistant page and authorization code -->

For security, enter the code in Home Assistant as soon as it is generated. If Home Assistant reports that the code is invalid or expired, return to the YomiSmart app and generate a new one.

## Add YomiSmart to Home Assistant

1. Open your Home Assistant instance.
2. Go to **Settings > Devices & services**.
3. Select **Add Integration** in the bottom-right corner.
4. Search for and select **YomiSmart**.
5. Enter the authorization code from the YomiSmart app, including the hyphen, for example `123-456`.
6. Follow the on-screen instructions to finish setup.

<!-- IMAGE PLACEHOLDER: Home Assistant Add Integration screen -->

<!-- IMAGE PLACEHOLDER: YomiSmart authorization code dialog in Home Assistant -->

Once setup is complete, Home Assistant automatically adds the supported YomiSmart devices linked to your account. You do not need to select a device type manually.

## Available devices and entities

The entities shown in Home Assistant depend on the device type, its capabilities, and the permissions granted to your account.

### Washing Machine Monitor

A washing machine monitor can provide:

- **Washer state** — `idle`, `running`, `ending`, or `completed`.
- **Completion alarm** — indicates whether the laundry-complete alarm is active.
- **Connectivity** — indicates whether the device is online.
- **Volume** — shows the configured alert volume.
- **Alarm delay** — shows the configured delay in minutes.
- **Current power** — shows the latest power reading in watts.
- **Peak power** — shows the peak power reading in watts.
- **Cancel alarm** — stops an active completion alarm when your account has permission to control it.

### Power Cut Monitor

A power cut monitor can provide:

- **Power status** — displays `Power cut` or `Power restored`.
- **Connectivity** — indicates whether the device is online.
- **Status light** — turns the device status light on or off when your account has control permission.
- **Cancel alarm** — stops an active alarm when your account has alarm-control permission.

Some entity names may include the device name assigned in the YomiSmart app.

<!-- IMAGE PLACEHOLDER: YomiSmart device and entity list in Home Assistant -->

## Use YomiSmart in automations

You can use YomiSmart entity state changes as automation triggers. For example, an automation can send a notification when **Washer state** changes to `completed`, or alert you when **Power status** changes to `Power cut`.

When creating an automation, select the relevant YomiSmart device or entity and choose the state you want Home Assistant to monitor.

<!-- IMAGE PLACEHOLDER: Example Home Assistant automation using a YomiSmart entity -->

## Troubleshooting

### The authorization code is not accepted

- Confirm that the code is entered in the `123-456` format.
- Generate a new code in the YomiSmart app if the original code has expired or has already been used.
- Make sure the code was generated from the YomiSmart account you want to link.

### No devices appear after setup

- Confirm that the devices are online and visible in the YomiSmart app.
- Wait at least one minute for the next cloud update.
- In Home Assistant, go to **Settings > Devices & services > YomiSmart** and reload the integration.

### An entity is unavailable or a control is missing

- Check that the device is online.
- Confirm that your YomiSmart account has permission to view or control the device.
- Some entities are available only on specific device types.
- Home Assistant controls appear only when the linked account has the required permission.

### Account access has changed

If Home Assistant asks you to authenticate again, generate a new authorization code in the YomiSmart app and enter it in the reauthentication dialog.

## Remove the integration

1. In Home Assistant, go to **Settings > Devices & services**.
2. Open the **YomiSmart** integration.
3. Open the integration menu and select **Delete**.

Removing the integration removes its devices and entities from Home Assistant and attempts to unlink the Home Assistant connection from your YomiSmart account. It does not delete your YomiSmart devices or your YomiSmart account.

## Data updates

YomiSmart is a cloud-polling integration. Home Assistant retrieves updated device information from the YomiSmart service approximately every 60 seconds. Some supported readings may use local device data when it is available.
