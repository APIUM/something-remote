# Manifest file for ESP32-WROOM-32D Shield Remote

# Include the standard ESP32 manifest
include("$(PORT_DIR)/boards/manifest.py")

# Freeze our custom modules
freeze("$(BOARD_DIR)/../../modules")
