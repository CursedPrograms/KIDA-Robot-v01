# options_link.py — her options (config.json) from the PC controller: O / the Options button
#
# Fetches her config.json from her Flask server (/options.json), opens it in the
# repo's options.py (the same menu as on her), and when you've changed something
# main.py asks for her PIN and this POSTs it back (she keeps config.json.bak).
# Most settings take effect when she restarts.

import json
import os
import subprocess
import sys
import tempfile
import threading

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class OptionsLink:
    def __init__(self, remote):
        self.remote = remote
        self.busy = False
        self.pending = None    # an edited config.json waiting for her PIN
        self.message = ""

    def open(self):
        if self.busy or self.pending is not None:
            return
        self.busy = True
        threading.Thread(target=self._edit, daemon=True, name="options").start()

    def _edit(self):
        try:
            r = requests.get(f"{self.remote.base_url}/options.json", timeout=3)
            before = r.json()["config"]
            folder = tempfile.mkdtemp(prefix="kida-options-")
            path = os.path.join(folder, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(before, f, indent=2, ensure_ascii=False)
            subprocess.run([sys.executable, os.path.join(_ROOT, "options.py"), path])
            with open(path, encoding="utf-8") as f:
                after = json.load(f)
            if after != before:
                self.pending = after
                self.message = "Her PIN to save the options"
            else:
                self.message = "Options: nothing changed"
        except Exception as e:
            self.message = f"Options: {e}"
        finally:
            self.busy = False
        print(f"⚙️  {self.message}")

    def send(self, pin, data):
        try:
            r = requests.post(f"{self.remote.base_url}/options.json",
                              json={"password": pin, "config": data}, timeout=5)
            j = r.json()
            self.message = ("Options saved: restart her for most of it to take effect" if j.get("ok")
                            else f"Options not saved: {j.get('error')}")
        except Exception as e:
            self.message = f"Options not saved: {e}"
        print(f"⚙️  {self.message}")
