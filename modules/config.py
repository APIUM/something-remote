# Configuration storage for Something Remote
# Stores WiFi and MQTT settings in NVS

import json

try:
    import esp32
    HAS_NVS = True
except ImportError:
    HAS_NVS = False


class Config:
    """Configuration storage using ESP32 NVS."""

    NAMESPACE = "remote_cfg"

    # Default values
    DEFAULTS = {
        "wifi_ssid": "",
        "wifi_password": "",
        "mqtt_host": "",
        "mqtt_port": 1883,
        "mqtt_user": "",
        "mqtt_password": "",
        "device_name": "something_remote",
        "configured": False,
    }

    def __init__(self):
        self._config = dict(self.DEFAULTS)
        self._nvs = None
        if HAS_NVS:
            try:
                self._nvs = esp32.NVS(self.NAMESPACE)
            except Exception as e:
                print("NVS init failed:", e)

    def load(self):
        """Load configuration from NVS."""
        if not self._nvs:
            return False

        try:
            data = bytearray(512)
            num_bytes = self._nvs.get_blob("config", data)
            if num_bytes > 0:
                loaded = json.loads(data[:num_bytes].decode('utf-8'))
                self._config.update(loaded)
                print("Config loaded")
                return True
        except OSError:
            print("No saved config")
        except Exception as e:
            print("Config load failed:", e)
        return False

    def save(self):
        """Save configuration to NVS."""
        if not self._nvs:
            return False

        try:
            data = json.dumps(self._config)
            self._nvs.set_blob("config", data)
            self._nvs.commit()
            print("Config saved")
            return True
        except Exception as e:
            print("Config save failed:", e)
            return False

    def clear(self):
        """Clear all configuration."""
        self._config = dict(self.DEFAULTS)
        if self._nvs:
            try:
                self._nvs.erase_key("config")
                self._nvs.commit()
                print("Config cleared")
            except Exception:
                pass

    def get(self, key, default=None):
        """Get a config value."""
        return self._config.get(key, default)

    def set(self, key, value):
        """Set a config value."""
        self._config[key] = value

    @property
    def is_configured(self):
        """Check if WiFi and MQTT are configured."""
        return (
            self._config.get("configured", False) and
            self._config.get("wifi_ssid", "") != "" and
            self._config.get("mqtt_host", "") != ""
        )

    @property
    def wifi_ssid(self):
        return self._config.get("wifi_ssid", "")

    @wifi_ssid.setter
    def wifi_ssid(self, value):
        self._config["wifi_ssid"] = value

    @property
    def wifi_password(self):
        return self._config.get("wifi_password", "")

    @wifi_password.setter
    def wifi_password(self, value):
        self._config["wifi_password"] = value

    @property
    def mqtt_host(self):
        return self._config.get("mqtt_host", "")

    @mqtt_host.setter
    def mqtt_host(self, value):
        self._config["mqtt_host"] = value

    @property
    def mqtt_port(self):
        return self._config.get("mqtt_port", 1883)

    @mqtt_port.setter
    def mqtt_port(self, value):
        self._config["mqtt_port"] = value

    @property
    def mqtt_user(self):
        return self._config.get("mqtt_user", "")

    @mqtt_user.setter
    def mqtt_user(self, value):
        self._config["mqtt_user"] = value

    @property
    def mqtt_password(self):
        return self._config.get("mqtt_password", "")

    @mqtt_password.setter
    def mqtt_password(self, value):
        self._config["mqtt_password"] = value

    @property
    def device_name(self):
        return self._config.get("device_name", "something_remote")

    @device_name.setter
    def device_name(self, value):
        self._config["device_name"] = value

    def set_configured(self, value=True):
        self._config["configured"] = value


# Global config instance
config = Config()
