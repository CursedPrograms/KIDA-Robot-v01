# flask_server.py — KIDA web control server
import queue
from flask import Flask, render_template, jsonify, request
from stats import stats_lock, system_stats

app = Flask(__name__, static_folder='static', template_folder='templates')
command_queue = queue.Queue()


@app.route('/control/stats/', methods=['GET'])
def control_stats():
    with stats_lock:
        return jsonify({'stats': system_stats.copy()})


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/status')
def status():
    return jsonify({'status': 'online', 'robot': 'KIDA', 'message': 'All systems go!'})


@app.route('/command', methods=['POST'])
def receive_command():
    data = request.get_json()
    command = data.get('command')
    command_queue.put(command)
    return jsonify({'received': command, 'status': 'queued'})


def run_flask_server():
    app.run(host='0.0.0.0', port=5000, debug=False)
