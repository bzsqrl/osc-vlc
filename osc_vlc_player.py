#!/usr/bin/env python3
"""
OSC- and GPIO-controlled VLC video player for Raspberry Pi.

Listens for OSC messages over UDP, and for physical buttons / a rotary
encoder on the GPIO header, and drives a python-vlc playlist.

Install (Raspberry Pi OS Desktop; vlc and gpiozero come preinstalled):
    sudo apt install vlc python3-gpiozero
    python3 -m venv --system-site-packages ~/venv
    ~/venv/bin/pip install python-osc python-vlc

Run (from a terminal on the desktop, or via osc-vlc-player.service):
    python3 osc_vlc_player.py                  # plays ~/Videos of whoever runs it
    python3 osc_vlc_player.py /media/usb/show  # or any folder / files
    python3 osc_vlc_player.py clip1.mp4 clip2.mov --port 9000 --loop all

OSC address map (all arguments optional unless noted):
    /play                    resume / start playback
    /pause                   pause
    /toggle                  toggle play/pause
    /stop                    stop playback
    /next                    next video in the playlist
    /prev                    previous video in the playlist
    /goto        <int>       jump to playlist index (0-based)
    /seek        <float>     seek to absolute time, in seconds
    /skip        <float>     seek relative to current time, in seconds (+/-)
    /position    <float>     seek to position 0.0 - 1.0
    /volume      <int>       set volume 0 - 100
    /mute        [int]       1 = mute, 0 = unmute, no arg = toggle
    /rate        <float>     playback speed (1.0 = normal)
    /loop        <str>       playlist mode: "none", "all", or "one"
    /fullscreen  [int]       1 = on, 0 = off, no arg = toggle
    /aspect      <str>       "fill" = stretch to the screen, "original" = the
                             video's own shape (black bars), or a ratio "16:9"
    /ab/a                    set loop start (A) at the current time
    /ab/b                    set loop end (B) at the current time; loop starts
    /ab/clear                clear the A-B loop
    /ab                      cycle: set A -> set B -> clear
    /ab/set  <float> <float> set A and B explicitly, in seconds
    /status      [int]       reply with state to sender, on the given port
                             (default: --reply-port)
    /quit                    shut down the player

GPIO controls (BCM pin numbers, override with --pin-* options):
    play/pause button     GPIO17
    previous button       GPIO27
    next button           GPIO22
    loop mode button      GPIO23   cycles none -> all -> one
    A-B loop button       GPIO24   cycles set A -> set B -> clear
    encoder A / B         GPIO5 / GPIO6   seek back/forward one step per detent
    encoder push button   GPIO13   cycles step length 1s -> 5s -> 10s -> 30s

    Wire each button between its pin and GND (internal pull-ups are used).
    Wire the encoder's common pin to GND; on KY-040 style modules connect
    CLK -> A, DT -> B, SW -> push button, + -> 3.3V, GND -> GND.
"""

import argparse
import ctypes
import functools
import os
import re
import subprocess
import signal
import sys
import threading
import time
from pathlib import Path

import vlc
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

try:
    from gpiozero import Button, RotaryEncoder
except ImportError:  # not on a Pi, or gpiozero not installed
    Button = RotaryEncoder = None

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm", ".mpg", ".mpeg", ".ts", ".wmv",
}

# Playlist modes: "none" plays through once, "all" loops the playlist,
# "one" repeats the current video
LOOP_MODES = ("none", "all", "one")

# When moving to a video whose format (codec, resolution, frame rate) differs
# from the one on screen, stop VLC's video output completely first. Reusing the
# output for a different format can crash VLC on the Pi; a full stop makes the
# new video start as cleanly as the first one. Costs a brief flash of the
# desktop while the video window is recreated.
SWITCH_MODES = ("auto", "always", "never")
PROBE_TIMEOUT_MS = 10000  # how long VLC may take to read each file's format

# How long after a seek to trust our own target over player.get_time(),
# which lags behind while VLC is still performing the seek.
SEEK_SETTLE_SECONDS = 0.5

# How often to check whether playback has reached the B point of an A-B loop.
# libVLC 3 has no native A-B loop, so it's done by polling.
AB_POLL_SECONDS = 0.05

# The desktop ignores a fullscreen request made before VLC's video window is
# on screen, so it's re-sent this long after a new video window appears.
FULLSCREEN_DELAY_SECONDS = 0.5

