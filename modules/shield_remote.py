# Shield Remote - BLE HID Remote for Nvidia Shield
# Everything Remote hardware layout (21 buttons)
# https://www.thestockpot.net/videos/theeverythingremote

from machine import Pin
import time
import sys
from neopixel import NeoPixel
from hid_services import Keyboard

# Everything Remote GPIO assignments
PIN_POWER = 0         # Strapping pin - needs care
PIN_BACK = 2          # Strapping pin - needs care
PIN_HOME = 4
PIN_PLAY_PAUSE = 5
PIN_UP = 18
PIN_LEFT = 19
PIN_SELECT = 22
PIN_RIGHT = 23
PIN_DOWN = 25
PIN_VOL_UP = 12
PIN_MUTE = 13
PIN_CH_UP = 14
PIN_VOL_DOWN = 15
PIN_SETTINGS = 16
PIN_CH_DOWN = 17
PIN_SHORTCUT_3 = 32
PIN_SHORTCUT_4 = 33
PIN_BRIGHT_DOWN = 26
PIN_BRIGHT_UP = 27
PIN_SHORTCUT_1 = 34   # Input-only, no internal pull-up
PIN_SHORTCUT_2 = 35   # Input-only, no internal pull-up

# Status LED (directly on GPIO, optional external NeoPixel)
LED_PIN = 21          # Or use onboard LED if available

# HID key codes (USB HID Keyboard Usage Tables - Page 0x07)
KEY_UP = 0x52
KEY_DOWN = 0x51
KEY_LEFT = 0x50
KEY_RIGHT = 0x4F
KEY_ENTER = 0x28      # Select
KEY_ESCAPE = 0x29     # Back (fallback)
KEY_PAGE_UP = 0x4B    # Channel Up
KEY_PAGE_DOWN = 0x4E  # Channel Down
KEY_F1 = 0x3A         # Shortcut 1
KEY_F2 = 0x3B         # Shortcut 2
KEY_F3 = 0x3C         # Shortcut 3
KEY_F4 = 0x3D         # Shortcut 4
KEY_F5 = 0x3E         # Settings
KEY_F7 = 0x40         # Brightness Down
KEY_F8 = 0x41         # Brightness Up

# Consumer Control codes (USB HID Consumer Page 0x0C)
# These work for media keys on Shield
CC_POWER = 0x30       # Power
CC_MENU = 0x40        # Menu/Home
CC_PLAY_PAUSE = 0xCD  # Play/Pause
CC_MUTE = 0xE2        # Mute
CC_VOL_UP = 0xE9      # Volume Up
CC_VOL_DOWN = 0xEA    # Volume Down
CC_HOME = 0x223       # AC Home
CC_BACK = 0x224       # AC Back

# LED colors (accent LED if present)
COLOR_OFF = (0, 0, 0)
COLOR_BLUE = (0, 0, 32)       # Advertising
COLOR_GREEN = (32, 0, 0)      # Connected (GRB)
COLOR_WHITE = (32, 32, 32)    # Button pressed
COLOR_RED = (0, 32, 0)        # Error (GRB)

# Button type constants
TYPE_KEY = 0      # Keyboard HID
TYPE_CONSUMER = 1 # Consumer Control HID

# Button definitions: (pin, code, name, has_pullup, type)
BUTTONS = [
    # Navigation - Keyboard HID
    (PIN_UP, KEY_UP, "Up", True, TYPE_KEY),
    (PIN_DOWN, KEY_DOWN, "Down", True, TYPE_KEY),
    (PIN_LEFT, KEY_LEFT, "Left", True, TYPE_KEY),
    (PIN_RIGHT, KEY_RIGHT, "Right", True, TYPE_KEY),
    (PIN_SELECT, KEY_ENTER, "Select", True, TYPE_KEY),

    # Navigation - Consumer Control (proper Shield codes)
    (PIN_BACK, CC_BACK, "Back", True, TYPE_CONSUMER),
    (PIN_HOME, CC_HOME, "Home", True, TYPE_CONSUMER),
    (PIN_POWER, CC_POWER, "Power", True, TYPE_CONSUMER),

    # Media - Consumer Control
    (PIN_PLAY_PAUSE, CC_PLAY_PAUSE, "Play/Pause", True, TYPE_CONSUMER),
    (PIN_VOL_UP, CC_VOL_UP, "Vol+", True, TYPE_CONSUMER),
    (PIN_VOL_DOWN, CC_VOL_DOWN, "Vol-", True, TYPE_CONSUMER),
    (PIN_MUTE, CC_MUTE, "Mute", True, TYPE_CONSUMER),

    # Channels - Keyboard HID (Page Up/Down)
    (PIN_CH_UP, KEY_PAGE_UP, "Ch+", True, TYPE_KEY),
    (PIN_CH_DOWN, KEY_PAGE_DOWN, "Ch-", True, TYPE_KEY),

    # Function keys - Keyboard HID
    (PIN_SETTINGS, KEY_F5, "Settings", True, TYPE_KEY),
    (PIN_BRIGHT_UP, KEY_F8, "Bright+", True, TYPE_KEY),
    (PIN_BRIGHT_DOWN, KEY_F7, "Bright-", True, TYPE_KEY),
    (PIN_SHORTCUT_1, KEY_F1, "Shortcut1", False, TYPE_KEY),  # No internal pull-up
    (PIN_SHORTCUT_2, KEY_F2, "Shortcut2", False, TYPE_KEY),  # No internal pull-up
    (PIN_SHORTCUT_3, KEY_F3, "Shortcut3", True, TYPE_KEY),
    (PIN_SHORTCUT_4, KEY_F4, "Shortcut4", True, TYPE_KEY),
]


