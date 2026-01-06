#!/bin/bash
# Build MicroPython firmware with frozen modules for M5Stack Atom Echo

set -e

# Configuration - adjust these paths as needed
IDF_PATH="${IDF_PATH:-$HOME/esp-idf}"
MICROPYTHON="${MICROPYTHON:-$HOME/micropython}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOARD_DIR="$SCRIPT_DIR/board/ATOM_ECHO"

# Check prerequisites
if [ ! -d "$IDF_PATH" ]; then
    echo "Error: ESP-IDF not found at $IDF_PATH"
    echo "Set IDF_PATH or install ESP-IDF v5.2.x"
    exit 1
fi

if [ ! -d "$MICROPYTHON" ]; then
    echo "Error: MicroPython not found at $MICROPYTHON"
    echo "Set MICROPYTHON or clone the repository"
    exit 1
fi

# Source ESP-IDF environment
echo "Sourcing ESP-IDF environment..."
source "$IDF_PATH/export.sh"

# Build mpy-cross if needed
if [ ! -f "$MICROPYTHON/mpy-cross/build/mpy-cross" ]; then
    echo "Building mpy-cross..."
    make -C "$MICROPYTHON/mpy-cross"
fi

# Build the firmware
echo "Building firmware..."
cd "$MICROPYTHON/ports/esp32"
make BOARD_DIR="$BOARD_DIR" "$@"

echo ""
echo "Build complete!"
echo "Firmware location: $MICROPYTHON/ports/esp32/build-ATOM_ECHO/"
echo ""
echo "To flash: ./flash.sh [PORT]"
