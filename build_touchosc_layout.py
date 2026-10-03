#!/usr/bin/env python3
"""
Generate osc_vlc_player.tosc, a TouchOSC layout for osc_vlc_player.py that
controls up to 8 players (one per Raspberry Pi).

    python3 build_touchosc_layout.py            # writes osc_vlc_player.tosc

Pages (tabs along the top):
    ALL      every button goes to all players; shows a one-line status per player
    1 .. 8   one player each, with the full status display

Player n is TouchOSC connection n (OSC, UDP): host = that Pi's IP address,
send port 9000, receive port 9000 + n (9001 for player 1, 9002 for player 2 ...).
The layout polls each player with "/status <port>" twice a second, so every
player answers on its own port and the replies can be told apart.

A .tosc file is zlib-compressed XML. Edit the LAYOUT section below and
re-run to change buttons, sizes or colours.
"""

import uuid
import zlib
from pathlib import Path

DEVICES = 8               # TouchOSC has 10 connections; pages for 1..DEVICES
BASE_PORT = 9000          # player n replies on BASE_PORT + n
W, H = 1024, 768          # size of one page (landscape tablet); TouchOSC scales to fit
TAB = 50                  # height of the page tab bar above the pages
MARGIN, GAP = 16, 10

# --- colours (r, g, b, a) ---------------------------------------------------
BG = (0.08, 0.08, 0.10, 1)
PANEL = (0.14, 0.14, 0.17, 1)
TEXT = (1, 1, 1, 1)
DIM_TEXT = (0.7, 0.7, 0.75, 1)
GREEN = (0.20, 0.65, 0.35, 1)
RED = (0.75, 0.25, 0.25, 1)
BLUE = (0.20, 0.45, 0.80, 1)
ORANGE = (0.85, 0.50, 0.15, 1)
PURPLE = (0.55, 0.35, 0.80, 1)
GREY = (0.40, 0.40, 0.45, 1)
TEAL = (0.15, 0.60, 0.65, 1)
GOLD = (0.75, 0.60, 0.15, 1)