# What each Raspberry Pi can decode smoothly: codec -> (max width, max height, max fps).
# Anything else falls back to software decoding and will stutter (or worse).
DECODE_LIMITS = {
    # Pi Zero, Zero W, Zero 2 W, 1, 2, 3: VideoCore IV, no HEVC hardware
    "vc4": {"h264": (1920, 1080, 30)},
    # Pi 4 / 400 / CM4: H.264 and HEVC hardware
    "pi4": {"hevc": (3840, 2160, 60), "h264": (1920, 1080, 60)},
    # Pi 5 / 500 / CM5: HEVC hardware; H.264 decoded fast enough by the CPU
    "pi5": {"hevc": (3840, 2160, 60), "h264": (1920, 1080, 60)},
}
HEVC_MAX_LEVEL = 153  # level 5.1 (4K60), the limit of the Pi 4/5 HEVC decoder
CODEC_NAMES = {"h264": "H.264", "hevc": "HEVC (H.265)"}


def codec_name(codec):
    return CODEC_NAMES.get(codec, codec.upper())


def collect_media(paths):
    """Expand files and directories into a sorted list of video file paths."""
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files.extend(sorted(
                f for f in p.iterdir()
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
            ))
        elif p.is_file():
            files.append(p)
        else:
            print(f"warning: skipping missing path {p}", file=sys.stderr)
    return [str(f.resolve()) for f in files]


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_wlr_randr(text):
    # "    1920x1200 px, 59.950001 Hz (preferred, current)"
    m = re.search(r"(\d+)x(\d+) px[^\n]*\bcurrent\b", text)
    return (int(m[1]), int(m[2])) if m else None


def parse_xrandr(text):
    # "   1920x1200     59.95*+  59.88"   (* marks the active mode)
    m = re.search(r"^\s+(\d+)x(\d+)\S*\s+[^\n]*\*", text, re.M)
    return (int(m[1]), int(m[2])) if m else None


def detect_screen_size():
    """Current screen resolution as (width, height), or None if unknown."""
    # Wayland (Pi OS desktop default) / X11 or XWayland
    size = parse_wlr_randr(_run(["wlr-randr"])) or parse_xrandr(_run(["xrandr", "--current"]))
    if size:
        return size
    # Fallback: preferred mode of the first connected display, from the kernel
    for status in sorted(Path("/sys/class/drm").glob("card*-*/status")):
        try:
            if status.read_text().strip() != "connected":
                continue
            m = re.match(r"(\d+)x(\d+)", (status.parent / "modes").read_text())
        except OSError:
            continue
        if m:
            return int(m[1]), int(m[2])
    return None


def detect_board():
    """(model name, DECODE_LIMITS key) for this Raspberry Pi, or (None, None)."""
    try:
        model = Path("/proc/device-tree/model").read_text().rstrip("\x00").strip()
    except OSError:
        return None, None  # not a Pi
    if re.search(r"Pi 5|Pi 500|Compute Module 5", model):
        return model, "pi5"
    if re.search(r"Pi 4|Pi 400|Compute Module 4", model):
        return model, "pi4"
    if re.search(r"Pi 3|Pi 2|Zero|Pi Model|Compute Module( 3)?\b", model):
        return model, "vc4"
    return model, None  # a newer model: no known limits


class _Track(ctypes.Structure):
    # libvlc_media_track_t. Declared here because python-vlc's MediaTrack gets
    # the audio/video/subtitle union wrong, which crashes on video tracks.
    _fields_ = [("codec", ctypes.c_uint32), ("original_fourcc", ctypes.c_uint32),
                ("id", ctypes.c_int), ("type", ctypes.c_int), ("profile", ctypes.c_int),
                ("level", ctypes.c_int), ("details", ctypes.c_void_p),
                ("bitrate", ctypes.c_uint), ("language", ctypes.c_char_p),
                ("description", ctypes.c_char_p)]


class _VideoTrack(ctypes.Structure):
    # leading fields of libvlc_video_track_t
    _fields_ = [("height", ctypes.c_uint), ("width", ctypes.c_uint),
                ("sar_num", ctypes.c_uint), ("sar_den", ctypes.c_uint),
                ("frame_rate_num", ctypes.c_uint), ("frame_rate_den", ctypes.c_uint)]


