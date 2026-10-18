#!/bin/bash
# ladder_setup.sh - let KIDA change her own WiFi for the fleet's ladder (scripts/fleet_ladder.py).
# Her service runs as you, not root, and NetworkManager only lets a logged-in desktop user change
# the WiFi. This polkit rule lets your user do it from the service too. Run once: sudo ./ladder_setup.sh
# Undo: sudo rm /etc/polkit-1/rules.d/50-fleet-ladder.rules
set -e
RUN_USER="${SUDO_USER:-$USER}"
RULE=/etc/polkit-1/rules.d/50-fleet-ladder.rules
if [ "$(id -u)" -ne 0 ]; then echo "Run it with sudo: sudo ./ladder_setup.sh"; exit 1; fi
cat > "$RULE" <<RULE_EOF
// The fleet's WiFi ladder: $RUN_USER may join and host WiFi networks (KIDA's fleet_ladder.py).
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") == 0 && subject.user == "$RUN_USER") {
        return polkit.Result.YES;
    }
});
RULE_EOF
chmod 644 "$RULE"
systemctl restart polkit 2>/dev/null || true
echo "Done: $RUN_USER can change the WiFi. Try it: python3 scripts/fleet_ladder.py KIDA00 (a look, changes nothing)"
