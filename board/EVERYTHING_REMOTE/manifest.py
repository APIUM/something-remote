# Manifest file for Everything Remote

# Include the standard ESP32 manifest
include("$(PORT_DIR)/boards/manifest.py")

# Include MQTT library for Home Assistant
require("umqtt.simple")

# Freeze our custom modules
freeze("$(BOARD_DIR)/../../modules")
