# ObstacleAvoidance.py
import state
from arduino import send_command
import time

# Configuration
SAFE_LASER_DISTANCE = 40
SAFE_ULTRASONIC_DISTANCE = 20
LOOP_DELAY = 0.05
MIN_US_VALID = 5

def parse_sensor(value):
    """Convert sensor value to int. Works for int or 'LASER:111' format."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        # Handle "LASER:111" or "ULTRASONIC0:8"
        return int(value.split(":")[1])
    except:
        return None

def read_sensors():
    laser = parse_sensor(getattr(state, 'laserValue', None))
    us0 = parse_sensor(getattr(state, 'ultrasonic0Value', None))
    us1 = parse_sensor(getattr(state, 'ultrasonic1Value', None))

    # Ignore invalid ultrasonic readings
    if us0 is not None and us0 < MIN_US_VALID:
        us0 = None
    if us1 is not None and us1 < MIN_US_VALID:
        us1 = None

    return laser, us0, us1

def obstacle_avoidance_step():
    laser, us0, us1 = read_sensors()
    command = "FORWARD"

    left_clear = us0 is None or us0 > SAFE_ULTRASONIC_DISTANCE
    right_clear = us1 is None or us1 > SAFE_ULTRASONIC_DISTANCE

    if laser is not None and laser < SAFE_LASER_DISTANCE:
        if left_clear and right_clear:
            command = "LEFT" if (us0 or SAFE_ULTRASONIC_DISTANCE) >= (us1 or SAFE_ULTRASONIC_DISTANCE) else "RIGHT"
        elif left_clear:
            command = "LEFT"
        elif right_clear:
            command = "RIGHT"
        else:
            command = "STOP"
    else:
        if us0 is not None and us0 < SAFE_ULTRASONIC_DISTANCE:
            command = "RIGHT" if right_clear else "STOP"
        elif us1 is not None and us1 < SAFE_ULTRASONIC_DISTANCE:
            command = "LEFT" if left_clear else "STOP"

    send_command("dev00", command)
    state.systemStatus = f"ObstacleAvoidance: {command} | Sensors: laser={laser}, us_left={us0}, us_right={us1}"
    print(state.systemStatus)

def run_obstacle_avoidance():
    try:
        while True:
            obstacle_avoidance_step()
            time.sleep(LOOP_DELAY)
    except KeyboardInterrupt:
        send_command("dev00", "STOP")
        print("Obstacle avoidance stopped safely.")

if __name__ == "__main__":
    run_obstacle_avoidance()
