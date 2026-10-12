#!/usr/bin/env python3
"""
Generate osc_vlc_player_phone.tosc, a portrait TouchOSC layout for phones with
the same controls, pages and connections as the tablet layout
(build_touchosc_layout.py, which this reuses).

    python3 build_touchosc_phone.py             # writes osc_vlc_player_phone.tosc

It's sized for tall phones (screens of 19.5:9 to 20:9, such as the Pixel 6-9,
Galaxy S21-S25 and iPhone X-16): 540 x 1110 units, the shape of the area left
for the layout once the phone's status bar, gesture bar and TouchOSC's own
toolbar are taken off. TouchOSC scales it to fit the screen.
"""

import zlib
from pathlib import Path

from build_touchosc_layout import (
    BASE_PORT, BG, BLUE, DEVICES, DIM_TEXT, GOLD, GREEN, GREY, PANEL, PINK, PURPLE,
    RED, ROOT_SCRIPT, TEAL, TEXT, VOLUME_STEP, button, connections, fader, label,
    loop_button, node, osc, partial, prop, quit_button, sync_all_button, value,
)

W, H = 540, 1050          # one page (portrait); plus the tab bar: 540 x 1110
TAB = 60                  # page tab bar: ALL, 1 .. 10
MARGIN, GAP = 12, 10
X0, X1 = MARGIN, W - MARGIN


def row(y, h, n=1, x0=X0, x1=X1):
    """Split a horizontal strip into n equal frames."""
    w = (x1 - x0 - GAP * (n - 1)) / n
    return [(x0 + i * (w + GAP), y, w, h) for i in range(n)]


def controls(p, devices, y, sizes, last_row):
    """The control rows, from `y` down. `sizes` gives each row's height;
    `last_row(frames)` fills the 4th frame of the volume row."""
    conn = connections(devices)
    c = []

    def next_row(name):
        nonlocal y
        top = y
        y += sizes[name] + GAP
        return top, sizes[name]

    # Scrub fader, full width
    top, h = next_row("scrub")
    c.append(fader(p + "scrub", (X0, top, X1 - X0, h), TEAL,
                   [osc("/position", [partial("VALUE", "FLOAT", "x")], conn)]))

    # Transport: a big PLAY / PAUSE between PREV and NEXT ...
    top, h = next_row("transport")
    side = 130
    c.append(button(p + "prev", (X0, top, side, h), "<<\nPREV", BLUE, "/prev", conn))
    c.append(button(p + "toggle", (X0 + side + GAP, top, X1 - X0 - 2 * (side + GAP), h),
                    "PLAY / PAUSE", GREEN, "/toggle", conn))
    c.append(button(p + "next", (X1 - side, top, side, h), ">>\nNEXT", BLUE, "/next", conn))
    # ... then restart, stop and sync
    restart, stop, sync = row(*next_row("transport2"), n=3)
    c.append(button(p + "restart", restart, "RESTART\nVIDEO", GREY, "/seek", conn,
                    ("FLOAT", 0)))
    c.append(button(p + "stop", stop, "STOP", RED, "/stop", conn))
    if len(devices) > 1:
        c.append(sync_all_button(p + "sync", sync))
    else:
        c.append(button(p + "sync", sync, "SYNC", PINK, "/sync", conn))

    # Skip back / forward
    skips = [-60, -20, -5, 5, 20, 60]
    for frame, s in zip(row(*next_row("skip"), n=len(skips)), skips):
        c.append(button(f"{p}skip{s:+d}", frame, f"{s:+d}s", GREY, "/skip", conn,
                        ("FLOAT", s)))

    # Loop mode and playback speed
    loop, *speeds = row(*next_row("loop"), n=4)
    c.append(loop_button(p + "loop", loop, devices))
    for frame, r in zip(speeds, [0.5, 1, 2]):
        c.append(button(f"{p}rate{r}", frame, f"SPEED\n{r}x", PURPLE, "/rate", conn,
                        ("FLOAT", r)))

    # Picture shape and fullscreen
    *aspects, full = row(*next_row("picture"), n=5)
    for frame, (mode, text) in zip(aspects, [
        ("fill", "FILL\nSCREEN"),
        ("original", "ORIG\nSHAPE"),
        ("16:9", "16:9"),
        ("4:3", "4:3"),
    ]):
        c.append(button(f"{p}aspect_{mode.replace(':', 'x')}", frame, text, GOLD,
                        "/aspect", conn, ("STRING", mode)))
    c.append(button(p + "fullscreen", full, "FULL\nSCREEN", GREY, "/fullscreen",
                    conn, toggle=True, default=1))

    # A-B loop
    for frame, (name, text, path) in zip(row(*next_row("ab"), n=3), [
        ("ab_a", "SET A", "/ab/a"),
        ("ab_b", "SET B", "/ab/b"),
        ("ab_clear", "CLEAR\nA-B", "/ab/clear"),
    ]):
        c.append(button(p + name, frame, text, TEAL, path, conn))

    # Volume, and last_row() for the 4th frame
    mute, down, up, last = row(*next_row("volume"), n=4)
    c.append(button(p + "mute", mute, "MUTE", RED, "/mute", conn, toggle=True))
    c.append(button(p + "vol_down", down, "VOL\n-", GREEN, "/volume/step", conn,
                    ("INTEGER", -VOLUME_STEP)))
    c.append(button(p + "vol_up", up, "VOL\n+", GREEN, "/volume/step", conn,
                    ("INTEGER", VOLUME_STEP)))
    c.append(last_row(last))
    return c, y


