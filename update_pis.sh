#!/usr/bin/env bash
# Update the video player on several Raspberry Pis at once: on each Pi, runs
# "git pull" in the player folder, then "bash install.sh", then restarts the
# player. Run it from WSL (Ubuntu), or any Linux or macOS computer:
#
#     bash update_pis.sh                 # every Pi in update_pis.conf
#     bash update_pis.sh 192.168.1.52    # just these Pis
#     bash update_pis.sh --reboot        # reboot the Pis instead
#
# The Pis and their username are set in update_pis.conf (created from
# update_pis.conf.example on the first run). It asks for the Pis' password
# once (the same on all of them) and updates all the Pis at the same time.
#
# Needs sshpass:  sudo apt install sshpass

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$HERE/update_pis.conf"

if [ ! -f "$CONF" ]; then
    cp "$HERE/update_pis.conf.example" "$CONF"
    echo "Created $CONF"
    echo "Fill in your Pis' username and IP addresses there, then run this again."
    exit 1
fi
PI_USER=""
PIS=()
REPO_DIR="osc-vlc"
# shellcheck source=/dev/null
source <(sed 's/\r$//' "$CONF")  # in case it was saved with Windows line endings

REBOOT=0
if [ "${1:-}" = --reboot ]; then
    REBOOT=1; shift
fi
[ $# -gt 0 ] && PIS=("$@")
if [ -z "$PI_USER" ] || [[ "$PI_USER" == CHANGE_ME* ]]; then
    echo "Set PI_USER in $CONF first."; exit 1
fi
for pi in "${PIS[@]}"; do
    [[ "$pi" == CHANGE_ME* ]] && { echo "Fill in the IP addresses in $CONF first."; exit 1; }
done
[ ${#PIS[@]} -gt 0 ] || { echo "No Pis listed in $CONF."; exit 1; }
command -v sshpass > /dev/null || {
    echo "This needs sshpass. Install it with:  sudo apt install sshpass"; exit 1; }

read -rs -p "Password for $PI_USER on the Pis: " PASSWORD; echo
[ -n "$PASSWORD" ] || { echo "No password entered."; exit 1; }

# accept-new: trust a Pi the first time it's seen, but refuse one whose key
# has changed since (a reinstalled Pi: see the README)
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10
          -o ServerAliveInterval=15 -o LogLevel=ERROR)

# Run on each Pi. It gets the password, folder and whether to reboot on its
# first three input lines (so they never appear on a command line), then
# this script.
read -r -d '' REMOTE <<'EOF'
cd "$HOME/$OSC_DIR" 2> /dev/null || { echo "ERROR: there's no ~/$OSC_DIR folder"; exit 70; }
echo "== git pull"
git pull --ff-only < /dev/null || { echo "ERROR: git pull failed"; exit 71; }
# install.sh uses sudo: answer its password prompts from OSC_PW
askpass="$(mktemp)" && chmod 700 "$askpass"
trap 'rm -f "$askpass"' EXIT
printf '#!/bin/sh\nprintf "%%s\\n" "$OSC_PW"\n' > "$askpass"
export SUDO_ASKPASS="$askpass"
sudo() { command sudo -A "$@"; }
export -f sudo
sudo -v < /dev/null 2> /dev/null || { echo "ERROR: sudo didn't accept the password"; exit 72; }
echo "== bash install.sh"
# the player is (re)started below, once, rather than also by install.sh
OSC_SKIP_START=1 bash install.sh < /dev/null || exit
if [ "$OSC_REBOOT" = 1 ]; then
    echo "== rebooting"
    # in a few seconds, so this connection can finish cleanly first
    sudo systemd-run --on-active=3 systemctl reboot > /dev/null 2>&1 < /dev/null ||
        { echo "ERROR: couldn't reboot it"; exit 73; }
    exit 0
fi
# Lite mode: the player runs at boot. Desktop mode: it runs in the desktop
# session, which has handed its display to systemd when it logged in.
service=osc-vlc-player
if ! systemctl --user is-enabled --quiet "$service" 2> /dev/null &&
   ! systemctl --user show-environment 2> /dev/null | grep -qE '^(WAYLAND_)?DISPLAY='; then
    echo "NOTE: the desktop isn't logged in; the player starts when it is"
    exit 75
fi
echo "== restarting the player"
systemctl --user restart "$service" < /dev/null
sleep 3
systemctl --user is-active --quiet "$service" ||
    { echo "ERROR: the player didn't start: journalctl --user -u $service -n 30"; exit 74; }
EOF

LOGS="$(mktemp -d)"

update_one() {
    local pi="$1"
    { printf '%s\n%s\n%s\n' "$PASSWORD" "$REPO_DIR" "$REBOOT"; printf '%s\n' "$REMOTE"; } |
        SSHPASS="$PASSWORD" sshpass -e ssh "${SSH_OPTS[@]}" "$PI_USER@$pi" \
            'IFS= read -r OSC_PW; IFS= read -r OSC_DIR; IFS= read -r OSC_REBOOT
             export OSC_PW OSC_DIR OSC_REBOOT; exec bash -s' 2>&1 |
        tee "$LOGS/$pi.log" | sed -u "s/^/[$pi] /"
    echo "${PIPESTATUS[1]}" > "$LOGS/$pi.status"
}

echo "Updating ${#PIS[@]} Pi(s): ${PIS[*]}"
for pi in "${PIS[@]}"; do
    update_one "$pi" &
done
wait

echo
echo "===== Summary ====="
failed=0
for pi in "${PIS[@]}"; do
    status="$(cat "$LOGS/$pi.status" 2> /dev/null || echo 1)"
    case "$status" in
        0)   if [ "$REBOOT" = 1 ]; then
                 result="updated, rebooting (playing again in about a minute)"
             else
                 result="updated, player restarted"
                 if grep -q "Reboot to finish\|take effect at the next reboot" "$LOGS/$pi.log"; then
                     result="$result; some settings apply after a reboot: ssh -t $PI_USER@$pi sudo reboot"
                 fi
             fi ;;
        5)   result="FAILED: wrong password" ;;
        255) result="FAILED: couldn't connect (switched off, or wrong address?)"
             if grep -q "IDENTIFICATION HAS CHANGED" "$LOGS/$pi.log"; then
                 result="FAILED: its SSH key has changed (reinstalled?): run ssh-keygen -R $pi, then try again"
             fi ;;
        70)  result="FAILED: no ~/$REPO_DIR folder on it" ;;
        71)  result="FAILED: git pull failed (see its output above)" ;;
        72)  result="FAILED: sudo didn't accept the password" ;;
        73)  result="updated, but couldn't reboot it: ssh -t $PI_USER@$pi sudo reboot" ;;
        74)  result="updated, but the player didn't start again (see its output above)" ;;
        75)  result="updated; the player starts when the desktop logs in (or reboot it)" ;;
        *)   result="FAILED: install.sh stopped with an error (exit $status; see its output above)" ;;
    esac
    [ "$status" = 0 ] || failed=$((failed + 1))
    printf '  %-18s %s\n' "$pi" "$result"
done
echo "Full output of each Pi: $LOGS"
[ "$failed" = 0 ]
