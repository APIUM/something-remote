# Something Remote - BLE HID Remote for Nvidia Shield + Home Assistant
# Everything Remote hardware layout (21 buttons)
# https://www.thestockpot.net/videos/theeverythingremote

from machine import Pin, ADC, deepsleep
import machine
import esp32
import time
import sys
import asyncio
from neopixel import NeoPixel
from hid_services import Keyboard
from config import config, POWER_MODE_BLE, POWER_MODE_HA
from ha_client import ha_client
from logger import log
from mpu6050_wake import mpu6050

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
PIN_SHORTCUT_1 = 34   # Input-only, external 10k pull-up (R1 on PCB)
PIN_SHORTCUT_2 = 35   # Input-only, external 10k pull-up (R2 on PCB)
PIN_BATTERY = 39      # VN / ADC1_CH3. Hardware mod: 470k/470k divider from VBAT + 1uF cap to GND

# Accelerometer interrupt pin for motion wake
PIN_ACCEL_INT = 36    # Input-only, RTC capable for wake

# Status LED (optional - Everything Remote board has no LED)
HAS_LED = False       # Set to True if you add a NeoPixel LED
LED_PIN = 21          # GPIO for external NeoPixel if added

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
# Each wake from motion or button keeps the device at ~50mA for IDLE_TIMEOUT_MS
# before deep-sleeping again. 60s is a good balance — most sessions are longer
# than that anyway (Shield stays connected and resets the timer), but random
# motion-triggered wakes don't cost 5 minutes of awake current.
IDLE_TIMEOUT_MS = 60 * 1000              # 1 min no activity → deep sleep
SLEEP_INHIBIT_MS = 300 * 1000            # 5 min no-sleep for initial pairing
LOOP_SLEEP_MS = 50                       # 50ms polling
CPU_FREQ_ACTIVE = 160000000              # 160MHz when connected
CPU_FREQ_IDLE = 80000000                 # 80MHz when idle
BATTERY_STALE_MS = 30 * 60 * 1000        # 30 min — republish before sleep if older


# --- Wake counter (diagnostic, opt-in via config) ---------------------------
# Persists across deep sleep via RTC RAM; reset on cold boot / hard reset.
# Lets us count all wake cycles (including ones that never successfully
# publish to MQTT), which is otherwise invisible.

_WAKE_COUNT_MAGIC = 0xBEEF1234  # sentinel so we don't mistake garbage for a count


def _load_wake_count():
    """Return counter from RTC RAM, or 0 on cold boot / invalid data."""
    try:
        mem = machine.RTC().memory()
        if len(mem) >= 8:
            magic = int.from_bytes(mem[0:4], "little")
            if magic == _WAKE_COUNT_MAGIC:
                return int.from_bytes(mem[4:8], "little")
    except Exception:
        pass
    return 0


def _store_wake_count(n):
    try:
        machine.RTC().memory(
            _WAKE_COUNT_MAGIC.to_bytes(4, "little") + n.to_bytes(4, "little")
        )
    except Exception:
        pass

# LiPo discharge curve at low load (~0.2C), resting voltage.
# Sorted descending by voltage. Linear interp between points.
# Sourced from typical 1S LiPo discharge data; matches Adafruit/Sparkfun tables.
_LIPO_CURVE = (
    (4.20, 100), (4.15,  95), (4.11,  90), (4.08,  85),
    (4.02,  80), (3.98,  75), (3.95,  70), (3.91,  65),
    (3.87,  60), (3.85,  55), (3.84,  50), (3.82,  45),
    (3.80,  40), (3.79,  35), (3.77,  30), (3.75,  25),
    (3.73,  20), (3.71,  15), (3.69,  10), (3.61,   5),
    (3.27,   0),
)


def _lipo_voltage_to_percent(v):
    """Linear-interpolate state-of-charge from the LiPo discharge curve."""
    if v >= _LIPO_CURVE[0][0]:
        return 100
    if v <= _LIPO_CURVE[-1][0]:
        return 0
    for i in range(len(_LIPO_CURVE) - 1):
        v_hi, p_hi = _LIPO_CURVE[i]
        v_lo, p_lo = _LIPO_CURVE[i + 1]
        if v_lo <= v <= v_hi:
            frac = (v - v_lo) / (v_hi - v_lo)
            return int(p_lo + frac * (p_hi - p_lo))
    return 0

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

