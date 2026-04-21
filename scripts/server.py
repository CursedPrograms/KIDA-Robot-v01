#server.py

from flask import Flask, render_template_string
import requests
import socket
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

app = Flask(__name__)

# --- CONFIGURATION ---
THIS_NAME = "KIDA01"
THIS_PORT = 5004
TYPE      = "_flask-link._tcp.local."

found_servers = {}

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()

my_ip = get_ip()
print(f"Starting {THIS_NAME} on {my_ip}:{THIS_PORT}")

class MyListener:
    def remove_service(self, zc, type_, name):
        short = name.split('.')[0]
        found_servers.pop(short, None)

    def add_service(self, zc, type_, name):
        self.update_service(zc, type_, name)

    def update_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info:
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            if addresses:
                short = name.split('.')[0]
                if short != THIS_NAME:
                    found_servers[short] = f"http://{addresses[0]}:{info.port}"

# --- SINGLE Zeroconf instance ---
zeroconf = Zeroconf()
zc_info  = ServiceInfo(
    TYPE,
    f"{THIS_NAME}.{TYPE}",
    addresses=[socket.inet_aton(my_ip)],
    port=THIS_PORT,
    properties={'version': '1.0'},
)
zeroconf.register_service(zc_info)
ServiceBrowser(zeroconf, TYPE, MyListener())

@app.route("/")
def dashboard():
    status_html = (
        f'<div style="margin:10px;">'
        f'<span style="color:green;">●</span> <b>{THIS_NAME}</b> '
        f'(Self — {my_ip}:{THIS_PORT})</div>'
    )

    for name in list(found_servers.keys()):
        url = found_servers[name]
        try:
            r = requests.get(f"{url}/ping", timeout=0.5)
            colour = "green" if r.status_code == 200 else "orange"
            label  = "Online" if r.status_code == 200 else f"HTTP {r.status_code}"
        except Exception:
            colour = "red"
            label  = "Unreachable"
        status_html += (
            f'<div style="margin:10px;">'
            f'<span style="color:{colour};">●</span> '
            f'<b>{name}</b> {label} — {url}</div>'
        )

    return render_template_string(f"""
        <html>
          <head>
            <title>{THIS_NAME} — Active Network</title>
            <script>setTimeout(function(){{ window.location.reload(1); }}, 3000);</script>
          </head>
          <body style="text-align:center;font-family:sans-serif;padding-top:50px;background:#f4f4f9;">
            <div style="display:inline-block;padding:20px;border-radius:15px;background:white;
                        box-shadow:0 4px 6px rgba(0,0,0,0.1);">
              <h1>Active Network</h1>
              <p style="color:gray;font-size:0.8em;">Zeroconf type: {TYPE}</p>
              <hr>
              {status_html}
            </div>
          </body>
        </html>
    """) # delete this it should load ../templates/index.html

@app.route("/ping")
def ping():
    return f"{THIS_NAME} alive"

if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=THIS_PORT, debug=False, threaded=True)
    finally:
        print(f"[{THIS_NAME}] Shutting down Zeroconf...")
        zeroconf.unregister_service(zc_info)
        zeroconf.close()
