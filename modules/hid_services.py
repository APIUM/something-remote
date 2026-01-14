# MicroPython BLE HID Services
# Adapted from MicroPythonBLEHID by H. Groefsema
# https://github.com/Heerkog/MicroPythonBLEHID
# License: GPL-3.0

from micropython import const
import struct
import bluetooth
from bluetooth import UUID
import esp32
from hid_keystores import DefaultKeyStore

# BLE flags
F_READ = bluetooth.FLAG_READ
F_WRITE = bluetooth.FLAG_WRITE
F_READ_WRITE = bluetooth.FLAG_READ | bluetooth.FLAG_WRITE
F_READ_NOTIFY = bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY
F_READ_WRITE_NORESPONSE = bluetooth.FLAG_READ | bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE
F_READ_WRITE_NOTIFY_NORESPONSE = bluetooth.FLAG_READ | bluetooth.FLAG_WRITE | bluetooth.FLAG_NOTIFY | bluetooth.FLAG_WRITE_NO_RESPONSE

DSC_F_READ = const(0x02)

# Advertising types
_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID16_COMPLETE = const(0x03)
_ADV_TYPE_APPEARANCE = const(0x19)

# IRQ event codes
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_READ_REQUEST = const(4)
_IRQ_MTU_EXCHANGED = const(21)
_IRQ_CONNECTION_UPDATE = const(27)
_IRQ_ENCRYPTION_UPDATE = const(28)
_IRQ_GET_SECRET = const(29)
_IRQ_SET_SECRET = const(30)
_IRQ_PASSKEY_ACTION = const(31)

# IO capabilities
_IO_CAPABILITY_NO_INPUT_OUTPUT = const(3)

# Passkey actions
_PASSKEY_ACTION_INPUT = const(2)
_PASSKEY_ACTION_DISP = const(3)
_PASSKEY_ACTION_NUMCMP = const(4)

# GATT error codes
_GATTS_NO_ERROR = const(0x00)
_GATTS_ERROR_READ_NOT_PERMITTED = const(0x02)
_GATTS_ERROR_INVALID_HANDLE = const(0x01)
_GATTS_ERROR_INSUFFICIENT_AUTHENTICATION = const(0x05)
_GATTS_ERROR_INSUFFICIENT_AUTHORIZATION = const(0x08)
_GATTS_ERROR_INSUFFICIENT_ENCRYPTION = const(0x0f)


class Advertiser:
    """BLE advertiser for HID devices."""

    def __init__(self, ble, services=None, appearance=960, name="Generic HID"):
        self._ble = ble
        self._payload = self._advertising_payload(
            name=name,
            services=services or [UUID(0x1812)],
            appearance=appearance
        )
        self.advertising = False

    def _advertising_payload(self, name=None, services=None, appearance=0):
        payload = bytearray()

        def _append(adv_type, value):
            nonlocal payload
            payload += struct.pack("BB", len(value) + 1, adv_type) + value

        # Flags: general discoverable, BR/EDR not supported
        _append(_ADV_TYPE_FLAGS, struct.pack("B", 0x06))

        if name:
            _append(_ADV_TYPE_NAME, name.encode())

        if services:
            for uuid in services:
                b = bytes(uuid)
                if len(b) == 2:
                    _append(_ADV_TYPE_UUID16_COMPLETE, b)

        if appearance:
            _append(_ADV_TYPE_APPEARANCE, struct.pack("<H", appearance))

        return payload

    def start_advertising(self):
        if not self.advertising:
            # Advertise indefinitely (0 = no timeout) with 100ms interval
            self._ble.gap_advertise(100000, adv_data=self._payload, connectable=True)
            self.advertising = True

    def stop_advertising(self):
        if self.advertising:
            self._ble.gap_advertise(0)
            self.advertising = False


