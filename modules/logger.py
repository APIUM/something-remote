# Simple file logger for Something Remote
# Logs to flash so we can debug without serial

import time

LOG_FILE = "/log.txt"
MAX_LOG_SIZE = 8000  # Keep log small to not fill flash


def _timestamp():
    """Get timestamp string."""
    t = time.localtime()
    return f"{t[3]:02d}:{t[4]:02d}:{t[5]:02d}"


def log(msg):
    """Log a message to file and print."""
    line = f"[{_timestamp()}] {msg}"
    print(line)

    try:
        # Append to log
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")

        # Truncate if too large
        try:
            import os
            size = os.stat(LOG_FILE)[6]
            if size > MAX_LOG_SIZE:
                # Keep last half
                with open(LOG_FILE, "r") as f:
                    content = f.read()
                with open(LOG_FILE, "w") as f:
                    f.write(content[len(content)//2:])
        except:
            pass
    except Exception as e:
        print(f"Log error: {e}")


def read_log():
    """Read and print the log file."""
    try:
        with open(LOG_FILE, "r") as f:
            print(f.read())
    except:
        print("No log file")


def clear_log():
    """Clear the log file."""
    try:
        import os
        os.remove(LOG_FILE)
        print("Log cleared")
    except:
        pass
