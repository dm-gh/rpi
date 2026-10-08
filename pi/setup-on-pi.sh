#!/bin/sh
# Pi side of install.sh; files staged in /tmp.
set -eu
mkdir -p ~/.local/bin ~/.local/share/applications ~/.config/quickshell/desktop-icons
install -m755 /tmp/radio ~/.local/bin/radio
install -m644 /tmp/org.rpie.radio.desktop ~/.local/share/applications/
install -m644 /tmp/desktop-icon.qml ~/.config/quickshell/desktop-icons/shell.qml
~/.local/bin/radio --check

# Hyprland: drop old rpie blocks, append current
m=~/.config/hypr/monitors.lua
sed -i '/^-- MHS-3.5" SPI screen/,$d' "$m"
cat /tmp/monitors.lua.append >> "$m"
a=~/.config/hypr/autostart.lua
sed -i '/desktop-icons\|\/.local\/bin\/radio\|^-- Radio\|^-- rpie:/d' "$a"
cat /tmp/autostart.lua.append >> "$a"

# Omarchy bar: radio button + close-window escape hatch (no keyboard to close terminals)
python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.config/omarchy/shell.json"); c = json.load(open(p))
mods = [m for ms in c["bar"]["layout"].values() for m in ms]
big = {"type": "command", "fontSize": 18, "horizontalMargin": 14, "keepSpace": True}
# only if absent: bar widgets can be dragged to other sections
if not any(m.get("id") == "radio" for m in mods):
    c["bar"]["layout"]["left"].append(dict(big, id="radio", text="\U000F0439", tooltip="Radio", onClick="radio"))
if not any(m.get("id") == "close-window" for m in mods):
    c["bar"]["layout"]["right"].append(dict(big, id="close-window", text="\U000F0156", tooltip="Close window",
        onClick="hyprctl dispatch 'hl.dsp.window.close()'"))
json.dump(c, open(p, "w"), indent=2, ensure_ascii=False)
PY

# no popups (update/keybinding banners need keyboard); own-action toasts still show
OMARCHY_PATH=/usr/share/omarchy XDG_RUNTIME_DIR=/run/user/$(id -u) omarchy-shell notifications setDnd true >/dev/null || true

# lock never (unlock needs keyboard). 2e6 s: QML timer ms must fit int32
python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.config/omarchy/shell.json"); c = json.load(open(p))
c.setdefault("idle", {})["lock"] = 2000000
json.dump(c, open(p, "w"), indent=2, ensure_ascii=False)
PY
omarchy-toggle-idle allow-idle >/dev/null
# no screensaver: touch can't dismiss it (terminal app, keyboard only)
mkdir -p ~/.local/state/omarchy/toggles && touch ~/.local/state/omarchy/toggles/screensaver-off
rm -rf ~/.local/share/rpie/bin  # old tap-exit wrapper attempt

# boot straight to desktop
sudo install -m644 /tmp/20-autologin.conf /etc/sddm.conf.d/20-autologin.conf
# BlueZ default Pairable=no -> pairings never store link keys -> speaker lost after reboot
f=/etc/bluetooth/main.conf
grep -q '^AlwaysPairable' "$f" || { sudo cp -n "$f" "$f.orig"; sudo sed -i '0,/^\[General\]/s//[General]\nAlwaysPairable = true/' "$f"; sudo systemctl restart bluetooth; }
# restart radio on new code; SIGTERM handler saves offline position
pkill -f '[.]local/bin/radio' || true
export XDG_RUNTIME_DIR=/run/user/$(id -u)
HYPRLAND_INSTANCE_SIGNATURE=$(ls "$XDG_RUNTIME_DIR/hypr" 2>/dev/null | head -1) \
  hyprctl dispatch "hl.dsp.exec_cmd([[$HOME/.local/bin/radio]])" >/dev/null 2>&1 || true

echo "done. Pair speaker once (bluetoothctl: scan on, pair, trust, connect), then reboot."
