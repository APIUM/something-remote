# Something Remote

A port of [TheStockPot's Everything Remote](https://www.thestockpot.net/videos/theeverythingremote) to MicroPython, with changes that make it work much better on the Nvidia Shield by using a mix of BLE and Home Assistant.

## Why BLE + Home Assistant?

I found the HA actions on the original for navigation on the Shield had much too high latency, so I reimplemented the main nav buttons using BLE. You pair the remote to the Shield as a bluetooth remote and it works with very similar performance to the original Shield remote.

For the HA actions I use MQTT auto-discovery with triggers for the buttons. To set up an automation in HA (after doing the WiFi setup including your MQTT broker), target the device as "Something Remote" and use the trigger dropdown to select the button you want. Remember to set the automation mode to "queued" if you want multiple presses to all process (e.g., for dimming a light).

I've also added an MPU6050 to enable lift to wake as I didn't like having to press the power button just to make another input. This is optional, if it's not found at boot then it will just use the power button in a similar way to the original. Ensure it's wired as stated below.

## Re-pairing

- **BLE**: Hold **Power + Back** for 5 seconds
- **WiFi/MQTT**: Hold **Shortcut1 + Shortcut3** for 5 seconds

## Config

You can select whether the power button works over BLE or triggers a Home Assistant automation. This depends on your setup and whether you need to trigger other actions on power on/off. Configure this in the WiFi setup portal.

## Hardware

- Everything Remote v1.1 board (ESP32 with 21 buttons)
- MPU6050 accelerometer for motion wake (optional)
  - SDA: GPIO33, SCL: GPIO22, INT: GPIO36 (VP)

## Features

- **BLE HID** - Keyboard and Consumer Control for Shield navigation
- **Home Assistant** - MQTT integration with auto-discovery
- **Power Management** - Light sleep and deep sleep with motion wake
- **Captive Portal** - WiFi/MQTT setup via browser

## Quick Start - Flashing Pre-built Firmware

### Download

Get `something-remote-firmware.bin` from [Releases](../../releases/latest).

### Flash

1. **Connect** board via USB and find the port:
   - Linux: `/dev/ttyUSB0`
   - Mac: `/dev/cu.usbserial-*`
   - Windows: `COMx` (check Device Manager → Ports)

2. **Erase and flash**:
   ```bash
   # Using uv (recommended - no install needed)
   uvx esptool --port /dev/ttyUSB0 erase_flash
   uvx esptool --port /dev/ttyUSB0 write_flash 0x0 something-remote-firmware.bin

   # Or using pip
   pip install esptool
   esptool.py --port /dev/ttyUSB0 erase_flash
   esptool.py --port /dev/ttyUSB0 write_flash 0x0 something-remote-firmware.bin
   ```

3. **Configure**: Connect to "SomethingRemote-Setup" WiFi (password: `12345678`), enter your WiFi and MQTT settings

4. **Pair**: See [Pairing with Shield](#pairing-with-shield) below

## Button Combos

| Combo | Hold Time | Action |
|-------|-----------|--------|
| **Power + Back** | 5 seconds | Clear BLE bonds, restart advertising (for pairing) |
| **Shortcut1 + Shortcut3** | 5 seconds | Enter WiFi/MQTT setup portal |

## Button Mapping

### BLE HID (Shield Control)
- D-pad: Up/Down/Left/Right arrows
- Select: Enter
- Back: Consumer Control Back (AC Back)
- Home: Consumer Control Home (AC Home)
- Play/Pause, Vol+, Vol-, Mute: Consumer Control media keys
- Ch+/Ch-: Page Up/Down

### Home Assistant (MQTT)
- Power: `power` action
- Shortcuts 1-4: `shortcut_1` to `shortcut_4` actions
- Brightness +/-: `brightness_up`/`brightness_down` actions

## Setup

### First Time Setup

1. Flash firmware (see Build section)
2. Device creates WiFi AP: "Something Remote Setup"
3. Connect to AP, browser opens setup page
4. Enter WiFi credentials and MQTT broker details
5. Device restarts and connects

### Pairing with Shield

1. Hold **Power + Back** for 5 seconds to ensure device is advertising
2. On Shield: Settings → Remote & Accessories → Add Accessory
3. Select "Something Remote"

### Re-entering Setup

Hold **Shortcut1 + Shortcut3** for 5 seconds.

## Power Management

- **5 minutes** idle → Light sleep (BLE stays active)
- **1 hour** of light sleep → Deep sleep
- **Wake**: Any button press or motion (if MPU6050 installed)

## Build

### Prerequisites

```bash
# ESP-IDF v5.2.x
cd ~
git clone -b v5.2.2 --recursive https://github.com/espressif/esp-idf.git
cd esp-idf && ./install.sh esp32 && source export.sh

# MicroPython
cd ~
git clone https://github.com/micropython/micropython.git
cd micropython && git checkout v1.24.1 && git submodule update --init
make -C mpy-cross
```

### Build & Flash

```bash
./build.sh
./flash.sh /dev/ttyUSB0
```

## Project Structure

```
├── board/ATOM_ECHO/        # MicroPython board definition
├── modules/                # Python code (frozen into firmware)
│   ├── shield_remote.py    # Main application
│   ├── hid_services.py     # BLE HID implementation
│   ├── hid_keystores.py    # BLE bonding key storage
│   ├── ha_client.py        # Home Assistant MQTT client
│   ├── wifi_setup.py       # Captive portal for setup
│   ├── config.py           # Configuration storage
│   ├── mpu6050_wake.py     # Accelerometer motion wake
│   ├── logger.py           # File-based logging
│   └── main.py             # Entry point
├── build.sh                # Build script
└── flash.sh                # Flash script
```

## Troubleshooting

- **Can't pair**: Hold Power + Back 5 sec to clear bonds, then retry
- **Can't see in Shield menu**: Try nRF Connect app to verify device is advertising
- **WiFi issues**: Hold Shortcut1 + Shortcut3 5 sec to re-enter setup
- **Debug output**: `screen /dev/ttyUSB0 115200`

## License

BLE HID library adapted from MicroPythonBLEHID (GPL-3.0).
