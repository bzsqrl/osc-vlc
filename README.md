# OSC Video Player for Raspberry Pi

A fullscreen video player for Raspberry Pi OS. It plays every video in
`~/Videos`, or on a plugged-in USB drive, as a playlist and is controlled over
the network with OSC (e.g. from TouchOSC) and/or with physical buttons and a
rotary encoder.

- **Playback control:** play/pause, previous/next, seek, skip, scrub, speed,
  volume, loop modes and A-B loops.
- **Ready-made TouchOSC layout:** controls up to 10 Pis, one page each, plus a
  page that controls them all at once.
- **Hardware controls:** GPIO buttons and a rotary encoder for seeking.
- **Sync:** one button lines up every Pi on the network on the same playback
  position, and LOCK keeps them in step with gentle speed adjustments.
- **USB drives:** plug in a drive with videos and it plays those instead,
  until it's pulled out again.
- **Unattended use:** starts fullscreen at boot and restarts itself after a crash.
- **Desktop or Lite:** runs on Raspberry Pi OS with desktop, or without one
  (Lite) for smooth playback on older Pis.
- **Pi models:** works on every model from the Pi Zero to the Pi 5, and warns in the log about
  videos a model can't decode smoothly.
- **One-step install:** run `bash install.sh` on the Pi.

