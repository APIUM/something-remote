# Shield Remote - BLE HID Remote for Nvidia Shield
# M5Stack Atom Echo implementation with 10-button support

from machine import Pin, ADC
import time
import sys
from neopixel import NeoPixel
from hid_services import Keyboard

# Hardware pins for M5Stack Atom Echo
BUTTON_PIN = 39      # Built-in button (Center/Select)
POWER_PIN = 21       # External digital button (On/Off)
ADC_PIN = 25         # Resistor ladder (8 buttons)
LED_PIN = 27         # SK6812 NeoPixel

# HID key codes (USB HID Usage Tables)
KEY_UP = 0x52
KEY_DOWN = 0x51
KEY_LEFT = 0x50
KEY_RIGHT = 0x4F
KEY_ENTER = 0x28      # Center/Select
KEY_ESCAPE = 0x29     # Back
KEY_HOME = 0x4A       # Home (Keyboard Home key)
KEY_POWER = 0x66      # Power (Keyboard Power key)
KEY_VOL_UP = 0x80     # Volume Up
KEY_VOL_DOWN = 0x81   # Volume Down

# LED colors (GRB format for SK6812)
COLOR_OFF = (0, 0, 0)
COLOR_BLUE = (0, 0, 32)       # Advertising
COLOR_GREEN = (32, 0, 0)      # Connected
COLOR_WHITE = (32, 32, 32)    # Button pressed
COLOR_RED = (0, 32, 0)        # Error

# ADC thresholds for resistor ladder (8 buttons on G25)
# Values need calibration based on actual resistors used
# Format: (min_value, max_value, key_code, name)
ADC_BUTTONS = [
    (3300, 3700, KEY_UP, "Up"),
    (2800, 3200, KEY_DOWN, "Down"),
    (2300, 2700, KEY_LEFT, "Left"),
    (1800, 2200, KEY_RIGHT, "Right"),
    (1300, 1700, KEY_ESCAPE, "Back"),
    (800, 1200, KEY_HOME, "Home"),
    (400, 700, KEY_VOL_UP, "Vol+"),
    (100, 350, KEY_VOL_DOWN, "Vol-"),
]


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

        # Initialize buttons
        self.btn_center = Pin(BUTTON_PIN, Pin.IN)  # Built-in, active LOW
        self.btn_power = Pin(POWER_PIN, Pin.IN, Pin.PULL_UP)  # External, active LOW

        # Initialize ADC for resistor ladder
        self.adc = ADC(Pin(ADC_PIN))
        self.adc.atten(ADC.ATTN_11DB)  # Full range 0-3.3V
        self.adc.width(ADC.WIDTH_12BIT)  # 12-bit resolution (0-4095)

        # State tracking
        self._connected = False
        self._last_center_state = 1
        self._last_power_state = 1
        self._last_adc_key = None
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

    def _send_key(self, key_code, name=""):
        """Send a key press."""
        if self._connected:
            self.kb.set_keys(key_code)
            self.kb.notify_hid_report()
            if name:
                print(f"{name} pressed")
            return True
        return False

    def _release_keys(self):
        """Release all keys."""
        if self._connected:
            self.kb.set_keys()
            self.kb.notify_hid_report()

    def _read_adc_button(self):
        """Read resistor ladder and return key code or None."""
        value = self.adc.read()

        for min_val, max_val, key_code, name in ADC_BUTTONS:
            if min_val <= value <= max_val:
                return key_code, name

        return None, None

    def _handle_buttons(self):
        """Handle all button inputs."""
        now = time.ticks_ms()
        pressed = False

        # Debounce check
        if time.ticks_diff(now, self._last_press_time) < self._debounce_ms:
            return

        # Check center button (G39, built-in)
        center_state = self.btn_center.value()
        if center_state != self._last_center_state:
            self._last_press_time = now
            self._last_center_state = center_state
            if center_state == 0:  # Pressed
                self.set_led(COLOR_WHITE)
                self._send_key(KEY_ENTER, "Center")
                pressed = True
            else:  # Released
                self._release_keys()

        # Check power button (G21, external)
        power_state = self.btn_power.value()
        if power_state != self._last_power_state:
            self._last_press_time = now
            self._last_power_state = power_state
            if power_state == 0:  # Pressed
                self.set_led(COLOR_WHITE)
                self._send_key(KEY_POWER, "Power")
                pressed = True
            else:  # Released
                self._release_keys()

        # Check ADC resistor ladder (G25)
        adc_key, adc_name = self._read_adc_button()
        if adc_key != self._last_adc_key:
            self._last_press_time = now
            if adc_key is not None:  # Button pressed
                self.set_led(COLOR_WHITE)
                self._send_key(adc_key, adc_name)
                pressed = True
            else:  # Button released
                if self._last_adc_key is not None:
                    self._release_keys()
            self._last_adc_key = adc_key

        # Reset LED if not pressed
        if not pressed and center_state == 1 and power_state == 1 and adc_key is None:
            if self._connected:
                self.set_led(COLOR_GREEN)
            else:
                self.set_led(COLOR_BLUE)

    def calibrate_adc(self):
        """Helper to calibrate ADC values. Run interactively."""
        print("ADC Calibration Mode")
        print("Press each button and note the ADC value")
        print("Press Ctrl+C to exit")
        try:
            while True:
                value = self.adc.read()
                print(f"ADC: {value}", end="\r")
                time.sleep_ms(100)
        except KeyboardInterrupt:
            print("\nCalibration ended")

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
        print("Ready - 10 button remote")
        print("Buttons: Center(G39), Power(G21), D-pad+Nav(G25 ladder)")

        # Main loop
        while True:
            self._handle_buttons()
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


def calibrate():
    """Run ADC calibration helper."""
    remote = ShieldRemote()
    remote.calibrate_adc()


if __name__ == "__main__":
    main()
