"""
mpu6050_module.py
MPU6050 driver + background polling thread.
Writes accel/gyro values directly into state.py at ~20 Hz.
No external mpu6050 package required — uses smbus only.
"""

import threading
import time
import smbus
import state


# ─────────────────────────────────────────────
#  MPU6050 driver
# ─────────────────────────────────────────────

class MPU6050:
    def __init__(self, addr=0x68, bus_num=1):
        self.addr = addr
        self.bus  = smbus.SMBus(bus_num)
        # Clear sleep bit in PWR_MGMT_1 to wake the sensor
        self.bus.write_byte_data(self.addr, 0x6B, 0)

    def _read_word(self, reg):
        high = self.bus.read_byte_data(self.addr, reg)
        low  = self.bus.read_byte_data(self.addr, reg + 1)
        val  = (high << 8) + low
        if val >= 0x8000:
            val = -((65535 - val) + 1)
        return val

    def get_accel(self):
        return (
            self._read_word(0x3B) / 16384.0,
            self._read_word(0x3D) / 16384.0,
            self._read_word(0x3F) / 16384.0,
        )

    def get_gyro(self):
        return (
            self._read_word(0x43) / 131.0,
            self._read_word(0x45) / 131.0,
            self._read_word(0x47) / 131.0,
        )


# ─────────────────────────────────────────────
#  Polling thread
# ─────────────────────────────────────────────

_mpu    = None
_thread = None


def start_mpu_thread(addr=0x68, interval=0.05):
    """Start background thread polling MPU6050 at ~20 Hz."""
    global _mpu, _thread

    try:
        _mpu = MPU6050(addr=addr)
        print("✅ MPU6050 ready")
    except Exception as e:
        print(f"❌ MPU6050 init failed: {e}")
        return

    def _loop():
        # error tracking helps avoid flooding the log when the sensor
        # is missing or the I2C bus misbehaves.  After a certain number of
        # consecutive failures we give up and exit the thread.
        error_count = 0
        last_err = None
        while True:
            try:
                ax, ay, az = _mpu.get_accel()
                gx, gy, gz = _mpu.get_gyro()
                state.mpu_ax = round(ax, 3)
                state.mpu_ay = round(ay, 3)
                state.mpu_az = round(az, 3)
                state.mpu_gx = round(gx, 3)
                state.mpu_gy = round(gy, 3)
                state.mpu_gz = round(gz, 3)
                # reset error status on successful read
                error_count = 0
                last_err = None
            except Exception as e:
                msg = str(e)
                # only print when message changes to avoid log spam
                if msg != last_err:
                    print(f"[MPU6050] {msg}")
                    last_err = msg
                error_count += 1
                # after too many failures, stop polling and update status
                if error_count >= 20:
                    print("[MPU6050] too many errors, stopping thread")
                    state.systemStatus = "MPU DEAD"
                    break
            time.sleep(interval)

    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()