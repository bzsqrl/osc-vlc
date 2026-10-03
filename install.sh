#!/usr/bin/env bash
# Installer for the OSC/GPIO video player on Raspberry Pi OS Desktop.
#
# Copy this folder to the Pi, then from inside it run, as the user the desktop
# logs in as (NOT with sudo; it asks for your password when it needs it):
#
#     bash install.sh [options]
#
# Safe to run again, e.g. to update after copying over newer files.
#
# Options:
#   --desktop-icon   also put the start and stop icons on the desktop
#   --4k60           Pi 4 / 400 only: enable 4K 60 Hz HDMI output (edits config.txt)
#   --no-system      skip the steps that need sudo (packages, auto login,
#                    screen blanking, --4k60)
#   --uninstall      remove the player (keeps ~/Videos and ~/venv)
#   -h, --help       show this help

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FILES=(osc_vlc_player.py osc-vlc-player.service osc-vlc-player.desktop
       osc-vlc-player-launcher.desktop osc-vlc-player-stop.desktop)
PACKAGES=(vlc python3-venv python3-gpiozero python3-lgpio)
PIP_PACKAGES=(python-osc python-vlc)

SERVICE=osc-vlc-player.service
SERVICE_DIR="$HOME/.config/systemd/user"
AUTOSTART_DIR="$HOME/.config/autostart"
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
VIDEOS_DIR="$HOME/Videos"
VENV="$HOME/venv"

DESKTOP_ICON=false
HDMI_4K60=false
SYSTEM=true
UNINSTALL=false
REBOOT=false

step() { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '    WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Copy a file, dropping Windows line endings in case it was edited on a PC.
put() {  # put SRC DEST_DIR [MODE]
    local dest="$2/$(basename "$1")"
    sed 's/\r$//' "$1" > "$dest.tmp" && mv "$dest.tmp" "$dest"
    chmod "${3:-644}" "$dest"
}

for arg in "$@"; do
    case "$arg" in
        --desktop-icon) DESKTOP_ICON=true ;;
        --4k60)         HDMI_4K60=true ;;
        --no-system)    SYSTEM=false ;;
        --uninstall)    UNINSTALL=true ;;
        -h|--help)      sed -n '2,/^$/s/^# \{0,1\}//p' "$0"; exit 0 ;;
        *)              die "unknown option: $arg (see bash install.sh --help)" ;;
    esac
done

# --- checks -------------------------------------------------------------------

[ "$(id -u)" -ne 0 ] || die "run this as your normal user, not with sudo:  bash install.sh"

MODEL=""
[ -r /proc/device-tree/model ] && MODEL="$(tr -d '\0' < /proc/device-tree/model)"
if [[ "$MODEL" == "Raspberry Pi"* ]]; then
    echo "Installing the OSC video player for $USER on: $MODEL"
else
    warn "this doesn't look like a Raspberry Pi; continuing anyway"
fi

# --- uninstall ----------------------------------------------------------------

if $UNINSTALL; then
    step "Removing the video player"
    systemctl --user stop "$SERVICE" 2>/dev/null || true
    rm -f "$SERVICE_DIR/$SERVICE" "$AUTOSTART_DIR/osc-vlc-player.desktop" \
          "$APPS_DIR"/osc-vlc-player-{launcher,stop}.desktop \
          "$DESKTOP_DIR"/osc-vlc-player-{launcher,stop}.desktop
    # don't delete the script if this folder *is* the home folder
    [ "$SRC" = "$HOME" ] || rm -f "$HOME/osc_vlc_player.py"
    systemctl --user daemon-reload 2>/dev/null || true
    note "Done. Kept your videos in $VIDEOS_DIR, the Python environment in $VENV"
    note "(remove it with: rm -rf ~/venv) and the auto login / screen blanking settings."
    exit 0
fi

for f in "${FILES[@]}"; do
    [ -f "$SRC/$f" ] || die "$f is missing; run this from the folder with the player files"
done

# --- system settings (sudo) -----------------------------------------------------