def video_track_info(media):
    """(codec, width, height, fps) of a parsed or playing media's video track, or None."""
    tracks_get = vlc.dll.libvlc_media_tracks_get
    tracks_get.argtypes = [ctypes.c_void_p,
                           ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(_Track)))]
    tracks_get.restype = ctypes.c_uint
    tracks_release = vlc.dll.libvlc_media_tracks_release
    tracks_release.argtypes = [ctypes.POINTER(ctypes.POINTER(_Track)), ctypes.c_uint]
    tracks_release.restype = None

    tracks = ctypes.POINTER(ctypes.POINTER(_Track))()
    n = tracks_get(media._as_parameter_, ctypes.byref(tracks))
    try:
        for i in range(n):
            t = tracks[i].contents
            if t.type == 1 and t.details:  # libvlc_track_video
                v = ctypes.cast(t.details, ctypes.POINTER(_VideoTrack)).contents
                fps = v.frame_rate_num / v.frame_rate_den if v.frame_rate_den else 0
                codec = t.codec.to_bytes(4, "little").decode("ascii", "replace").strip()
                return codec, v.width, v.height, fps
    finally:
        if n:
            tracks_release(tracks, n)
    return None


def describe_format(fmt):
    if not fmt:
        return "unknown format"
    codec, width, height, fps = fmt
    return f"{codec_name(codec)} {width}x{height} {fps:g}fps"


def hevc_level(path):
    """HEVC general_level_idc (e.g. 153 = level 5.1) from an MP4/MOV file, or None."""
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            # the header box (moov) sits at the start or the end of the file
            for start, length in ((0, 2 << 20), (max(0, size - (8 << 20)), 8 << 20)):
                f.seek(start)
                data = f.read(length)
                i = data.find(b"hvcC")
                while i >= 0:
                    # hvcC: 'hvcC', version (1), profile, 4+6 flag bytes, level
                    if i + 17 <= len(data) and data[i + 4] == 1:
                        level = data[i + 16]
                        if 30 <= level <= 186 and level % 3 == 0:
                            return level
                    i = data.find(b"hvcC", i + 4)
    except OSError:
        pass
    return None


def decode_problems(board, codec, width, height, fps, level=None):
    """Reasons this board may not play a video smoothly (empty if it's fine)."""
    limits = DECODE_LIMITS[board]
    name = codec_name(codec)
    if codec not in limits:
        ok = " or ".join(codec_name(c) for c in limits)
        return [f"{name} isn't hardware-decoded on this Pi, expect stutter "
                f"or a crash; re-encode as {ok}"]
    max_w, max_h, max_fps = limits[codec]
    problems = []
    if width * height > max_w * max_h:
        problems.append(f"{width}x{height} is above this Pi's {name} limit "
                        f"of {max_w}x{max_h}")
    if fps > max_fps + 1:
        problems.append(f"{fps:.0f} fps is above this Pi's {name} limit "
                        f"of {max_fps} fps")
    if codec == "hevc" and level and level > HEVC_MAX_LEVEL:
        problems.append(f"HEVC level {level / 30:.1f} is above the decoder's limit of "
                        f"5.1 and can crash VLC; re-encode at level 5.1")
    return problems


def resolve_aspect(setting):
    """Turn the --aspect option into a VLC aspect ratio string, or None."""
    if setting == "off":
        return None
    if setting != "auto":
        return setting
    size = detect_screen_size()
    if not size:
        print("warning: couldn't detect the screen size; videos keep their own "
              "aspect ratio (set it with e.g. --aspect 16:10)", file=sys.stderr)
        return None
    return f"{size[0]}:{size[1]}"


def aspect_arg(value):
    if value in ("auto", "off") or re.fullmatch(r"\d+(\.\d+)?:\d+(\.\d+)?", value):
        return value
    raise argparse.ArgumentTypeError('use "auto", "off", or W:H such as 16:10')


