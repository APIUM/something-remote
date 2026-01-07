# Shield Remote

BLE HID remote control for Nvidia Shield using M5Stack Atom Echo and MicroPython.

## Hardware

- M5Stack Atom Echo (ESP32-PICO-D4)
- Button: GPIO39 (top button)
- LED: GPIO27 (SK6812 NeoPixel)

## Features

- BLE HID Keyboard profile
- Press button to send Right Arrow key
- LED status: Blue=advertising, Green=connected, White=key pressed
- Bonding keys stored in ESP32 NVS

## Prerequisites

- Docker

## Build (Docker)

### 1. Build Docker Image (first time only)

```bash
make docker-build
```

### 2. Build Firmware

```bash
make build
```

### 3. Copy Firmware to Local Directory

```bash
make copy-firmware
```

### 4. Flash to Device

Connect Atom Echo via USB, then:

```bash
make flash PORT=/dev/ttyUSB0
```

Or flash manually with esptool:

```bash
pip install esptool
esptool.py --chip esp32 --port /dev/ttyUSB0 write_flash -z 0x1000 build/firmware.bin
```

### Interactive Shell

To debug or explore the build environment:

```bash
make shell
```

## Usage

1. After flashing, device starts advertising (blue LED)
2. On Nvidia Shield: Settings → Remote & Accessories → Add Accessory
3. Select "Shield Remote"
4. Once connected (green LED), press button to navigate right
5. LED flashes white on button press

## Troubleshooting

- If Shield won't pair, ensure location services are enabled on Shield
- Use `screen /dev/ttyUSB0 115200` to view debug output
- Check BLE advertising with nRF Connect app on phone

## Project Structure

```
├── board/ATOM_ECHO/      # MicroPython board definition
├── modules/              # Python code (frozen into firmware)
│   ├── hid_services.py   # BLE HID implementation
│   ├── shield_remote.py  # Main application
│   └── main.py           # Entry point
├── build.sh              # Build script
└── flash.sh              # Flash script
```

## License

BLE HID library adapted from MicroPythonBLEHID (GPL-3.0).
