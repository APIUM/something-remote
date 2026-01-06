set(IDF_TARGET esp32)

set(SDKCONFIG_DEFAULTS
    ${MICROPY_PORT_DIR}/boards/sdkconfig.base
    ${MICROPY_PORT_DIR}/boards/sdkconfig.ble
    ${CMAKE_CURRENT_LIST_DIR}/sdkconfig.board
)

set(MICROPY_FROZEN_MANIFEST ${CMAKE_CURRENT_LIST_DIR}/manifest.py)