class HumanInterfaceDevice:
    """Base class for BLE HID devices."""

    DEVICE_STOPPED = const(0)
    DEVICE_IDLE = const(1)
    DEVICE_ADVERTISING = const(2)
    DEVICE_CONNECTED = const(3)

    def __init__(self, device_name="Generic HID"):
        self._ble = bluetooth.BLE()
        self.adv = None
        self.device_state = self.DEVICE_STOPPED
        self.conn_handle = None
        self.state_change_callback = None

        # Security settings
        self.io_capability = _IO_CAPABILITY_NO_INPUT_OUTPUT
        self.bond = True
        self.le_secure = True
        self.encrypted = False
        self.authenticated = False
        self.bonded = False
        self.key_size = 0
        self.passkey = 1234
        self.passkey_callback = None
        self.secrets = DefaultKeyStore()

        # Device info
        self.device_name = device_name
        self.device_appearance = 960  # Generic HID

        # Device Information Service characteristics
        self.model_number = "1"
        self.serial_number = "1"
        self.firmware_revision = "1"
        self.hardware_revision = "1"
        self.software_revision = "1"
        self.manufacture_name = "DIY"

        # PnP characteristics
        self.pnp_manufacturer_source = 0x01
        self.pnp_manufacturer_uuid = 0xFFFF
        self.pnp_product_id = 0x01
        self.pnp_product_version = 0x0100

        # Battery level
        self.battery_level = 100

        # Service definitions
        self.DIS = (
            UUID(0x180A),  # Device Information
            (
                (UUID(0x2A24), F_READ),  # Model number
                (UUID(0x2A25), F_READ),  # Serial number
                (UUID(0x2A26), F_READ),  # Firmware revision
                (UUID(0x2A27), F_READ),  # Hardware revision
                (UUID(0x2A28), F_READ),  # Software revision
                (UUID(0x2A29), F_READ),  # Manufacturer name
                (UUID(0x2A50), F_READ),  # PnP ID
            ),
        )

        self.BAS = (
            UUID(0x180F),  # Battery Service
            (
                (UUID(0x2A19), F_READ_NOTIFY, (
                    (UUID(0x2904), DSC_F_READ),
                )),
            ),
        )

        self.services = [self.DIS, self.BAS]
        self.characteristics = {}

    def ble_irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self.conn_handle, _, _ = data
            self.set_state(self.DEVICE_CONNECTED)
            print("Connected:", self.conn_handle)

        elif event == _IRQ_CENTRAL_DISCONNECT:
            self.conn_handle = None
            self.encrypted = False
            self.authenticated = False
            self.bonded = False
            self.set_state(self.DEVICE_IDLE)
            print("Disconnected")

        elif event == _IRQ_GATTS_WRITE:
            conn_handle, attr_handle = data
            value = self._ble.gatts_read(attr_handle)
            desc, _ = self.characteristics.get(attr_handle, (None, None))
            if desc:
                self.characteristics[attr_handle] = (desc, value)
            return _GATTS_NO_ERROR

        elif event == _IRQ_GATTS_READ_REQUEST:
            conn_handle, attr_handle = data
            desc, val = self.characteristics.get(attr_handle, (None, None))
            if conn_handle != self.conn_handle:
                return _GATTS_ERROR_READ_NOT_PERMITTED
            if desc is None:
                return _GATTS_ERROR_INVALID_HANDLE
            return _GATTS_NO_ERROR

        elif event == _IRQ_MTU_EXCHANGED:
            _, mtu = data
            self._ble.config(mtu=mtu)

        elif event == _IRQ_ENCRYPTION_UPDATE:
            _, self.encrypted, self.authenticated, self.bonded, self.key_size = data
            print("Encryption:", self.encrypted, "Auth:", self.authenticated, "Bonded:", self.bonded)

        elif event == _IRQ_PASSKEY_ACTION:
            conn_handle, action, passkey = data
            if action == _PASSKEY_ACTION_DISP:
                self._ble.gap_passkey(conn_handle, action, self.passkey)
            elif action == _PASSKEY_ACTION_NUMCMP:
                self._ble.gap_passkey(conn_handle, action, 1)
            elif action == _PASSKEY_ACTION_INPUT:
                pk = self.passkey_callback() if self.passkey_callback else self.passkey
                self._ble.gap_passkey(conn_handle, action, pk)

        elif event == _IRQ_SET_SECRET:
            sec_type, key, value = data
            if value is None:
                if self.secrets.has_secret(sec_type, key):
                    self.secrets.remove_secret(sec_type, key)
                    self.secrets.save_secrets()
                    return True
                return False
            self.secrets.add_secret(sec_type, key, value)
            self.secrets.save_secrets()
            return True

        elif event == _IRQ_GET_SECRET:
            sec_type, index, key = data
            return self.secrets.get_secret(sec_type, index, key)

    def start(self):
        if self.device_state == self.DEVICE_STOPPED:
            # Clear NimBLE's internal bonding state to prevent IRK conflicts
            # This ensures Python keystore is the sole source of bonding data
            # Without this, deep sleep causes "failed to configure restored IRK" errors
            try:
                nvs = esp32.NVS("nimble_bond")
                for key in ["cccd", "peer_id", "our_id", "peer_sec", "our_sec"]:
                    try:
                        nvs.erase_key(key)
                    except:
                        pass
                nvs.commit()
            except:
                pass  # Namespace may not exist on first boot

            self.secrets.load_secrets()
            self._ble.irq(self.ble_irq)
            self._ble.active(True)
            self._ble.config(gap_name=self.device_name)
            self._ble.config(mtu=23)
            self._ble.config(bond=self.bond)
            self._ble.config(le_secure=self.le_secure)
            self._ble.config(mitm=self.le_secure)
            self._ble.config(io=self.io_capability)
            self.set_state(self.DEVICE_IDLE)
            print("BLE active")

    def save_service_characteristics(self, handles):
        h_mod, h_ser, h_fwr, h_hwr, h_swr, h_man, h_pnp = handles[0]
        self.h_bat, h_bfmt = handles[1]

        def string_pack(s, n):
            return struct.pack(str(n) + "s", s.encode('UTF-8'))

        self.characteristics[h_mod] = ("Model", string_pack(self.model_number, 24))
        self.characteristics[h_ser] = ("Serial", string_pack(self.serial_number, 16))
        self.characteristics[h_fwr] = ("FW Rev", string_pack(self.firmware_revision, 8))
        self.characteristics[h_hwr] = ("HW Rev", string_pack(self.hardware_revision, 16))
        self.characteristics[h_swr] = ("SW Rev", string_pack(self.software_revision, 8))
        self.characteristics[h_man] = ("Manufacturer", string_pack(self.manufacture_name, 36))
        self.characteristics[h_pnp] = ("PnP", struct.pack(">BHHH",
            self.pnp_manufacturer_source,
            self.pnp_manufacturer_uuid,
            self.pnp_product_id,
            self.pnp_product_version))
        self.characteristics[self.h_bat] = ("Battery", struct.pack("<B", self.battery_level))
        self.characteristics[h_bfmt] = ("BatteryFmt", b'\x04\x00\xad\x27\x01\x00\x00')

    def write_service_characteristics(self):
        for handle, (_, value) in self.characteristics.items():
            self._ble.gatts_write(handle, value)

    def stop(self):
        if self.device_state != self.DEVICE_STOPPED:
            if self.adv:
                self.adv.stop_advertising()
            if self.conn_handle is not None:
                self._ble.gap_disconnect(self.conn_handle)
            self._ble.active(False)
            self.set_state(self.DEVICE_STOPPED)

    def is_connected(self):
        return self.device_state == self.DEVICE_CONNECTED

    def is_advertising(self):
        return self.device_state == self.DEVICE_ADVERTISING

    def set_state(self, state):
        self.device_state = state
        if self.state_change_callback:
            self.state_change_callback()

    def get_state(self):
        return self.device_state

    def set_state_change_callback(self, callback):
        self.state_change_callback = callback

    def start_advertising(self):
        if self.device_state not in (self.DEVICE_STOPPED, self.DEVICE_ADVERTISING):
            self.adv.start_advertising()
            self.set_state(self.DEVICE_ADVERTISING)

    def stop_advertising(self):
        if self.device_state != self.DEVICE_STOPPED and self.adv:
            self.adv.stop_advertising()
            if self.device_state != self.DEVICE_CONNECTED:
                self.set_state(self.DEVICE_IDLE)

    def set_battery_level(self, level):
        self.battery_level = max(0, min(100, level))

    def notify_battery_level(self):
        if self.is_connected():
            value = struct.pack("<B", self.battery_level)
            self.characteristics[self.h_bat] = ("Battery", value)
            self._ble.gatts_notify(self.conn_handle, self.h_bat, value)

    def notify_hid_report(self):
        pass


