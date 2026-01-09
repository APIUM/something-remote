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

# HID key codes (USB HID Keyboard Usage Tables)
KEY_UP = 0x52
KEY_DOWN = 0x51
KEY_LEFT = 0x50
KEY_RIGHT = 0x4F
KEY_ENTER = 0x28      # Select
KEY_ESCAPE = 0x29     # Back
KEY_HOME = 0x4A       # Home
KEY_POWER = 0x66      # Power
KEY_SPACE = 0x2C      # Play/Pause (space often works)
KEY_PAGE_UP = 0x4B    # Channel Up
KEY_PAGE_DOWN = 0x4E  # Channel Down
KEY_F1 = 0x3A         # Shortcut 1
KEY_F2 = 0x3B         # Shortcut 2
KEY_F3 = 0x3C         # Shortcut 3
KEY_F4 = 0x3D         # Shortcut 4
KEY_F5 = 0x3E         # Settings
KEY_F6 = 0x3F         # Mute (mapped to F6, needs Consumer HID for real mute)
KEY_F7 = 0x40         # Brightness Down
KEY_F8 = 0x41         # Brightness Up
KEY_VOL_UP = 0x80     # Volume Up (may need Consumer HID)
KEY_VOL_DOWN = 0x81   # Volume Down (may need Consumer HID)

# LED colors (accent LED if present)
COLOR_OFF = (0, 0, 0)
COLOR_BLUE = (0, 0, 32)       # Advertising
COLOR_GREEN = (32, 0, 0)      # Connected (GRB)
COLOR_WHITE = (32, 32, 32)    # Button pressed
COLOR_RED = (0, 32, 0)        # Error (GRB)

# Button definitions: (pin, key_code, name, has_pullup)
# GPIO 34/35 are input-only with no internal pull-up
BUTTONS = [
    (PIN_UP, KEY_UP, "Up", True),
    (PIN_DOWN, KEY_DOWN, "Down", True),
    (PIN_LEFT, KEY_LEFT, "Left", True),
    (PIN_RIGHT, KEY_RIGHT, "Right", True),
    (PIN_SELECT, KEY_ENTER, "Select", True),
    (PIN_BACK, KEY_ESCAPE, "Back", True),
    (PIN_HOME, KEY_HOME, "Home", True),
    (PIN_POWER, KEY_POWER, "Power", True),
    (PIN_PLAY_PAUSE, KEY_SPACE, "Play/Pause", True),
    (PIN_VOL_UP, KEY_VOL_UP, "Vol+", True),
    (PIN_VOL_DOWN, KEY_VOL_DOWN, "Vol-", True),
    (PIN_MUTE, KEY_F6, "Mute", True),
    (PIN_CH_UP, KEY_PAGE_UP, "Ch+", True),
    (PIN_CH_DOWN, KEY_PAGE_DOWN, "Ch-", True),
    (PIN_SETTINGS, KEY_F5, "Settings", True),
    (PIN_BRIGHT_UP, KEY_F8, "Bright+", True),
    (PIN_BRIGHT_DOWN, KEY_F7, "Bright-", True),
    (PIN_SHORTCUT_1, KEY_F1, "Shortcut1", False),  # No internal pull-up
    (PIN_SHORTCUT_2, KEY_F2, "Shortcut2", False),  # No internal pull-up
    (PIN_SHORTCUT_3, KEY_F3, "Shortcut3", True),
    (PIN_SHORTCUT_4, KEY_F4, "Shortcut4", True),
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
        for pin_num, key_code, name, has_pullup in BUTTONS:
            if has_pullup:
                btn = Pin(pin_num, Pin.IN, Pin.PULL_UP)
            else:
                # GPIO 34/35 need external pull-up resistor
                btn = Pin(pin_num, Pin.IN)
            self.buttons.append((btn, key_code, name))
            self.button_states.append(1)  # Initial state (not pressed)

        # State tracking
        self._connected = False
        self._last_press_time = 0
        self._debounce_ms = 50
        self._any_pressed = False

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

    def _handle_buttons(self):
        """Handle all button inputs."""
        now = time.ticks_ms()

        # Debounce check
        if time.ticks_diff(now, self._last_press_time) < self._debounce_ms:
            return

        # Check each button
        for i, (btn, key_code, name) in enumerate(self.buttons):
            state = btn.value()
            if state != self.button_states[i]:
                self._last_press_time = now
                self.button_states[i] = state
                if state == 0:  # Pressed (active LOW)
                    self.set_led(COLOR_WHITE)
                    self._send_key(key_code, name)
                    self._any_pressed = True
                else:  # Released
                    self._release_keys()

        # Check if any button is currently pressed
        any_currently_pressed = any(btn.value() == 0 for btn, _, _ in self.buttons)

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
                for i, (btn, key_code, name) in enumerate(self.buttons):
                    if btn.value() == 0:
                        print(f"{name} (GPIO{BUTTONS[i][0]}, 0x{key_code:02X})")
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