def locked(method):
    """Serialize controller calls; OSC and GPIO callbacks run on different threads."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return wrapper


class VideoController:
    def __init__(self, files, vlc_args, fullscreen, loop_mode, aspect=None,
                 switch_mode="auto"):
        self.lock = threading.RLock()
        self.files = files
        self.instance = vlc.Instance(vlc_args)
        self.player = self.instance.media_player_new()

        # The playlist is run here rather than by VLC's MediaListPlayer, so that
        # every change of video goes through _play_index() (see SWITCH_MODES).
        self.medias = [self.instance.media_new(f) for f in files]
        self.index = 0
        self.switch_mode = switch_mode
        self.formats = [None] * len(files)  # (codec, w, h, fps) per file, once probed
        # True from starting a video until stop(): VLC's video output (and window)
        # stays open even after a video ends, until the player is stopped
        self._output_open = False
        if switch_mode == "auto":
            for media in self.medias:  # read each file's format in the background
                media.parse_with_options(vlc.MediaParseFlag.local, PROBE_TIMEOUT_MS)
        self._ended = threading.Event()  # set by VLC when a video plays to the end
        self._on_end = lambda event: self._ended.set()  # keep a reference
        self.player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached, self._on_end)

        self.loop_mode = None
        self.loop(loop_mode)
        self.want_fullscreen = fullscreen
        self.player.set_fullscreen(fullscreen)
        self._new_window = True  # next video window needs fullscreen re-applied
        self._vout_at = None     # when that window appeared
        self.aspect = aspect       # current forced ratio, None = video's own
        self.fill_aspect = aspect  # ratio used by /aspect fill (detected on demand)
        if aspect:
            # Claiming every video has the screen's shape makes VLC stretch it
            # to fill. Must be set on the player: it overrides --aspect-ratio.
            self.player.video_set_aspect_ratio(aspect)

        self._seek_target = None  # ms
        self._seek_at = 0.0

        self.ab_start = None  # ms
        self.ab_end = None    # ms
        self._ab_index = -1   # playlist index the loop belongs to
        self.board_model, self.board = detect_board()
        self._checked_index = None  # last playlist index checked against the board
        self._closing = threading.Event()
        self._watch_thread = threading.Thread(target=self._watch, daemon=True)
        self._watch_thread.start()

    # --- helpers -----------------------------------------------------------

    def current_index(self):
        return self.index if self.player.get_media() else -1

    def _format(self, index):
        """The probed format of video `index`, or None if not known (yet)."""
        if self.formats[index] is None:
            media = self.medias[index]
            if media.get_parsed_status() == vlc.MediaParsedStatus.done:
                self.formats[index] = video_track_info(media)
        return self.formats[index]

    def _play_index(self, index):
        """Start video `index`, first stopping the video output if needed."""
        self._clear_seek()
        self._ended.clear()
        if self._output_open and self.switch_mode != "never":
            old, new = self._format(self.index), self._format(index)
            # frame rates count as equal to the nearest whole number (29.97 = 30)
            same = old and new and old[:3] == new[:3] and round(old[3]) == round(new[3])
            if self.switch_mode == "always" or not same:
                if self.switch_mode == "auto":
                    print(f"format change ({describe_format(old)} -> "
                          f"{describe_format(new)}): restarting video output")
                self.player.stop()
                self._new_window = True  # stopping closes the video window
        self.index = index
        self._output_open = True
        self.player.set_media(self.medias[index])
        self.player.play()

    def _step(self, delta, wrap):
        """Index `delta` videos from the current one, or None at the end of the list."""
        index = self.index + delta
        if wrap:
            return index % len(self.medias)
        return index if 0 <= index < len(self.medias) else None

    def _is_idle(self):
        return self.player.get_state() in (
            vlc.State.NothingSpecial, vlc.State.Stopped, vlc.State.Ended, vlc.State.Error,
        )

    def _clear_seek(self):
        self._seek_target = None

    def _now_ms(self):
        # Right after a seek get_time() still reports the pre-seek time,
        # so trust the last seek target until VLC has caught up.
        recent = time.monotonic() - self._seek_at < SEEK_SETTLE_SECONDS
        if self._seek_target is not None and recent:
            return self._seek_target
        return max(0, self.player.get_time())

    # --- transport ---------------------------------------------------------

    @locked
    def play(self):
        if not self._is_idle():
            self.player.set_pause(0)
        elif (self.player.get_state() == vlc.State.Ended
              and self._step(1, wrap=False) is None):
            self._play_index(0)  # the playlist has finished: start it over
        else:
            self._play_index(self.index)

    @locked
    def pause(self):
        self.player.set_pause(1)

    @locked
    def toggle(self):
        if self.player.is_playing():
            self.pause()
        else:
            self.play()

    @locked
    def stop(self):
        self._clear_seek()
        self.ab_clear()
        self._ended.clear()
        self.player.stop()
        self._output_open = False
        self._new_window = True  # stopping closes the video window

    @locked
    def next(self):
        index = self._step(1, wrap=self.loop_mode == "all")
        if index is None:
            print("already at last video")
        else:
            self._play_index(index)

    @locked
    def prev(self):
        index = self._step(-1, wrap=self.loop_mode == "all")
        if index is None:
            print("already at first video")
        else:
            self._play_index(index)

    @locked
    def goto(self, index):
        index = int(index)
        if 0 <= index < len(self.medias):
            self._play_index(index)
        else:
            print(f"goto: index {index} out of range (0-{len(self.medias) - 1})")

    @locked
    def _check_end(self):
        """When a video has played to the end, move on as the loop mode says."""
        if not self._ended.is_set():
            return
        self._ended.clear()
        if self.loop_mode == "one":
            self._play_index(self.index)
            return
        index = self._step(1, wrap=self.loop_mode == "all")
        if index is not None:
            self._play_index(index)
        # else: loop mode "none" and the last video has finished; stay stopped

    # --- seeking -----------------------------------------------------------

    @locked
    def seek(self, seconds):
        length = self.player.get_length()  # ms, -1 if unknown
        ms = max(0, int(float(seconds) * 1000))
        if length > 0:
            ms = min(ms, length - 1)
        self.player.set_time(ms)
        self._seek_target = ms
        self._seek_at = time.monotonic()

    @locked
    def skip(self, seconds):
        # _now_ms() keeps rapid skips (e.g. spinning the encoder) cumulative
        self.seek(self._now_ms() / 1000 + float(seconds))

    @locked
    def position(self, pos):
        self._clear_seek()
        self.player.set_position(min(max(float(pos), 0.0), 1.0))

    # --- A-B loop ----------------------------------------------------------

    @locked
    def ab_a(self):
        self.ab_start = self._now_ms()
        if self.ab_end is not None and self.ab_end <= self.ab_start:
            self.ab_end = None
        self._ab_index = self.current_index()
        print(f"A-B: A = {self.ab_start / 1000:.2f}s")

    @locked
    def ab_b(self):
        if self.ab_start is None:
            print("A-B: set A first")
            return
        now = self._now_ms()
        if now <= self.ab_start:
            print("A-B: B must be after A")
            return
        self.ab_end = now
        print(f"A-B: looping {self.ab_start / 1000:.2f}s - {self.ab_end / 1000:.2f}s")
        self.seek(self.ab_start / 1000)

    @locked
    def ab_set(self, a, b):
        a, b = int(float(a) * 1000), int(float(b) * 1000)
        if a < 0 or b <= a:
            print(f"A-B: invalid loop {a / 1000}s - {b / 1000}s")
            return
        self.ab_start, self.ab_end = a, b
        self._ab_index = self.current_index()
        print(f"A-B: looping {a / 1000:.2f}s - {b / 1000:.2f}s")
        self.seek(a / 1000)

    @locked
    def ab_clear(self):
        if self.ab_start is not None:
            print("A-B: cleared")
        self.ab_start = self.ab_end = None

    @locked
    def ab_cycle(self):
        if self.ab_start is None:
            self.ab_a()
        elif self.ab_end is None:
            self.ab_b()
        else:
            self.ab_clear()

    def _watch(self):
        while not self._closing.wait(AB_POLL_SECONDS):
            self._check_end()
            self._check_ab()
            self._check_fullscreen()
            self._check_media()

    @locked
    def _check_media(self):
        """Once per video, warn in the log if this Pi can't decode it smoothly."""
        if not self.board or self.player.has_vout() == 0:
            return
        index = self.current_index()
        if index == self._checked_index or not 0 <= index < len(self.files):
            return
        self._checked_index = index
        info = video_track_info(self.player.get_media())
        if info:
            # reading the HEVC level touches the disk; keep that out of the lock
            threading.Thread(target=self._warn_media, args=(self.files[index], *info),
                             daemon=True).start()

    def _warn_media(self, path, codec, width, height, fps):
        level = hevc_level(path) if codec == "hevc" else None
        for problem in decode_problems(self.board, codec, width, height, fps, level):
            print(f"warning: {Path(path).name}: {problem}")

    @locked
    def _check_ab(self):
        if self.ab_start is None:
            return
        if self.current_index() != self._ab_index:
            self.ab_clear()  # a different video is playing now
            return
        if self.ab_end is None or time.monotonic() - self._seek_at < SEEK_SETTLE_SECONDS:
            return
        if self.player.get_time() >= self.ab_end:
            self.seek(self.ab_start / 1000)

    # --- other -------------------------------------------------------------

    @locked
    def volume(self, level):
        self.player.audio_set_volume(min(max(int(level), 0), 100))

    @locked
    def mute(self, state=None):
        if state is None:
            self.player.audio_toggle_mute()
        else:
            self.player.audio_set_mute(bool(int(state)))

    @locked
    def rate(self, rate):
        self.player.set_rate(float(rate))

    @locked
    def loop(self, mode):
        mode = str(mode).lower()
        if mode in LOOP_MODES:
            self.loop_mode = mode
        else:
            print(f"loop: unknown mode {mode!r}, use one of {list(LOOP_MODES)}")

    @locked
    def cycle_loop(self):
        modes = list(LOOP_MODES)
        self.loop(modes[(modes.index(self.loop_mode) + 1) % len(modes)])
        return self.loop_mode

    @locked
    def set_aspect(self, mode):
        mode = str(mode).strip().lower()
        if mode in ("fill", "stretch", "auto"):
            if not self.fill_aspect:
                self.fill_aspect = resolve_aspect("auto")
            if not self.fill_aspect:
                return  # screen size unknown; resolve_aspect printed a warning
            ratio = self.fill_aspect
        elif mode in ("original", "off"):
            ratio = None
        elif re.fullmatch(r"\d+(\.\d+)?:\d+(\.\d+)?", mode):
            ratio = mode
        else:
            print(f'aspect: unknown value {mode!r}, use "fill", "original" or W:H')
            return
        self.aspect = ratio
        # VLC skips a ratio it believes is already in use, even when the picture
        # doesn't show it, so pass through a different ratio to force a redraw.
        self.player.video_set_aspect_ratio("1:1" if ratio is None else None)
        self.player.video_set_aspect_ratio(ratio)

    @locked
    def fullscreen(self, state=None):
        self.want_fullscreen = not self.want_fullscreen if state is None else bool(int(state))
        self._apply_fullscreen()

    def _apply_fullscreen(self):
        # VLC skips a request that matches the state it *thinks* the window is
        # in, even when the window never actually went fullscreen, so switch
        # through the opposite state to make sure the request reaches the window.
        self.player.set_fullscreen(not self.want_fullscreen)
        self.player.set_fullscreen(self.want_fullscreen)

    @locked
    def _check_fullscreen(self):
        # Only a freshly created window needs this. VLC restarts its video
        # output on every video change but keeps the window, and re-applying
        # fullscreen there would make the screen flicker.
        if not self._new_window:
            return
        if self.player.has_vout() == 0:
            self._vout_at = None
            return
        if self._vout_at is None:
            self._vout_at = time.monotonic()  # the window just appeared
        elif time.monotonic() - self._vout_at >= FULLSCREEN_DELAY_SECONDS:
            self._new_window = False
            if self.want_fullscreen:
                self._apply_fullscreen()

    @locked
    def status(self):
        idx = self.current_index()
        return {
            "state": str(self.player.get_state()).split(".")[-1].lower(),
            "index": idx,
            "file": Path(self.files[idx]).name if 0 <= idx < len(self.files) else "",
            "time": max(0, self.player.get_time()) / 1000,
            "length": max(0, self.player.get_length()) / 1000,
            "volume": self.player.audio_get_volume(),
            "abstart": self.ab_start / 1000 if self.ab_start is not None else -1,
            "abend": self.ab_end / 1000 if self.ab_end is not None else -1,
            "aspect": self.aspect or "original",
            "loop": self.loop_mode,  # keep last: the TouchOSC layout redraws on it
        }

    def release(self):
        # stop the watcher thread before taking the lock it also uses
        self._closing.set()
        self._watch_thread.join()
        with self.lock:
            self.player.stop()
            self.player.release()
            for media in self.medias:
                media.release()
            self.instance.release()


