#!/usr/bin/env python3
# Touch internet radio for 480x320. mpv plays to PipeWire default sink (BT speaker).
import html
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

# nts = channel_name in NTS live API, for live show info; dir = offline station
STATIONS = [
    dict(name="NTS 1", url="https://stream-relay-geo.ntslive.net/stream", nts="1",
         desc="Independent radio from London, live shows around the clock."),
    dict(name="NTS 2", url="https://stream-relay-geo.ntslive.net/stream2", nts="2",
         desc="NTS second channel, more experimental live shows."),
    dict(name="Groove Salad", url="https://ice1.somafm.com/groovesalad-128-mp3",
         desc="SomaFM. A nicely chilled plate of ambient/downtempo beats and grooves."),
    dict(name="Drone Zone", url="https://ice2.somafm.com/dronezone-128-mp3",
         desc="SomaFM. Atmospheric textures with minimal beats. Served best chilled."),
    dict(name="Secret Agent", url="https://ice4.somafm.com/secretagent-128-mp3",
         desc="SomaFM. Lounge soundtrack for your stylish, mysterious, dangerous life."),
    dict(name="Lush", url="https://ice2.somafm.com/lush-128-mp3",
         desc="SomaFM. Sensuous and mellow female vocals, many with electronic influence."),
    dict(name="Radio Paradise", url="https://stream.radioparadise.com/mp3-192",
         desc="Listener-supported eclectic mix: rock, indie, electronica, world and more."),
    dict(name="Paradise Mellow", url="https://stream.radioparadise.com/mellow-192",
         desc="Radio Paradise's quieter side: laid-back, mellow tracks."),
    dict(name="home alone.", dir="~/Music/home-alone",
         desc="Offline. YouTube playlist of one-hour mood mixes."),
]
ONLINE = [i for i, s in enumerate(STATIONS) if "dir" not in s]
OFFLINE = [i for i, s in enumerate(STATIONS) if "dir" in s]
AUDIO_EXT = (".opus", ".m4a", ".mp3", ".ogg", ".flac", ".webm")
NTS_API = "https://www.nts.live/api/v2/live"
MPV_SOCK = "/tmp/rpie-radio-mpv.sock"
# last station, whether user wants music, offline positions; survives reboot
STATE = os.path.expanduser("~/.local/state/rpie-radio.json")
SAVE_EVERY = 6  # track polls (x5s) between position writes; spares SD card

CSS = b"""
button { font-weight: bold; border-radius: 10px; padding: 0; }
button.arrow { min-width: 52px; }
button.ctl { min-height: 50px; }
button.card { padding: 6px 10px; }
label.status { font-size: 14px; }
label.name { font-size: 22px; font-weight: bold; }
label.now { font-size: 14px; font-weight: bold; color: #e0af68; }
label.online { font-size: 12px; font-weight: bold; color: #8fbc5a; }
label.desc { font-size: 13px; font-weight: normal; }
label.rowname { font-size: 16px; font-weight: bold; }
label.rowinfo { font-size: 12px; }
row { min-height: 56px; border-radius: 8px; padding: 2px 8px; margin: 2px 0; }
"""


def parse_nts(data):
    """NTS live API -> {channel: (now line, description)}"""
    out = {}
    for ch in data.get("results", []):
        now = ch.get("now", {})
        details = now.get("embeds", {}).get("details", {})
        title = html.unescape(now.get("broadcast_title") or "")
        end = now.get("end_timestamp")
        until = f" · until {datetime.fromisoformat(end).astimezone():%H:%M}" if end else ""
        extra = ", ".join(filter(None, [details.get("location_long")] +
                                 [g.get("value") for g in details.get("genres", [])][:3]))
        desc = html.unescape(details.get("description") or "")
        out[ch.get("channel_name")] = (f"{title}{until}", f"{extra}. {desc}" if extra else desc)
    return out


def tracks(st):
    d = os.path.expanduser(st["dir"])
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(AUDIO_EXT))


def track_args(files, resume):
    """mpv args for whole looping playlist, resumed at saved file + position"""
    names = [os.path.basename(f) for f in files]
    idx = names.index(resume["track"]) if resume.get("track") in names else 0
    pos = resume.get("pos", 0) if resume.get("track") in names else 0
    args = ["--loop-playlist=inf", f"--playlist-start={idx}"]
    for k, f in enumerate(files):
        # per-file group: --start only for resumed track, rest start at 0
        args += ["--{", f"--start={pos:.0f}", f, "--}"] if k == idx and pos > 0 else [f]
    return args


def pretty(path):
    """'012 - title [youtubeid].opus' -> '012 - title'"""
    return re.sub(r"( \[[\w-]{11}\])?\.\w+$", "", os.path.basename(path or ""))


