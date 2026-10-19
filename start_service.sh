#!/bin/bash
# start_service.sh - what the kida service runs at boot (install_service.sh sets it up).
# Points the HUD at whichever Wayland socket the desktop made (wayland-0, or wayland-1
# after the desktop restarted), then starts KIDA as run.sh does. By hand, use run.sh.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

for s in "$XDG_RUNTIME_DIR"/wayland-*; do
    case "$s" in
        *.lock) ;;
        *) if [ -S "$s" ]; then export WAYLAND_DISPLAY="$(basename "$s")"; break; fi ;;
    esac
done

exec /bin/bash ./run.sh