if $SYSTEM; then
    step "Checking system packages (may ask for your password)"
    missing=()
    for p in "${PACKAGES[@]}"; do
        dpkg -s "$p" > /dev/null 2>&1 || missing+=("$p")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        note "installing: ${missing[*]}"
        { sudo apt-get update && sudo apt-get install -y "${missing[@]}"; } ||
            warn "couldn't install ${missing[*]}; the player may not work"
    else
        note "all present"
    fi

    # An early version of the player ran as a system-wide service
    if compgen -G "/etc/systemd/system/osc-vlc-player@*" > /dev/null ||
       compgen -G "/etc/systemd/system/*/osc-vlc-player@*" > /dev/null; then
        step "Removing the old system-wide service from an earlier version"
        for unit in $(systemctl list-units --all --plain --no-legend 'osc-vlc-player@*' |
                      awk '{print $1}'); do
            sudo systemctl disable --now "$unit" || true
        done
        sudo rm -f /etc/systemd/system/osc-vlc-player@.service \
                   /etc/systemd/system/*/osc-vlc-player@*.service
        sudo systemctl daemon-reload
    fi

    if command -v raspi-config > /dev/null; then
        step "Setting the desktop to log in automatically as $USER"
        # takes effect at the next boot; the player can still start right now
        sudo raspi-config nonint do_boot_behaviour B4 ||
            warn "couldn't set auto login; use raspi-config > System Options > Boot / Auto Login"
        step "Turning off screen blanking"
        sudo raspi-config nonint do_blanking 1 ||
            warn "couldn't turn off blanking; use raspi-config > Display Options > Screen Blanking"
    else
        warn "raspi-config not found: set Desktop Autologin and turn off Screen Blanking yourself"
    fi

    if $HDMI_4K60; then
        step "Enabling 4K 60 Hz HDMI output"
        if [[ "$MODEL" == *"Pi 4"* || "$MODEL" == *"Pi 400"* || "$MODEL" == *"Compute Module 4"* ]]; then
            CONFIG=/boot/firmware/config.txt
            [ -f "$CONFIG" ] || CONFIG=/boot/config.txt
            if grep -q '^hdmi_enable_4kp60=1' "$CONFIG"; then
                note "already enabled"
            else
                printf '\n[all]\nhdmi_enable_4kp60=1\n' | sudo tee -a "$CONFIG" > /dev/null
                note "added hdmi_enable_4kp60=1 to $CONFIG (use the HDMI 0 port)"
                REBOOT=true
            fi
        else
            note "only needed on a Pi 4 / 400; skipped"
        fi
    fi
else
    step "Skipping system settings (--no-system)"
    note "make sure these are installed: ${PACKAGES[*]}"
fi

# --- player files ---------------------------------------------------------------

step "Installing the player files"
mkdir -p "$SERVICE_DIR" "$AUTOSTART_DIR" "$APPS_DIR" "$VIDEOS_DIR"
[ "$SRC" = "$HOME" ] || put "$SRC/osc_vlc_player.py" "$HOME"
put "$SRC/osc-vlc-player.service" "$SERVICE_DIR"
put "$SRC/osc-vlc-player.desktop" "$AUTOSTART_DIR"
put "$SRC/osc-vlc-player-launcher.desktop" "$APPS_DIR"
put "$SRC/osc-vlc-player-stop.desktop" "$APPS_DIR"
note "script:      ~/osc_vlc_player.py"
note "service:     ~/.config/systemd/user/$SERVICE"
note "autostart:   ~/.config/autostart/osc-vlc-player.desktop"
note "menu:        Sound & Video > Video Player (OSC) / Stop Video Player (OSC)"
if $DESKTOP_ICON; then
    mkdir -p "$DESKTOP_DIR"
    put "$SRC/osc-vlc-player-launcher.desktop" "$DESKTOP_DIR" 755
    put "$SRC/osc-vlc-player-stop.desktop" "$DESKTOP_DIR" 755
    note "desktop icons: start and stop, in $DESKTOP_DIR"
fi

# --- Python environment ---------------------------------------------------------

step "Setting up the Python environment in ~/venv"
if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv --system-site-packages "$VENV"
elif grep -q '^include-system-site-packages = false' "$VENV/pyvenv.cfg" 2>/dev/null; then
    # gpiozero comes from the system packages, so the venv must be able to see them
    sed -i 's/^include-system-site-packages = false/include-system-site-packages = true/' \
        "$VENV/pyvenv.cfg"
    note "enabled system packages in the existing ~/venv"
fi
"$VENV/bin/pip" install --quiet --disable-pip-version-check --upgrade "${PIP_PACKAGES[@]}"
if "$VENV/bin/python" -c "import vlc, pythonosc" 2> /dev/null; then
    note "python-vlc and python-osc OK"
else
    warn "python-vlc / python-osc didn't import; check the output above"
fi
"$VENV/bin/python" -c "import gpiozero" 2> /dev/null && note "gpiozero OK" ||
    warn "gpiozero not available: GPIO buttons won't work (OSC still will)"

systemctl --user daemon-reload

# --- start ----------------------------------------------------------------------

shopt -s nullglob nocaseglob
videos=("$VIDEOS_DIR"/*.{mp4,mkv,mov,avi,m4v,webm,mpg,mpeg,ts,wmv})
shopt -u nullglob nocaseglob

if [ ${#videos[@]} -eq 0 ]; then
    step "No videos yet"
    note "Put your videos in $VIDEOS_DIR, then start the player from the menu"
    note "(Sound & Video > Video Player (OSC)) or reboot."
elif [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ] && ! $REBOOT; then
    step "Starting the player with ${#videos[@]} video(s)"
    systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY 2> /dev/null || true
    systemctl --user restart "$SERVICE"
    sleep 3
    if systemctl --user is-active --quiet "$SERVICE"; then
        note "running"
    else
        warn "it didn't start; see: journalctl --user -u osc-vlc-player -n 30"
    fi
fi

# --- summary --------------------------------------------------------------------

IP="$(hostname -I 2> /dev/null | awk '{print $1}')"
[ -n "$IP" ] || IP="<the Pi's IP address>"
step "Installed"
note "TouchOSC connection: host $IP, send port 9000, receive port 9001"
note "                     (for player N of several: connection N, receive port 9000 + N)"
note "Live log:            journalctl --user -u osc-vlc-player -f"
note "Uninstall:           bash install.sh --uninstall"
if $REBOOT; then
    echo
    echo "    Reboot to finish (sudo reboot). The player starts automatically."
elif [ -z "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ] && [ ${#videos[@]} -gt 0 ]; then
    echo
    echo "    Reboot, or log in to the desktop, to start the player."
fi
