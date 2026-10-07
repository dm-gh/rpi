#!/bin/sh
# Reapply rpie customisations to a Pi flashed with the mhs35/build.sh image. Run on Mac.
# Idempotent: safe to rerun after editing anything here.
set -eu
cd "$(dirname "$0")/.."
H=${PI:-rpie}  # ~/.ssh/config host alias, see README

scp -q radio/radio.py "$H:/tmp/radio"
scp -q radio/org.rpie.radio.desktop radio/desktop-icon.qml \
  mhs35/files/monitors.lua.append pi/autostart.lua.append pi/20-autologin.conf pi/omarchy-screensaver pi/setup-on-pi.sh "$H:/tmp/"
# offline stations: audio only, no yt-dlp logs
rsync -a -e ssh --include='*/' --include='*.opus' --exclude='*' media/ "$H:Music/"
# -t: sudo may ask for password
ssh -t "$H" sh /tmp/setup-on-pi.sh
