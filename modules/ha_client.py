# Home Assistant MQTT Client for Something Remote
# Asynchronous: mqtt_as owns WiFi + MQTT connection lifecycle and auto-reconnect.
# Public surface is deliberately synchronous (enqueue-and-return) so button
# handlers on the main loop never block on the network.

import time
import json
import ubinascii
import machine
import asyncio
from config import config
from logger import log

try:
    from _version import VERSION
except ImportError:
    VERSION = "dev"

from mqtt_as import MQTTClient, config as _mqtt_config


class HomeAssistantClient:
    """MQTT client for Home Assistant with auto-discovery, backed by mqtt_as."""

    BATTERY_REPORT_INTERVAL_MS = 10 * 60 * 1000  # 10 min rate-limit for piggy-back publishes
    OUTBOX_MAX = 32  # drop-oldest ceiling on pending publishes
    PUBLISH_TIMEOUT_S = 30  # per-message timeout; mqtt_as internally retries within this

    def __init__(self):
        self._device_id = self._get_device_id()
        self._client = None
        self._outbox = None  # list of (topic, payload, retain); None until start()
        self._last_battery_report = 0
        self._worker_task = None
        self._watcher_task = None
        self._started = False

    def _get_device_id(self):
        mac = ubinascii.hexlify(machine.unique_id()).decode()
        return f"something_remote_{mac[-6:]}"

    @property
    def device_name(self):
        return config.device_name or "Something Remote"

    @property
    def is_configured(self):
        return config.is_configured

    # --- lifecycle ---

    async def start(self):
        """Initialise mqtt_as, spawn worker + watcher tasks, kick off connect.

        Non-blocking in the sense that we don't wait for the broker to come up
        before returning — we do give the initial connect a short head-start
        so first-press latency is usually fine."""
        if self._started or not self.is_configured:
            return self._started

        cfg = _mqtt_config.copy()
        cfg["server"] = config.mqtt_host
        cfg["port"] = config.mqtt_port
        cfg["user"] = config.mqtt_user or ""
        cfg["password"] = config.mqtt_password or ""
        cfg["client_id"] = self._device_id
        cfg["ssid"] = config.wifi_ssid
        cfg["wifi_pw"] = config.wifi_password
        cfg["keepalive"] = 60
        cfg["clean"] = True
        # Non-zero queue_len is what enables mqtt_as's up/down asyncio Events
        # (see mqtt_as.py: self._events = config["queue_len"] > 0). We don't
        # subscribe to anything, so size 1 is plenty; the queue itself is idle.
        cfg["queue_len"] = 1

        self._client = MQTTClient(cfg)
        self._outbox = []
        self._started = True

        self._worker_task = asyncio.create_task(self._publish_worker())
        self._watcher_task = asyncio.create_task(self._connection_watcher())

        # Initial connect — give it up to 10s for a fast first publish. If it
        # times out, mqtt_as continues retrying in the background; queued
        # publishes will drain whenever it lands.
        try:
            log(f"MQTT starting: {config.mqtt_host}:{config.mqtt_port}")
            await asyncio.wait_for(self._client.connect(quick=True), 10)
        except asyncio.TimeoutError:
            log("MQTT initial connect slow, continuing in background")
        except Exception as e:
            log(f"MQTT initial connect error: {e}")
        return True

    async def stop(self):
        """Graceful shutdown, safe to call on a client that never started."""
        if not self._started:
            return
        for task in (self._worker_task, self._watcher_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except Exception:
                pass
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            try:
                self._client.close()
            except Exception:
                pass
        self._worker_task = None
        self._watcher_task = None
        self._client = None
        self._outbox = None
        self._started = False

    async def drain(self, timeout_ms=3000):
        """Block until the outbox is empty or timeout elapses. Returns bool."""
        if not self._started or self._outbox is None:
            return True
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while self._outbox:
            if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                log(f"drain timeout, {len(self._outbox)} msgs dropped")
                return False
            await asyncio.sleep_ms(50)
        return True

    # --- background tasks ---

    async def _connection_watcher(self):
        """Re-send discovery on every (re)connect event from mqtt_as."""
        while True:
            await self._client.up.wait()
            self._client.up.clear()
            log("MQTT up")
            try:
                await self._send_discovery()
            except Exception as e:
                log(f"Discovery failed: {e}")

    async def _publish_worker(self):
        """Drain the outbox onto mqtt_as.publish, which blocks until the
        broker is reachable. On failure or timeout we drop the message
        rather than head-of-line blocking forever."""
        while True:
            if not self._outbox:
                await asyncio.sleep_ms(50)
                continue
            topic, payload, retain = self._outbox[0]
            try:
                await asyncio.wait_for(
                    self._client.publish(topic, payload, retain=retain),
                    self.PUBLISH_TIMEOUT_S,
                )
                # Successful publish — pop and continue
                self._outbox.pop(0)
            except asyncio.TimeoutError:
                log(f"Publish timeout, dropped: {topic}")
                if self._outbox:
                    self._outbox.pop(0)
            except Exception as e:
                log(f"Publish error, dropped ({e}): {topic}")
                if self._outbox:
                    self._outbox.pop(0)

    # --- public synchronous API (safe from non-async handlers) ---

    def enqueue(self, topic, payload, retain=False):
        """Queue a publish. Returns True if accepted, False if client not ready."""
        if not self._started or self._outbox is None:
            return False
        if len(self._outbox) >= self.OUTBOX_MAX:
            # Drop oldest — if we're this backed up, freshest data is more useful
            dropped = self._outbox.pop(0)
            log(f"Outbox full, dropped oldest: {dropped[0]}")
        self._outbox.append((topic, payload, retain))
        return True

    def send_button(self, button_id):
        """Enqueue a button action publish."""
        if not self.is_configured:
            log("HA not configured")
            return False
        ok = self.enqueue(f"{self._device_id}/action", button_id)
        if ok:
            log(f"Enqueued button: {button_id}")
        return ok

    def send_battery(self, percent, voltage, raw_uv=0, force=False):
        """Enqueue a battery state publish.

        force=True bypasses the 10-min rate limit; used for boot/wake/pre-sleep.
        force=False piggy-backs on button presses and skips if within the window.
        """
        if not self.is_configured or not config.battery_enabled:
            return False
        now = time.ticks_ms()
        if not force and self._last_battery_report != 0:
            if time.ticks_diff(now, self._last_battery_report) < self.BATTERY_REPORT_INTERVAL_MS:
                return True
        payload = json.dumps({
            "percent": percent,
            "voltage": round(voltage, 3),
            "raw_uv": raw_uv,
        })
        ok = self.enqueue(f"{self._device_id}/battery", payload)
        if ok:
            self._last_battery_report = now
            log(f"Enqueued battery: {percent}% ({voltage:.3f}V, raw {raw_uv}uV){' [forced]' if force else ''}")
        return ok

    def time_since_last_battery_ms(self):
        if self._last_battery_report == 0:
            return None
        return time.ticks_diff(time.ticks_ms(), self._last_battery_report)

    # --- discovery ---

    async def _send_discovery(self):
        """Publish retained discovery configs. Awaits mqtt_as.publish directly
        because this runs on the connection-up event, not via the outbox."""
        device_info = {
            "identifiers": [self._device_id],
            "name": self.device_name,
            "manufacturer": "DIY",
            "model": "Everything Remote",
            "sw_version": VERSION,
        }

        buttons = [
            ("power", "Power"),
            ("shortcut_1", "Shortcut 1"),
            ("shortcut_2", "Shortcut 2"),
            ("shortcut_3", "Shortcut 3"),
            ("shortcut_4", "Shortcut 4"),
            ("brightness_up", "Brightness Up"),
            ("brightness_down", "Brightness Down"),
        ]

        for btn_id, btn_name in buttons:
            topic = f"homeassistant/device_automation/{self._device_id}/{btn_id}/config"
            payload = json.dumps({
                "automation_type": "trigger",
                "type": "button_short_press",
                "subtype": btn_id,
                "topic": f"{self._device_id}/action",
                "payload": btn_id,
                "device": device_info,
            })
            await self._client.publish(topic, payload, retain=True)

        # Battery sensors — only advertised if the hardware mod is installed.
        # Blank the retained configs when disabled so HA drops stale entities.
        if not config.battery_enabled:
            for subtopic in ("battery", "voltage", "battery_raw_uv"):
                await self._client.publish(
                    f"homeassistant/sensor/{self._device_id}/{subtopic}/config",
                    "", retain=True,
                )
            log("Discovery complete (battery disabled)")
            return

        battery_cfg = {
            "name": "Battery",
            "device_class": "battery",
            "unit_of_measurement": "%",
            "state_topic": f"{self._device_id}/battery",
            "value_template": "{{ value_json.percent }}",
            "unique_id": f"{self._device_id}_battery",
            "device": device_info,
        }
        await self._client.publish(
            f"homeassistant/sensor/{self._device_id}/battery/config",
            json.dumps(battery_cfg), retain=True,
        )

        voltage_cfg = {
            "name": "Battery Voltage",
            "device_class": "voltage",
            "unit_of_measurement": "V",
            "state_topic": f"{self._device_id}/battery",
            "value_template": "{{ value_json.voltage }}",
            "unique_id": f"{self._device_id}_voltage",
            "device": device_info,
            "entity_category": "diagnostic",
        }
        await self._client.publish(
            f"homeassistant/sensor/{self._device_id}/voltage/config",
            json.dumps(voltage_cfg), retain=True,
        )

        raw_uv_cfg = {
            "name": "Battery ADC Raw",
            "unit_of_measurement": "µV",
            "state_topic": f"{self._device_id}/battery",
            "value_template": "{{ value_json.raw_uv }}",
            "unique_id": f"{self._device_id}_battery_raw_uv",
            "device": device_info,
            "entity_category": "diagnostic",
        }
        await self._client.publish(
            f"homeassistant/sensor/{self._device_id}/battery_raw_uv/config",
            json.dumps(raw_uv_cfg), retain=True,
        )

        log("Discovery complete")


# Global HA client instance
ha_client = HomeAssistantClient()