ROOT_SCRIPT = r"""
-- Poll every player for status and show it on its page and on the ALL page.
-- Player n is connection n and replies on port BASE_PORT + n.
local DEVICES = %(devices)d
local BASE_PORT = %(base_port)d
local POLL_MS = 500
local OFFLINE_MS = 2500
local last = 0
local status, seen, conns, cache = {}, {}, {}, {}

for n = 1, DEVICES do
  status[n] = {}
  seen[n] = -1                  -- time of the last complete reply, -1 = never
  local c = {}
  for i = 1, 10 do c[i] = (i == n) end
  conns[n] = c
end

local function fmt(t)
  t = math.floor(tonumber(t) or 0)
  return string.format('%%d:%%02d', math.floor(t / 60), t %% 60)
end

local function ctl(name)
  local c = cache[name]
  if c == nil then
    c = root:findByName(name, true) or false
    cache[name] = c
  end
  return c
end

local function setText(name, text)
  local c = ctl(name)
  if c then c.values.text = text end
end

local function up(v) return string.upper(tostring(v or '?')) end

-- one line per player for the ALL page
local function summary(n, now)
  local s = status[n]
  if seen[n] < 0 then return n .. '    not connected' end
  if now - seen[n] > OFFLINE_MS then return n .. '    NO REPLY' end
  local index = tonumber(s.index) or -1
  local file = index >= 0 and string.format('%%d. %%s', index + 1, tostring(s.file or '')) or 'no video'
  return string.format('%%d    %%s    %%s / %%s    %%s', n, up(s.state),
    fmt(s.time), fmt(s.length), file)
end

local function refresh(n, now)
  local s, p = status[n], 'd' .. n .. '_'
  setText('all_dev' .. n, summary(n, now))
  if now - seen[n] > OFFLINE_MS then
    setText(p .. 'lblState', 'NO REPLY from player ' .. n .. ' (connection ' .. n ..
      ', receive port ' .. (BASE_PORT + n) .. ')')
    return
  end
  local index = tonumber(s.index) or -1
  if index >= 0 then
    setText(p .. 'lblFile', string.format('%%d.  %%s', index + 1, tostring(s.file or '')))
  else
    setText(p .. 'lblFile', 'no video')
  end
  setText(p .. 'lblTime', fmt(s.time) .. ' / ' .. fmt(s.length))
  setText(p .. 'lblState', up(s.state) .. '     loop: ' .. up(s.loop) ..
    '     vol: ' .. tostring(s.volume or '?') .. '     aspect: ' .. up(s.aspect))
  local a, b = tonumber(s.abstart) or -1, tonumber(s.abend) or -1
  if a < 0 then
    setText(p .. 'lblAB', 'A-B loop: off')
  elseif b < 0 then
    setText(p .. 'lblAB', 'A-B loop: A = ' .. fmt(a) .. ', set B...')
  else
    setText(p .. 'lblAB', 'A-B loop: ' .. fmt(a) .. '  to  ' .. fmt(b))
  end
  local length = tonumber(s.length) or 0
  local bar = ctl(p .. 'progress')
  if bar and length > 0 then
    bar.values.x = math.min(1, (tonumber(s.time) or 0) / length)
  end
end

function update()
  local now = getMillis()
  if now - last < POLL_MS then return end
  last = now
  for n = 1, DEVICES do
    sendOSC({ '/status', { { tag = 'i', value = BASE_PORT + n } } }, conns[n])
    -- a player that stops answering is shown as NO REPLY
    if seen[n] >= 0 and now - seen[n] > OFFLINE_MS then refresh(n, now) end
  end
end

function onReceiveOSC(message, connections)
  local key = string.match(message[1], '^/status/(%%a+)$')
  if not key then return end
  local n
  for i = 1, DEVICES do
    if connections[i] then n = i break end
  end
  if not n then return end
  local args = message[2]
  if args and args[1] then status[n][key] = args[1].value end
  -- the player sends /status/loop last, so redraw once the set is complete
  if key == 'loop' then
    seen[n] = getMillis()
    refresh(n, seen[n])
  end
end
""" % {"devices": DEVICES, "base_port": BASE_PORT}


# --- XML helpers --------------------------------------------------------------

def cdata(s):
    return f"<![CDATA[{s}]]>"


def prop(ptype, key, value):
    if ptype == "r":
        inner = "".join(f"<{k}>{int(v)}</{k}>" for k, v in zip("xywh", value))
    elif ptype == "c":
        inner = "".join(f"<{k}>{v}</{k}>" for k, v in zip("rgba", value))
    elif ptype == "s":
        inner = cdata(value)
    elif ptype == "b":
        inner = str(int(bool(value)))
    else:
        inner = str(value)
    return f"<property type='{ptype}'><key>{cdata(key)}</key><value>{inner}</value></property>"


def value(key, default):
    d = cdata(default) if isinstance(default, str) else default
    return (f"<value><key>{cdata(key)}</key><locked>0</locked>"
            f"<lockedDefaultCurrent>0</lockedDefaultCurrent>"
            f"<default>{d}</default><defaultPull>0</defaultPull></value>")


def partial(ptype, conversion, val, scale=(0, 1)):
    return (f"<partial><type>{ptype}</type><conversion>{conversion}</conversion>"
            f"<value>{cdata(val)}</value>"
            f"<scaleMin>{scale[0]}</scaleMin><scaleMax>{scale[1]}</scaleMax></partial>")


def connections(devices):
    """TouchOSC's 10-digit connection mask, a binary number with connection 1
    as the rightmost digit: [1] -> '0000000001', [3] -> '0000000100'."""
    return "".join("1" if i in devices else "0" for i in range(10, 0, -1))


def osc(path, args, conn, trigger="ANY"):
    """One outgoing OSC message to the connections in mask `conn`.
    `args` is a list of partial() strings."""
    return ("<osc><enabled>1</enabled><send>1</send><receive>0</receive>"
            "<feedback>0</feedback><noDuplicates>0</noDuplicates>"
            f"<connections>{conn}</connections>"
            f"<triggers><trigger><var>{cdata('x')}</var>"
            f"<condition>{trigger}</condition></trigger></triggers>"
            f"<path>{partial('CONSTANT', 'STRING', path)}</path>"
            f"<arguments>{''.join(args)}</arguments></osc>")


