#stats.py

import psutil
import socket
import threading
import time

# Thread-safe storage for system metrics
stats_lock = threading.Lock()
system_stats = {
    "cpu": 0.0,
    "ram": 0.0,
    "temp": "N/A",
    "ip": "127.0.0.1",
    "uptime": "0:00:00"
}

def get_cpu_temp():
    """Reads the Raspberry Pi 5 SoC temperature."""
    try:
        # Standard Linux thermal path
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_milli = int(f.read())
        return f"{temp_milli / 1000:.1f}°C"
    except (FileNotFoundError, ValueError):
        # Fallback for systems where zone0 isn't the CPU
        try:
            temps = psutil.sensors_temperatures()
            if 'cpu_thermal' in temps:
                return f"{temps['cpu_thermal'][0].current:.1f}°C"
        except:
            return "N/A"

def get_local_ip():
    """Retrieves the primary local IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually connect, just probes the interface
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def update_loop(interval=2.0):
    """
    Continuous background loop to keep stats fresh.
    Meant to be run in a daemon thread.
    """
    while True:
        cpu = psutil.cpu_percent(interval=None) # Non-blocking if interval is None
        ram = psutil.virtual_memory().percent
        temp = get_cpu_temp()
        ip = get_local_ip()
        
        with stats_lock:
            system_stats.update({
                "cpu": cpu,
                "ram": ram,
                "temp": temp,
                "ip": ip
            })
        
        time.sleep(interval)

# Initial execution
if __name__ == "__main__":
    # Example of how to start this as a background service
    daemon = threading.Thread(target=update_loop, daemon=True)
    daemon.start()
    
    try:
        while True:
            with stats_lock:
                print(f"[{system_stats['ip']}] CPU: {system_stats['cpu']}% | Temp: {system_stats['temp']}")
            time.sleep(5)
    except KeyboardInterrupt:
        print("Stats monitoring stopped.")