def mpv(*command):
    """one IPC request to running mpv; None if not reachable"""
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(0.3)
            s.connect(MPV_SOCK)
            s.sendall(json.dumps({"command": list(command)}).encode() + b"\n")
            return json.loads(s.recv(65536).split(b"\n")[0]).get("data")
    except (OSError, ValueError):
        return None


def label(text="", css=None, lines=1, wrap=False, xalign=0, **kw):
    lb = Gtk.Label(label=text, css_classes=[css] if css else [], wrap=wrap, lines=lines,
                   ellipsize=3, xalign=xalign, **kw)
    if wrap:
        lb.set_justify(Gtk.Justification.CENTER if xalign == 0.5 else Gtk.Justification.LEFT)
    return lb


def icon_button(icon, cb, css, name, sign=None):
    b = Gtk.Button(css_classes=[css], hexpand=True, tooltip_text=name)
    content = Gtk.Box(spacing=2, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    content.append(Gtk.Image(icon_name=icon, pixel_size=32))
    if sign:  # icon, not text: glyph metrics never centre
        content.append(Gtk.Image(icon_name=sign, pixel_size=20))
    b.set_child(content)
    b.update_property([Gtk.AccessibleProperty.LABEL], [name])
    b.connect("clicked", cb)
    return b


def set_icon(button, icon):
    button.get_child().get_first_child().set_from_icon_name(icon)


def with_online(name_label, text="● Online"):
    """name + green badge, shown only while playing"""
    online = label(text, "online", valign=Gtk.Align.CENTER)
    box = Gtk.Box(spacing=8)
    box.append(name_label)
    box.append(online)
    return box, online


# mode button shows current view
MODES = ["auto", "list", "offline"]
MODE_ICON = {"auto": "audio-x-generic-symbolic", "list": "view-list-symbolic",
             "offline": "folder-symbolic"}


class Radio(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.rpie.radio")
        self.player = None
        self.playing = None  # station mpv is streaming now
        self.want = None  # station user asked for; plays whenever speaker is up
        self.cur = ONLINE[0]  # station shown in auto-radio card (online only)
        self.last = ONLINE[0]  # what play button resumes
        self.resume = {}  # offline station name -> {"track", "pos"}
        self.speaker = False
        self.nts = {}
        self.track = ""  # ICY title / offline track of playing stream
        self.polls = 0
        self.load_state()

    def do_activate(self):
        # relaunch from bar/desktop raises existing window
        if self.get_active_window():
            self.get_active_window().present()
            return
        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.status = label("Stopped", "status")

        # auto-radio: one big card, arrows switch + play (online stations)
        self.card_name = label(css="name")
        self.card_now = label(css="now")
        self.card_desc = label(css="desc", lines=2, wrap=True, max_width_chars=20)
        card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER,
                           halign=Gtk.Align.FILL)
        name_row, self.card_online = with_online(self.card_name)
        for w in (name_row, self.card_now, self.card_desc):
            card_box.append(w)
        self.card = Gtk.Button(child=card_box, css_classes=["card"], hexpand=True,
                               overflow=Gtk.Overflow.HIDDEN)
        self.card.connect("clicked", lambda *_: self.toggle(self.cur))
        auto = Gtk.Box(spacing=6)
        prev = icon_button("go-previous-symbolic", lambda *_: self.switch(-1), "arrow", "Previous station")
        nxt = icon_button("go-next-symbolic", lambda *_: self.switch(1), "arrow", "Next station")
        for w in (prev, self.card, nxt):
            auto.append(w)
        prev.set_hexpand(False)
        nxt.set_hexpand(False)

        # lists: vertical scroll, tap row to play
        self.rows = {}  # station -> (info label, badge)
        online_list = self.station_list(ONLINE, "● Online")
        offline_list = self.station_list(OFFLINE, "● Playing")

        # offline: track skip under the list
        self.track_label = label(css="now", lines=2, wrap=True, max_width_chars=20)
        self.track_prev = icon_button("media-skip-backward-symbolic", lambda *_: self.skip("playlist-prev"),
                                      "arrow", "Previous track")
        self.track_next = icon_button("media-skip-forward-symbolic", lambda *_: self.skip("playlist-next"),
                                      "arrow", "Next track")
        self.track_bar = Gtk.Box(spacing=6)
        for w in (self.track_prev, self.track_label, self.track_next):
            self.track_bar.append(w)
        self.track_prev.set_hexpand(False)
        self.track_next.set_hexpand(False)
        self.track_label.set_hexpand(True)
        offline_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        offline_page.append(offline_list)
        offline_page.append(self.track_bar)

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(auto, "auto")
        self.stack.add_named(online_list, "list")
        self.stack.add_named(offline_page, "offline")

        self.play_btn = icon_button("media-playback-start-symbolic", self.play_pause, "ctl", "Play or pause")
        self.mode_btn = icon_button(MODE_ICON["auto"], self.next_mode, "ctl", "Switch view")
        controls = Gtk.Box(spacing=6, homogeneous=True)
        controls.append(icon_button("audio-volume-low-symbolic", lambda *_: self.volume("5%-"), "ctl", "Volume down", "list-remove-symbolic"))
        controls.append(self.play_btn)
        controls.append(icon_button("audio-volume-high-symbolic", lambda *_: self.volume("5%+"), "ctl", "Volume up", "list-add-symbolic"))
        controls.append(self.mode_btn)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin_top=4, margin_bottom=6, margin_start=6, margin_end=6)
        for w in (self.status, self.stack, controls):
            box.append(w)

        win = Gtk.ApplicationWindow(application=self, title="Radio", child=box)
        win.connect("close-request", lambda *_: self.stream(None))
        self.show_mode("auto")
        self.poll_speaker()
        self.refresh()
        win.present()

        self.fetch_nts()
        GLib.timeout_add_seconds(60, self.fetch_nts)
        GLib.timeout_add_seconds(5, self.poll_track)
        # ponytail: 3s poll of default sink; pactl subscribe if lag ever matters
        GLib.timeout_add_seconds(3, self.poll_speaker)
        # reboot/shutdown sends SIGTERM: save offline position before dying
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.on_term)

    def on_term(self):
        self.stream(None)
        self.quit()
        return False

    def station_list(self, indices, badge):
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        for i in indices:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            info = label(css="rowinfo")
            name_row, online = with_online(label(STATIONS[i]["name"], "rowname"), badge)
            box.append(name_row)
            box.append(info)
            listbox.append(Gtk.ListBoxRow(child=box, activatable=True))
            self.rows[i] = (info, online)
        listbox.connect("row-activated", lambda _lb, row: self.toggle(indices[row.get_index()]))
        return Gtk.ScrolledWindow(child=listbox, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)

    # --- actions

    def next_mode(self, *_):
        mode = MODES[(MODES.index(self.stack.get_visible_child_name()) + 1) % len(MODES)]
        self.stack.set_visible_child_name(mode)
        self.show_mode(mode)

    def show_mode(self, mode):
        set_icon(self.mode_btn, MODE_ICON[mode])

    def switch(self, step):
        pos = ONLINE.index(self.cur) if self.cur in ONLINE else 0
        self.choose(ONLINE[(pos + step) % len(ONLINE)])

    def toggle(self, i):
        self.choose(None if i == self.want else i)

    def play_pause(self, *_):
        self.choose(None if self.want is not None else self.last)

    def skip(self, command):
        mpv(command)
        GLib.timeout_add(400, lambda: self.poll_track() and False)

    def choose(self, i):
        """user intent; actual playback follows speaker presence"""
        self.want = i
        if i is not None:
            self.last = i
            if i in ONLINE:
                self.cur = i
        self.save_state()
        self.sync()

    def sync(self):
        target = self.want if self.speaker else None
        if target != self.playing:
            self.stream(target)
        self.refresh()

    def stream(self, i):
        if self.player:
            if self.playing in OFFLINE:
                self.remember_position()
                self.save_state()
            self.player.terminate()
            self.player.wait()
            self.player = None
        self.track = ""
        self.playing = i
        if i is None:
            return
        st = STATIONS[i]
        if i in OFFLINE:
            files = tracks(st)
            if not files:
                self.playing = None
                return
            source = track_args(files, self.resume.get(st["name"], {}))
        else:
            source = [st["url"]]
        self.player = subprocess.Popen(
            ["mpv", "--no-video", "--really-quiet", "--cache-secs=10",
             f"--input-ipc-server={MPV_SOCK}", *source]
        )

    def poll_speaker(self):
        try:
            sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                                  text=True, timeout=2).stdout
        except (OSError, subprocess.TimeoutExpired):
            sink = ""
        # BT speaker gone -> PipeWire falls back to built-in output; don't stream into nothing
        speaker = sink.startswith("bluez_output")
        if speaker != self.speaker:
            self.speaker = speaker
            self.sync()
        return True

    def volume(self, step):
        # speaker volume, not mpv's: one knob for everything
        subprocess.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", step])

    # --- state

    def remember_position(self):
        path, pos = mpv("get_property", "path"), mpv("get_property", "time-pos")
        if path and pos is not None:
            self.resume[STATIONS[self.playing]["name"]] = {"track": os.path.basename(path), "pos": pos}

    def load_state(self):
        try:
            with open(STATE) as f:
                st = json.load(f)
        except (OSError, ValueError):
            return
        names = [s["name"] for s in STATIONS]
        if st.get("cur") in names and names.index(st["cur"]) in ONLINE:
            self.cur = names.index(st["cur"])
        if st.get("last") in names:
            self.last = names.index(st["last"])
        # want not restored: boot starts paused; speaker auto-resume only within a session
        self.resume = st.get("resume", {})

    def save_state(self):
        name = lambda i: STATIONS[i]["name"] if i is not None else None
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"cur": name(self.cur), "last": name(self.last), "want": name(self.want),
                       "resume": self.resume}, f)
        os.replace(tmp, STATE)  # atomic: power cut can't leave half a file

    # --- live info

    def fetch_nts(self):
        def work():
            try:
                with urllib.request.urlopen(NTS_API, timeout=10) as r:
                    nts = parse_nts(json.load(r))
            except Exception:
                return  # keep last known; static desc is fallback
            GLib.idle_add(self.set_nts, nts)
        threading.Thread(target=work, daemon=True).start()
        return True

    def set_nts(self, nts):
        self.nts = nts
        self.refresh()

    def poll_track(self):
        if not self.player:
            return True
        if self.playing in OFFLINE:
            path = mpv("get_property", "path")
            n, count = mpv("get_property", "playlist-pos"), mpv("get_property", "playlist-count")
            title = f"{pretty(path)}   ({n + 1}/{count})" if path and n is not None else ""
            self.remember_position()
            self.polls += 1
            if self.polls % SAVE_EVERY == 0:
                self.save_state()
        else:
            title = mpv("get_property", "media-title") or ""
            # no ICY title -> mpv falls back to URL/filename
            title = "" if "/" in title or title.startswith("stream") else title
        if title != self.track:
            self.track = title
            self.refresh()
        return True

    def info(self, i):
        """(now line, description) for station i"""
        st = STATIONS[i]
        if st.get("nts") in self.nts:
            return self.nts[st["nts"]]
        if i == self.playing and self.track:
            return (self.track, st["desc"])
        if i in OFFLINE and st["name"] in self.resume:
            return (f"Resume: {pretty(self.resume[st['name']]['track'])}", st["desc"])
        return ("", st["desc"])

    # --- view

    def refresh(self):
        if not hasattr(self, "card"):
            return
        now, desc = self.info(self.cur)
        self.card_name.set_label(STATIONS[self.cur]["name"])
        self.card_now.set_label(now)
        self.card_now.set_visible(bool(now))
        self.card_desc.set_label(desc)
        self.card_online.set_visible(self.cur == self.playing)

        for i, (info, online) in self.rows.items():
            now, desc = self.info(i)
            info.set_label(now or desc)
            online.set_visible(i == self.playing)

        offline = self.want if self.want in OFFLINE else self.last if self.last in OFFLINE else None
        self.track_bar.set_visible(offline is not None)
        if offline is not None:
            self.track_label.set_label(self.info(offline)[0] or STATIONS[offline]["name"])
        for b in (self.track_prev, self.track_next):
            b.set_sensitive(self.playing in OFFLINE)

        if self.want is None:
            self.status.set_label("Stopped")
        elif self.playing is None:
            self.status.set_label(f"Waiting for speaker   ·   {STATIONS[self.want]['name']}")
        else:
            now = self.info(self.playing)[0]
            self.status.set_label(f"▶ {STATIONS[self.playing]['name']}" + (f" · {now}" if now else ""))
        set_icon(self.play_btn, "media-playback-pause-symbolic" if self.want is not None
                 else "media-playback-start-symbolic")


def check():
    """radio --check: resume/track-name logic"""
    f = ["/m/001 - a [abcdefghijk].opus", "/m/002 - b [abcdefghijk].opus"]
    assert track_args(f, {}) == ["--loop-playlist=inf", "--playlist-start=0", *f]
    assert track_args(f, {"track": "002 - b [abcdefghijk].opus", "pos": 12.4}) == [
        "--loop-playlist=inf", "--playlist-start=1", f[0], "--{", "--start=12", f[1], "--}"]
    # deleted file -> start of playlist, no stale offset
    assert track_args(f, {"track": "gone.opus", "pos": 50}) == track_args(f, {})
    assert pretty(f[0]) == "001 - a" and pretty("/x/song.mp3") == "song"
    print("ok")


if __name__ == "__main__":
    check() if sys.argv[1:] == ["--check"] else Radio().run()
