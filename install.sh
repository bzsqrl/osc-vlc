#!/usr/bin/env bash
# Installer for the OSC/GPIO video player on Raspberry Pi OS (Desktop or Lite).
#
# Copy this folder to the Pi, then from inside it run, as your normal user
# (NOT with sudo; it asks for your password when it needs it):
#
#     bash install.sh [options]
#
# Safe to run again, e.g. to update after copying over newer files.
#
# Two ways to run the player:
#   desktop  plays in a fullscreen window on the desktop (needs Raspberry Pi OS
#            with desktop). Fine on a Pi 4 or 5.
#   lite     no desktop: starts at boot and draws straight to the screen. Much
#            lighter; use it for smooth playback on a Pi Zero, 2 or 3. Works on
#            Raspberry Pi OS Lite, or on a desktop install (the desktop is then
#            turned off at boot; switch back with --desktop).
# Without --lite / --desktop it picks lite on a Pi 3B+ or older (they can't play
# smoothly through the desktop) and on Raspberry Pi OS Lite, and desktop
# otherwise. A mode chosen with --lite / --desktop is remembered by later runs.
#
# Options:
#   --lite           use lite mode (see above)
#   --desktop        use desktop mode (see above)
#   --desktop-icon   desktop mode: also put the start and stop icons on the desktop
#   --no-4k60        Pi 4 / 400: don't enable 4K 60 Hz HDMI output (otherwise the
#                    installer adds hdmi_enable_4kp60=1 to config.txt)
#   --no-system      skip the steps that need sudo (packages, boot settings,
#                    screen blanking, 4K 60 Hz)
#   --uninstall      remove the player (keeps ~/Videos and ~/venv)
#   -h, --help       show this help
#
# The player plays ~/Videos, or the videos on a USB drive while one is plugged
# in. In lite mode the installer adds a udev rule that mounts USB drives.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FILES=(osc_vlc_player.py osc-vlc-player.service osc-vlc-player.desktop
       osc-vlc-player-launcher.desktop osc-vlc-player-stop.desktop
       osc-vlc-usb-mount 99-osc-vlc-usb.rules)
PACKAGES=(vlc python3-venv python3-gpiozero python3-lgpio)
PIP_PACKAGES=(python-osc python-vlc)

SERVICE=osc-vlc-player.service
SERVICE_DIR="$HOME/.config/systemd/user"
AUTOSTART_DIR="$HOME/.config/autostart"
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
VIDEOS_DIR="$HOME/Videos"
VENV="$HOME/venv"
MODE_FILE="$HOME/.config/osc-vlc-player/mode"  # mode chosen with --lite / --desktop
# Pi 1, 2, 3 (incl. 3B+), Zero, Zero 2 W, CM1, CM3: too slow for video on the desktop
OLDER_PI='Pi (Model|Zero|2 |3 )|Compute Module (Rev|3)'
# lite mode: mount USB drives (the desktop does this itself)
USB_RULE=/etc/udev/rules.d/99-osc-vlc-usb.rules
USB_MOUNT=/usr/local/sbin/osc-vlc-usb-mount
# kernel options for lite mode: no console blanking, cursor or boot logo
CMDLINE_OPTIONS=(consoleblank=0 vt.global_cursor_default=0 logo.nologo)

MODE=""
DESKTOP_ICON=false
HDMI_4K60=auto     # auto: on for a Pi 4 / 400 / CM4, unless config.txt says otherwise
SYSTEM=true
UNINSTALL=false
REBOOT=false        # a reboot is needed before the player can run
BOOT_CHANGED=false  # boot settings changed; they apply at the next boot

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

desktop_installed() {
    [ -x /usr/sbin/lightdm ] || dpkg -s raspberrypi-ui-mods > /dev/null 2>&1
}

desktop_running() {
    pgrep -x labwc > /dev/null || pgrep -x wayfire > /dev/null || pgrep -x Xorg > /dev/null
}

remove_usb_mounting() {
    if [ -e "$USB_RULE" ] || [ -e "$USB_MOUNT" ]; then
        sudo rm -f "$USB_RULE" "$USB_MOUNT" && sudo udevadm control --reload-rules
    fi
}