def node(ntype, props, values=(), messages=(), children=()):
    return (f"<node ID='{uuid.uuid4()}' type='{ntype}'>"
            f"<properties>{''.join(props)}</properties>"
            f"<values>{''.join(values)}</values>"
            f"<messages>{''.join(messages)}</messages>"
            f"<children>{''.join(children)}</children></node>")


# --- control builders -----------------------------------------------------------

def label(name, frame, text, size=18, color=TEXT, background=False, bg=PANEL):
    return node("LABEL", [
        prop("s", "name", name),
        prop("r", "frame", frame),
        prop("c", "color", bg),
        prop("b", "background", background),
        prop("b", "outline", False),
        prop("b", "interactive", False),
        prop("c", "textColor", color),
        prop("i", "textSize", size),
    ], [value("text", text)])


def button(name, frame, text, color, path, conn, arg=None, toggle=False, default=0):
    """A button plus a text label drawn on top of it.

    arg=None      -> sends the button value (1 press / 0 release; player ignores 0)
    arg=(conv, v) -> sends a constant, on press only
    """
    if arg is None:
        message = osc(path, [partial("VALUE", "FLOAT", "x")], conn)
    else:
        message = osc(path, [partial("CONSTANT", arg[0], arg[1])], conn, trigger="RISE")
    btn = node("BUTTON", [
        prop("s", "name", name),
        prop("r", "frame", frame),
        prop("c", "color", color),
        prop("i", "buttonType", 1 if toggle else 0),  # 0 momentary, 1 toggle
    ], [value("x", default)], [message])
    return btn + label(name + "_lbl", frame, text, size=20)


QUIT_SCRIPT = r"""
-- Quit needs two taps: the first arms it, a second within 3 seconds sends /quit.
local ARM_MS = 3000
local CONNECTIONS = %(connections)s
local TEXT = '%(text)s'
local armed = -1

local function setLabel(text)
  local lbl = self.parent:findByName(self.name .. '_lbl')
  if lbl then lbl.values.text = text end
end

function onValueChanged(key)
  if key ~= 'x' or self.values.x < 1 then return end
  if armed >= 0 and getMillis() - armed < ARM_MS then
    armed = -1
    sendOSC('/quit', CONNECTIONS)
    setLabel(TEXT)
  else
    armed = getMillis()
    setLabel('TAP AGAIN\nTO QUIT')
  end
end

function update()
  if armed >= 0 and getMillis() - armed >= ARM_MS then
    armed = -1
    setLabel(TEXT)
  end
end
"""


def quit_button(name, frame, text, devices):
    """A QUIT button that sends /quit to `devices` only after a second tap."""
    lua_connections = "{ " + ", ".join(
        "true" if i in devices else "false" for i in range(1, 11)) + " }"
    script = QUIT_SCRIPT % {"connections": lua_connections,
                            "text": text.replace("\n", "\\n")}
    btn = node("BUTTON", [
        prop("s", "name", name),
        prop("r", "frame", frame),
        prop("c", "color", RED),
        prop("i", "buttonType", 0),
        prop("s", "script", script),
    ], [value("x", 0)])
    return btn + label(name + "_lbl", frame, text, size=18)


def fader(name, frame, color, messages=(), interactive=True, default=0):
    return node("FADER", [
        prop("s", "name", name),
        prop("r", "frame", frame),
        prop("c", "color", color),
        prop("i", "orientation", 1),  # horizontal, left to right
        prop("b", "interactive", interactive),
    ], [value("x", default)], messages)


def row(y, h, x0=MARGIN, x1=W - MARGIN, n=1):
    """Split a horizontal strip into n equal frames."""
    w = (x1 - x0 - GAP * (n - 1)) / n
    return [(x0 + i * (w + GAP), y, w, h) for i in range(n)]


