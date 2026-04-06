import psutil
import time
import platform

try:
    from pynvml import (
        nvmlInit,
        nvmlShutdown,
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetTemperature,
        nvmlDeviceGetUtilizationRates,
        nvmlDeviceGetMemoryInfo,
        NVML_TEMPERATURE_GPU
    )
    GPU_ENABLED = True
    nvmlInit()
    gpu_handle = nvmlDeviceGetHandleByIndex(0)
except Exception:
    GPU_ENABLED = False

def get_cpu_info():
    return f"CPU Usage: {psutil.cpu_percent(interval=1)}%"

def get_ram_info():
    ram = psutil.virtual_memory()
    return f"RAM Usage: {ram.percent}% of {round(ram.total / (1024**3), 2)} GB"

def get_temp_info():
    if hasattr(psutil, "sensors_temperatures"):
        temps = psutil.sensors_temperatures()
        if not temps:
            return "Temperature: Not available"
        results = []
        for name, entries in temps.items():
            for entry in entries:
                results.append(f"{name} - {entry.label or 'CPU'}: {entry.current}°C")
        return "\n".join(results)
    return "Temperature: Unsupported on this OS"

def get_gpu_info():
    if GPU_ENABLED:
        try:
            temp = nvmlDeviceGetTemperature(gpu_handle, NVML_TEMPERATURE_GPU)
            util = nvmlDeviceGetUtilizationRates(gpu_handle)
            mem = nvmlDeviceGetMemoryInfo(gpu_handle)
            return f"GPU Temp: {temp}°C\nGPU Usage: {util.gpu}%\nGPU Memory Used: {round(mem.used / (1024**2))} MB"
        except Exception as e:
            return f"GPU Info Error: {e}"
    return "GPU Info: Not available"

def monitor():
    print(f"System Monitor - Platform: {platform.system()}\n{'=' * 40}")
    while True:
        print(get_cpu_info())
        print(get_ram_info())
        print(get_temp_info())
        print(get_gpu_info())
        print("=" * 40)
        time.sleep(2)

try:
    monitor()
except KeyboardInterrupt:
    if GPU_ENABLED:
        nvmlShutdown()
    print("\nMonitoring stopped.")