for arg in "$@"; do
    case "$arg" in
        --lite)         MODE=lite ;;
        --desktop)      MODE=desktop ;;
        --desktop-icon) DESKTOP_ICON=true ;;
        --4k60)         HDMI_4K60=true ;;  # overrides hdmi_enable_4kp60=0
        --no-4k60)      HDMI_4K60=false ;;
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
    systemctl --user disable --now "$SERVICE" 2>/dev/null || true
    rm -f "$SERVICE_DIR/$SERVICE" "$AUTOSTART_DIR/osc-vlc-player.desktop" \
          "$APPS_DIR"/osc-vlc-player-{launcher,stop}.desktop \
          "$DESKTOP_DIR"/osc-vlc-player-{launcher,stop}.desktop
    # don't delete the script if this folder *is* the home folder
    [ "$SRC" = "$HOME" ] || rm -f "$HOME/osc_vlc_player.py"
    rm -rf "$(dirname "$MODE_FILE")"
    remove_usb_mounting || warn "couldn't remove $USB_RULE and $USB_MOUNT"
    systemctl --user daemon-reload 2>/dev/null || true
    note "Done. Kept your videos in $VIDEOS_DIR, the Python environment in $VENV"
    note "(remove it with: rm -rf ~/venv) and the boot / screen blanking settings."
    exit 0
fi

for f in "${FILES[@]}"; do
    [ -f "$SRC/$f" ] || die "$f is missing; run this from the folder with the player files"
done

# --- mode ---------------------------------------------------------------------

SAVED_MODE=""
[ -r "$MODE_FILE" ] && SAVED_MODE="$(cat "$MODE_FILE")"
if [ -n "$MODE" ]; then
    WHY="chosen with --$MODE"
elif [ "$SAVED_MODE" = lite ] || [ "$SAVED_MODE" = desktop ]; then
    MODE="$SAVED_MODE"; WHY="chosen earlier with --$MODE"
elif [[ "$MODEL" =~ $OLDER_PI ]]; then
    MODE=lite; WHY="recommended for this model; use --desktop to override"
elif systemctl --user is-enabled --quiet "$SERVICE" 2> /dev/null; then
    MODE=lite; WHY="already installed in lite mode"
elif [ -f "$AUTOSTART_DIR/osc-vlc-player.desktop" ]; then
    MODE=desktop; WHY="already installed in desktop mode"
elif desktop_installed; then
    MODE=desktop; WHY="desktop found"
else
    MODE=lite; WHY="no desktop found"
fi
if [ "$MODE" = desktop ] && ! desktop_installed; then
    die "desktop mode needs Raspberry Pi OS with desktop; this looks like Lite (use --lite)"
fi
if [ "$MODE" = lite ]; then
    echo "Mode: lite, $WHY (no desktop; the player starts at boot and draws straight to the screen)"
else
    echo "Mode: desktop, $WHY (the player runs fullscreen on the desktop)"
fi
if [[ "$WHY" == "chosen with"* ]]; then
    mkdir -p "$(dirname "$MODE_FILE")" && echo "$MODE" > "$MODE_FILE"