# Home Assistant Button definitions: (pin, ha_action, name, has_pullup)
# These buttons send MQTT messages to Home Assistant
# Note: Shortcut1/Shortcut2 (GPIO34/35) are input-only; R1/R2 on the PCB provide external pull-ups
# Note: Shortcut4 (GPIO33) shared with I2C SDA - I2C released after boot so button works
# Note: Power button is handled separately based on config.power_button_mode
HA_BUTTONS = [
    (PIN_SHORTCUT_1, "shortcut_1", "Shortcut1", False),
    (PIN_SHORTCUT_2, "shortcut_2", "Shortcut2", False),
    (PIN_SHORTCUT_3, "shortcut_3", "Shortcut3", True),
    (PIN_SHORTCUT_4, "shortcut_4", "Shortcut4", True),  # Shared with I2C SDA at boot
    (PIN_BRIGHT_UP, "brightness_up", "Bright+", True),
    (PIN_BRIGHT_DOWN, "brightness_down", "Bright-", True),
]


class ShieldRemote:
    """BLE HID remote control for Nvidia Shield + Home Assistant."""

    def __init__(self, name="Something Remote"):
        # Initialize LED if enabled (Everything Remote has no onboard LED)
        self.led = None
        if HAS_LED:
            try:
                self.led = NeoPixel(Pin(LED_PIN, Pin.OUT), 1)
                self.set_led(COLOR_OFF)
            except Exception:
                print("LED init failed on GPIO", LED_PIN)

        # Initialize accelerometer BEFORE button setup
        # MPU6050 uses GPIO22 (SCL) and GPIO33 (SDA) for I2C, then releases them.
        # Button init on those pins must happen after I2C is done.
        log("Initializing MPU6050 accelerometer...")
        if mpu6050.init():
            log("MPU6050 ready - motion wake enabled")
        else:
            log("MPU6050 not found - motion wake disabled")

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
        for pin_num, action, name, has_pullup in HA_BUTTONS:
            if has_pullup:
                btn = Pin(pin_num, Pin.IN, Pin.PULL_UP)
            else:
                btn = Pin(pin_num, Pin.IN)
            self.ha_buttons.append((btn, action, name))
            self.ha_button_states.append(1)  # Initial state (not pressed)

        # Power button - handled separately based on config.power_button_mode
        self._power_btn = Pin(PIN_POWER, Pin.IN, Pin.PULL_UP)
        self._power_btn_state = 1  # Initial state (not pressed)

        # State tracking
        self._connected = False
        self._last_press_time = 0
        self._debounce_ms = 50
        self._any_pressed = False
        self._active_type = None  # Track which report type is active
        self._failed_connects = 0  # Track connect-without-encryption failures

        # Wake counter (diagnostic, opt-in). Load from RTC RAM and bump.
        self._wake_counter_enabled = config.wake_counter_enabled
        self._wake_count = 0
        if self._wake_counter_enabled:
            self._wake_count = _load_wake_count() + 1
            _store_wake_count(self._wake_count)
            log(f"Wake counter: {self._wake_count}")

        # Battery monitoring — opt-in via config.battery_enabled because it
        # requires a hardware mod (470k/470k divider from VBAT to GPIO39/VN
        # plus a 1uF cap to GND). Without the mod the ADC pin is floating and
        # reporting numbers would just be noise, so we skip the whole path.
        self._battery_enabled = config.battery_enabled
        self._battery_adc = None
        self._last_battery_update = 0
        self._battery_update_interval = 60000  # Update every 60 seconds
        self._last_battery_uv = 0  # Last raw ADC reading in microvolts (for debug)
        if self._battery_enabled:
            self._battery_adc = ADC(Pin(PIN_BATTERY))
            self._battery_adc.atten(ADC.ATTN_11DB)
            log("Battery monitoring: enabled (GPIO39, 2:1 divider)")
        else:
            log("Battery monitoring: disabled (enable in setup portal if board has mod)")

        # Power management
        self._last_activity = time.ticks_ms()
        self._boot_time = time.ticks_ms()

        self._setup_wake_pins()

        # BLE forget combo (Power + Back held for 5 seconds)
        self._forget_combo_start = 0
        self._forget_combo_duration = 5000  # 5 seconds

        # Setup portal combo (Shortcut1 + Shortcut3 held for 5 seconds)
        self._setup_combo_start = 0
        self._setup_combo_duration = 5000  # 5 seconds

    def _setup_wake_pins(self):
        """Configure GPIO pins with pull-ups for button input."""
        for pin_num in WAKE_PINS:
            Pin(pin_num, Pin.IN, Pin.PULL_UP)
        log(f"Configured {len(WAKE_PINS)} wake pins")

    # --- Power management ---

    async def _enter_deep_sleep(self):
        """Enter deep sleep. Does not return."""
        log("DEEP SLEEP - entering")
        self.set_led(COLOR_OFF)

        # Publish a final battery reading if stale, then drain the outbox so
        # we don't lose it to the shutdown. Wrapped: network flake never
        # blocks sleep past the drain timeout.
        if self._battery_enabled and ha_client.is_configured:
            try:
                stale_ms = ha_client.time_since_last_battery_ms()
                if stale_ms is None or stale_ms > BATTERY_STALE_MS:
                    log("Pre-sleep battery publish (stale)")
                    self._publish_battery_forced()
                else:
                    log(f"Pre-sleep battery publish skipped ({stale_ms // 1000}s since last)")
            except Exception as e:
                log(f"Pre-sleep battery publish errored: {e}")

        # Give mqtt_as up to 3s to flush any queued publishes before teardown.
        # BaseException (not Exception) because MicroPython's CancelledError
        # is a BaseException and can bubble up from the awaited shutdown.
        try:
            await ha_client.drain(3000)
            await ha_client.stop()
        except BaseException as e:
            log(f"HA stop errored: {e}")

        # Configure wake sources BEFORE BLE shutdown
        power_pin = Pin(PIN_POWER, Pin.IN, Pin.PULL_UP)
        esp32.wake_on_ext0(power_pin, 0)
        if mpu6050.is_initialized:
            try:
                accel_int = Pin(PIN_ACCEL_INT, Pin.IN)
                esp32.wake_on_ext1([accel_int], esp32.WAKEUP_ANY_HIGH)
            except Exception:
                pass
        # Shut down BLE
        if self._ble_ready:
            try:
                if self._connected and self.kb.conn_handle is not None:
                    self.kb._ble.gap_disconnect(self.kb.conn_handle)
                    time.sleep_ms(200)
                self.kb.stop_advertising()
                time.sleep_ms(100)
                self.kb.stop()
            except Exception:
                pass
            self._ble_ready = False
            self._connected = False
        deepsleep()

    async def _check_idle_timeout(self):
        """Deep-sleep when idle timer expires (async because sleep entry is async)."""
        idle_time = time.ticks_diff(time.ticks_ms(), self._last_activity)
        if idle_time >= IDLE_TIMEOUT_MS:
            # Don't sleep if no bonds and within pairing window
            if len(self.kb.secrets.secrets) <= 1:
                since_boot = time.ticks_diff(time.ticks_ms(), self._boot_time)
                if since_boot < SLEEP_INHIBIT_MS:
                    return
            await self._enter_deep_sleep()

    def _reset_activity(self, from_button=False):
        """Reset the idle timer on activity."""
        self._last_activity = time.ticks_ms()

    def _ensure_advertising(self):
        """Ensure advertising is running when not connected."""
        if not self._connected and self._ble_ready:
            if not self.kb.adv.advertising:
                self.kb.start_advertising()

    def _check_forget_combo(self):
        """Check if Power + Back held for 5 seconds to forget BLE bonds."""
        # Get Power (GPIO0) and Back (GPIO2) button states
        power_pressed = Pin(PIN_POWER, Pin.IN, Pin.PULL_UP).value() == 0
        back_pressed = Pin(PIN_BACK, Pin.IN, Pin.PULL_UP).value() == 0

        now = time.ticks_ms()

        if power_pressed and back_pressed:
            if self._forget_combo_start == 0:
                self._forget_combo_start = now
                log("COMBO: Power+Back detected, hold for 5s...")
            else:
                elapsed = time.ticks_diff(now, self._forget_combo_start)
                # Log progress every second
                if elapsed > 0 and elapsed % 1000 < 60:
                    log(f"COMBO: holding... {elapsed//1000}s")
                if elapsed >= self._forget_combo_duration:
                    log("COMBO: Success! Triggering BLE forget")
                    self._perform_ble_forget()
                    self._forget_combo_start = 0
        else:
            if self._forget_combo_start != 0:
                elapsed = time.ticks_diff(now, self._forget_combo_start)
                log(f"COMBO: Power+Back released after {elapsed}ms")
            self._forget_combo_start = 0

    @staticmethod
    def _clear_all_bonds(kb):
        """Clear both Python keystore and NimBLE NVS bond data."""
        kb.secrets.clear_secrets()
        kb.secrets.save_secrets()
        try:
            nvs = esp32.NVS("nimble_bond")
            for prefix in ["peer_sec_", "our_sec_", "cccd_", "p_dev_rec_", "rpa_rec_"]:
                for i in range(1, 16):
                    try:
                        nvs.erase_key(prefix + str(i))
                    except Exception:
                        continue
            try:
                nvs.erase_key("local_irk")
            except Exception:
                pass
            nvs.commit()
        except Exception:
            pass

    def _perform_ble_forget(self):
        """Clear BLE bonds and reset device for clean pairing state."""
        log("BLE FORGET - clearing bonds")
        self.set_led(COLOR_RED)
        self._clear_all_bonds(self.kb)
        log("BLE FORGET - secrets cleared, resetting device")
        time.sleep_ms(500)
        machine.reset()

    def _check_setup_combo(self):
        """Check if Shortcut1 + Shortcut3 held for 5 seconds to enter setup."""
        # Get Shortcut1 (GPIO34) and Shortcut3 (GPIO32) button states
        s1_pressed = Pin(PIN_SHORTCUT_1, Pin.IN).value() == 0
        s3_pressed = Pin(PIN_SHORTCUT_3, Pin.IN, Pin.PULL_UP).value() == 0

        now = time.ticks_ms()

        if s1_pressed and s3_pressed:
            if self._setup_combo_start == 0:
                self._setup_combo_start = now
                log("COMBO: S1+S3 detected, hold for 5s for setup...")
                self.set_led(COLOR_YELLOW)  # Visual feedback
            else:
                elapsed = time.ticks_diff(now, self._setup_combo_start)
                if elapsed >= self._setup_combo_duration:
                    self._enter_setup_portal()
                    self._setup_combo_start = 0
        else:
            if self._setup_combo_start != 0:
                log("COMBO: S1+S3 cancelled")
                # Restore LED color
                if self._connected:
                    self.set_led(COLOR_GREEN)
                else:
                    self.set_led(COLOR_BLUE)
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

        for i, (btn, action, name) in enumerate(self.ha_buttons):
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
            # Also send battery if due (piggy-back, rate-limited in send_battery)
            if self._battery_enabled:
                percent, voltage = self._read_battery()
                wc = self._wake_count if self._wake_counter_enabled else None
                ha_client.send_battery(percent, voltage, self._last_battery_uv, wake_count=wc)
        else:
            log("HA not configured - hold Shortcut1+3 for setup")

    def _handle_power_button(self):
        """Handle power button based on config.power_button_mode."""
        now = time.ticks_ms()

        # Debounce check
        if time.ticks_diff(now, self._last_press_time) < self._debounce_ms:
            return

        state = self._power_btn.value()
        if state != self._power_btn_state:
            self._last_press_time = now
            self._power_btn_state = state
            if state == 0:  # Pressed
                self._reset_activity(from_button=True)
                if config.power_button_mode == POWER_MODE_BLE:
                    # Send BLE Consumer Control Power command
                    self.set_led(COLOR_WHITE)
                    self._send_key(CC_POWER, "Power", TYPE_CONSUMER)
                    self._any_pressed = True
                else:
                    # Send to Home Assistant (default)
                    self.set_led(COLOR_PURPLE)
                    self._send_ha_button("power", "Power")
                    self._any_pressed = True
            else:  # Released
                if config.power_button_mode == POWER_MODE_BLE:
                    self._release_keys()

    def set_led(self, color):
        """Set LED color (GRB tuple)."""
        if self.led:
            self.led[0] = color
            self.led.write()

    def _read_battery(self):
        """Read battery voltage and return (percent, voltage).

        Uses calibrated ADC (read_uv), median-of-N sampling to reject the
        VN/VP ADC-glitch erratum, then a LiPo discharge LUT for percent.
        Divider is 2:1 (470k/470k), so VBAT = 2 * pin voltage.
        Returns (0, 0.0) if battery monitoring is disabled.
        """
        if not self._battery_enabled:
            return 0, 0.0
        samples = []
        for _ in range(16):
            samples.append(self._battery_adc.read_uv())
        samples.sort()
        pin_uv = samples[8]  # median
        self._last_battery_uv = pin_uv

        voltage = (pin_uv / 1000000.0) * 2.0  # divider ratio
        percent = _lipo_voltage_to_percent(voltage)
        return percent, voltage

    def _update_battery(self):
        """Update battery level if interval has passed."""
        if not self._battery_enabled:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_battery_update) >= self._battery_update_interval:
            self._last_battery_update = now
            percent, voltage = self._read_battery()
            self.kb.set_battery_level(percent)
            if self._connected:
                self.kb.notify_battery_level()
            log(f"Battery: {percent}% ({voltage:.2f}V)")

    def _publish_battery_forced(self):
        """Read battery and force-publish to HA, connecting MQTT if needed.

        Used on boot/wake and (conditionally) before deep sleep. Swallows
        errors so the caller's main flow (e.g. entering deep sleep) is never
        blocked by a flaky network. No-op if battery monitoring is disabled.
        """
        if not self._battery_enabled:
            return False
        percent, voltage = self._read_battery()
        self.kb.set_battery_level(percent)
        log(f"Battery: {percent}% ({voltage:.2f}V)")
        if not ha_client.is_configured:
            return False
        wc = self._wake_count if self._wake_counter_enabled else None
        try:
            return ha_client.send_battery(
                percent, voltage, self._last_battery_uv, force=True, wake_count=wc,
            )
        except Exception as e:
            log(f"Battery force-publish failed: {e}")
            return False

    def _log_ble_state(self):
        """Log BLE events from main loop context (IRQ-safe bitmask)."""
        evts = self.kb._irq_events
        if evts == 0:
            return
        self.kb._irq_events = 0
        if evts & 1:
            log(f"BLE IRQ: Connected handle={self.kb.conn_handle}")
        if evts & 4:
            log(f"BLE IRQ: Encryption enc={self.kb.encrypted} auth={self.kb.authenticated} bonded={self.kb.bonded} key_size={self.kb.key_size}")
        if evts & 8:
            log("BLE IRQ: Passkey action")
        if evts & 16:
            log(f"BLE IRQ: Secret stored ({len(self.kb.secrets.secrets)} keys)")
        if evts & 2:
            log("BLE IRQ: Disconnected")

    def _on_state_change(self):
        """Handle BLE state changes. Called from BLE IRQ via set_state callback.
        Note: log() calls here are safe on ESP32 because NimBLE IRQs run as
        MicroPython scheduled callbacks, not true hardware interrupts."""
        state = self.kb.get_state()
        was_connected = self._connected

        if state == Keyboard.DEVICE_CONNECTED:
            self._connected = True
            self._reset_activity()
    
            machine.freq(CPU_FREQ_ACTIVE)
            self.set_led(COLOR_GREEN)
            log("BLE: Connected!")
        elif state == Keyboard.DEVICE_IDLE:
            self._connected = False
            if was_connected:
                if not self.kb._was_encrypted and len(self.kb.secrets.secrets) > 1:
                    self._failed_connects += 1
                    log(f"BLE: Connect without encryption (fail #{self._failed_connects})")
                    if self._failed_connects >= 3:
                        log("BLE: Auto-clearing stale bonds after 3 failed connects")
                        self._clear_all_bonds(self.kb)
                        time.sleep_ms(500)
                        machine.reset()
                else:
                    self._failed_connects = 0
                log("BLE: Connection lost, restarting advertising")
                machine.freq(CPU_FREQ_IDLE)
                self.set_led(COLOR_BLUE)
                if self._ble_ready:
                    try:
                        self.kb.start_fast_advertising()
                    except Exception as e:
                        log(f"BLE: Failed to start advertising: {e}")
        elif state == Keyboard.DEVICE_ADVERTISING:
            if was_connected:
                self._connected = False
                log("BLE: Disconnected, advertising for reconnection")
                machine.freq(CPU_FREQ_IDLE)
                self.set_led(COLOR_BLUE)

    def _send_key(self, code, name="", btn_type=TYPE_KEY):
        """Send a key press."""
        if self._connected:
            if btn_type == TYPE_CONSUMER:
                self.kb.set_consumer(code)
                self.kb.notify_consumer_report()
                log(f"BLE key: {name} (Consumer 0x{code:02X})")
            else:
                self.kb.set_keys(code)
                self.kb.notify_hid_report()
                log(f"BLE key: {name} (Key 0x{code:02X})")
            self._active_type = btn_type
            return True
        else:
            if name:
                log(f"BLE key: {name} - NOT CONNECTED, not sent")
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

        any_ha_pressed = any(btn.value() == 0 for btn, _, _ in self.ha_buttons)

        # Check power button
        power_pressed = self._power_btn.value() == 0

        # Reset LED if no buttons pressed
        if not (any_ble_pressed or any_ha_pressed or power_pressed) and self._any_pressed:
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
                for i, (btn, action, name) in enumerate(self.ha_buttons):
                    if btn.value() == 0:
                        print(f"HA: {name} ({action})")
                        self.set_led(COLOR_PURPLE)
                        while btn.value() == 0:
                            time.sleep_ms(10)
                        self.set_led(COLOR_OFF)

                time.sleep_ms(10)
        except KeyboardInterrupt:
            print("\nTest ended")

    async def run(self):
        """Main loop — async. Button handlers stay synchronous; they enqueue
        to ha_client which is drained by an independent mqtt_as-backed task."""
        log("Starting Something Remote")
        log(f"BLE buttons: {len(BLE_BUTTONS)}, HA buttons: {len(HA_BUTTONS)}")
        log(f"Power: {IDLE_TIMEOUT_MS // 1000}s idle → deep sleep")
        self.set_led(COLOR_RED)  # Initializing

        # Check wake reason
        wake_reason = machine.wake_reason() if hasattr(machine, 'wake_reason') else 0
        log(f"Wake reason: {wake_reason}")

        if config.is_configured:
            log(f"HA configured: {config.mqtt_host}")
            power_mode = "BLE" if config.power_button_mode == POWER_MODE_BLE else "Home Assistant"
            log(f"Power button: {power_mode}")
        else:
            log("HA not configured - entering setup")
            self._enter_setup_portal()
            return  # Won't reach here, portal resets

        # Start BLE services
        log("Starting BLE services")
        self.kb.start()
        await asyncio.sleep_ms(100)

        # Mark BLE as ready and start fast advertising for reconnection
        self._ble_ready = True
        self.kb.start_fast_advertising()

        machine.freq(CPU_FREQ_IDLE)
        self.set_led(COLOR_BLUE)
        log("Ready - BLE advertising as 'Something Remote' (30ms fast)")

        # Kick off mqtt_as (WiFi + MQTT + discovery + auto-reconnect) in the
        # background. This does not block button handling.
        if ha_client.is_configured:
            await ha_client.start()

        # Enqueue boot/wake battery publish — delivered whenever the outbox drains.
        self._publish_battery_forced()

        # Main loop
        log("Entering main loop")
        error_count = 0
        while True:
            try:
                self._log_ble_state()
                self._handle_ble_buttons()
                self._handle_ha_buttons()
                self._handle_power_button()
                self._check_forget_combo()
                self._check_setup_combo()
                self._update_battery()
                self._ensure_advertising()

                # Motion detection resets idle timer (keeps device awake when held)
                if mpu6050.is_initialized and mpu6050.check_motion():
                    self._reset_activity()

                await self._check_idle_timeout()

                await asyncio.sleep_ms(LOOP_SLEEP_MS)
                error_count = 0

            except Exception as e:
                error_count += 1
                log(f"Loop error #{error_count}: {type(e).__name__}: {e}")
                if error_count >= 5:
                    log("Too many errors, restarting...")
                    raise
                await asyncio.sleep_ms(100)


async def _async_main():
    remote = ShieldRemote()
    try:
        await remote.run()
    finally:
        # If run() exits for any reason (clean or error), make sure mqtt_as
        # and its tasks aren't left running before we reset. BaseException
        # is needed because CancelledError is a BaseException in MicroPython.
        try:
            await ha_client.stop()
        except BaseException:
            pass


def main():
    """Entry point with error handling."""
    led = None
    if HAS_LED:
        try:
            led = NeoPixel(Pin(LED_PIN, Pin.OUT), 1)
        except Exception:
            pass
    # Load config before ShieldRemote() so __init__ sees user settings (e.g. battery_enabled)
    config.load()
    try:
        asyncio.run(_async_main())
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
        except Exception:
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
