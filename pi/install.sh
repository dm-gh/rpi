#!/bin/sh
# Reapply rpie customisations to a Pi flashed with the mhs35/build.sh image. Run on Mac.
# Idempotent: safe to rerun after editing anything here.
set -eu
cd "$(dirname "$0")/.."
H=${PI:-dm@rpie.local}
KEY="-4 -i $HOME/.ssh/rpie"  # -4: rpie.local IPv6 addresses not routable from Mac

scp $KEY -q radio/radio.py "$H:/tmp/radio"
scp $KEY -q radio/org.rpie.radio.desktop radio/desktop-icon.qml \
  mhs35/files/monitors.lua.append pi/autostart.lua.append pi/20-autologin.conf pi/omarchy-screensaver pi/setup-on-pi.sh "$H:/tmp/"
# offline stations: audio only, no yt-dlp logs
rsync -a -e "ssh $KEY" --include='*/' --include='*.opus' --exclude='*' media/ "$H:Music/"
# -t: sudo may ask for password
ssh $KEY -t "$H" sh /tmp/setup-on-pi.sh