# --- LAYOUT -------------------------------------------------------------------

# (y, height) of each row of controls. A device page has a status panel at the
# top; the ALL page squeezes the rows a little to fit 8 status lines instead.
DEVICE_ROWS = dict(scrub=(134, 60), transport=(206, 120), skip=(336, 80),
                   loop=(426, 80), ab=(516, 70), picture=(596, 70), volume=(676, 76))
ALL_ROWS = dict(scrub=(196, 56), transport=(262, 100), skip=(372, 70),
                loop=(452, 70), ab=(532, 60), picture=(602, 60), volume=(672, 80))


def controls(p, devices, rows, ab_info, quit_text):
    """The control rows shared by every page. `p` prefixes the control names,
    `devices` are the connections the messages go to, `ab_info` is the control
    shown to the right of the A-B buttons, next to the QUIT button."""
    conn = connections(devices)
    c = []

    # Scrub fader
    y, h = rows["scrub"]
    c.append(label(p + "scrub_cap", (MARGIN, y, 120, h), "SCRUB", size=16, color=DIM_TEXT))
    c.append(fader(p + "scrub", (MARGIN + 130, y, W - 2 * MARGIN - 130, h), TEAL,
                   [osc("/position", [partial("VALUE", "FLOAT", "x")], conn)]))

    # Transport
    for frame, (name, text, color, path) in zip(row(*rows["transport"], n=4), [
        ("prev", "<<  PREV", BLUE, "/prev"),
        ("toggle", "PLAY / PAUSE", GREEN, "/toggle"),
        ("stop", "STOP", RED, "/stop"),
        ("next", "NEXT  >>", BLUE, "/next"),
    ]):
        c.append(button(p + name, frame, text, color, path, conn))

    # Skip buttons
    skips = [-30, -10, -5, -1, 1, 5, 10, 30]
    for frame, s in zip(row(*rows["skip"], n=len(skips)), skips):
        c.append(button(f"{p}skip{s:+d}", frame, f"{s:+d}s", GREY, "/skip", conn,
                        ("FLOAT", s)))

    # Loop mode + restart + playback speed
    y, h = rows["loop"]
    left = row(y, h, x1=W / 2 - GAP / 2, n=4)
    right = row(y, h, x0=W / 2 + GAP / 2, n=4)
    for frame, (mode, text) in zip(left, [("none", "LOOP\nOFF"), ("all", "LOOP\nALL"),
                                          ("one", "LOOP\nONE")]):
        c.append(button(f"{p}loop_{mode}", frame, text, ORANGE, "/loop", conn,
                        ("STRING", mode)))
    c.append(button(p + "restart", left[3], "RESTART\nVIDEO", GREY, "/seek", conn,
                    ("FLOAT", 0)))
    for frame, r in zip(right, [0.5, 1, 1.5, 2]):
        c.append(button(f"{p}rate{r}", frame, f"SPEED\n{r}x", PURPLE, "/rate", conn,
                        ("FLOAT", r)))

    # A-B loop: set A, set B (starts looping), clear, and a readout / note
    y, h = rows["ab"]
    for frame, (name, text, path) in zip(row(y, h, x1=W / 2 - GAP / 2, n=3), [
        ("ab_a", "SET A", "/ab/a"),
        ("ab_b", "SET B", "/ab/b"),
        ("ab_clear", "CLEAR\nA-B", "/ab/clear"),
    ]):
        c.append(button(p + name, frame, text, TEAL, path, conn))
    QUIT_W = 140
    c.append(ab_info(row(y, h, x0=W / 2 + GAP / 2, x1=W - MARGIN - QUIT_W - GAP)[0]))
    c.append(quit_button(p + "quit", (W - MARGIN - QUIT_W, y, QUIT_W, h), quit_text,
                         devices))

    # Picture: aspect ratio buttons, fullscreen and mute toggles
    y, h = rows["picture"]
    for frame, (mode, text) in zip(row(y, h, x1=W / 2 - GAP / 2, n=4), [
        ("fill", "FILL\nSCREEN"),
        ("original", "ORIGINAL\nSHAPE"),
        ("16:9", "16:9"),
        ("4:3", "4:3"),
    ]):
        c.append(button(f"{p}aspect_{mode.replace(':', 'x')}", frame, text, GOLD,
                        "/aspect", conn, ("STRING", mode)))
    toggles = row(y, h, x0=W / 2 + GAP / 2, n=2)
    c.append(button(p + "fullscreen", toggles[0], "FULL\nSCREEN", GREY, "/fullscreen",
                    conn, toggle=True, default=1))
    c.append(button(p + "mute", toggles[1], "MUTE", RED, "/mute", conn, toggle=True))

    # Volume
    y, h = rows["volume"]
    c.append(label(p + "vol_cap", (MARGIN, y, 120, h), "VOLUME", size=16, color=DIM_TEXT))
    c.append(fader(p + "volume", (MARGIN + 130, y, W - 2 * MARGIN - 130, h), GREEN,
                   [osc("/volume", [partial("VALUE", "INTEGER", "x", scale=(0, 100))], conn)],
                   default=1))
    return c


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
        label(p + "lblFile", (MARGIN, 16, 700, 50), f"player {n}: waiting for reply...",
              size=24, background=True),
        label(p + "lblTime", (MARGIN + 710, 16, W - 2 * MARGIN - 710, 50), "0:00 / 0:00",
              size=24, background=True),
        label(p + "lblState", (MARGIN, 72, W - 2 * MARGIN, 30),
              f"connection {n}: send port 9000, receive port {BASE_PORT + n}",
              size=16, color=DIM_TEXT, background=True),
        fader(p + "progress", (MARGIN, 110, W - 2 * MARGIN, 14), TEAL, interactive=False),
    ]
    c += controls(p, [n], DEVICE_ROWS, lambda frame: label(
        p + "lblAB", frame, "A-B loop: off", size=18, background=True), "QUIT\nPLAYER")
    return page(str(n), c, BLUE)


