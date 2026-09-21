# wheel_calibration.py — straight-line drive calibration for dev00
#
# Two paths, chosen automatically based on whether the MPU6050 actually
# came up (state.mpu_available — see mpu6050_module.py):
#
#   Gyro-assisted (MPU6050 alive): drives forward in short bursts, samples
#   yaw rate (mpu_gz) during each burst, and nudges wheel_trim opposite the
#   measured drift until it converges or gives up after MAX_ITERATIONS.
#
#   Manual fallback (MPU6050 not available — this has actually happened on
#   this robot, see the "MPU6050 init failed" errors in logs/kida_run.log):
#   there's no closed-loop signal to calibrate against, so this just
#   refuses and points at the manual nudge_trim() +/- controls instead.
#
# Either way, run_calibration() only proceeds if nothing else currently
# owns dev00's motors (KEYBOARD or IDLE) and the motor lock is off — same
# safety bar as any other direct-drive action.

import threading
import time

import state
import mode_manager
import motor_lock
import kida_db
from state import DriveMode
from arduino import send_command, set_wheel_trim

BURST_SECONDS   = 1.2   # how long each forward test-drive burst runs
SETTLE_SECONDS  = 0.3   # pause after stopping before the next burst/sample
MAX_ITERATIONS  = 6
STEP_PERCENT    = 4     # trim adjustment per iteration
DRIFT_TOLERANCE = 3.0   # deg/s average yaw — under this, call it "straight"
TRIM_STEP       = 2     # manual nudge_trim() step size

_running = threading.Event()


def _safe_to_drive() -> bool:
    return (
        not motor_lock.is_locked()
        and mode_manager.current_mode() in (DriveMode.KEYBOARD, DriveMode.IDLE)
    )


def _sample_average_yaw(seconds: float) -> float:
    """Drive FORWARD for `seconds`, sampling mpu_gz throughout, then STOP.
    Returns the average yaw rate (deg/s) — near zero means straight."""
    send_command("dev00", "FORWARD")
    samples = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        samples.append(state.mpu_gz)
        time.sleep(0.05)
    send_command("dev00", "STOP")
    time.sleep(SETTLE_SECONDS)
    return sum(samples) / len(samples) if samples else 0.0


def _run_gyro_assisted():
    state.systemStatus = "Wheel calibration: running (gyro-assisted)"
    print("🔧 Wheel calibration: gyro-assisted mode")
    trim = state.wheel_trim

    for i in range(1, MAX_ITERATIONS + 1):
        if not _running.is_set():
            break
        drift = _sample_average_yaw(BURST_SECONDS)
        print(f"🔧 Calibration pass {i}: drift={drift:.2f} deg/s, trim={trim}")
        if abs(drift) <= DRIFT_TOLERANCE:
            state.systemStatus = f"Wheel calibration: converged, trim={trim}"
            print(f"✅ Wheel calibration converged at trim={trim}")
            break
        # Positive gz here is assumed CCW-positive (left turn); a leftward
        # drift means the right wheel is over-driving, so bias trim
        # positive (slows the right motor) — and vice versa.
        trim += STEP_PERCENT if drift > 0 else -STEP_PERCENT
        trim = max(-50, min(50, trim))
        set_wheel_trim(trim)
    else:
        state.systemStatus = f"Wheel calibration: gave up after {MAX_ITERATIONS} passes, trim={trim}"
        print(f"⚠️ Wheel calibration did not converge — left at trim={trim}")

    kida_db.set_setting("wheel_trim", state.wheel_trim)
    send_command("dev00", "STOP")


def run_calibration() -> bool:
    """Kick off calibration in a background thread. Returns False (and
    does nothing) if it's not currently safe to drive. Non-blocking —
    check state.systemStatus for progress/result."""
    if not _safe_to_drive():
        state.systemStatus = "Wheel calibration: refused (locked or not in KEYBOARD/IDLE)"
        print("⚠️ Wheel calibration refused — motor locked or not in KEYBOARD/IDLE mode")
        return False

    if not state.mpu_available:
        state.systemStatus = "Wheel calibration: MPU6050 unavailable — use manual +/- trim"
        print("⚠️ Wheel calibration: MPU6050 not available, no auto-converge possible. "
              "Use nudge_trim(+1)/nudge_trim(-1) manually instead.")
        return False

    if _running.is_set():
        return False

    def _wrapper():
        _running.set()
        try:
            _run_gyro_assisted()
        finally:
            _running.clear()

    threading.Thread(target=_wrapper, daemon=True, name="WheelCalibration").start()
    return True


def nudge_trim(direction: int) -> int:
    """Manual fallback: nudge wheel_trim by one TRIM_STEP in `direction`'s
    sign (only its sign matters). Always available — no MPU6050 needed.
    Returns the new trim value."""
    new_trim = max(-50, min(50, state.wheel_trim + (TRIM_STEP if direction > 0 else -TRIM_STEP)))
    set_wheel_trim(new_trim)
    kida_db.set_setting("wheel_trim", new_trim)
    return new_trim
