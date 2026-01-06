#!/bin/bash
# Flash MicroPython firmware to M5Stack Atom Echo

set -e

# Configuration
IDF_PATH="${IDF_PATH:-$HOME/esp-idf}"
MICROPYTHON="${MICROPYTHON:-$HOME/micropython}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOARD_DIR="$SCRIPT_DIR/board/ATOM_ECHO"
PORT="${1:-/dev/ttyUSB0}"

# Check prerequisites
if [ ! -d "$IDF_PATH" ]; then
    echo "Error: ESP-IDF not found at $IDF_PATH"
    exit 1
fi

if [ ! -d "$MICROPYTHON" ]; then
    echo "Error: MicroPython not found at $MICROPYTHON"
    exit 1
fi

# Source ESP-IDF environment
source "$IDF_PATH/export.sh"

cd "$MICROPYTHON/ports/esp32"

# Erase flash first (optional, uncomment if needed)
# echo "Erasing flash..."
# make BOARD_DIR="$BOARD_DIR" erase PORT="$PORT"

# Deploy firmware
echo "Flashing to $PORT..."
make BOARD_DIR="$BOARD_DIR" deploy PORT="$PORT"

echo ""
echo "Flash complete!"
echo "Connect to serial monitor: screen $PORT 115200"
