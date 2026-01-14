# WiFi Setup Portal for Something Remote
# Captive portal using Microdot web framework

import network
import socket
import time
from config import config, POWER_MODE_BLE, POWER_MODE_HA
from microdot import Microdot, Response

app = Microdot()

# HTML template for setup page
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="Cache-Control" content="no-cache">
    <title>Something Remote Setup</title>
    <style>
        body{{font-family:sans-serif;margin:20px;background:#1a1a2e;color:#eee}}
        h1{{color:#0f0}}
        form{{max-width:400px}}
        label{{display:block;margin-top:15px;color:#aaa}}
        input[type="text"],input[type="password"],input[type="number"]{{width:100%;padding:10px;margin-top:5px;border:1px solid #444;background:#16213e;color:#fff;border-radius:4px;box-sizing:border-box}}
        button{{margin-top:20px;padding:12px 30px;background:#0f0;color:#000;border:none;border-radius:4px;cursor:pointer;font-weight:bold}}
        .section{{margin-top:25px;padding-top:15px;border-top:1px solid #333}}
        .radio-group{{margin-top:10px}}
        .radio-group label{{display:flex;align-items:center;margin-top:8px;cursor:pointer}}
        .radio-group input[type="radio"]{{width:auto;margin-right:10px}}
    </style>
</head>
<body>
    <h1>Something Remote Setup</h1>
    <form method="POST" action="/save">
        <div class="section">
            <h3>WiFi Settings</h3>
            <label>SSID</label>
            <input type="text" name="wifi_ssid" value="{wifi_ssid}" required>
            <label>Password</label>
            <input type="password" name="wifi_password" value="{wifi_password}">
        </div>
        <div class="section">
            <h3>MQTT Settings</h3>
            <label>Host</label>
            <input type="text" name="mqtt_host" value="{mqtt_host}" required placeholder="192.168.1.100">
            <label>Port</label>
            <input type="number" name="mqtt_port" value="{mqtt_port}">
            <label>Username (optional)</label>
            <input type="text" name="mqtt_user" value="{mqtt_user}">
            <label>Password (optional)</label>
            <input type="password" name="mqtt_password" value="{mqtt_password}">
        </div>
        <div class="section">
            <h3>Power Button Functionality</h3>
            <div class="radio-group">
                <label><input type="radio" name="power_button_mode" value="ha" {power_ha_checked}> Custom Home Assistant Trigger</label>
                <label><input type="radio" name="power_button_mode" value="ble" {power_ble_checked}> BLE Power Command</label>
            </div>
        </div>
        <button type="submit">Save & Restart</button>
    </form>
</body>
</html>
"""

HTML_SUCCESS = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Something Remote Setup</title>
    <style>
        body{font-family:sans-serif;margin:20px;background:#1a1a2e;color:#eee;text-align:center;padding-top:50px}
        h1{color:#0f0}
    </style>
</head>
<body>
    <h1>Settings Saved!</h1>
    <p>Device will restart in 3 seconds...</p>
</body>
</html>
"""


@app.route('/')
async def index(request):
    """Main setup page."""
    power_mode = config.power_button_mode
    html = HTML_PAGE.format(
        wifi_ssid=config.wifi_ssid,
        wifi_password=config.wifi_password,
        mqtt_host=config.mqtt_host,
        mqtt_port=config.mqtt_port,
        mqtt_user=config.mqtt_user,
        mqtt_password=config.mqtt_password,
        power_ha_checked='checked' if power_mode == POWER_MODE_HA else '',
        power_ble_checked='checked' if power_mode == POWER_MODE_BLE else '',
    )
    return html, 200, {'Content-Type': 'text/html'}


@app.route('/save', methods=['POST'])
async def save(request):
    """Save configuration."""
    form = request.form

    config.wifi_ssid = form.get('wifi_ssid', '')
    config.wifi_password = form.get('wifi_password', '')
    config.mqtt_host = form.get('mqtt_host', '')
    config.mqtt_port = int(form.get('mqtt_port', 1883))
    config.mqtt_user = form.get('mqtt_user', '')
    config.mqtt_password = form.get('mqtt_password', '')
    config.power_button_mode = form.get('power_button_mode', POWER_MODE_HA)
    config.set_configured(True)
    config.save()

    print("Config saved, restarting in 3s...")

    # Schedule restart
    import _thread
    def restart():
        time.sleep(3)
        import machine
        machine.reset()
    _thread.start_new_thread(restart, ())

    return HTML_SUCCESS, 200, {'Content-Type': 'text/html'}


# Captive portal detection - redirect to main page
@app.route('/generate_204')
@app.route('/gen_204')
@app.route('/hotspot-detect.html')
@app.route('/connecttest.txt')
@app.route('/ncsi.txt')
@app.route('/redirect')
@app.route('/success.txt')
@app.route('/canonical.html')
@app.route('/favicon.ico')
async def captive_portal(request):
    """Handle captive portal detection."""
    return '', 302, {'Location': 'http://192.168.4.1/'}


# Catch-all route
@app.route('/<path:path>')
async def catch_all(request, path):
    """Redirect everything else to main page."""
    return '', 302, {'Location': 'http://192.168.4.1/'}


class CaptivePortalDNS:
    """DNS server that redirects all queries to AP IP."""

    def __init__(self, ip="192.168.4.1"):
        self.ip = ip
        self.sock = None
        self._running = False

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', 53))
        self.sock.setblocking(False)
        self._running = True
        print("DNS server started")

    def stop(self):
        self._running = False
        if self.sock:
            self.sock.close()
            self.sock = None

    def poll(self):
        if not self._running or not self.sock:
            return
        try:
            data, addr = self.sock.recvfrom(512)
            if len(data) < 12:
                return

            # Build DNS response pointing to our IP
            response = bytearray(data[:2])  # Transaction ID
            response += b'\x81\x80'  # Flags
            response += data[4:6]  # Questions
            response += data[4:6]  # Answers
            response += b'\x00\x00\x00\x00'  # Auth + Additional

            # Copy question
            pos = 12
            while pos < len(data) and data[pos] != 0:
                pos += data[pos] + 1
            pos += 5
            response += data[12:pos]

            # Add answer
            response += b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04'
            response += bytes(map(int, self.ip.split('.')))

            self.sock.sendto(response, addr)
        except:
            pass


_dns = None

def run_setup_portal(led_callback=None):
    """Run the setup portal."""
    global _dns

    print("Starting setup portal...")

    # Disable STA interface first (may interfere with AP)
    sta = network.WLAN(network.STA_IF)
    if sta.active():
        sta.disconnect()
        sta.active(False)
        print("STA disabled")

    # Create AP
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid="SomethingRemote-Setup", password="12345678", authmode=network.AUTH_WPA_WPA2_PSK)

    for _ in range(50):
        if ap.active():
            break
        time.sleep_ms(100)

    ip = ap.ifconfig()[0]
    print(f"AP: SomethingRemote-Setup (pw: 12345678)")
    print(f"Go to http://{ip}")

    # Start DNS
    _dns = CaptivePortalDNS(ip)
    _dns.start()

    # Run DNS in background thread
    import _thread
    def dns_loop():
        while _dns and _dns._running:
            _dns.poll()
            time.sleep_ms(10)
    _thread.start_new_thread(dns_loop, ())

    # Run Microdot (blocking)
    try:
        app.run(port=80)
    finally:
        if _dns:
            _dns.stop()
        ap.active(False)