fi

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

    if [ "$MODE" = lite ]; then
        step "Starting the player at boot, without logging in"
        sudo loginctl enable-linger "$USER" ||
            warn "couldn't enable lingering; the player will only start once you log in"

        if desktop_installed && command -v raspi-config > /dev/null &&
           [ "$(systemctl get-default 2> /dev/null)" = graphical.target ]; then
            step "Turning off the desktop at boot (bash install.sh --desktop turns it back on)"
            sudo raspi-config nonint do_boot_behaviour B1 ||
                warn "couldn't change it; use raspi-config > System Options > Boot / Auto Login > Console"
            BOOT_CHANGED=true
            desktop_running && REBOOT=true  # the desktop holds the screen until then
        fi

        step "Mounting USB drives when they're plugged in"
        # copied with put() via a temp folder: it needs sudo to write there
        tmp="$(mktemp -d)"
        put "$SRC/osc-vlc-usb-mount" "$tmp" 755
        put "$SRC/99-osc-vlc-usb.rules" "$tmp"
        if sudo install -m 755 "$tmp/osc-vlc-usb-mount" "$USB_MOUNT" &&
           sudo install -m 644 "$tmp/99-osc-vlc-usb.rules" "$USB_RULE" &&
           sudo udevadm control --reload-rules; then
            # mount any drive that's already plugged in
            sudo udevadm trigger --action=add --subsystem-match=block || true
            note "drives are mounted read-only under /media/usb/"
        else
            warn "couldn't set it up; videos on USB drives won't be found"
        fi
        rm -rf "$tmp"

        step "Hiding the text console behind the video"
        CMDLINE=/boot/firmware/cmdline.txt
        [ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
        if [ -f "$CMDLINE" ]; then
            added=()
            for opt in "${CMDLINE_OPTIONS[@]}"; do
                grep -qw -- "$opt" "$CMDLINE" || added+=("$opt")
            done
            if [ ${#added[@]} -gt 0 ]; then
                # cmdline.txt must stay a single line
                sudo sed -i "1 s/\$/ ${added[*]}/" "$CMDLINE"
                note "added to $CMDLINE: ${added[*]}"
                BOOT_CHANGED=true
            else
                note "already set"
            fi
        else
            warn "cmdline.txt not found; the console cursor may show between videos"
        fi
    elif command -v raspi-config > /dev/null; then
        remove_usb_mounting || true  # left from lite mode; the desktop mounts drives
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

    # A Pi 4 outputs 4K at only 30 Hz unless this is set (it raises the GPU
    # clock), so 4K60 videos would show at 30 fps. The Pi 5 doesn't need it.
    if [[ "$MODEL" == *"Pi 4"* || "$MODEL" == *"Compute Module 4"* ]]; then
        CONFIG=/boot/firmware/config.txt
        [ -f "$CONFIG" ] || CONFIG=/boot/config.txt
        current="$(grep -o '^hdmi_enable_4kp60=[0-9]*' "$CONFIG" 2> /dev/null | tail -n 1 || true)"
        if [ "$HDMI_4K60" = false ]; then
            if [ "$current" = hdmi_enable_4kp60=1 ]; then
                note "4K 60 Hz output is still on: remove hdmi_enable_4kp60=1 from $CONFIG to turn it off"
            fi
        elif [ "$current" = hdmi_enable_4kp60=1 ]; then
            step "4K 60 Hz HDMI output: already on"
        elif [ ! -f "$CONFIG" ]; then
            warn "config.txt not found; add hdmi_enable_4kp60=1 to it for 4K 60 Hz output"
        elif [ -n "$current" ] && [ "$HDMI_4K60" = auto ]; then
            step "4K 60 Hz HDMI output: left off ($current in $CONFIG; --4k60 turns it on)"
        else
            step "Enabling 4K 60 Hz HDMI output (--no-4k60 skips this)"
            if [ -n "$current" ]; then
                sudo sed -i 's/^hdmi_enable_4kp60=[0-9]*/hdmi_enable_4kp60=1/' "$CONFIG"
            else
                printf '\n[all]\nhdmi_enable_4kp60=1\n' | sudo tee -a "$CONFIG" > /dev/null
            fi
            note "added hdmi_enable_4kp60=1 to $CONFIG"
            note "for 4K at 60 Hz, plug the screen into HDMI 0 (on a Pi 4, the port next to the power socket)"
            BOOT_CHANGED=true
        fi
    elif [ "$HDMI_4K60" = true ]; then
        note "--4k60 is only needed on a Pi 4 / 400; skipped"
    fi
else
    step "Skipping system settings (--no-system)"
    note "make sure these are installed: ${PACKAGES[*]}"
    if [ "$MODE" = lite ]; then
        note "and run: sudo loginctl enable-linger $USER   (to start at boot)"
        note "USB drives are not mounted automatically without the system steps"
    fi
fi

# --- player files ---------------------------------------------------------------

step "Installing the player files"
mkdir -p "$SERVICE_DIR" "$VIDEOS_DIR"
[ "$SRC" = "$HOME" ] || put "$SRC/osc_vlc_player.py" "$HOME"
put "$SRC/osc-vlc-player.service" "$SERVICE_DIR"
note "script:      ~/osc_vlc_player.py"
note "service:     ~/.config/systemd/user/$SERVICE"
if [ "$MODE" = lite ]; then
    # the desktop entries would start a second copy if the desktop came back
    rm -f "$AUTOSTART_DIR/osc-vlc-player.desktop" \
          "$APPS_DIR"/osc-vlc-player-{launcher,stop}.desktop \
          "$DESKTOP_DIR"/osc-vlc-player-{launcher,stop}.desktop
else
    mkdir -p "$AUTOSTART_DIR" "$APPS_DIR"
    put "$SRC/osc-vlc-player.desktop" "$AUTOSTART_DIR"
    put "$SRC/osc-vlc-player-launcher.desktop" "$APPS_DIR"
    put "$SRC/osc-vlc-player-stop.desktop" "$APPS_DIR"
    note "autostart:   ~/.config/autostart/osc-vlc-player.desktop"
    note "menu:        Sound & Video > Video Player (OSC) / Stop Video Player (OSC)"
    if $DESKTOP_ICON; then
        mkdir -p "$DESKTOP_DIR"
        put "$SRC/osc-vlc-player-launcher.desktop" "$DESKTOP_DIR" 755
        put "$SRC/osc-vlc-player-stop.desktop" "$DESKTOP_DIR" 755
        note "desktop icons: start and stop, in $DESKTOP_DIR"
    fi
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
if [ "$MODE" = lite ]; then
    systemctl --user enable "$SERVICE" 2> /dev/null ||
        warn "couldn't enable the service; run: systemctl --user enable osc-vlc-player"
    # forget any desktop display passed to systemd earlier, so VLC uses the screen
    systemctl --user unset-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY 2> /dev/null || true
else
    # desktop mode: started by the autostart entry, not at boot
    systemctl --user disable "$SERVICE" 2> /dev/null || true
fi

# --- start ----------------------------------------------------------------------

shopt -s nullglob nocaseglob
videos=("$VIDEOS_DIR"/*.{mp4,mkv,mov,avi,m4v,webm,mpg,mpeg,ts,wmv})
shopt -u nullglob nocaseglob

start_player() {
    step "Starting the player"
    systemctl --user restart "$SERVICE"
    sleep 3
    if systemctl --user is-active --quiet "$SERVICE"; then
        note "running"
    else
        warn "it didn't start; see: journalctl --user -u osc-vlc-player -n 30"
    fi
}

STARTED=false
if [ ${#videos[@]} -eq 0 ]; then
    step "No videos yet"
    note "Put your videos in $VIDEOS_DIR, or on a USB drive (in its top folder)."
    note "The player waits for them and starts playing once they're there."
fi
if $REBOOT; then
    :  # started after the reboot
elif [ "$MODE" = lite ]; then
    start_player; STARTED=true
elif [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]; then
    systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY 2> /dev/null || true
    start_player; STARTED=true
fi

# --- summary --------------------------------------------------------------------

IP="$(hostname -I 2> /dev/null | awk '{print $1}')"
[ -n "$IP" ] || IP="<the Pi's IP address>"
step "Installed ($MODE mode)"
note "TouchOSC connection: host $IP, send port 9000, receive port 9001"
note "                     (for player N of several: connection N, receive port 9000 + N)"
note "Live log:            journalctl --user -u osc-vlc-player -f"
note "Stop / start:        systemctl --user stop osc-vlc-player / start osc-vlc-player"
note "Uninstall:           bash install.sh --uninstall"
if $REBOOT; then
    echo
    echo "    Reboot to finish (sudo reboot). The player starts automatically."
elif $BOOT_CHANGED; then
    echo
    echo "    Boot settings changed; they take effect at the next reboot."
elif [ "$MODE" = desktop ] && ! $STARTED; then
    echo
    echo "    Reboot, or log in to the desktop, to start the player."
fi
