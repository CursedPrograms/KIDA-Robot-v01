# server.py — Flask web server for KIDA
# Serves the HUD dashboard at http://<ip>:5004/
# Provides MJPEG streams (/video_feed/0 and /video_feed/1) and a /status JSON endpoint.

import zlib
import os
import socket
import time
import cv2
import requests
from flask import Flask, render_template, Response, jsonify, request, send_file
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

import fleet_register
from fleet_near import FleetNear

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


# Which robots are nearby: Bluetooth LE beacons from NORA, WHIP and the other KIDA,
# heard by the Pi's own Bluetooth (fleet_near.py), and this robot's beacon for them.
near = FleetNear(THIS_NAME).start()


@app.route('/near')
def near_robots():
    return jsonify(near.status())


@app.route('/ping')
def ping():
    return f"{THIS_NAME} alive"


@app.route('/video_feed/0')
def video_feed_cam0():
    from camera_threads import frame_queue_web
    return Response(_gen_frames(frame_queue_web),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/video_feed/1')
def video_feed_cam1():
    from camera_threads import frame_queue2_web
    return Response(_gen_frames(frame_queue2_web),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/last_photo')
def last_photo():
    import camera_memory
    path, _ = camera_memory.get_last_photo()
    if not path or not os.path.isfile(path):
        return '', 204
    return send_file(path)


@app.route('/character_face')
def character_face():
    # KIDA's avatar (her human representation) first, the old character art as a fallback
    for face_path in (os.path.join(_here, '..', 'images', 'kida_avatar.jpeg'),
                      os.path.join(_here, '..', 'images', 'characters', 'KIDA002.jpeg')):
        if os.path.isfile(face_path):
            return send_file(face_path)
    return '', 404


def _pose_json() -> dict:
    try:
        import odometry
        return odometry.summary()
    except Exception:
        return {}


def _person_now():
    import state
    name = getattr(state, 'person_name', None)
    return name if name and time.time() - getattr(state, 'person_seen_ts', 0) < 90 else None


@app.route('/odometry')
def odometry_route():
    # where she thinks she is, and the path she's driven (for the web map)
    import odometry
    return jsonify({**odometry.summary(), 'trail': odometry.trail()[-800:]})


@app.route('/routes')
def routes_route():
    import routes
    return jsonify({'routes': routes.list_routes(), 'status': routes.status()})


@app.route('/daylog')
def daylog_route():
    # ?date=YYYY-MM-DD (default today): the day's record, its summary, and the days on file
    import daylog
    return jsonify({**daylog.day(request.args.get('date') or None), 'days': daylog.days()})


def _rumble_json() -> dict:
    try:
        import haptics
        low, high, reason = haptics.level()
    except Exception:
        low, high, reason = 0.0, 0.0, ''
    return {'low': low, 'high': high, 'reason': reason}


@app.route('/mind')
def mind_status():
    # /mind?act=<move>&steps=1-4: the PC mind host's moves in MIND mode (kida_drive_mind.py).
    if 'act' in request.args:
        import kida_drive_mind
        out, code = kida_drive_mind.pc_move(request.remote_addr, request.args.get('act', ''),
                                            request.args.get('steps', '1'))
        return jsonify(out), code
    # Otherwise: KIDA's inner life (kida_mind): mood, needs, thoughts, dreams, goals.
    import kida_mind_host
    if kida_mind_host.MIND is None:
        return jsonify({'error': 'inner life unavailable'}), 503
    import state
    status = kida_mind_host.MIND.status()
    status['sleeping'] = kida_mind_host.is_sleeping()
    status['person'] = _person_now()
    status['last_exchange'] = getattr(state, 'last_exchange', None)
    return jsonify(status)


@app.route('/haptics')
def haptics_route():
    # Tiny sibling of /status for the website's gamepad, which polls it
    # every few hundred ms — /status is far too heavy for that rate.
    return jsonify(_rumble_json())


@app.route('/status')
def status():
    import state
    import mode_manager
    import web_bridge
    import camera_memory
    import camera_actions
    from stats import get_cpu_temp, get_system_stats, get_local_ip
    cpu_temp    = get_cpu_temp()
    cpu, ram    = get_system_stats()
    _, last_photo_ts = camera_memory.get_last_photo()
    # Her settings in one number (WHIP's rev): a page or program sees at once that something changed elsewhere
    rev = zlib.crc32(repr([mode_manager.current_mode().name, state.voice_mode.name, getattr(state, 'motorSpeedValue', 0),
                           getattr(state, 'drive_scheme', ''), getattr(state, 'inference_on', False),
                           getattr(state, 'motor_lock', False)]).encode())
    return jsonify({
        'rev':          rev,
        'name':         THIS_NAME,
        'ip':           get_local_ip(),
        'mode':         mode_manager.current_mode().name,
        'voice_mode':   state.voice_mode.name,
        'cpu_temp':     cpu_temp,
        'cpu':          round(cpu, 1),
        'ram':          round(ram, 1),
        'motor_speed':  getattr(state, 'motorSpeedValue', '—'),
        'music_on':     web_bridge.music_playing(),
        'inference_on': getattr(state, 'inference_on', False),
        'motor_lock':   getattr(state, 'motor_lock', False),
        'tipped':       getattr(state, 'tipped', False),
        'drive_scheme': getattr(state, 'drive_scheme', 'WASD'),
        'active_cam_id': camera_actions.active_cam_id,
        'last_photo_ts': last_photo_ts,
        'bus_v':        round(getattr(state, 'bus_v',   0.0), 2),
        'cur_ma':       round(getattr(state, 'cur_ma',  0.0), 1),
        'pwr_w':        round(getattr(state, 'pwr_w',   0.0), 2),
        'bat_pct':      round(getattr(state, 'bat_pct', 0.0), 0),
        'rumble':       _rumble_json(),
        'pose':         _pose_json(),
        'person':       _person_now(),
        **_mind_fields(),
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


@app.route('/action', methods=['POST'])
def action():
    try:
        import web_bridge
        data     = request.get_json(force=True) or {}
        cmd      = data.get('command', '')
        password = data.get('password')
        ok       = web_bridge.action(cmd, password=password,
                                     left=data.get('left'), right=data.get('right'),
                                     angle=data.get('angle'),
                                     throttle=data.get('throttle'), turn=data.get('turn'),
                                     name=data.get('name'), text=data.get('text'))
        return jsonify({'ok': ok, 'command': cmd})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Talking with DREAM (peer_talk.py) ──────────────────────────────────────────
# When RIFT pairs her with another robot that has a mind, they play rock paper
# scissors and the winner picks words (her Piper voice) or Brainfuck (the buzzer).
# Only while nobody is with her and nobody is driving her.
import peer_talk

PEER_PERSONA = ("a small robot who drives around the house: you look around through your cameras, "
                "patrol, follow people, and keep an eye on your battery.")
_peer_until = 0.0   # she's saying a line to another robot until then


def _peer_available():
    import kida_mind_host as host
    import web_bridge
    mine = time.time() < _peer_until
    if host.is_sleeping():
        return False, "asleep"
    if web_bridge.is_driving():
        return False, "someone's driving me"
    if host._present and not mine:
        return False, "someone's here"
    if host._busy and not mine:
        return False, "busy"
    return True, "alone"


def _peer_speak(text):
    global _peer_until
    import kida_chat_wakeword
    _peer_until = time.time() + 120
    try:
        kida_chat_wakeword.say_and_wait(text, timeout=90)
    finally:
        _peer_until = time.time() + 5


def _peer_chirp(u):
    import web_bridge
    return web_bridge.action('chirp', text=str(u))


def _peer_generate(prompt, **kw):
    import kida_mind_host
    if kida_mind_host.mind_llm is not None:
        return kida_mind_host.mind_llm.generate(prompt, **kw)
    options = {'temperature': kw.get('temperature', 0.7), 'num_predict': kw.get('num_predict', 70)}
    if kw.get('stop'):
        options['stop'] = kw['stop']
    r = requests.post('http://localhost:11434/api/generate', timeout=kw.get('timeout', 90),
                      json={'model': 'qwen2.5:0.5b', 'prompt': prompt, 'stream': False, 'options': options})
    return r.json().get('response', '')


def _peer_thought(text, kind):
    from kida_mind.reflection import add_thought
    add_thought(text, kind)


def _peer_body():
    import state
    import mode_manager
    body = {'mode': mode_manager.current_mode().name.lower()}
    bat = getattr(state, 'bat_pct', None)
    if bat:
        body['battery'] = round(bat)
    return body


import kida_mind_host   # noqa: E402 (already loaded by kida_chat_wakeword; MIND is None if it failed)

PEER = peer_talk.PeerTalk(THIS_NAME, PEER_PERSONA, kida_mind_host.MIND, _peer_generate, _peer_thought,
                          _peer_speak, _peer_chirp, _peer_available, extra=_peer_body)
peer_talk.register_routes(app, PEER)


# ── Music together (RIFT conducts; fleet_music.py) ───────────────────────────────
# POST {"action": "play"|"pause"|"resume"|"stop", "track": 7, "at": RIFT's time}; GET: what's playing.
# RIFT's clock is on :5000 of whoever sent it (only RIFT conducts).
import fleet_music   # noqa: E402


@app.route('/music', methods=['GET', 'POST'])
def music_together():
    if request.method == 'GET':
        return jsonify(fleet_music.status())
    out, code = fleet_music.command(request.get_json(silent=True) or {}, f"http://{request.remote_addr}:5000")
    return jsonify(out), code


@app.route('/chirp')
def chirp():
    # RIFT's fleet conversations: /chirp?u=<0-16> says that utterance (a
    # Brainfuck phrase, beeped on the buzzer). `from` is only for the log.
    import web_bridge
    ok = web_bridge.action('chirp', text=request.args.get('u'))
    return jsonify({'ok': ok}), (200 if ok else 400)


@app.route('/voice_upload', methods=['POST'])
def voice_upload():
    # A workaround for the robot's own USB mic being too quiet: record on
    # whatever mic the browser has (phone/laptop, usually much better) and
    # upload the clip instead of speaking at the robot directly. Runs
    # through the exact same Whisper→voice_commands→LLM pipeline the
    # wake-word loop uses (see kida_chat_wakeword.transcribe_file).
    try:
        f = request.files.get('audio')
        if not f:
            return jsonify({'ok': False, 'error': 'no audio file in request'}), 400
        import web_bridge
        text = web_bridge.transcribe_upload(f)
        return jsonify({'ok': True, 'transcribed': text})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── MIND mode (kida_drive_mind.py): an LLM drives her, her PC's or her own ──────────
# The fleet's contract: a PC that can think unlocks with ctl=1 and checks in on
# /status?ctl=1; /mode?m=mind; the PC's moves on /mind?act=&steps=; /speak plays its WAV.
_ctl_ips: set = set()   # PCs that unlocked as a mind host


def _mind_fields() -> dict:
    import kida_drive_mind
    if request.args.get('ctl') == '1' and request.remote_addr in _ctl_ips:
        kida_drive_mind.check_in(request.remote_addr)
    return kida_drive_mind.status_fields()


@app.route('/unlock')
def unlock():
    # The PIN is a safety catch (her motor lock), not security. With ctl=1 a PC
    # signs in as her mind host and her motor lock is left as it is (unlocking
    # her wheels stays something a person does: U, the button, the IR remote).
    import config
    import motor_lock
    if request.args.get('pw') != config.MOTOR_LOCK_PASSWORD:
        return jsonify({'ok': False, 'error': 'wrong PIN'}), 403
    if request.args.get('ctl') == '1':
        import kida_drive_mind
        _ctl_ips.add(request.remote_addr)
        kida_drive_mind.check_in(request.remote_addr)
    else:
        motor_lock.try_unlock(request.args.get('pw'))
    return jsonify({'ok': True, 'motor_lock': motor_lock.is_locked()})


@app.route('/mode')
def set_mode_route():
    m = (request.args.get('m') or '').lower()
    import web_bridge
    if m == 'mind':
        ok = web_bridge.action('mode_9')
        return jsonify({'ok': ok, 'error': None if ok else 'no mind can drive her now'}), (200 if ok else 409)
    numbers = {'keyboard': 1, 'kb': 1, 'ir': 2, 'auto': 3, 'idle': 4, 'line': 5,
               'watchdog': 6, 'lane': 7, 'follow': 8}
    if m not in numbers:
        return jsonify({'ok': False, 'error': 'm is mind, keyboard, ir, auto, idle, line, watchdog, lane or follow'}), 400
    return jsonify({'ok': web_bridge.action(f'mode_{numbers[m]}')})


@app.route('/speak', methods=['POST'])
def speak():
    # A WAV from the PC's mind (mind.windows_wav), played on her voice channel.
    import io
    import pygame
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.Channel(7).play(pygame.mixer.Sound(io.BytesIO(request.get_data())))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


# ── Options (config.json), from any browser or the PC controller ──────────────────
# GET /options is the page; /options.json is the file and the choices; POST saves it
# (her PIN, the safety catch; config.json.bak keeps the old one). Most settings take
# effect when she restarts.
_ROOT = os.path.dirname(_here)


def _read_json(name, default):
    import json
    try:
        with open(os.path.join(_ROOT, name), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


@app.route('/options')
def options_page():
    return render_template('options.html', this_name=THIS_NAME)


@app.route('/options.json', methods=['GET', 'POST'])
def options_json():
    import json
    import shutil
    import config
    if request.method == 'GET':   # json.dumps, not jsonify: that would sort her sections
        return Response(json.dumps({'config': _read_json('config.json', {}),
                                    'choices': _read_json('options_choices.json', {})}, ensure_ascii=False),
                        mimetype='application/json')
    body = request.get_json(force=True, silent=True) or {}
    if str(body.get('password', '')) != config.MOTOR_LOCK_PASSWORD:
        return jsonify({'ok': False, 'error': 'wrong PIN'}), 403
    new = body.get('config')
    if not isinstance(new, dict) or not isinstance(new.get('Config'), dict):
        return jsonify({'ok': False, 'error': 'config must be {"Config": {...}}'}), 400
    path = os.path.join(_ROOT, 'config.json')
    if os.path.exists(path):
        shutil.copy(path, path + '.bak')
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(new, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(path + '.tmp', path)
    print(f"⚙️  Options saved from {request.remote_addr} (config.json.bak is the old one)")
    return jsonify({'ok': True})


# ── Entry point ──────────────────────────────────────────────────────────────────
def run_flask_server():
    fleet_register.start_fleet_heartbeat(THIS_NAME)
    import nina_report
    nina_report.start(zeroconf)   # her state and distances to NINA every 15 s, once RIFT is found
    try:
        app.run(host='0.0.0.0', port=THIS_PORT, debug=False, threaded=True)
    finally:
        print(f"[{THIS_NAME}] Shutting down Zeroconf...")
        zeroconf.unregister_service(zc_info)
        zeroconf.close()


if __name__ == '__main__':
    run_flask_server()
