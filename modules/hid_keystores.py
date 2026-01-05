# MicroPython BLE HID Keystore
# Adapted from MicroPythonBLEHID by H. Groefsema
# https://github.com/Heerkog/MicroPythonBLEHID
# License: GPL-3.0

import json
import binascii

try:
    import esp32
    HAS_NVS = True
except ImportError:
    HAS_NVS = False


class KeyStore:
    """Generic keystore for BLE bonding secrets."""

    def __init__(self):
        self.secrets = {}

    def add_secret(self, sec_type, key, value):
        _key = (sec_type, bytes(key))
        self.secrets[_key] = bytes(value)

    def get_secret(self, sec_type, index, key):
        _key = (sec_type, bytes(key) if key else None)
        value = None

        if key is None:
            i = 0
            for (t, _k), _val in self.secrets.items():
                if t == sec_type:
                    if i == index:
                        value = _val
                    i += 1
        else:
            value = self.secrets.get(_key, None)

        return value

    def remove_secret(self, sec_type, key):
        _key = (sec_type, bytes(key))
        if _key in self.secrets:
            del self.secrets[_key]

    def has_secret(self, sec_type, key):
        _key = (sec_type, bytes(key))
        return _key in self.secrets

    def get_json_secrets(self):
        return [
            (sec_type, binascii.b2a_base64(key, newline=False).decode(),
             binascii.b2a_base64(value, newline=False).decode())
            for (sec_type, key), value in self.secrets.items()
        ]

    def add_json_secrets(self, entries):
        for sec_type, key, value in entries:
            key_bytes = binascii.a2b_base64(key) if isinstance(key, str) else binascii.a2b_base64(key)
            val_bytes = binascii.a2b_base64(value) if isinstance(value, str) else binascii.a2b_base64(value)
            self.secrets[(sec_type, key_bytes)] = val_bytes

    def load_secrets(self):
        pass

    def save_secrets(self):
        pass


class NVSKeyStore(KeyStore):
    """Keystore using ESP32 non-volatile storage."""

    def __init__(self):
        super().__init__()
        if HAS_NVS:
            self.nvsdata = esp32.NVS("BLE")
        else:
            self.nvsdata = None

    def load_secrets(self):
        if not self.nvsdata:
            return

        try:
            data = bytearray(512)
            num_bytes = self.nvsdata.get_blob("Keys", data)
            if num_bytes > 0:
                entries = json.loads(data[:num_bytes].decode('utf-8'))
                self.add_json_secrets(entries)
                print("Loaded", len(entries), "bonding keys")
        except OSError:
            print("No saved bonding keys")
        except Exception as e:
            print("Failed to load secrets:", e)

    def save_secrets(self):
        if not self.nvsdata:
            return

        try:
            data = json.dumps(self.get_json_secrets())
            self.nvsdata.set_blob("Keys", data)
            self.nvsdata.commit()
            print("Saved bonding keys")
        except Exception as e:
            print("Failed to save secrets:", e)


# Default keystore - use NVS on ESP32
if HAS_NVS:
    DefaultKeyStore = NVSKeyStore
else:
    DefaultKeyStore = KeyStore
