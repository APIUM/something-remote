# Home Assistant MQTT Client for Something Remote
# On-demand WiFi connection with MQTT Discovery

import network
import time
import json
import ubinascii
import machine
from config import config

try:
    from umqtt.simple import MQTTClient
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("umqtt.simple not available")


class HomeAssistantClient:
    """MQTT client for Home Assistant with auto-discovery."""

    WIFI_TIMEOUT_MS = 15000  # 15 sec to connect WiFi
    WIFI_IDLE_TIMEOUT_MS = 60000  # 1 min idle before disconnect
    BATTERY_REPORT_INTERVAL_MS = 10 * 60 * 1000  # 10 minutes

    def __init__(self):
        self.wlan = None
        self.mqtt = None
        self._wifi_connected = False
        self._mqtt_connected = False
        self._last_activity = 0
        self._last_battery_report = 0
        self._discovery_sent = False
        self._device_id = self._get_device_id()

    def _get_device_id(self):
        """Get unique device ID from MAC address."""
        mac = ubinascii.hexlify(machine.unique_id()).decode()
        return f"something_remote_{mac[-6:]}"

    @property
    def device_name(self):
        return config.device_name or "Something Remote"

    @property
    def is_configured(self):
        return config.is_configured

    def _connect_wifi(self):
        """Connect to WiFi."""
        if self._wifi_connected:
            return True

        if not config.wifi_ssid:
            print("WiFi not configured")
            return False

        print(f"Connecting to WiFi: {config.wifi_ssid}")

        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.wlan.connect(config.wifi_ssid, config.wifi_password)

        start = time.ticks_ms()
        while not self.wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), start) > self.WIFI_TIMEOUT_MS:
                print("WiFi connection timeout")
                self.wlan.active(False)
                return False
            time.sleep_ms(100)

        print(f"WiFi connected: {self.wlan.ifconfig()[0]}")
        self._wifi_connected = True
        self._last_activity = time.ticks_ms()
        return True

    def _disconnect_wifi(self):
        """Disconnect from WiFi."""
        if self.wlan:
            self.wlan.active(False)
        self._wifi_connected = False
        self._mqtt_connected = False
        self._discovery_sent = False
        print("WiFi disconnected")

    def _connect_mqtt(self):
        """Connect to MQTT broker."""
        if self._mqtt_connected:
            return True

        if not self._wifi_connected:
            if not self._connect_wifi():
                return False

        if not config.mqtt_host:
            print("MQTT not configured")
            return False

        if not HAS_MQTT:
            print("MQTT library not available")
            return False

        try:
            print(f"Connecting to MQTT: {config.mqtt_host}:{config.mqtt_port}")

            self.mqtt = MQTTClient(
                self._device_id,
                config.mqtt_host,
                port=config.mqtt_port,
                user=config.mqtt_user if config.mqtt_user else None,
                password=config.mqtt_password if config.mqtt_password else None,
                keepalive=60
            )
            self.mqtt.connect()
            self._mqtt_connected = True
            self._last_activity = time.ticks_ms()
            print("MQTT connected")

            # Send discovery on first connect
            if not self._discovery_sent:
                self._send_discovery()
                self._discovery_sent = True

            return True

        except Exception as e:
            print(f"MQTT connection failed: {e}")
            self._mqtt_connected = False
            # Disconnect WiFi on failure to avoid issues
            self._disconnect_wifi()
            return False

    def _disconnect_mqtt(self):
        """Disconnect from MQTT."""
        if self.mqtt:
            try:
                self.mqtt.disconnect()
            except Exception:
                pass
        self._mqtt_connected = False

    def _send_discovery(self):
        """Send Home Assistant MQTT Discovery messages."""
        if not self._mqtt_connected:
            return

        device_info = {
            "identifiers": [self._device_id],
            "name": self.device_name,
            "manufacturer": "DIY",
            "model": "Everything Remote",
            "sw_version": "1.0"
        }

        # Button triggers
        buttons = [
            ("power", "Power"),  # Power via HA - can turn Shield on/off
            ("shortcut_1", "Shortcut 1"),
            ("shortcut_2", "Shortcut 2"),
            ("shortcut_3", "Shortcut 3"),
            ("shortcut_4", "Shortcut 4"),
            ("brightness_up", "Brightness Up"),
            ("brightness_down", "Brightness Down"),
        ]

        for btn_id, btn_name in buttons:
            # Short press trigger
            discovery_topic = f"homeassistant/device_automation/{self._device_id}/{btn_id}/config"
            payload = {
                "automation_type": "trigger",
                "type": "button_short_press",
                "subtype": btn_id,
                "topic": f"{self._device_id}/action",
                "payload": btn_id,
                "device": device_info
            }
            self.mqtt.publish(discovery_topic, json.dumps(payload), retain=True)
            print(f"Discovery: {btn_name}")

        # Battery sensor
        battery_topic = f"homeassistant/sensor/{self._device_id}/battery/config"
        battery_payload = {
            "name": "Battery",
            "device_class": "battery",
            "unit_of_measurement": "%",
            "state_topic": f"{self._device_id}/battery",
            "value_template": "{{ value_json.percent }}",
            "unique_id": f"{self._device_id}_battery",
            "device": device_info
        }
        self.mqtt.publish(battery_topic, json.dumps(battery_payload), retain=True)
        print("Discovery: Battery sensor")

        # Battery voltage sensor
        voltage_topic = f"homeassistant/sensor/{self._device_id}/voltage/config"
        voltage_payload = {
            "name": "Battery Voltage",
            "device_class": "voltage",
            "unit_of_measurement": "V",
            "state_topic": f"{self._device_id}/battery",
            "value_template": "{{ value_json.voltage }}",
            "unique_id": f"{self._device_id}_voltage",
            "device": device_info,
            "entity_category": "diagnostic"
        }
        self.mqtt.publish(voltage_topic, json.dumps(voltage_payload), retain=True)
        print("Discovery: Voltage sensor")

        print("HA Discovery complete")

    def send_button(self, button_id):
        """Send a button press event to HA."""
        if not self.is_configured:
            print("HA not configured")
            return False

        if not self._connect_mqtt():
            return False

        try:
            topic = f"{self._device_id}/action"
            self.mqtt.publish(topic, button_id)
            print(f"HA button: {button_id}")
            self._last_activity = time.ticks_ms()
            return True
        except Exception as e:
            print(f"MQTT publish failed: {e}")
            self._mqtt_connected = False
            return False

    def send_battery(self, percent, voltage):
        """Send battery status to HA."""
        if not self.is_configured:
            return False

        # Check if we should report (every 10 min)
        now = time.ticks_ms()
        if self._last_battery_report != 0:
            if time.ticks_diff(now, self._last_battery_report) < self.BATTERY_REPORT_INTERVAL_MS:
                return True  # Skip, too soon

        if not self._mqtt_connected:
            # Don't connect just for battery, piggyback on button press
            return False

        try:
            topic = f"{self._device_id}/battery"
            payload = json.dumps({"percent": percent, "voltage": round(voltage, 2)})
            self.mqtt.publish(topic, payload)
            print(f"HA battery: {percent}% ({voltage:.2f}V)")
            self._last_battery_report = now
            return True
        except Exception as e:
            print(f"Battery report failed: {e}")
            return False

    def check_idle_timeout(self):
        """Disconnect WiFi if idle too long."""
        if not self._wifi_connected:
            return

        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_activity) > self.WIFI_IDLE_TIMEOUT_MS:
            print("WiFi idle timeout")
            self._disconnect_mqtt()
            self._disconnect_wifi()


# Global HA client instance
ha_client = HomeAssistantClient()
