# Something Remote - BLE HID Remote for Nvidia Shield + Home Assistant
# Everything Remote hardware layout (21 buttons)
# https://www.thestockpot.net/videos/theeverythingremote

from machine import Pin, ADC, lightsleep, deepsleep
import machine
import esp32
import time
import sys
from neopixel import NeoPixel
from hid_services import Keyboard
from config import config
from ha_client import ha_client
from logger import log

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
PIN_SHORTCUT_2 = 35   # Shared with battery ADC (LOLIN voltage divider)
PIN_BATTERY = 35      # Same as SHORTCUT_2 - dual use

# Status LED (directly on GPIO, optional external NeoPixel)
LED_PIN = 21          # Or use onboard LED if available

# RTC GPIO pins that can wake from deep sleep
# These are the button pins that are also RTC-capable
WAKE_PINS = [
    PIN_POWER,      # GPIO0
    PIN_BACK,       # GPIO2
    PIN_HOME,       # GPIO4
    PIN_VOL_UP,     # GPIO12
    PIN_MUTE,       # GPIO13
    PIN_CH_UP,      # GPIO14
    PIN_VOL_DOWN,   # GPIO15
    PIN_DOWN,       # GPIO25
    PIN_BRIGHT_DOWN,# GPIO26
    PIN_BRIGHT_UP,  # GPIO27
    PIN_SHORTCUT_3, # GPIO32
    PIN_SHORTCUT_4, # GPIO33
    PIN_SHORTCUT_1, # GPIO34
]

# Power management settings
IDLE_TIMEOUT_CONNECTED_MS = 30 * 60 * 1000  # 30 minutes when connected
IDLE_TIMEOUT_DISCONNECTED_MS = 2 * 60 * 1000  # 2 minutes when not connected
LIGHT_SLEEP_MS = 50               # Light sleep interval between polls
DEEP_SLEEP_AFTER_MS = 3 * 60 * 60 * 1000  # 3 hours of light sleep before deep sleep

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

# LED colors (accent LED if present, GRB format)
COLOR_OFF = (0, 0, 0)
COLOR_BLUE = (0, 0, 32)       # BLE Advertising
COLOR_GREEN = (32, 0, 0)      # BLE Connected
COLOR_WHITE = (32, 32, 32)    # Button pressed
COLOR_RED = (0, 32, 0)        # Error
COLOR_PURPLE = (0, 16, 32)    # HA activity (WiFi/MQTT)
COLOR_YELLOW = (32, 32, 0)    # Setup portal

# Button type constants
TYPE_KEY = 0      # Keyboard HID
TYPE_CONSUMER = 1 # Consumer Control HID
TYPE_HA = 2       # Home Assistant (MQTT)

# BLE HID Button definitions: (pin, code, name, has_pullup, type)
# These buttons control the Shield via BLE
BLE_BUTTONS = [
    # Navigation - Keyboard HID
    (PIN_UP, KEY_UP, "Up", True, TYPE_KEY),
    (PIN_DOWN, KEY_DOWN, "Down", True, TYPE_KEY),
    (PIN_LEFT, KEY_LEFT, "Left", True, TYPE_KEY),
    (PIN_RIGHT, KEY_RIGHT, "Right", True, TYPE_KEY),
    (PIN_SELECT, KEY_ENTER, "Select", True, TYPE_KEY),

    # Navigation - Consumer Control (proper Shield codes)
    (PIN_BACK, CC_BACK, "Back", True, TYPE_CONSUMER),
    (PIN_HOME, CC_HOME, "Home", True, TYPE_CONSUMER),

    # Media - Consumer Control
    (PIN_PLAY_PAUSE, CC_PLAY_PAUSE, "Play/Pause", True, TYPE_CONSUMER),
    (PIN_VOL_UP, CC_VOL_UP, "Vol+", True, TYPE_CONSUMER),
    (PIN_VOL_DOWN, CC_VOL_DOWN, "Vol-", True, TYPE_CONSUMER),
    (PIN_MUTE, CC_MUTE, "Mute", True, TYPE_CONSUMER),

    # Channels - Keyboard HID (Page Up/Down)
    (PIN_CH_UP, KEY_PAGE_UP, "Ch+", True, TYPE_KEY),
    (PIN_CH_DOWN, KEY_PAGE_DOWN, "Ch-", True, TYPE_KEY),

    # Settings - Keyboard HID
    (PIN_SETTINGS, KEY_F5, "Settings", True, TYPE_KEY),
]

