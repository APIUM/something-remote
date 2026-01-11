# MicroPython main entry point
# Auto-starts Something Remote on boot

import time
from machine import Pin

# Hold SELECT (GPIO22) during boot to skip auto-start
SKIP_PIN = 22

print("Something Remote - boot")

# Check if SELECT button is held (active LOW)
skip_btn = Pin(SKIP_PIN, Pin.IN, Pin.PULL_UP)
time.sleep_ms(100)  # Debounce

if skip_btn.value() == 0:
    print("SELECT held - skipping auto-start")
    print("Run: from shield_remote import main; main()")
else:
    from shield_remote import main
    main()