class GpioControls:
    """Physical buttons and a rotary encoder with push button, via gpiozero."""

    SEEK_STEPS = [1, 5, 10, 30]  # seconds per encoder detent

    def __init__(self, ctrl, pins):
        self.ctrl = ctrl
        self.step_index = 0
        self.devices = []

        self._button(pins.pin_play, "play/pause", ctrl.toggle)
        self._button(pins.pin_prev, "prev", ctrl.prev)
        self._button(pins.pin_next, "next", ctrl.next)
        self._button(pins.pin_loop, "loop", lambda: f"mode {ctrl.cycle_loop()}")
        self._button(pins.pin_ab, "A-B", ctrl.ab_cycle)
        self._button(pins.pin_enc_button, "seek step", self.cycle_step)

        # max_steps=0: we only care about rotation events, not an absolute value
        encoder = RotaryEncoder(pins.pin_enc_a, pins.pin_enc_b, max_steps=0)
        encoder.when_rotated_clockwise = lambda: self._turn(+1)
        encoder.when_rotated_counter_clockwise = lambda: self._turn(-1)
        self.devices.append(encoder)

    @property
    def step(self):
        return self.SEEK_STEPS[self.step_index]

    def _button(self, pin, name, action):
        def pressed():
            result = action()
            print(f"gpio: {name}" + (f" -> {result}" if result else ""))
        button = Button(pin, bounce_time=0.05)
        button.when_pressed = pressed
        self.devices.append(button)

    def _turn(self, direction):
        self.ctrl.skip(direction * self.step)
        print(f"gpio: skip {direction * self.step:+d}s")

    def cycle_step(self):
        self.step_index = (self.step_index + 1) % len(self.SEEK_STEPS)
        return f"{self.step}s"

    def close(self):
        for device in self.devices:
            device.close()


