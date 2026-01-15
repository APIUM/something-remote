# MPU6050 Motion Wake Driver
# Configures MPU6050 to trigger INT pin HIGH on motion for ESP32 wake

from machine import I2C, Pin
import time

# MPU6050 I2C address
MPU6050_ADDR = 0x68

# Registers
REG_PWR_MGMT_1 = 0x6B
REG_PWR_MGMT_2 = 0x6C
REG_INT_PIN_CFG = 0x37
REG_INT_ENABLE = 0x38
REG_MOT_THR = 0x1F  # Motion detection threshold
REG_MOT_DUR = 0x20  # Motion detection duration
REG_ACCEL_CONFIG = 0x1C
REG_MOT_DETECT_CTRL = 0x69
REG_WHO_AM_I = 0x75


class MPU6050Wake:
    """MPU6050 configured for motion-triggered wake."""

    def __init__(self, sda_pin=33, scl_pin=22, int_pin=36):
        # Note: GPIO33 used for SDA (sacrificing Shortcut4 button)
        # GPIO21 is not exposed on the Everything Remote ESP32 board
        self.int_pin = int_pin
        self._i2c = None
        self._initialized = False
        self.sda_pin = sda_pin
        self.scl_pin = scl_pin

    def init(self):
        """Initialize MPU6050 for motion detection, then release I2C pins."""
        try:
            # Initialize I2C
            self._i2c = I2C(0, sda=Pin(self.sda_pin), scl=Pin(self.scl_pin), freq=400000)

            # Check if MPU6050 is present
            devices = self._i2c.scan()
            if MPU6050_ADDR not in devices:
                print(f"MPU6050 not found at 0x{MPU6050_ADDR:02X}, found: {[hex(d) for d in devices]}")
                self._release_i2c_pins()
                return False

            # Verify WHO_AM_I register (should be 0x68)
            who = self._read_byte(REG_WHO_AM_I)
            if who != 0x68:
                print(f"MPU6050 WHO_AM_I mismatch: got 0x{who:02X}, expected 0x68")
                # Some clones return different values, continue anyway

            # Wake up MPU6050 (clear sleep bit)
            self._write_byte(REG_PWR_MGMT_1, 0x00)
            time.sleep_ms(100)

            # Configure for low power motion detection
            self._configure_motion_detect()

            self._initialized = True
            print("MPU6050 initialized for motion wake")

            # Release I2C pins so they can be used for buttons
            self._release_i2c_pins()
            print("I2C pins released - Shortcut4 button available")

            return True

        except Exception as e:
            print(f"MPU6050 init error: {e}")
            self._release_i2c_pins()
            return False

    def _release_i2c_pins(self):
        """Release I2C pins so SDA pin can be used as button."""
        try:
            if self._i2c:
                self._i2c.deinit()
                self._i2c = None
            # Reconfigure SDA pin as input with pull-up (for button use)
            Pin(self.sda_pin, Pin.IN, Pin.PULL_UP)
        except:
            pass

    def _write_byte(self, reg, value):
        """Write a byte to a register."""
        self._i2c.writeto_mem(MPU6050_ADDR, reg, bytes([value]))

    def _read_byte(self, reg):
        """Read a byte from a register."""
        return self._i2c.readfrom_mem(MPU6050_ADDR, reg, 1)[0]

    def _configure_motion_detect(self):
        """Configure motion detection with INT pin HIGH on motion."""
        # Configure accelerometer with High-Pass Filter enabled
        # HPF is CRITICAL for motion detection to work
        # Bits [2:0] = ACCEL_HPF: 001 = 5Hz cutoff
        self._write_byte(REG_ACCEL_CONFIG, 0x01)

        # Set motion detection threshold (1-255, lower = more sensitive)
        # Each LSB = 2mg at ±2g scale
        # 20 = ~40mg threshold - sensitive enough for pickup, ignores small vibrations
        self._write_byte(REG_MOT_THR, 20)

        # Set motion detection duration (1-255 ms)
        self._write_byte(REG_MOT_DUR, 1)

        # Configure motion detect control
        # 0x15 = proper decrement and delay settings for motion detection
        self._write_byte(REG_MOT_DETECT_CTRL, 0x15)

        # Configure INT pin:
        # Bit 7: INT_LEVEL = 0 (active HIGH)
        # Bit 6: INT_OPEN = 0 (push-pull)
        # Bit 5: LATCH_INT_EN = 1 (latched - stays HIGH until status read)
        # Bit 4: INT_RD_CLEAR = 1 (clear INT on any read)
        # Latched mode is required for deep sleep wake
        self._write_byte(REG_INT_PIN_CFG, 0x30)

        # Enable motion detection interrupt
        self._write_byte(REG_INT_ENABLE, 0x40)  # MOT_EN bit

        # Put into cycle mode for low power (~10µA vs ~3.5mA)
        # Note: cycle mode works for deep sleep wake but not for active polling
        # PWR_MGMT_1: CYCLE=1, SLEEP=0, TEMP_DIS=1
        self._write_byte(REG_PWR_MGMT_1, 0x28)

        # PWR_MGMT_2: LP_WAKE_CTRL = 01 (5Hz sample rate), disable gyro
        self._write_byte(REG_PWR_MGMT_2, 0x47)

        print("MPU6050 motion detection configured (threshold=20, HPF=5Hz, cycle mode)")

    def get_int_pin(self):
        """Get the interrupt pin object for wake configuration."""
        return Pin(self.int_pin, Pin.IN)

    @property
    def is_initialized(self):
        return self._initialized

    def check_motion(self):
        """Check if motion was detected (reads INT status)."""
        if not self._initialized:
            return False
        try:
            # Reading INT_STATUS clears the interrupt
            status = self._read_byte(0x3A)
            return (status & 0x40) != 0  # MOT_INT bit
        except:
            return False


# Singleton instance
mpu6050 = MPU6050Wake()