Built on VLC ([python-vlc](https://pypi.org/project/python-vlc/)) and
[python-osc](https://pypi.org/project/python-osc/).

| File | What it is |
|---|---|
| `osc_vlc_player.py` | The player |
| `install.sh` | Installer (section 1) |
| `osc-vlc-player.service` | systemd user service that runs the player |
| `osc-vlc-player.desktop` | Autostart entry that starts the service at login |
| `osc-vlc-player-launcher.desktop`, `osc-vlc-player-stop.desktop` | Start / stop entries for the desktop menu |
| `osc-vlc-usb-mount`, `99-osc-vlc-usb.rules` | Lite mode: mount USB drives when they're plugged in |
| `osc_vlc_player.tosc` | TouchOSC layout for tablets (section 2) |
| `osc_vlc_player_phone.tosc` | TouchOSC layout for phones, portrait (section 2) |
| `build_touchosc_layout.py`, `build_touchosc_phone.py` | Generate the two TouchOSC layouts |

Released under the [MIT License](LICENSE).

---

## 1. Install

### Username
The player works with any username. There is nothing to edit in the files.
Install it as your normal user (usually `pi`, or whatever was set in
Raspberry Pi Imager). It runs as that user and plays that user's `~/Videos` folder. In this guide, `~`
means that user's home folder, e.g. `/home/pi`.

Run the installer as that user, never with `sudo`. It asks for your password
itself for the few steps that need it.

### Desktop or Lite
The player can run in two ways. The installer picks one for you, and you can
switch at any time.

| | **Desktop mode** | **Lite mode** |
|---|---|---|
| **Runs on** | Raspberry Pi OS with desktop | Raspberry Pi OS Lite, or a desktop install with the desktop turned off |
| **How it shows video** | Fullscreen window on the desktop | Straight to the screen, with no desktop in between |
| **Playback** | Smooth on a Pi 4 / 5 | Smooth on every model: lighter and faster |
| **Starts at boot** | Once the desktop has logged in | Straight away, no login needed |
| **Desktop menu entries** | Yes | No (use TouchOSC or the commands below) |
| **Recommended for** | Pi 4 / 5, if you want the desktop | Pi Zero, 2 and 3, and any unattended player |

On a **Pi Zero, 2 or 3, use Lite mode**: going through the desktop drops
frames even with videos those models can play. The installer picks it for
you on these models.

The installer chooses the mode like this:
- **Pi 3B+ and older** (Pi 1, 2, 3, Zero, Zero 2 W): Lite mode, even if the
  desktop is installed. The desktop is turned off at boot.
- **Pi 4 and 5:** Desktop mode if the desktop is installed, otherwise Lite.

To choose for yourself:
- `bash install.sh --lite` switches to Lite mode, even on a desktop install. It
  sets the Pi to boot to the text console instead of the desktop, so there's no
  need to reinstall the OS.
- `bash install.sh --desktop` switches to Desktop mode, e.g. to keep the
  desktop on a Pi 3. The desktop returns at the next boot.

A mode chosen with `--lite` or `--desktop` is remembered, so later runs (e.g.
to update) keep it. Without one, the rules above apply each time. So rerunning
the installer on a Pi 3 that was set up in Desktop mode by an older version of
the installer switches it to Lite, unless you add `--desktop`.

### Quick install
1. **Copy the player files to a folder on the Pi:** `install.sh`,
   `osc_vlc_player.py`, `osc-vlc-player.service`, `osc-vlc-player.desktop`,
   `osc-vlc-player-launcher.desktop` and `osc-vlc-player-stop.desktop`. Use a USB stick, or run these from a
   Windows PowerShell prompt in the folder that has them. Replace
   `<pi-address>` with the Pi's hostname or IP, and `pi` with your username if
   it's different:
   ```
   ssh pi@<pi-address> mkdir -p osc-vlc-player
   scp install.sh osc_vlc_player.py osc-vlc-player.service osc-vlc-player.desktop osc-vlc-player-launcher.desktop osc-vlc-player-stop.desktop pi@<pi-address>:osc-vlc-player/
   ```
2. **On the Pi**, open a terminal and run:
   ```bash
   cd ~/osc-vlc-player
   bash install.sh
   ```
3. **Add videos** to `~/Videos` (mp4, mkv, mov, avi, m4v, webm, mpg, ts, wmv),
   or put them on a USB drive (see *Playing from a USB drive* below).
   They play in alphabetical order, so prefix names with numbers to set the order
   (`01-intro.mp4`, `02-main.mp4`, ...). Which formats play smoothly depends
   on the Pi model; see **section 5**.
4. **Reboot** (`sudo reboot`). The player starts fullscreen and plays the
   whole playlist on a loop: in Desktop mode once the desktop loads, in Lite
   mode straight after boot. The installer has usually started it already,
   unless it said a reboot is needed. With no videos yet, it waits for them.

At the end, the installer prints the settings for TouchOSC (section 2).

**What the installer does:**
- **System packages:** installs any that are missing (`vlc`, `python3-venv`,
  `python3-gpiozero`, `python3-lgpio`).
- **Old version:** removes the system-wide service from an early version of
  the player, if it finds one.
- **Unattended use, Desktop mode:** sets the desktop to log in automatically
  as you, and turns off screen blanking.
- **Unattended use, Lite mode:** starts the player at boot without anyone
  logging in. It turns off the desktop at boot if there is one, and hides the
  text console's cursor, boot logo and blanking (it adds
  `consoleblank=0 vt.global_cursor_default=0 logo.nologo` to
  `/boot/firmware/cmdline.txt`).
- **4K at 60 Hz, Pi 4 / 400:** adds `hdmi_enable_4kp60=1` to
  `/boot/firmware/config.txt` (applies at the next reboot). Without it a Pi 4
  outputs 4K at only 30 Hz, so 4K60 videos show at 30 fps. It raises the GPU
  clock, so the Pi runs a little warmer. Skip it with `--no-4k60`; if
  `config.txt` already has `hdmi_enable_4kp60=0`, the installer leaves that
  alone unless you use `--4k60`. The Pi 5 doesn't need it.
- **Wi-Fi:** turns off Wi-Fi power saving
  (`/etc/NetworkManager/conf.d/osc-vlc-wifi-powersave.conf`). With it on, the
  Pi can hold incoming messages back for a few hundred milliseconds, making
  TouchOSC sluggish and LOCK less exact.
- **USB drives, Lite mode:** adds a udev rule (`/etc/udev/rules.d/99-osc-vlc-usb.rules`,
  with `/usr/local/sbin/osc-vlc-usb-mount`) that mounts USB drives when
  they're plugged in. On the desktop, the desktop does this itself.
- **Player files:** copies the script to `~/osc_vlc_player.py` and the service
  to `~/.config/systemd/user/`. In Desktop mode it also adds the autostart
  entry to `~/.config/autostart/` and the menu entries for starting and
  stopping it to `~/.local/share/applications/`. It removes any Windows line
  endings on the way.
- **Python:** creates `~/venv` (or fixes an existing one so it can see
  gpiozero) and installs `python-osc` and `python-vlc` into it.
- **Start:** starts the player right away (in Desktop mode, only when run
  from the desktop).

**Options:**
| Option | Effect |
|---|---|
| `--lite` | Use Lite mode (see *Desktop or Lite*) |
| `--desktop` | Use Desktop mode |
| `--desktop-icon` | Desktop mode: also put the start and stop icons on the desktop |
| `--no-4k60` | Pi 4 / 400: don't turn on 4K 60 Hz output (see *What the installer does*) |
| `--no-system` | Skip everything that needs `sudo` |
| `--uninstall` | Remove the player. Keeps `~/Videos`, `~/venv` and the system settings |

**To update** after changing any of the files, copy the folder over again and
rerun `bash install.sh`. It's safe to run as often as you like.

### Playing from a USB drive
Like [Raspberry Pi Video Looper](https://videolooper.de/), the player can play
videos straight from a USB drive:
- Put the videos in the drive's **top folder** (not in a subfolder). Videos
  in subfolders are ignored.
- **Plug it in**, before or after the player starts. Within a couple of
  seconds the player switches to the drive's videos and plays them from the
  first one, as a playlist in alphabetical order.
- **Pull it out** and the player goes back to the videos in `~/Videos`. It
  only reads the drive, so it's safe to pull out at any time.
- A drive with no videos in its top folder is ignored, and `~/Videos` keeps
  playing. If several drives with videos are plugged in, the first one (in
  order of the name it's mounted under) is used.

Format the drive as **FAT32** or **exFAT** (most drives come that way; both
work with Windows and Mac) or ext4. The log shows where the videos come from,
e.g. `loaded 3 video(s) from USB drive /media/usb/sda1:`.

How it finds the drive: in Desktop mode the desktop mounts drives under
`/media/<your username>/`; in Lite mode the installer's udev rule mounts them,
read-only, under `/media/usb/`. The player plays from any drive mounted under
`/media`. To turn this off, add `--no-usb` to the end of the `ExecStart=` line
in the service file (see *Troubleshooting*, *Picture shape*, for how).

### Quit and start again
**To quit**, use any of these:
- the **QUIT PLAYER** button in TouchOSC (tap it twice)
- **Sound & Video → Stop Video Player (OSC)** from the menu (Desktop mode)
- `systemctl --user stop osc-vlc-player` in a terminal or over SSH

The video window's own close button (×) and the taskbar's **Close** do
nothing. VLC ignores them when another program is controlling it.

After quitting, the player stays quit until you start it again or reboot.
It only restarts by itself after a crash.

**To start it again in Lite mode**, run `systemctl --user start osc-vlc-player`
(over SSH, or after logging in at the Pi's console), or reboot.

**To start it again in Desktop mode**, choose **Sound & Video → Video Player (OSC)** from the
menu, or double-click the desktop icon if you installed it with
`--desktop-icon`. If the player is already running, this restarts it, which is
also how to pick up newly added videos. When you double-click a desktop icon,
the file manager may ask whether to execute it.
To stop it asking, turn on *Don't ask options on launch executable file* in
File Manager → Edit → Preferences.

### Manual install
If you'd rather not use the installer, these are the equivalent steps. Run
them from the player folder:
```bash
sudo apt install vlc python3-venv python3-gpiozero python3-lgpio
mkdir -p ~/Videos ~/.config/systemd/user ~/.config/autostart ~/.local/share/applications
cp osc_vlc_player.py ~/
cp osc-vlc-player.service ~/.config/systemd/user/
cp osc-vlc-player.desktop ~/.config/autostart/
cp osc-vlc-player-launcher.desktop osc-vlc-player-stop.desktop ~/.local/share/applications/
python3 -m venv --system-site-packages ~/venv
~/venv/bin/pip install python-osc python-vlc
systemctl --user daemon-reload
```
Then, in `sudo raspi-config`, set System Options → Boot / Auto Login →
**Desktop Autologin** and Display Options → Screen Blanking → **Off**, and
reboot.

For **Lite mode**, skip the three `.desktop` files and the raspi-config
settings above. Instead, run:
```bash
sudo loginctl enable-linger $USER          # start user services at boot
systemctl --user enable osc-vlc-player
sudo raspi-config nonint do_boot_behaviour B1   # only on a desktop install: boot to console
```
Then add `consoleblank=0 vt.global_cursor_default=0 logo.nologo` to the end of
the single line in `/boot/firmware/cmdline.txt`. To play from USB drives,
install the rule that mounts them:
```bash
sudo install -m 755 osc-vlc-usb-mount /usr/local/sbin/
sudo install -m 644 99-osc-vlc-usb.rules /etc/udev/rules.d/
```
Then reboot.

### Useful commands
```bash
systemctl --user status osc-vlc-player       # is it running?
systemctl --user restart osc-vlc-player      # restart (e.g. after adding videos)
systemctl --user stop osc-vlc-player         # stop (e.g. to use the desktop)
systemctl --user start osc-vlc-player        # start again
journalctl --user -u osc-vlc-player -f       # live log of every command received
hostname -I                                  # the Pi's IP address, for TouchOSC
```
**Changing the videos without restarting the player:** press **STOP** in
TouchOSC, add or remove videos in `~/Videos` (or on the USB drive), then press
**PLAY**. Playing from stopped re-reads the videos first, and the log lists
the new playlist. It carries on with the video it was on if that's still
there, and otherwise starts from the first. (PLAY while playing or paused
doesn't re-read, so it never interrupts a video.) A player with no videos at
all picks them up as soon as they appear, and USB drives are picked up when
they're plugged in.

### Troubleshooting
- **Which mode is it running in?** The log's first lines say
  `desktop session found: playing in a fullscreen window` or
  `no desktop session: VLC draws straight to the screen`.
- **Lite mode, no picture:** the log says `warning: the video is playing but
  VLC couldn't open the screen to show it`. Usually the desktop is still
  running (e.g. right after switching with `--lite`): reboot. While the desktop
  is up, VLC can't use the screen. In Lite mode the player always uses VLC's
  direct output (`drm_vout`); to try a different one, add e.g.
  `--vlc-args "--vout=any"` to the `ExecStart=` line.
- **Desktop mode, no picture, or not fullscreen:** edit `~/.config/systemd/user/osc-vlc-player.service`,
  remove the `#` from `#UnsetEnvironment=WAYLAND_DISPLAY`, then run
  `systemctl --user daemon-reload` and restart the player.
- **Doesn't start at login:** add this line to `~/.config/labwc/autostart`:
  `systemctl --user import-environment DISPLAY WAYLAND_DISPLAY; systemctl --user restart osc-vlc-player &`
- **Wrong resolution, low-resolution picture, or colour ghosting:** the log
  says `warning: the screen on HDMI-A-1 didn't say which resolutions it
  supports`. The screen didn't send its EDID (the data listing its
  resolutions), so the Pi falls back to 1024x768. Run
  `cat /sys/class/drm/card*-HDMI-A-*/modes`: a list topped by `1024x768`
  with `848x480` in it is that fallback. Shrinking 4K video that far can also
  show a ghostly, shifted colour image over a greyscale one in Lite mode.
  - Connect the Pi straight to the screen: video mixers, switches and
    extenders often don't pass the EDID on. Try another cable or adapter.
  - On a Pi 4, use **HDMI 0**. In a case like the Argon ONE that may not be
    the socket you'd expect; check the labels.
  - If the screen still isn't recognised, set its mode by hand: add e.g.
    `video=HDMI-A-1:1920x1080@60D` to the end of the single line in
    `/boot/firmware/cmdline.txt`, with the screen's resolution, and reboot.
    `HDMI-A-1` is HDMI 0 and `HDMI-A-2` is HDMI 1; the `D` turns the output
    on even without an EDID. For resolutions above 1920x1200, add `R`
    (e.g. `2560x1600R@60D`). If the screen then stays black, it doesn't
    accept that mode: remove the setting over SSH and reboot.
- **Picture shape:** videos are stretched to fill the whole screen. The player
  detects the screen resolution at startup; the log shows e.g.
  `stretching videos to fill the screen (aspect 1920:1200)`. To set the ratio
  by hand, or to keep black bars instead, add `--aspect 16:10` or `--aspect off`
  to the end of the `ExecStart=` line in the service file, then run
  `systemctl --user daemon-reload` and restart the player. If the picture ever
  goes back to black bars, press **FILL SCREEN** in TouchOSC (or send
  `/aspect fill`) to stretch it again.
- **Crashes when changing to a video in a different format:** the player
  already guards against this. When the next video's codec, resolution or
  frame rate differs from the current one, it closes VLC's video output and
  starts fresh. The log shows `format change (...): restarting video output`,
  and the desktop (or, in Lite mode, the black text console) shows for a
  moment while the video output restarts. Videos in
  the same format still switch seamlessly. To restart the output on *every*
  change, add `--clean-switch always` to the end of the `ExecStart=` line
  (as for `--aspect` above). To never restart it, add `--clean-switch never`.
  Matching all your videos' formats avoids the flash entirely; see section 5.
- **No sound (Desktop mode):** pick the output (e.g. HDMI) from the volume
  icon on the desktop taskbar.
- **No sound (Lite mode):** VLC uses the Pi's default sound output. List the
  outputs with `aplay -l`, then choose one by adding e.g.
  `--vlc-args "--alsa-audio-device=hw:CARD=vc4hdmi0"` to the `ExecStart=`
  line, using a card name from that list.
- **USB drive not played:** check the videos are in the drive's top folder.
  Run `findmnt | grep /media` to see if the drive is mounted. If it isn't in
  Lite mode, rerun `bash install.sh` to install the mounting rule, then plug
  the drive in again. NTFS drives may not mount; use FAT32 or exFAT.
- **Anything else:** check the log with `journalctl` (above).

---

## 2. Connect TouchOSC

1. Put the Pis and the phone/tablet/computer running TouchOSC on the same network.
2. Find each Pi's IP address: `hostname -I` on the Pi.
3. In TouchOSC, open **Connections → OSC**. Each Pi gets its own connection:
   player 1 is Connection 1, player 2 is Connection 2, and so on, up to 10
   (all of TouchOSC's connections).
   Set each one to **UDP**, Host: *that Pi's IP*, Send Port: **9000**, and
   Receive Port: **9000 + its number**:

   | Connection | Host | Send Port | Receive Port |
   |---|---|---|---|
   | 1 | first Pi | 9000 | **9001** |
   | 2 | second Pi | 9000 | **9002** |
   | … | … | 9000 | … |
   | 10 | tenth Pi | 9000 | **9010** |

   The Pis themselves all use the same install, with no per-Pi settings. With
   only one Pi, just set up Connection 1.
4. Test it: add a button with the address `/toggle`, run the layout and press
   it. The video should pause and resume.

### Ready-made layouts
There are two, with the same controls and pages:
- `osc_vlc_player.tosc` for **tablets** (landscape),
- `osc_vlc_player_phone.tosc` for **phones** (portrait; see *Phone layout*
  below).

Open one in TouchOSC (File → Open), set up the connections as above, and press
Play. Each has a tab for each page along the top:
- **ALL:** every button and fader goes to all 10 players at once. Instead of
  the full status panel it shows one line per player: play state, time and
  video, or `not connected` / `NO REPLY`.
- **1 to 10:** one page per player, each with the full set of controls below,
  going to that player only. If a page says `NO REPLY`, check that
  connection's host and receive port.

Each page has:
- **Status panel (player pages):** current video, time / length, play state,
  loop mode, aspect ratio, and a progress bar. Updates twice a second.
- **Scrub fader:** drag to any point in the video.
- **Transport buttons:** previous, restart video (back to its start),
  play/pause, stop and next. PLAY / PAUSE after STOP re-reads the videos
  folder, picking up videos added or removed meanwhile.
- **Skip buttons:** jump back or forward by 5, 20 or 60 seconds.
- **Loop button:** each tap moves to the next playlist mode: ALL (loop the
  playlist, the default) → ONE (repeat the current video) → OFF (stop after
  the last video). On a player page it shows that player's mode. A video
  that repeats (ONE, or ALL with a single video) starts over inside VLC,
  without reopening the file, so the restart is quicker and smoother.
- **Speed buttons:** 0.5x, 1x (normal) and 2x.
- **SYNC:** every player jumps to the same playback position, then plays or
  pauses together (see *Syncing players* below).
- **LOCK:** keeps every player in step with one master, without jumps (see
  *Keeping players in step* below). The button shows the player's lock
  state: MASTER, its offset from the master (e.g. `+0.03s`), WAITING, TOO FAR
  or OFF.
- **QUIT PLAYER / QUIT ALL:** quits the player(s). Tap once and the button
  says *TAP AGAIN TO QUIT*. Tap again within 3 seconds to quit. Start the
  player again from the Pi's menu (section 1) or by rebooting.
- **A-B loop:** Set A, Set B and Clear buttons, with a readout of the loop
  points on the player pages. On the ALL page, each player sets the point at
  its own current time.
- **Picture:** Fill Screen (stretch), Original Shape (black bars), 16:9 and
  4:3 buttons, plus the Fullscreen toggle. The current aspect ratio is shown
  in the status panel.
- **Volume:** a Mute toggle, and VOL - / VOL + buttons that turn the volume
  down or up by 10 (out of 100). Player pages show the current volume.

The Mute and Fullscreen toggles don't follow the players: after using Mute on
the ALL page, the Mute button on a player page may show the opposite state.
Press it again to bring them back in step. Likewise, the ALL page's Loop button
shows the last mode it set, which a player page may since have changed.

### Syncing players
Press **SYNC** to line up the players:
- **On a player page,** that player is the master.
- **On the ALL page,** the master is the first player (1, 2, 3 ...) that's
  playing, or if none is, the first one that's paused. The page names it for
  a few seconds where it normally says *Everything on this page goes to all 10
  players*.
- **Every other player** on the network that's playing or paused jumps to the
  master's current time in its own video, and then plays or stays paused like
  the master. So you can, for example, pause them all, press SYNC to put them
  on the same frame, then press PLAY on the ALL page.
- **Players that ignore it:** stopped players, and players whose current video
  is shorter than the master's time. Those carry on as they were.
- **It happens once per press.** The players then run on their own and can
  slowly drift apart again. Press SYNC again to line them back up, or use
  LOCK to keep them in step.

How it works: jumping to a new position takes each player a different time
(VLC has to decode from the last keyframe), which would leave them out of
step. So SYNC works in two steps: every player, the master included, pauses
and jumps to the master's time, and **1.5 seconds later**, once all of them
have finished, they all start playing again at the same moment. The picture
holds still during that pause.

It works with any mix of videos, formats and lengths, and reaches every player
on the local network, not just those set up in TouchOSC. For the closest
result:
- **Wired Ethernet is best.** Over Wi-Fi the start signal can reach some
  players a little later than others. The installer turns off Wi-Fi power
  saving, which otherwise delays messages the most.
- **If one player still starts late,** its jump is taking longer than the
  pause (e.g. 4K video with keyframes far apart). Make the pause longer by
  adding e.g. `--sync-hold 2.5` to the end of the `ExecStart=` line on the
  players (the master's setting is the one used). A shorter pause, such as
  `--sync-hold 1`, is fine for videos that jump quickly.

The master sends to port 9000 at every address on the network (a broadcast).
If your players listen on another port, or the network blocks broadcasts,
add `--sync-port` or `--sync-address` to the end of the `ExecStart=` line (as
for `--aspect` in section 1, *Troubleshooting*). `--sync-address` can be given
once per player, with each player's IP address:
```
--sync-address 192.168.1.51 --sync-address 192.168.1.52 --sync-address 192.168.1.53
```

### Keeping players in step (LOCK)
Players drift apart slowly once they're playing: each Pi's clock runs at a
very slightly different speed, and each player loses a slightly different
moment whenever it starts a video again. **LOCK** keeps them together without
jumping:
1. Press **SYNC** to line them up.
2. Press **LOCK**. On a player page, that player becomes the master; on the
   ALL page, the master is picked as for SYNC. Every other player on the
   network keeps in step with it.
3. Press **LOCK** again (on the master's page, or the ALL page) to stop.
   Turning LOCK on for another player makes that one the master instead.

While locked, the master sends its exact position once a second (one small
message, so the network barely notices it). Each other player compares it
with its own position, and if it has drifted more than 0.05 seconds, plays 1%
faster or slower (2% if more than 0.15 s out) until it's back within about
0.02 s, then returns to normal speed. The change is too small to see, and the
sound keeps its pitch. Players keep within about 0.05 s of the master, also
over Wi-Fi.

It works for the same video on every player, different videos of the same
length, and identical playlists of several videos (including across the
change from one video to the next).

The lock state shows on each player page's LOCK button and status line:

| Shown | Meaning |
|---|---|
| `MASTER` | The others keep in step with this player |
| `+0.03s` | Following the master, 0.03 seconds ahead of it (`-` = behind) |
| `WAITING` | Following, but this player or the master is paused, or has just jumped |
| `TOO FAR` | More than 3 seconds from the master (the status line shows how far): too far to catch up by speed. Press SYNC |
| `OFF` | Not locked |

Up to 3 seconds apart, a player catches up by speed alone (at 2%, a second
takes under a minute), so even a player that falls well behind, or loses a
moment when restarting its video, comes back in step by itself.

Notes:
- LOCK only adjusts speed; it never jumps. After a big change (another video
  on one player, or a skip), press SYNC to line them up again.
- Each time a video starts over, the picture holds for a moment, a little
  longer on some players than others. That shifts them slightly at every
  loop, and LOCK then brings them back. If a player's log often says
  `loop restart took 0.45s`, that player restarts slowly (e.g. a slow SD card
  or USB drive), and with short videos it will spend more time catching up.
- Followers log their offset once a minute (`lock: +0.012s from the master,
  speed 100%`), so the log shows how well they stayed in step over a long run.
- With 4K video at 50-60 fps on a Pi 4, which is at the limit of what it can
  decode, a player that's behind catches up at no more than 1% faster.
- The players' logs show each adjustment, e.g. `lock: 0.119s ahead of the
  master, playing at 99% speed`.

### Phone layout
`osc_vlc_player_phone.tosc` puts the same controls in one column for a phone
held upright: a large PLAY / PAUSE in the middle of the screen, every other
button at least thumb-sized, and the status at the top. On the player pages,
QUIT PLAYER sits at the bottom right, out of the way (it still needs two
taps).

It's 540 x 1110 units, the shape left for the layout on a tall modern phone
once the phone's status bar, gesture bar and TouchOSC's toolbar have taken
their share. TouchOSC scales it to fit, so it fills the screen on:
- **Pixel 6, 7 (including the 7a), 8 and 9** (20:9 screens),
- **Samsung Galaxy S21 to S25 and the A series** (19.5:9 and 20:9),
- **iPhone X to 16** (19.5:9; on the small mini models the text is smaller).

Other phones still work, with a narrow empty band at the top and bottom or at
the sides:
- **Older or compact phones with 16:9 screens** (iPhone SE, iPhone 8 and
  earlier) show it smaller, with bands at the sides. Text gets small but stays
  usable.
- **Extra-tall phones** (21:9, such as Sony Xperia and the Galaxy Z Flip) show
  bands at the top and bottom.
- **Foldables opened up** (Galaxy Z Fold, Pixel Fold): use the tablet layout.
- **Tablets:** use the tablet layout.

To change the layouts (for example the number of players, `DEVICES` at the
top of `build_touchosc_layout.py`, which both use), edit the build scripts and
run `python build_touchosc_layout.py` and `python build_touchosc_phone.py` to
regenerate the files, or edit them directly in the TouchOSC editor. The
sections below describe how the controls are set up.

---

## 3. Build a TouchOSC layout

For each control, set its OSC message **address** as in the tables below. By
default a TouchOSC button sends `1` when pressed and `0` when released.

### Buttons (no arguments)
Use **momentary** buttons with the default argument. The player acts on the
press and ignores the release, so each tap acts once.

| Address | Action |
|---|---|
| `/toggle` | Play / pause |
| `/play` | Play. From stopped, re-reads the videos first (picking up added / removed ones) |
| `/pause` | Pause |
| `/stop` | Stop |
| `/next` | Next video |
| `/prev` | Previous video |
| `/ab/a` | A-B loop: set A (loop start) at the current time |
| `/ab/b` | A-B loop: set B (loop end) at the current time and start looping |
| `/ab/clear` | A-B loop: clear |
| `/ab` | A-B loop in one button: 1st press sets A, 2nd sets B, 3rd clears |
| `/sync` | Every player on the network jumps to this player's position, then plays or pauses like it (see *Syncing players*) |
| `/sync/lock` | Switch LOCK on / off with this player as the master (see *Keeping players in step*); with an integer argument, `1` = on, `0` = off |

An A-B loop plays the section between A and B over and over. It clears itself
when the player stops or moves to another video. To set exact times from
another OSC app, send `/ab/set <A seconds> <B seconds>`.

### Buttons with a fixed value
Replace the argument with a **constant** value, and set the message's trigger
to fire on the **rising edge (press) only**. Otherwise the release sends the
value a second time.

| Address | Constant argument | Action |
|---|---|---|
| `/skip` | float, e.g. `10` or `-10` | Jump forward / back that many seconds |
| `/seek` | float, e.g. `0` | Jump to that time in seconds (`0` = restart video) |
| `/goto` | integer, e.g. `0` | Play video number N (the first video is `0`) |
| `/loop` | string: `none`, `all` or `one` | Playlist mode: stop at end / loop playlist / repeat current video |
| `/volume/step` | integer, e.g. `10` or `-10` | Turn the volume up / down by that much (0–100) |
| `/aspect` | string: `fill`, `original`, or a ratio like `16:9` | Picture shape: stretch to fill the screen / video's own shape with black bars / force that ratio |

### Toggle buttons
A **toggle** button sends `1` when switched on and `0` when switched off.

| Address | Action |
|---|---|
| `/mute` | Mute on / off |
| `/fullscreen` | Fullscreen on / off |

### Faders
A fader sends a value between 0 and 1 by default.

| Address | Fader setup | Action |
|---|---|---|
| `/position` | Default 0 → 1 | Scrub through the current video |
| `/volume` | Scale the argument to 0 → 100, integer | Volume |
| `/rate` | Scale the argument to e.g. 0.5 → 2 | Playback speed (1 = normal) |

### Player status (optional)
Sending `/status` (e.g. from a button) makes the player reply to TouchOSC on
port 9001 with the messages below. Add an integer argument to choose another
port: `/status 9003` replies on port 9003. This is how the ready-made layout
tells the players apart. The messages are:
`/status/state`, `/status/index`, `/status/file`, `/status/time`,
`/status/length`, `/status/volume`, `/status/abstart`, `/status/abend`
(A-B loop points in seconds, `-1` if not set), `/status/aspect` (the forced
ratio, or `original`) and `/status/loop`.
To show one, give a label the matching address and turn on receiving for it.
Values update only when `/status` is sent; they don't update continuously.

---

## 4. Hardware controls (optional)

Physical controls work at the same time as TouchOSC. Wire each button between
its pin and GND. The encoder's common pin (or a KY-040 module's GND) goes to
GND, and a KY-040's `+` goes to **3.3V**, never 5V.

| Control | GPIO | Physical pin | Action |
|---|---|---|---|
| Play/pause button | 17 | 11 | Play / pause |
| Previous button | 27 | 13 | Previous video |
| Next button | 22 | 15 | Next video |
| Loop button | 23 | 16 | Cycle loop mode: none → all → one |
| A-B button | 24 | 18 | Set A → set B (starts looping) → clear |
| Encoder A / CLK | 5 | 29 | Turn: seek back / forward one step |
| Encoder B / DT | 6 | 31 | |
| Encoder push / SW | 13 | 33 | Cycle step length: 1s → 5s → 10s → 30s |

---

## 5. Raspberry Pi models and video formats

The same files and install steps work on every model: Pi Zero / Zero W,
Zero 2 W, Pi 2, 3, 3B+, 4 (and 400) and 5 (and 500), running the current
Raspberry Pi OS, with desktop or Lite. Use the OS image that Raspberry Pi Imager offers
for the chosen board (the 32-bit image on a Pi Zero / Zero W and Pi 2).

What differs is which videos each model can decode smoothly. Encode your
videos to suit the *oldest* Pi that will play them:

| Model | Best format | Limit |
|---|---|---|
| Pi Zero / Zero W | H.264, 1080p, 30 fps, **Lite mode** | H.264 up to 1080p30 in Lite mode (tested on a Zero W). Through the desktop, playback is far too slow |
| Pi Zero 2 W, Pi 2, Pi 3 / 3B+ | H.264, 1080p, 30 fps, ≤ 20 Mbps | H.264 up to 1080p30. **No HEVC/H.265**: 4K or HEVC files will stutter badly or crash |
| Pi 4 / 400 | HEVC (H.265), up to 4K 60 fps, **level 5.1**, ≤ 60 Mbps; or H.264 up to 1080p60 | H.264 is limited to 1080p; HEVC above level 5.1 can crash VLC |
| Pi 5 / 500 | Same as Pi 4 | H.264 is decoded by the CPU (fine up to 1080p60) |

When a video starts, the player checks it against the Pi it's running on and
writes a warning to the log if it's too much for that model, e.g.
`warning: Neon Oblivion (4K H265).mp4: HEVC level 6.1 is above the decoder's
limit of 5.1 and can crash VLC; re-encode at level 5.1`. The log's first lines
also name the detected model and its limits. To check:
```bash
journalctl --user -u osc-vlc-player | grep -iE "warning|Raspberry Pi"
```

**Lite mode on older Pis:** on a Pi Zero, 2 or 3, the installer uses Lite
mode automatically (section 1, *Desktop or Lite*). Even within these limits,
playing through the desktop drops frames on these models.

**Mixing formats:** a playlist can mix formats, for example 1080p30 H.264 and
4K60 HEVC. At each change of format, the screen briefly shows the desktop
(or the text console in Lite mode) while VLC restarts its video output (see Troubleshooting in section 1). For
seamless changes throughout, export every video with the same codec,
resolution and frame rate.

### Converting videos
The best quality comes from exporting again from the original project in your
editing software with the settings in the table. To convert an existing file
with [ffmpeg](https://ffmpeg.org) instead:

```bash
# Smaller files: 720p30 H.264
ffmpeg -i input.mp4 -map 0:v:0 -map 0:a? -vf "scale=1280:720,fps=30" -c:v libx264 -preset slow -crf 22 \
  -maxrate 8M -bufsize 16M -pix_fmt yuv420p -c:a aac -b:a 160k -movflags +faststart output.mp4

# Pi Zero / Zero 2 W / 2 / 3: 1080p30 H.264
ffmpeg -i input.mp4 -map 0:v:0 -map 0:a? -vf "scale=1920:1080,fps=30" -c:v libx264 -preset slow -crf 20 \
  -profile:v high -level 4.1 -maxrate 20M -bufsize 40M -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart output.mp4

# Pi 4 / 5: 4K60 HEVC at level 5.1
ffmpeg -i input.mp4 -map 0:v:0 -map 0:a? -c:v libx265 -preset medium -crf 20 \
  -x265-params "level-idc=5.1:vbv-maxrate=50000:vbv-bufsize=100000" -pix_fmt yuv420p -tag:v hvc1 \
  -c:a copy -write_tmcd 0 -movflags +faststart output.mp4
```
A 4K source converted for the older Pis ends up with a different shape only
if the source isn't 16:9. Either way, the player stretches it to fill the
screen (see *Picture shape* in section 1).

### Model-specific notes
- **Pi 4, 4K at 60 fps:** plug the screen into **HDMI 0** (on a bare Pi 4, the
  port next to the USB-C power socket; cases that bring the ports out to
  full-size sockets, like the Argon ONE, may put it elsewhere, so check the
  case's labels) and use a screen and cable that support 4K at
  60 Hz. The installer adds the `hdmi_enable_4kp60=1` setting this needs to
  `/boot/firmware/config.txt`; reboot once after installing. Without it, 4K
  output is limited to 30 Hz. The Pi 5 doesn't need this.
- **Pi Zero / Zero W / Zero 2 W:** 512 MB of RAM is tight for the desktop plus
  VLC, so they use Lite mode. Keep videos to 1080p30 H.264. They have a mini-HDMI port, so you need an adapter.
- **Pi 2, Pi 3 and the Zeros:** use Lite mode for smooth playback. It also
  starts the video much sooner after boot.
- **Two screens (Pi 4 / 5):** the player stretches to fit the first screen it
  finds. With two screens connected, set the ratio by hand with `--aspect`
  (section 1, *Picture shape*).
- **GPIO:** the 40-pin header and the pin numbers in section 4 are the same on
  every model listed here.