class Keyboard(HumanInterfaceDevice):
    """BLE HID Keyboard with Consumer Control support."""

    def __init__(self, name="BLE Keyboard"):
        super().__init__(name)
        self.device_appearance = 961  # Keyboard

        self.HIDS = (
            UUID(0x1812),  # Human Interface Device
            (
                (UUID(0x2A4A), F_READ),  # HID Information
                (UUID(0x2A4B), F_READ),  # Report Map
                (UUID(0x2A4C), F_READ_WRITE_NORESPONSE),  # Control Point
                (UUID(0x2A4D), F_READ_NOTIFY, (  # Input Report (Keyboard)
                    (UUID(0x2908), DSC_F_READ),  # Report Reference
                )),
                (UUID(0x2A4D), F_READ_WRITE_NOTIFY_NORESPONSE, (  # Output Report
                    (UUID(0x2908), DSC_F_READ),
                )),
                (UUID(0x2A4D), F_READ_NOTIFY, (  # Input Report (Consumer)
                    (UUID(0x2908), DSC_F_READ),  # Report Reference
                )),
                (UUID(0x2A4E), F_READ_WRITE_NORESPONSE),  # Protocol Mode
            ),
        )

        # HID Report Descriptor for keyboard + consumer control
        self.HID_INPUT_REPORT = bytes([
            # Keyboard Report (ID 1)
            0x05, 0x01,  # Usage Page (Generic Desktop)
            0x09, 0x06,  # Usage (Keyboard)
            0xA1, 0x01,  # Collection (Application)
            0x85, 0x01,  #   Report ID (1)
            0x75, 0x01,  #   Report Size (1)
            0x95, 0x08,  #   Report Count (8)
            0x05, 0x07,  #   Usage Page (Key Codes)
            0x19, 0xE0,  #   Usage Minimum (224)
            0x29, 0xE7,  #   Usage Maximum (231)
            0x15, 0x00,  #   Logical Minimum (0)
            0x25, 0x01,  #   Logical Maximum (1)
            0x81, 0x02,  #   Input (Data, Variable, Absolute) - Modifiers
            0x95, 0x01,  #   Report Count (1)
            0x75, 0x08,  #   Report Size (8)
            0x81, 0x01,  #   Input (Constant) - Reserved byte
            0x95, 0x05,  #   Report Count (5)
            0x75, 0x01,  #   Report Size (1)
            0x05, 0x08,  #   Usage Page (LEDs)
            0x19, 0x01,  #   Usage Minimum (1)
            0x29, 0x05,  #   Usage Maximum (5)
            0x91, 0x02,  #   Output (Data, Variable, Absolute) - LED report
            0x95, 0x01,  #   Report Count (1)
            0x75, 0x03,  #   Report Size (3)
            0x91, 0x01,  #   Output (Constant) - LED padding
            0x95, 0x06,  #   Report Count (6)
            0x75, 0x08,  #   Report Size (8)
            0x15, 0x00,  #   Logical Minimum (0)
            0x25, 0x65,  #   Logical Maximum (101)
            0x05, 0x07,  #   Usage Page (Key Codes)
            0x19, 0x00,  #   Usage Minimum (0)
            0x29, 0x65,  #   Usage Maximum (101)
            0x81, 0x00,  #   Input (Data, Array) - Key array
            0xC0,        # End Collection

            # Consumer Control Report (ID 2)
            0x05, 0x0C,  # Usage Page (Consumer)
            0x09, 0x01,  # Usage (Consumer Control)
            0xA1, 0x01,  # Collection (Application)
            0x85, 0x02,  #   Report ID (2)
            0x15, 0x00,  #   Logical Minimum (0)
            0x26, 0xFF, 0x03,  # Logical Maximum (1023)
            0x19, 0x00,  #   Usage Minimum (0)
            0x2A, 0xFF, 0x03,  # Usage Maximum (1023)
            0x75, 0x10,  #   Report Size (16)
            0x95, 0x01,  #   Report Count (1)
            0x81, 0x00,  #   Input (Data, Array)
            0xC0,        # End Collection
        ])

        # Keyboard state
        self.modifiers = 0
        self.keypresses = [0x00] * 6
        self.kb_callback = None

        # Consumer control state
        self.consumer_code = 0

        self.services.append(self.HIDS)

    def ble_irq(self, event, data):
        if event == _IRQ_GATTS_WRITE:
            conn_handle, attr_handle = data
            if hasattr(self, 'h_repout') and attr_handle == self.h_repout:
                report = self._ble.gatts_read(attr_handle)
                if self.kb_callback:
                    self.kb_callback(struct.unpack("B", report))
                return _GATTS_NO_ERROR
        return super().ble_irq(event, data)

    def start(self):
        super().start()
        print("Registering HID services")
        handles = self._ble.gatts_register_services(self.services)
        self.save_service_characteristics(handles)
        self.write_service_characteristics()
        self.adv = Advertiser(self._ble, [UUID(0x1812)], self.device_appearance, self.device_name)
        print("Keyboard ready")

    def save_service_characteristics(self, handles):
        super().save_service_characteristics(handles)

        # Unpack handles for HID service
        # Order: info, report_map, ctrl, kb_input, kb_ref, kb_output, kb_out_ref, consumer_input, consumer_ref, proto
        h_info, h_hid, h_ctrl, self.h_rep, h_d1, self.h_repout, h_d2, self.h_rep_consumer, h_d3, h_proto = handles[2]

        state = struct.pack("8B", self.modifiers, 0,
                           self.keypresses[0], self.keypresses[1],
                           self.keypresses[2], self.keypresses[3],
                           self.keypresses[4], self.keypresses[5])

        consumer_state = struct.pack("<H", self.consumer_code)

        self.characteristics[h_info] = ("HID Info", b"\x01\x01\x00\x00")
        self.characteristics[h_hid] = ("Report Map", self.HID_INPUT_REPORT)
        self.characteristics[h_ctrl] = ("Control", b"\x00")
        self.characteristics[self.h_rep] = ("KB Input", state)
        self.characteristics[h_d1] = ("KB Input Ref", struct.pack("<BB", 1, 1))  # Report ID 1, Input
        self.characteristics[self.h_repout] = ("KB Output", state)
        self.characteristics[h_d2] = ("KB Output Ref", struct.pack("<BB", 1, 2))  # Report ID 1, Output
        self.characteristics[self.h_rep_consumer] = ("Consumer Input", consumer_state)
        self.characteristics[h_d3] = ("Consumer Ref", struct.pack("<BB", 2, 1))  # Report ID 2, Input
        self.characteristics[h_proto] = ("Protocol", b"\x01")

    def notify_hid_report(self):
        if self.is_connected():
            state = struct.pack("8B", self.modifiers, 0,
                               self.keypresses[0], self.keypresses[1],
                               self.keypresses[2], self.keypresses[3],
                               self.keypresses[4], self.keypresses[5])
            self.characteristics[self.h_rep] = ("KB Input", state)
            self._ble.gatts_notify(self.conn_handle, self.h_rep, state)

    def notify_consumer_report(self):
        """Send consumer control report (media keys)."""
        if self.is_connected():
            state = struct.pack("<H", self.consumer_code)
            self.characteristics[self.h_rep_consumer] = ("Consumer Input", state)
            self._ble.gatts_notify(self.conn_handle, self.h_rep_consumer, state)

    def set_modifiers(self, right_gui=0, right_alt=0, right_shift=0, right_control=0,
                      left_gui=0, left_alt=0, left_shift=0, left_control=0):
        self.modifiers = ((right_gui << 7) | (right_alt << 6) | (right_shift << 5) |
                         (right_control << 4) | (left_gui << 3) | (left_alt << 2) |
                         (left_shift << 1) | left_control)

    def set_keys(self, k0=0x00, k1=0x00, k2=0x00, k3=0x00, k4=0x00, k5=0x00):
        self.keypresses = [k0, k1, k2, k3, k4, k5]

    def set_consumer(self, code=0x00):
        """Set consumer control code. Common codes:
        0x00 = Release
        0x30 = Power
        0x40 = Menu
        0xB5 = Next Track
        0xB6 = Prev Track
        0xB7 = Stop
        0xCD = Play/Pause
        0xE2 = Mute
        0xE9 = Volume Up
        0xEA = Volume Down
        0x223 = AC Home
        0x224 = AC Back
        """
        self.consumer_code = code

    def set_kb_callback(self, callback):
        self.kb_callback = callback