DEVICE_SIZES = dict(scrub=64, transport=130, transport2=90, skip=84, loop=84,
                    picture=84, ab=84, volume=84)
ALL_SIZES = dict(scrub=56, transport=110, transport2=76, skip=70, loop=70,
                 picture=70, ab=70, volume=70)


def page(tab, children, tab_color):
    return node("GROUP", [
        prop("s", "name", "page_" + tab.lower()),
        prop("r", "frame", (0, TAB, W, H)),
        prop("c", "color", BG),
        prop("b", "background", True),
        prop("s", "tabLabel", tab),
        prop("c", "tabColorOff", PANEL),
        prop("c", "tabColorOn", tab_color),
        prop("c", "textColorOff", DIM_TEXT),
        prop("c", "textColorOn", TEXT),
    ], children=children)


def device_page(n):
    p = f"d{n}_"
    c = [
        label(p + "lblFile", (X0, 10, X1 - X0, 46), f"player {n}: waiting for reply...",
              size=20, background=True),
        label(p + "lblTime", (X0, 62, 190, 34), "0:00 / 0:00", size=20, background=True),
        label(p + "lblAB", (X0 + 200, 62, X1 - X0 - 200, 34), "A-B loop: off", size=15,
              background=True),
        label(p + "lblState", (X0, 102, X1 - X0, 30),
              f"connection {n}: receive port {BASE_PORT + n}",
              size=14, color=DIM_TEXT, background=True),
        fader(p + "progress", (X0, 140, X1 - X0, 10), TEAL, interactive=False),
    ]
    rows, y = controls(p, [n], 160, DEVICE_SIZES, lambda frame: label(
        p + "lblVolume", frame, "volume: ?", size=15, background=True))
    c += rows
    # quit, out of the way at the bottom right (it needs two taps anyway)
    c.append(label(p + "conn", (X0, y, 300, 66),
                   f"player {n}: connection {n}\nreceive port {BASE_PORT + n}",
                   size=13, color=DIM_TEXT))
    c.append(quit_button(p + "quit", (X1 - 200, y, 200, 66), "QUIT\nPLAYER", [n]))
    return page(str(n), c, BLUE)


def all_page():
    p = "all_"
    # one status line per player
    c = [label(f"all_dev{n}", (X0, 10 + (n - 1) * 30, X1 - X0, 27), f"{n}    not connected",
               size=13, color=DIM_TEXT, background=True)
         for n in range(1, DEVICES + 1)]
    y = 10 + DEVICES * 30 + 2
    c.append(label(p + "info", (X0, y, X1 - X0, 40),
                   f"Everything on this page\ngoes to all {DEVICES} players",
                   size=14, color=DIM_TEXT))
    devices = list(range(1, DEVICES + 1))
    rows, _ = controls(p, devices, y + 50, ALL_SIZES,
                       lambda frame: quit_button(p + "quit", frame, "QUIT\nALL", devices))
    return page("ALL", c + rows, GOLD)


def build():
    pager = node("PAGER", [
        prop("s", "name", "pages"),
        prop("r", "frame", (0, 0, W, TAB + H)),
        prop("c", "color", BG),
        prop("b", "tabbar", True),
        prop("i", "tabbarSize", TAB),
        prop("b", "tabbarDoubleTap", False),
        prop("b", "tabLabels", True),
        prop("i", "textSizeOff", 16),
        prop("i", "textSizeOn", 18),
    ], [value("page", 0)],
        children=[all_page()] + [device_page(n) for n in range(1, DEVICES + 1)])

    root = node("GROUP", [
        prop("s", "name", "osc_vlc_player_phone"),
        prop("r", "frame", (0, 0, W, TAB + H)),
        prop("c", "color", BG),
        prop("b", "background", True),
        prop("s", "script", ROOT_SCRIPT),
    ], children=[pager])
    return f"<?xml version='1.0' encoding='UTF-8'?><lexml version='3'>{root}</lexml>"


if __name__ == "__main__":
    xml = build()
    out = Path(__file__).with_name("osc_vlc_player_phone.tosc")  # next to this script
    out.write_bytes(zlib.compress(xml.encode("utf-8")))
    print(f"wrote {out}")
