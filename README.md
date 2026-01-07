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

- Linux (tested on Ubuntu/WSL)
- Python 3.8+
- Git

## Setup

### 1. Install ESP-IDF v5.2.x

```bash
cd ~
git clone -b v5.2.2 --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32
source export.sh
```

### 2. Clone MicroPython

```bash
cd ~
git clone https://github.com/micropython/micropython.git
cd micropython
git checkout v1.24.1
git submodule update --init
make -C mpy-cross
```

### 3. Build Firmware

```bash
cd /path/to/something-remote
./build.sh
```

### 4. Flash to Device

Connect Atom Echo via USB, then:

```bash
./flash.sh /dev/ttyUSB0
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