def build_dispatcher(ctrl, reply_port, shutdown):
    dispatcher = Dispatcher()

    def trigger(address, method):
        """Map a no-argument command. Controllers like TouchOSC send 1.0 on
        button press and 0.0 on release, so a 0 argument is ignored."""
        def handler(addr, *args):
            if args and isinstance(args[0], (int, float)) and args[0] == 0:
                return
            method()
            print(addr)
        dispatcher.map(address, handler)

    def value(address, method, optional=False):
        """Map a command that takes one argument (optional if `optional`)."""
        def handler(addr, *args):
            if not args and not optional:
                print(f"{addr}: expected an argument")
                return
            try:
                method(*args[:1])
                print(f"{addr} {' '.join(map(str, args[:1]))}".rstrip())
            except (TypeError, ValueError) as e:
                print(f"{addr}: bad argument {args}: {e}")
        dispatcher.map(address, handler)

    trigger("/play", ctrl.play)
    trigger("/pause", ctrl.pause)
    trigger("/toggle", ctrl.toggle)
    trigger("/stop", ctrl.stop)
    trigger("/next", ctrl.next)
    trigger("/prev", ctrl.prev)
    value("/goto", ctrl.goto)
    value("/seek", ctrl.seek)
    value("/skip", ctrl.skip)
    value("/position", ctrl.position)
    value("/volume", ctrl.volume)
    value("/mute", ctrl.mute, optional=True)
    value("/rate", ctrl.rate)
    value("/loop", ctrl.loop)
    value("/fullscreen", ctrl.fullscreen, optional=True)
    value("/aspect", ctrl.set_aspect)
    trigger("/ab", ctrl.ab_cycle)
    trigger("/ab/a", ctrl.ab_a)
    trigger("/ab/b", ctrl.ab_b)
    trigger("/ab/clear", ctrl.ab_clear)

    def ab_set_handler(addr, *args):
        try:
            ctrl.ab_set(*args[:2])
        except (TypeError, ValueError) as e:
            print(f"{addr}: expected two times in seconds, got {args}: {e}")

    dispatcher.map("/ab/set", ab_set_handler)

    def status_handler(client_address, addr, *args):
        # an optional argument picks the reply port, so one TouchOSC layout can
        # tell several players apart (each replies on its own port)
        port = reply_port
        if args and isinstance(args[0], (int, float)) and 1 <= int(args[0]) <= 65535:
            port = int(args[0])
        status = ctrl.status()
        client = SimpleUDPClient(client_address[0], port)
        for key, value in status.items():
            client.send_message(f"/status/{key}", value)
        # not logged: the TouchOSC layout polls /status twice a second

    dispatcher.map("/status", status_handler, needs_reply_address=True)
    dispatcher.map("/quit", lambda addr, *args: shutdown())
    dispatcher.set_default_handler(lambda addr, *args: print(f"unhandled: {addr} {args}"))
    return dispatcher