def all_page():
    p = "all_"
    # one status line per player: 1-4 in the left column, 5-8 in the right
    c = []
    per_col = (DEVICES + 1) // 2
    cols = row(16, 0, n=2)
    for n in range(1, DEVICES + 1):
        x, _, w, _ = cols[(n - 1) // per_col]
        y = 16 + ((n - 1) % per_col) * 44
        c.append(label(f"all_dev{n}", (x, y, w, 38), f"{n}    not connected",
                       size=15, color=DIM_TEXT, background=True))
    c += controls(p, list(range(1, DEVICES + 1)), ALL_ROWS, lambda frame: label(
        p + "info", frame, f"Everything on this page\ngoes to all {DEVICES} players",
        size=16, color=DIM_TEXT), "QUIT\nALL")
    return page("ALL", c, GOLD)


def build():
    pager = node("PAGER", [
        prop("s", "name", "pages"),
        prop("r", "frame", (0, 0, W, TAB + H)),
        prop("c", "color", BG),
        prop("b", "tabbar", True),
        prop("i", "tabbarSize", TAB),
        prop("b", "tabbarDoubleTap", False),
        prop("b", "tabLabels", True),
        prop("i", "textSizeOff", 18),
        prop("i", "textSizeOn", 20),
    ], [value("page", 0)],
        children=[all_page()] + [device_page(n) for n in range(1, DEVICES + 1)])

    root = node("GROUP", [
        prop("s", "name", "osc_vlc_player"),
        prop("r", "frame", (0, 0, W, TAB + H)),
        prop("c", "color", BG),
        prop("b", "background", True),
        prop("s", "script", ROOT_SCRIPT),
    ], children=[pager])
    return f"<?xml version='1.0' encoding='UTF-8'?><lexml version='3'>{root}</lexml>"


if __name__ == "__main__":
    xml = build()
    out = Path(__file__).with_name("osc_vlc_player.tosc")  # next to this script
    out.write_bytes(zlib.compress(xml.encode("utf-8")))
    print(f"wrote {out}")
