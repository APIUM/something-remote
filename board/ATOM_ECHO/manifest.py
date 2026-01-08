# Manifest file for M5Stack Atom Echo Shield Remote

# Include the standard ESP32 manifest
include("$(PORT_DIR)/boards/manifest.py")

# Freeze our custom modules
freeze("$(BOARD_DIR)/../../modules")
