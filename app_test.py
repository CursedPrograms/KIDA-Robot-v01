from flask import Flask, render_template_string
import requests
import socket
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser
import threading

app = Flask(__name__)

# --- CONFIGURATION ---
THIS_NAME = "KIDA01"  # Change per app
THIS_PORT = 5004      # Change per app
TYPE = "_flask-link._tcp.local."

found_servers = {}

def get_ip():
    """Helper to find the actual local network IP address"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

class MyListener:
    def remove_service(self, zeroconf, type, name):
        short_name = name.split('.')[0]
        if short_name in found_servers:
            del found_servers[short_name]

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            # Convert binary IP to string
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            if addresses:
                short_name = name.split('.')[0]
                if short_name != THIS_NAME:
                    found_servers[short_name] = f"http://{addresses[0]}:{info.port}"

# --- ZEROCONF SETUP ---
my_ip = get_ip()
print(f"Starting {THIS_NAME} on {my_ip}:{THIS_PORT}")

zeroconf = Zeroconf()
info = ServiceInfo(
    TYPE,
    f"{THIS_NAME}.{TYPE}",
    addresses=[socket.inet_aton(my_ip)],
    port=THIS_PORT,
    properties={'version': '1.0'}
)
zeroconf.register_service(info)
browser = ServiceBrowser(zeroconf, TYPE, MyListener())

@app.route("/")
def dashboard():
    status_html = f'<div style="margin:10px;"><span style="color:green;">●</span> <b>{THIS_NAME}</b> (Self)</div>'

    # Copy dict keys to avoid "dictionary changed size during iteration" errors
    for name in list(found_servers.keys()):
        url = found_servers[name]
        try:
            r = requests.get(f"{url}/ping", timeout=0.5)
            if r.status_code == 200:
                status_html += f'<div style="margin:10px;"><span style="color:green;">●</span> <b>{name}</b> Online</div>'
        except:
            continue

    return render_template_string(f"""
        <html>
            <head>
                <script>
                    setTimeout(function(){{ window.location.reload(1); }}, 3000);
                </script>
            </head>
            <body style="text-align:center; font-family:sans-serif; padding-top:50px; background-color:#f4f4f9;">
                <div style="display:inline-block; padding:20px; border-radius:15px; background:white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    <h1>Active Network</h1>
                    <p style="color:gray; font-size:0.8em;">My IP: {my_ip}</p>
                    <hr>
                    {status_html}
                </div>
            </body>
        </html>
    """)

@app.route("/ping")
def ping():
    return f"{THIS_NAME} alive"

if __name__ == "__main__":
    try:
        # Use threaded=True so the ping requests don't block the UI
        app.run(host="0.0.0.0", port=THIS_PORT, debug=False, threaded=True)
    finally:
        print("Shutting down...")
        zeroconf.unregister_service(info)
        zeroconf.close()