def setup_gpio(ctrl, args):
    """Start GPIO controls, or return None (and keep running OSC-only) if unavailable."""
    if args.no_gpio:
        return None
    if Button is None:
        print("warning: gpiozero not installed, GPIO controls disabled", file=sys.stderr)
        return None
    try:
        gpio = GpioControls(ctrl, args)
    except Exception as e:  # not a Pi, pin in use, missing pin factory, ...
        print(f"warning: GPIO controls disabled: {e}", file=sys.stderr)
        return None
    print(f"GPIO controls active (seek step {gpio.step}s)")
    return gpio


def init_x11_threads():
    """Make Xlib thread-safe, as the vlc app does at startup.

    On X11/XWayland libVLC's accelerated (OpenGL) video outputs use Xlib from
    several threads; libVLC apps must call XInitThreads() before creating the
    instance. (The alternative, --no-xlib, disables those outputs and forces
    slow software rendering.) Harmless under Wayland or without libX11.
    """
    if sys.platform.startswith("linux"):
        try:
            ctypes.CDLL("libX11.so.6").XInitThreads()
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description="OSC/GPIO-controlled VLC video player")
    parser.add_argument("paths", nargs="*", default=[str(Path.home() / "Videos")],
                        help="video files and/or directories "
                             "(default: the Videos folder in your home directory)")
    parser.add_argument("--ip", default="0.0.0.0", help="address to listen on (default: all)")
    parser.add_argument("--port", type=int, default=9000, help="OSC listen port (default: 9000)")
    parser.add_argument("--reply-port", type=int, default=9001,
                        help="port /status replies are sent to on the sender (default: 9001)")
    parser.add_argument("--loop", choices=LOOP_MODES, default="all",
                        help="playlist loop mode (default: all)")
    parser.add_argument("--windowed", action="store_true", help="don't start fullscreen")
    parser.add_argument("--no-autoplay", action="store_true", help="wait for /play to start")
    parser.add_argument("--vlc-args", default="",
                        help='extra libVLC options, e.g. "--vout=drm_vout --aout=alsa"')
    parser.add_argument("--aspect", type=aspect_arg, default="auto",
                        help='stretch videos to fill the screen: "auto" (detect screen size, '
                             'default), a ratio such as 16:10, or "off" to keep each '
                             "video's own shape (black bars)")
    parser.add_argument("--clean-switch", choices=SWITCH_MODES, default="auto",
                        help="fully restart VLC's video output when changing videos: "
                             '"auto" (default) only when the next video has a different '
                             'codec, resolution or frame rate, "always", or "never"')
    parser.add_argument("--debug", action="store_true",
                        help="verbose VLC log (shows which decoder / video output is used)")

    gpio_opts = parser.add_argument_group("GPIO (BCM pin numbers)")
    gpio_opts.add_argument("--no-gpio", action="store_true", help="disable GPIO controls")
    for name, default, help_text in [
        ("play", 17, "play/pause button"),
        ("prev", 27, "previous video button"),
        ("next", 22, "next video button"),
        ("loop", 23, "loop mode button"),
        ("ab", 24, "A-B loop button"),
        ("enc-a", 5, "encoder A / CLK"),
        ("enc-b", 6, "encoder B / DT"),
        ("enc-button", 13, "encoder push button / SW"),
    ]:
        gpio_opts.add_argument(f"--pin-{name}", type=int, default=default,
                               help=f"{help_text} (default: {default})")
    args = parser.parse_args()

    files = collect_media(args.paths)
    if not files:
        sys.exit("no video files found")

    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        print("desktop session found: playing in a fullscreen window")
    else:
        print("no desktop session: VLC draws straight to the screen")
    init_x11_threads()
    vlc_args = [
        "--no-video-title-show",   # don't overlay the filename on each video
        "--mouse-hide-timeout=0",
        "-vv" if args.debug else "--quiet",
    ]
    aspect = resolve_aspect(args.aspect)
    if aspect:
        print(f"stretching videos to fill the screen (aspect {aspect})")
    vlc_args += args.vlc_args.split()
    ctrl = VideoController(files, vlc_args, not args.windowed, args.loop, aspect,
                           args.clean_switch)
    if ctrl.board:
        limits = ", ".join(f"{codec_name(codec)} up to {w}x{h}@{fps}"
                           for codec, (w, h, fps) in DECODE_LIMITS[ctrl.board].items())
        print(f"{ctrl.board_model}: smooth playback for {limits}")
    elif ctrl.board_model:
        print(f"{ctrl.board_model}: unknown model, video format checks disabled")
    gpio = setup_gpio(ctrl, args)

    server = None

    def shutdown(*_):
        print("shutting down")
        # server.shutdown() blocks until serve_forever exits, so call it off-thread
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    dispatcher = build_dispatcher(ctrl, args.reply_port, shutdown)
    # Blocking server handles one OSC message at a time
    server = BlockingOSCUDPServer((args.ip, args.port), dispatcher)

    print(f"loaded {len(files)} video(s):")
    for i, f in enumerate(files):
        print(f"  [{i}] {Path(f).name}")
    print(f"listening for OSC on {args.ip}:{args.port}")

    if not args.no_autoplay:
        ctrl.play()

    try:
        server.serve_forever()
    finally:
        server.server_close()
        if gpio:
            gpio.close()
        ctrl.release()


if __name__ == "__main__":
    main()
