# Shield Remote - BLE HID Remote for Nvidia Shield
# M5Stack Atom Echo implementation

from machine import Pin
import time
import sys
from neopixel import NeoPixel
from hid_services import Keyboard

# Hardware pins for M5Stack Atom Echo
BUTTON_PIN = 39  # Input only, active LOW
LED_PIN = 27     # SK6812 NeoPixel

# HID key codes (USB HID Usage Tables)
KEY_RIGHT_ARROW = 0x4F
KEY_LEFT_ARROW = 0x50
KEY_DOWN_ARROW = 0x51
KEY_UP_ARROW = 0x52
KEY_ENTER = 0x28
KEY_ESCAPE = 0x29

# LED colors (GRB format for SK6812)
COLOR_OFF = (0, 0, 0)
COLOR_BLUE = (0, 0, 32)       # Advertising
COLOR_GREEN = (32, 0, 0)      # Connected
COLOR_WHITE = (32, 32, 32)    # Button pressed
COLOR_RED = (0, 32, 0)        # Error


class ShieldRemote:
    """BLE HID remote control for Nvidia Shield."""

    def __init__(self, name="Shield Remote"):
        # Initialize NeoPixel LED first for error display
        self.led = NeoPixel(Pin(LED_PIN, Pin.OUT), 1)
        self.set_led(COLOR_OFF)

        # Track if BLE is fully initialized
        self._ble_ready = False

        # Initialize keyboard HID
        self.kb = Keyboard(name)
        self.kb.set_state_change_callback(self._on_state_change)

        # Initialize button (active LOW with external pullup)
        self.button = Pin(BUTTON_PIN, Pin.IN)

        # State tracking
        self._connected = False
        self._last_button_state = 1  # Not pressed (active LOW)
        self._last_press_time = 0
        self._debounce_ms = 50

    def set_led(self, color):
        """Set LED color (GRB tuple)."""
        self.led[0] = color
        self.led.write()

    def _on_state_change(self):
        """Handle BLE state changes."""
        state = self.kb.get_state()
        if state == Keyboard.DEVICE_CONNECTED:
            self._connected = True
            self.set_led(COLOR_GREEN)
            print("Shield connected")
        elif state == Keyboard.DEVICE_ADVERTISING:
            self._connected = False
            self.set_led(COLOR_BLUE)
            print("Advertising...")
        elif state == Keyboard.DEVICE_IDLE:
            self._connected = False
            self.set_led(COLOR_BLUE)
            # Only auto-restart advertising if BLE is fully initialized
            if self._ble_ready:
                self.kb.start_advertising()
        else:
            self._connected = False
            self.set_led(COLOR_OFF)

    def send_key(self, key_code):
        """Send a key press and release."""
        if self._connected:
            # Press
            self.kb.set_keys(key_code)
            self.kb.notify_hid_report()
            time.sleep_ms(10)
            # Release
            self.kb.set_keys()
            self.kb.notify_hid_report()
            return True
        return False

    def _handle_button(self):
        """Handle button press with debouncing."""
        state = self.button.value()

        # Check for state change
        if state != self._last_button_state:
            now = time.ticks_ms()

            # Debounce check
            if time.ticks_diff(now, self._last_press_time) >= self._debounce_ms:
                self._last_press_time = now
                self._last_button_state = state

                if state == 0:  # Button pressed (active LOW)
                    self.set_led(COLOR_WHITE)
                    if self._connected:
                        self.kb.set_keys(KEY_RIGHT_ARROW)
                        self.kb.notify_hid_report()
                        print("Right arrow pressed")
                else:  # Button released
                    if self._connected:
                        self.kb.set_keys()  # Release all keys
                        self.kb.notify_hid_report()
                        self.set_led(COLOR_GREEN)
                        print("Key released")
                    else:
                        self.set_led(COLOR_BLUE)

    def run(self):
        """Main loop - start BLE and handle button input."""
        print("Starting Shield Remote...")
        self.set_led(COLOR_RED)  # Initializing

        # Start BLE services
        self.kb.start()
        time.sleep_ms(100)

        # Mark BLE as ready and start advertising
        self._ble_ready = True
        self.kb.start_advertising()
        self.set_led(COLOR_BLUE)
        print("Ready - press button to send Right Arrow")

        # Main loop
        while True:
            self._handle_button()
            time.sleep_ms(10)  # 10ms poll interval


def main():
    """Entry point with error handling."""
    led = None
    try:
        led = NeoPixel(Pin(LED_PIN, Pin.OUT), 1)
        remote = ShieldRemote()
        remote.run()
    except Exception as e:
        # Show red LED on error
        print("Error:", e)
        sys.print_exception(e)
        if led:
            led[0] = COLOR_RED
            led.write()
        # Keep LED red and don't exit so error is visible
        while True:
            time.sleep_ms(1000)


if __name__ == "__main__":
    main()
