import psutil
import platform
import tkinter as tk
from tkinter import ttk
import threading
import time

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
    return f"CPU Usage: {psutil.cpu_percent()}%"


def get_ram_info():
    ram = psutil.virtual_memory()
    return f"RAM Usage: {ram.percent}% of {round(ram.total / (1024 ** 3), 2)} GB"


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
    return "Temperature: Unsupported"


def get_gpu_info():
    if GPU_ENABLED:
        try:
            temp = nvmlDeviceGetTemperature(gpu_handle, NVML_TEMPERATURE_GPU)
            util = nvmlDeviceGetUtilizationRates(gpu_handle)
            mem = nvmlDeviceGetMemoryInfo(gpu_handle)
            return f"GPU Temp: {temp}°C\nGPU Usage: {util.gpu}%\nGPU Mem: {round(mem.used / (1024 ** 2))} MB"
        except Exception as e:
            return f"GPU Error: {e}"
    return "GPU Info: Not available"


class SystemMonitorApp:
    def __init__(self, root):
        self.root = root
        root.title("System Monitor")
        root.geometry("400x300")

        self.text = tk.Text(root, font=("Courier", 10), bg="black", fg="lime", wrap=tk.WORD)
        self.text.pack(fill=tk.BOTH, expand=True)

        self.running = True
        self.update_loop()

    def update_loop(self):
        if not self.running:
            return
        output = []
        output.append(f"🖥️ Platform: {platform.system()} {platform.machine()}")
        output.append(get_cpu_info())
        output.append(get_ram_info())
        output.append(get_temp_info())
        output.append(get_gpu_info())
        self.text.delete(1.0, tk.END)
        self.text.insert(tk.END, "\n".join(output))
        self.root.after(2000, self.update_loop)


def run_gui():
    root = tk.Tk()
    app = SystemMonitorApp(root)
    try:
        root.mainloop()
    finally:
        if GPU_ENABLED:
            nvmlShutdown()


run_gui()
