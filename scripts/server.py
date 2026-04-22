# server.py — Flask web server for KIDA
# Serves the HUD dashboard at http://<ip>:5004/
# Provides MJPEG streams (/video_feed/0 and /video_feed/1) and a /status JSON endpoint.

import os
import socket
import time
import cv2
import requests
from flask import Flask, render_template, Response, jsonify
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

_here = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(_here, '..', 'templates'),
    static_folder=os.path.join(_here, '..', 'static'),
)

# ── Configuration ──────────────────────────────────────────────────────────────
THIS_NAME = "KIDA01"
THIS_PORT = 5004
TYPE      = "_flask-link._tcp.local."

found_servers: dict = {}


def _get_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


my_ip = _get_ip()
print(f"Starting {THIS_NAME} on {my_ip}:{THIS_PORT}")


# ── Zeroconf discovery ──────────────────────────────────────────────────────────
class _Listener:
    def remove_service(self, zc, type_, name):
        found_servers.pop(name.split('.')[0], None)

    def add_service(self, zc, type_, name):
        self.update_service(zc, type_, name)

    def update_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info:
            addresses = [socket.inet_ntoa(a) for a in info.addresses]
            if addresses:
                short = name.split('.')[0]
                if short != THIS_NAME:
                    found_servers[short] = f"http://{addresses[0]}:{info.port}"


zeroconf = Zeroconf()
zc_info  = ServiceInfo(
    TYPE,
    f"{THIS_NAME}.{TYPE}",
    addresses=[socket.inet_aton(my_ip)],
    port=THIS_PORT,
    properties={'version': '1.0'},
)
zeroconf.register_service(zc_info)
ServiceBrowser(zeroconf, TYPE, _Listener())


# ── MJPEG stream helper ─────────────────────────────────────────────────────────
def _gen_frames(queue):
    last_frame = None
    while True:
        try:
            from queue import Empty
            frame = queue.get(timeout=0.1)
            last_frame = frame
        except Exception:
            if last_frame is None:
                time.sleep(0.05)
                continue
            frame = last_frame
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            continue
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n'


# ── Routes ──────────────────────────────────────────────────────────────────────
@app.route('/')
def dashboard():
    peers = {}
    for name, url in list(found_servers.items()):
        try:
            r = requests.get(f"{url}/ping", timeout=0.5)
            peers[name] = {'url': url, 'status': 'Online' if r.status_code == 200 else f'HTTP {r.status_code}', 'ok': r.status_code == 200}
        except Exception:
            peers[name] = {'url': url, 'status': 'Unreachable', 'ok': False}
    return render_template('index.html',
                           this_name=THIS_NAME,
                           this_ip=my_ip,
                           this_port=THIS_PORT,
                           peers=peers)


@app.route('/ping')
def ping():
    return f"{THIS_NAME} alive"


@app.route('/video_feed/0')
def video_feed_cam0():
    from camera_threads import frame_queue
    return Response(_gen_frames(frame_queue),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/video_feed/1')
def video_feed_cam1():
    from camera_threads import frame_queue2
    return Response(_gen_frames(frame_queue2),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/status')
def status():
    import state
    import mode_manager
    from stats import get_cpu_temp, get_system_stats, get_local_ip
    cpu_temp    = get_cpu_temp()
    cpu, ram    = get_system_stats()
    return jsonify({
        'name':     THIS_NAME,
        'ip':       get_local_ip(),
        'mode':     mode_manager.current_mode().name,
        'cpu_temp': cpu_temp,
        'cpu':      round(cpu, 1),
        'ram':      round(ram, 1),
        'sensors': {
            'Photo':    getattr(state, 'photoValue',       '—'),
            'UV':       getattr(state, 'uvValue',          '—'),
            'Metal':    getattr(state, 'metalValue',       '—'),
            'Ball Sw':  getattr(state, 'ballSwitchValue',  '—'),
            'Motion':   getattr(state, 'motionValue',      '—'),
            'LF L':     getattr(state, 'lfLeftValue',      '—'),
            'LF M':     getattr(state, 'lfMidValue',       '—'),
            'LF R':     getattr(state, 'lfRightValue',     '—'),
            'Laser':    getattr(state, 'laserValue',       '—'),
            'US0':      getattr(state, 'ultrasonic0Value', '—'),
            'US1':      getattr(state, 'ultrasonic1Value', '—'),
            'AX':       getattr(state, 'mpu_ax',           '—'),
            'AY':       getattr(state, 'mpu_ay',           '—'),
            'AZ':       getattr(state, 'mpu_az',           '—'),
            'GX':       getattr(state, 'mpu_gx',           '—'),
            'GY':       getattr(state, 'mpu_gy',           '—'),
            'GZ':       getattr(state, 'mpu_gz',           '—'),
            'Status':   getattr(state, 'systemStatus',     '—'),
        },
    })


# ── Entry point ──────────────────────────────────────────────────────────────────
def run_flask_server():
    try:
        app.run(host='0.0.0.0', port=THIS_PORT, debug=False, threaded=True)
    finally:
        print(f"[{THIS_NAME}] Shutting down Zeroconf...")
        zeroconf.unregister_service(zc_info)
        zeroconf.close()


if __name__ == '__main__':
    run_flask_server()