class ShieldRemote:
    """BLE HID remote control for Nvidia Shield."""

    def __init__(self, name="Shield Remote"):
        # Try to initialize LED (may not be present)
        self.led = None
        try:
            self.led = NeoPixel(Pin(LED_PIN, Pin.OUT), 1)
            self.set_led(COLOR_OFF)
        except Exception:
            print("No NeoPixel LED on GPIO", LED_PIN)

        # Track if BLE is fully initialized
        self._ble_ready = False

        # Initialize keyboard HID
        self.kb = Keyboard(name)
        self.kb.set_state_change_callback(self._on_state_change)

        # Initialize buttons
        self.buttons = []
        self.button_states = []
        for pin_num, code, name, has_pullup, btn_type in BUTTONS:
            if has_pullup:
                btn = Pin(pin_num, Pin.IN, Pin.PULL_UP)
            else:
                # GPIO 34/35 need external pull-up resistor
                btn = Pin(pin_num, Pin.IN)
            self.buttons.append((btn, code, name, btn_type))
            self.button_states.append(1)  # Initial state (not pressed)

        # State tracking
        self._connected = False
        self._last_press_time = 0
        self._debounce_ms = 50
        self._any_pressed = False
        self._active_type = None  # Track which report type is active

    def set_led(self, color):
        """Set LED color (GRB tuple)."""
        if self.led:
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
            if self._ble_ready:
                self.kb.start_advertising()
        else:
            self._connected = False
            self.set_led(COLOR_OFF)

    def _send_key(self, code, name="", btn_type=TYPE_KEY):
        """Send a key press."""
        if self._connected:
            if btn_type == TYPE_CONSUMER:
                self.kb.set_consumer(code)
                self.kb.notify_consumer_report()
            else:
                self.kb.set_keys(code)
                self.kb.notify_hid_report()
            self._active_type = btn_type
            if name:
                print(f"{name} pressed")
            return True
        return False

    def _release_keys(self):
        """Release all keys."""
        if self._connected:
            if self._active_type == TYPE_CONSUMER:
                self.kb.set_consumer(0)
                self.kb.notify_consumer_report()
            else:
                self.kb.set_keys()
                self.kb.notify_hid_report()
            self._active_type = None

    def _handle_buttons(self):
        """Handle all button inputs."""
        now = time.ticks_ms()

        # Debounce check
        if time.ticks_diff(now, self._last_press_time) < self._debounce_ms:
            return

        # Check each button
        for i, (btn, code, name, btn_type) in enumerate(self.buttons):
            state = btn.value()
            if state != self.button_states[i]:
                self._last_press_time = now
                self.button_states[i] = state
                if state == 0:  # Pressed (active LOW)
                    self.set_led(COLOR_WHITE)
                    self._send_key(code, name, btn_type)
                    self._any_pressed = True
                else:  # Released
                    self._release_keys()

        # Check if any button is currently pressed
        any_currently_pressed = any(btn.value() == 0 for btn, _, _, _ in self.buttons)

        # Reset LED if no buttons pressed
        if not any_currently_pressed and self._any_pressed:
            self._any_pressed = False
            if self._connected:
                self.set_led(COLOR_GREEN)
            else:
                self.set_led(COLOR_BLUE)

    def test_buttons(self):
        """Interactive button test mode."""
        print("Button Test Mode - Everything Remote")
        print("Press each button to test. Ctrl+C to exit.")
        print(f"Testing {len(self.buttons)} buttons")
        try:
            while True:
                for i, (btn, code, name, btn_type) in enumerate(self.buttons):
                    if btn.value() == 0:
                        type_str = "Consumer" if btn_type == TYPE_CONSUMER else "Keyboard"
                        print(f"{name} (GPIO{BUTTONS[i][0]}, 0x{code:02X}, {type_str})")
                        self.set_led(COLOR_WHITE)
                        while btn.value() == 0:
                            time.sleep_ms(10)
                        self.set_led(COLOR_OFF)
                time.sleep_ms(10)
        except KeyboardInterrupt:
            print("\nTest ended")

    def run(self):
        """Main loop - start BLE and handle button input."""
        print("Starting Shield Remote...")
        print("Everything Remote hardware - 21 buttons")
        print("Keyboard + Consumer Control HID")
        self.set_led(COLOR_RED)  # Initializing

        # Start BLE services
        self.kb.start()
        time.sleep_ms(100)

        # Mark BLE as ready and start advertising
        self._ble_ready = True
        self.kb.start_advertising()
        self.set_led(COLOR_BLUE)
        print("Ready - BLE advertising as 'Shield Remote'")

        # Main loop
        while True:
            self._handle_buttons()
            time.sleep_ms(10)  # 10ms poll interval


def main():
    """Entry point with error handling."""
    led = None
    try:
        try:
            led = NeoPixel(Pin(LED_PIN, Pin.OUT), 1)
        except Exception:
            pass
        remote = ShieldRemote()
        remote.run()
    except Exception as e:
        print("Error:", e)
        sys.print_exception(e)
        if led:
            led[0] = COLOR_RED
            led.write()
        while True:
            time.sleep_ms(1000)


def test():
    """Run button test mode."""
    remote = ShieldRemote()
    remote.test_buttons()


if __name__ == "__main__":
    main()
