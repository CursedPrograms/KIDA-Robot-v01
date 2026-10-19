#!/bin/bash
# KIDA-01 autostart — installs (or replaces) the kida systemd service that launches run.sh at boot.
#
#   sudo ./install_service.sh              install + enable + start
#   sudo ./install_service.sh --uninstall  stop, disable and remove
#
# Handy afterwards:
#   sudo systemctl status kida      is it running?
#   journalctl -u kida -f           live log
#   sudo systemctl restart kida     restart after pulling new code
#   sudo systemctl stop kida        stop it to run things by hand (frees GPIO/camera)

set -e

SERVICE_NAME="kida"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [ "$EUID" -ne 0 ]; then
    echo "Run with sudo: sudo ./install_service.sh $*"
    exit 1
fi

if [ "$1" = "--uninstall" ]; then
    systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    echo "✔ ${SERVICE_NAME} service removed"
    exit 0
fi

# Repo root = where this script lives
REPO_DIR="$(dirname "$(readlink -f "$0")")"

# Run as the user who called sudo (not root), so files, audio and the
# desktop session all belong to the right account
RUN_USER="${SUDO_USER:-$(logname 2>/dev/null)}"
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = "root" ]; then
    echo "Couldn't tell which user to run as — run this with sudo from your normal account."
    exit 1
fi
RUN_UID="$(id -u "$RUN_USER")"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"

if [ ! -f "$REPO_DIR/run.sh" ]; then
    echo "run.sh not found in $REPO_DIR"
    exit 1
fi

# Fix Windows line endings (a CRLF shebang won't run) and make the scripts executable
for f in "$REPO_DIR"/*.sh; do
    sed -i 's/\r$//' "$f"
    chmod +x "$f"
done

# The fleet's WiFi ladder (scripts/fleet_ladder.py) changes the WiFi from inside the service,
# which NetworkManager only allows a desktop user: ladder_setup.sh adds the polkit rule for it.
if [ -f "$REPO_DIR/ladder_setup.sh" ]; then
    SUDO_USER="$RUN_USER" bash "$REPO_DIR/ladder_setup.sh" \
        || echo "(ladder_setup.sh failed: KIDA still runs, she just can't move the WiFi)"
fi

# Hardware access: GPIO (motors, sensors, servo), SPI (LED strip),
# video (camera), audio (ALSA), i2c — only the groups that exist on this Pi
for grp in gpio spi video audio i2c render input dialout; do   # dialout: her Arduino on USB serial
    if getent group "$grp" >/dev/null; then
        usermod -aG "$grp" "$RUN_USER"
    fi
done

echo "=== Writing $SERVICE_FILE (user=$RUN_USER, repo=$REPO_DIR) ==="
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=KIDA-01 robot
After=graphical.target network-online.target sound.target
Wants=graphical.target network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO_DIR

# The HUD is a fullscreen pygame window, so it needs the desktop session's
# display. These cover both Wayland (Pi OS Bookworm) and X11 (older Pi OS).
Environment=XDG_RUNTIME_DIR=/run/user/$RUN_UID
Environment=DISPLAY=:0
Environment=XAUTHORITY=$RUN_HOME/.Xauthority
Environment=PYTHONUNBUFFERED=1

# Wait for the desktop to come up before starting (TimeoutStartSec caps the
# wait; if it times out, Restart= tries again)
ExecStartPre=/bin/sh -c 'until [ -S /run/user/$RUN_UID/wayland-0 ] || [ -S /run/user/$RUN_UID/wayland-1 ] || [ -S /tmp/.X11-unix/X0 ]; do sleep 1; done'
TimeoutStartSec=90
ExecStart=/bin/bash $REPO_DIR/start_service.sh

# Come back if it crashes (or started before the display was ready),
# but not if you quit her with Q (run.sh stops on that: exit 99)
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo
echo "✔ KIDA-01 will now start automatically at boot."
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$IP" ] && echo "  Dashboard: http://$IP:5004"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    journalctl -u $SERVICE_NAME -f"
echo "  Remove:  sudo ./install_service.sh --uninstall"
echo
echo "Make sure the Pi boots to the desktop with auto-login (sudo raspi-config →"
echo "System Options → Boot / Auto Login → Desktop Autologin), since the HUD needs it."
echo "If $RUN_USER was just added to new groups, reboot once for that to take effect."