# Home Assistant Button definitions: (pin, ha_action, name, has_pullup, is_adc)
# These buttons send MQTT messages to Home Assistant
HA_BUTTONS = [
    (PIN_POWER, "power", "Power", True, False),  # Power via HA (works when Shield is off)
    (PIN_SHORTCUT_1, "shortcut_1", "Shortcut1", False, False),
    (PIN_SHORTCUT_2, "shortcut_2", "Shortcut2", False, True),  # ADC-based (shared with battery)
    (PIN_SHORTCUT_3, "shortcut_3", "Shortcut3", True, False),
    (PIN_SHORTCUT_4, "shortcut_4", "Shortcut4", True, False),
    (PIN_BRIGHT_UP, "brightness_up", "Bright+", True, False),
    (PIN_BRIGHT_DOWN, "brightness_down", "Bright-", True, False),
]

# ADC threshold for button press detection on GPIO35
# When button pressed, ADC reads near 0. When not pressed, reads battery voltage.
ADC_BUTTON_THRESHOLD = 500  # Below this = button pressed


class ShieldRemote:
    """BLE HID remote control for Nvidia Shield + Home Assistant."""

    def __init__(self, name="Something Remote"):
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

        # Initialize BLE buttons
        self.ble_buttons = []
        self.ble_button_states = []
        for pin_num, code, name, has_pullup, btn_type in BLE_BUTTONS:
            if has_pullup:
                btn = Pin(pin_num, Pin.IN, Pin.PULL_UP)
            else:
                btn = Pin(pin_num, Pin.IN)
            self.ble_buttons.append((btn, code, name, btn_type))
            self.ble_button_states.append(1)  # Initial state (not pressed)

        # Initialize HA buttons
        self.ha_buttons = []
        self.ha_button_states = []
        for pin_num, action, name, has_pullup, is_adc in HA_BUTTONS:
            if is_adc:
                # ADC-based button (GPIO35)
                btn = ADC(Pin(pin_num))
                btn.atten(ADC.ATTN_11DB)
            elif has_pullup:
                btn = Pin(pin_num, Pin.IN, Pin.PULL_UP)
            else:
                btn = Pin(pin_num, Pin.IN)
            self.ha_buttons.append((btn, action, name, is_adc))
            self.ha_button_states.append(1)  # Initial state (not pressed)

        # State tracking
        self._connected = False
        self._last_press_time = 0
        self._debounce_ms = 50
        self._any_pressed = False
        self._active_type = None  # Track which report type is active

        # Battery monitoring (LOLIN boards have 100k/100k divider on GPIO35)
        self._battery_adc = ADC(Pin(PIN_BATTERY))
        self._battery_adc.atten(ADC.ATTN_11DB)  # Full range 0-3.3V
        self._last_battery_update = 0
        self._battery_update_interval = 60000  # Update every 60 seconds

        # Power management
        self._last_activity = time.ticks_ms()
        self._setup_wake_pins()

        # Advertising check - be aggressive about staying visible
        self._last_adv_check = 0
        self._adv_check_interval = 5000  # Check every 5 seconds
        self._adv_restart_count = 0  # Track how many times we've restarted advertising

        # BLE forget combo (Power + Back held for 5 seconds)
        self._forget_combo_start = 0
        self._forget_combo_duration = 5000  # 5 seconds

        # Setup portal combo (Shortcut1 + Shortcut3 held for 5 seconds)
        self._setup_combo_start = 0
        self._setup_combo_duration = 5000  # 5 seconds

        # Light sleep tracking (for transition to deep sleep)
        self._light_sleep_start = 0  # When we first entered light sleep mode

    def _setup_wake_pins(self):
        """Configure GPIO pins for light sleep wake (any button)."""
        self._wake_pin_objects = []
        for pin_num in WAKE_PINS:
            pin = Pin(pin_num, Pin.IN, Pin.PULL_UP)
            # Enable wake from light sleep on falling edge (button press)
            pin.irq(trigger=Pin.IRQ_FALLING, wake=machine.SLEEP)
            self._wake_pin_objects.append(pin)
        log(f"Configured {len(self._wake_pin_objects)} wake pins")

    def _enter_light_sleep(self):
        """Enter light sleep mode, wake on ANY button press."""
        # Track when we first started light sleeping
        now = time.ticks_ms()
        if self._light_sleep_start == 0:
            self._light_sleep_start = now
            log("LIGHT SLEEP - first entry, any button wakes")

        # Check if we've been in light sleep mode too long -> deep sleep
        light_sleep_duration = time.ticks_diff(now, self._light_sleep_start)
        if light_sleep_duration >= DEEP_SLEEP_AFTER_MS:
            self._enter_deep_sleep()
            return

        self.set_led(COLOR_OFF)

        # Use light sleep - can wake on any GPIO interrupt
        # Wake pins already configured with IRQ in _setup_wake_pins()
        lightsleep()

        # Woke up! Log and reset activity timer
        log("WOKE UP from light sleep")
        self._reset_activity()
        # Don't reset _light_sleep_start - we're still in "sleep mode" until real activity
        if self._connected:
            self.set_led(COLOR_GREEN)
        else:
            self.set_led(COLOR_BLUE)

    def _enter_deep_sleep(self):
        """Enter deep sleep mode, wake on POWER button only."""
        log("DEEP SLEEP - entering after 3h light sleep, POWER button wakes")
        self.set_led(COLOR_OFF)

        # Use ext0 wake on single pin (POWER button = GPIO0)
        # ext0 level: 0 = wake on LOW, 1 = wake on HIGH
        wake_pin = Pin(PIN_POWER, Pin.IN, Pin.PULL_UP)
        esp32.wake_on_ext0(wake_pin, 0)

        deepsleep()

    def _check_idle_timeout(self):
        """Check if we should enter deep sleep due to inactivity."""
        now = time.ticks_ms()
        idle_time = time.ticks_diff(now, self._last_activity)

        # Use shorter timeout when not connected
        if self._connected:
            timeout = IDLE_TIMEOUT_CONNECTED_MS
        else:
            timeout = IDLE_TIMEOUT_DISCONNECTED_MS

        if idle_time >= timeout:
            log(f"Idle timeout: {idle_time}ms, entering light sleep")
            self._enter_light_sleep()

    def _reset_activity(self, from_button=False):
        """Reset the idle timer on activity."""
        self._last_activity = time.ticks_ms()
        # Reset light sleep tracker on real button activity
        if from_button and self._light_sleep_start != 0:
            log("Activity detected, resetting sleep timer")
            self._light_sleep_start = 0

    def _ensure_advertising(self):
        """Make sure we're advertising if not connected - be aggressive."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_adv_check) >= self._adv_check_interval:
            self._last_adv_check = now
            if not self._connected and self._ble_ready:
                # Always restart advertising to stay visible to Shield
                # Shield may need to see fresh advertising after it wakes from standby
                self._adv_restart_count += 1
                try:
                    # Stop and restart to refresh advertising data
                    self.kb.stop_advertising()
                    time.sleep_ms(100)
                    self.kb.start_advertising()
                    if self._adv_restart_count <= 3 or self._adv_restart_count % 10 == 0:
                        log(f"Advertising refresh #{self._adv_restart_count}")
                    self.set_led(COLOR_BLUE)
                except Exception as e:
                    log(f"Advertising error: {e}")

    def _check_forget_combo(self):
        """Check if Power + Back held for 5 seconds to forget BLE bonds."""
        # Get Power (GPIO0) and Back (GPIO2) button states
        power_pressed = Pin(PIN_POWER, Pin.IN, Pin.PULL_UP).value() == 0
        back_pressed = Pin(PIN_BACK, Pin.IN, Pin.PULL_UP).value() == 0

        now = time.ticks_ms()

        if power_pressed and back_pressed:
            if self._forget_combo_start == 0:
                self._forget_combo_start = now
                print("Hold Power + Back for 5s to forget BLE...")
            elif time.ticks_diff(now, self._forget_combo_start) >= self._forget_combo_duration:
                self._perform_ble_forget()
                self._forget_combo_start = 0
        else:
            if self._forget_combo_start != 0:
                print("Cancelled")
            self._forget_combo_start = 0

    def _perform_ble_forget(self):
        """Clear BLE bonds and restart advertising."""
        log("BLE FORGET - clearing bonds")
        self.set_led(COLOR_RED)

        # Clear stored keys
        self.kb.secrets.clear_secrets()
        self.kb.secrets.save_secrets()

        # Disconnect if connected
        if self._connected:
            self.kb.stop()
            time.sleep_ms(500)
            self.kb.start()
            self._connected = False

        # Restart advertising
        self._ble_ready = True
        self.kb.start_advertising()
        self.set_led(COLOR_BLUE)
        print("BLE reset - ready to pair")

    def _check_setup_combo(self):
        """Check if Shortcut1 + Shortcut3 held for 5 seconds to enter setup."""
        # Get Shortcut1 (GPIO34) and Shortcut3 (GPIO32) button states
        s1_pressed = Pin(PIN_SHORTCUT_1, Pin.IN).value() == 0
        s3_pressed = Pin(PIN_SHORTCUT_3, Pin.IN, Pin.PULL_UP).value() == 0

        now = time.ticks_ms()

        if s1_pressed and s3_pressed:
            if self._setup_combo_start == 0:
                self._setup_combo_start = now
                print("Hold Shortcut1 + Shortcut3 for 5s for setup...")
            elif time.ticks_diff(now, self._setup_combo_start) >= self._setup_combo_duration:
                self._enter_setup_portal()
                self._setup_combo_start = 0
        else:
            if self._setup_combo_start != 0:
                print("Cancelled")
            self._setup_combo_start = 0

    def _enter_setup_portal(self):
        """Enter WiFi/MQTT setup portal."""
        print("Entering setup portal...")
        self.set_led(COLOR_YELLOW)

        try:
            # Stop BLE
            if self._ble_ready:
                self.kb.stop()
                self._ble_ready = False

            # Run setup portal
            from wifi_setup import run_setup_portal
            run_setup_portal()  # This will reset when done
        except Exception as e:
            print(f"Setup portal error: {e}")
            sys.print_exception(e)
            self.set_led(COLOR_RED)
            time.sleep(3)
            import machine
            machine.reset()

    def _handle_ha_buttons(self):
        """Handle Home Assistant button presses."""
        now = time.ticks_ms()

        # Debounce check
        if time.ticks_diff(now, self._last_press_time) < self._debounce_ms:
            return

        for i, (btn, action, name, is_adc) in enumerate(self.ha_buttons):
            # Read button state
            if is_adc:
                # ADC-based button - pressed when ADC reads near 0
                raw = btn.read()
                state = 0 if raw < ADC_BUTTON_THRESHOLD else 1
            else:
                state = btn.value()

            if state != self.ha_button_states[i]:
                self._last_press_time = now
                self.ha_button_states[i] = state
                if state == 0:  # Pressed
                    self.set_led(COLOR_PURPLE)
                    self._send_ha_button(action, name)
                    self._any_pressed = True
                    self._reset_activity(from_button=True)

    def _send_ha_button(self, action, name):
        """Send button press to Home Assistant."""
        log(f"HA button: {name}")
        if ha_client.is_configured:
            ha_client.send_button(action)
            # Also send battery if due
            percent, voltage = self._read_battery()
            ha_client.send_battery(percent, voltage)
        else:
            log("HA not configured - hold Shortcut1+3 for setup")

    def set_led(self, color):
        """Set LED color (GRB tuple)."""
        if self.led:
            self.led[0] = color
            self.led.write()

    def _read_battery(self):
        """Read battery voltage and return percentage (0-100)."""
        raw = self._battery_adc.read()
        # LOLIN has 100k/100k divider, so multiply by 2
        voltage = (raw / 4095) * 3.3 * 2

        # LiPo voltage to percentage (approximate)
        # 4.2V = 100%, 3.2V = 0%
        if voltage >= 4.2:
            percent = 100
        elif voltage <= 3.2:
            percent = 0
        else:
            percent = int((voltage - 3.2) / 1.0 * 100)

        return percent, voltage

    def _update_battery(self):
        """Update battery level if interval has passed."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_battery_update) >= self._battery_update_interval:
            self._last_battery_update = now
            percent, voltage = self._read_battery()
            self.kb.set_battery_level(percent)
            if self._connected:
                self.kb.notify_battery_level()
            log(f"Battery: {percent}% ({voltage:.2f}V)")

    def _on_state_change(self):
        """Handle BLE state changes."""
        state = self.kb.get_state()
        was_connected = self._connected

        if state == Keyboard.DEVICE_CONNECTED:
            self._connected = True
            self._adv_restart_count = 0  # Reset counter on successful connection
            self.set_led(COLOR_GREEN)
            log("BLE: Shield connected!")
        elif state == Keyboard.DEVICE_ADVERTISING:
            self._connected = False
            self.set_led(COLOR_BLUE)
            if was_connected:
                log("BLE: Disconnected, now advertising (Shield turned off?)")
            else:
                log("BLE: Advertising")
        elif state == Keyboard.DEVICE_IDLE:
            self._connected = False
            self.set_led(COLOR_BLUE)
            if was_connected:
                log("BLE: Connection lost, restarting advertising")
            else:
                log("BLE: Idle, restarting advertising")
            if self._ble_ready:
                try:
                    self.kb.start_advertising()
                except Exception as e:
                    log(f"BLE: Failed to start advertising: {e}")
        else:
            self._connected = False
            self.set_led(COLOR_OFF)
            log(f"BLE: Unknown state {state}")

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

    def _handle_ble_buttons(self):
        """Handle BLE HID button inputs."""
        now = time.ticks_ms()

        # Debounce check
        if time.ticks_diff(now, self._last_press_time) < self._debounce_ms:
            return

        # Check each BLE button
        for i, (btn, code, name, btn_type) in enumerate(self.ble_buttons):
            state = btn.value()
            if state != self.ble_button_states[i]:
                self._last_press_time = now
                self.ble_button_states[i] = state
                if state == 0:  # Pressed (active LOW)
                    self.set_led(COLOR_WHITE)
                    self._send_key(code, name, btn_type)
                    self._any_pressed = True
                    self._reset_activity(from_button=True)
                else:  # Released
                    self._release_keys()

        # Check if any BLE button is currently pressed
        any_ble_pressed = any(btn.value() == 0 for btn, _, _, _ in self.ble_buttons)

        # Check if any HA button is pressed (including ADC-based)
        any_ha_pressed = False
        for btn, _, _, is_adc in self.ha_buttons:
            if is_adc:
                if btn.read() < ADC_BUTTON_THRESHOLD:
                    any_ha_pressed = True
                    break
            elif btn.value() == 0:
                any_ha_pressed = True
                break

        # Reset LED if no buttons pressed
        if not (any_ble_pressed or any_ha_pressed) and self._any_pressed:
            self._any_pressed = False
            if self._connected:
                self.set_led(COLOR_GREEN)
            else:
                self.set_led(COLOR_BLUE)

    def test_buttons(self):
        """Interactive button test mode."""
        print("Button Test Mode - Everything Remote")
        print("Press each button to test. Ctrl+C to exit.")
        print(f"BLE: {len(self.ble_buttons)}, HA: {len(self.ha_buttons)}")
        try:
            while True:
                # Test BLE buttons
                for i, (btn, code, name, btn_type) in enumerate(self.ble_buttons):
                    if btn.value() == 0:
                        type_str = "Consumer" if btn_type == TYPE_CONSUMER else "Keyboard"
                        print(f"BLE: {name} (0x{code:02X}, {type_str})")
                        self.set_led(COLOR_WHITE)
                        while btn.value() == 0:
                            time.sleep_ms(10)
                        self.set_led(COLOR_OFF)

                # Test HA buttons
                for i, (btn, action, name, is_adc) in enumerate(self.ha_buttons):
                    if is_adc:
                        if btn.read() < ADC_BUTTON_THRESHOLD:
                            print(f"HA: {name} ({action}, ADC)")
                            self.set_led(COLOR_PURPLE)
                            while btn.read() < ADC_BUTTON_THRESHOLD:
                                time.sleep_ms(10)
                            self.set_led(COLOR_OFF)
                    elif btn.value() == 0:
                        print(f"HA: {name} ({action})")
                        self.set_led(COLOR_PURPLE)
                        while btn.value() == 0:
                            time.sleep_ms(10)
                        self.set_led(COLOR_OFF)

                time.sleep_ms(10)
        except KeyboardInterrupt:
            print("\nTest ended")

    def run(self):
        """Main loop - start BLE and handle button input."""
        log("Starting Something Remote")
        log(f"BLE buttons: {len(BLE_BUTTONS)}, HA buttons: {len(HA_BUTTONS)}")
        log(f"Power: light sleep {LIGHT_SLEEP_MS}ms, deep sleep {IDLE_TIMEOUT_DISCONNECTED_MS // 60000}m/{IDLE_TIMEOUT_CONNECTED_MS // 60000}m")
        self.set_led(COLOR_RED)  # Initializing

        # Check wake reason
        wake_reason = machine.wake_reason() if hasattr(machine, 'wake_reason') else 0
        log(f"Wake reason: {wake_reason}")

        # Load config
        config.load()
        if config.is_configured:
            log(f"HA configured: {config.mqtt_host}")
        else:
            log("HA not configured - entering setup")
            self._enter_setup_portal()
            return  # Won't reach here, portal resets

        # Start BLE services
        log("Starting BLE services")
        self.kb.start()
        time.sleep_ms(100)

        # Mark BLE as ready and start advertising
        self._ble_ready = True
        self.kb.start_advertising()
        self.set_led(COLOR_BLUE)
        log("Ready - BLE advertising as 'Something Remote'")

        # Initial battery reading
        percent, voltage = self._read_battery()
        self.kb.set_battery_level(percent)
        log(f"Battery: {percent}% ({voltage:.2f}V)")

        # Main loop with power management
        log("Entering main loop")
        loop_count = 0
        error_count = 0
        while True:
            try:
                if loop_count < 3:
                    log(f"Loop {loop_count}: ble_buttons")
                self._handle_ble_buttons()
                if loop_count < 3:
                    log(f"Loop {loop_count}: ha_buttons")
                self._handle_ha_buttons()
                if loop_count < 3:
                    log(f"Loop {loop_count}: forget_combo")
                self._check_forget_combo()
                if loop_count < 3:
                    log(f"Loop {loop_count}: setup_combo")
                self._check_setup_combo()
                if loop_count < 3:
                    log(f"Loop {loop_count}: battery")
                self._update_battery()
                if loop_count < 3:
                    log(f"Loop {loop_count}: advertising")
                self._ensure_advertising()
                if loop_count < 3:
                    log(f"Loop {loop_count}: idle_timeout")
                self._check_idle_timeout()
                if loop_count < 3:
                    log(f"Loop {loop_count}: ha_idle")
                ha_client.check_idle_timeout()

                if loop_count < 3:
                    log(f"Loop {loop_count}: sleep")
                time.sleep_ms(LIGHT_SLEEP_MS)
                loop_count += 1
                error_count = 0  # Reset on successful loop

            except Exception as e:
                error_count += 1
                log(f"Loop error #{error_count}: {type(e).__name__}: {e}")
                if error_count >= 5:
                    log("Too many errors, restarting...")
                    raise  # Let main() handle it
                time.sleep_ms(100)


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
    except MemoryError as e:
        log(f"FATAL: MemoryError - {e}")
        sys.print_exception(e)
        # Try to restart after memory error
        time.sleep(3)
        machine.reset()
    except Exception as e:
        # Log full exception details
        log(f"FATAL ERROR: {type(e).__name__}: {e}")
        try:
            import io
            buf = io.StringIO()
            sys.print_exception(e, buf)
            log(f"Traceback: {buf.getvalue()}")
        except:
            pass
        sys.print_exception(e)
        if led:
            led[0] = COLOR_RED
            led.write()
        # Wait then restart
        time.sleep(5)
        machine.reset()


def test():
    """Run button test mode."""
    remote = ShieldRemote()
    remote.test_buttons()


if __name__ == "__main__":
    main()
