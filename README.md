# rpie

Raspberry Pi 4 (4 GB) + MHS-3.5" SPI touchscreen running Omarchy (Hyprland), used as a
touch internet radio playing to a Bluetooth speaker (Marshall Emberton III).

## Restore from scratch

1. **Image** (needs Docker on the Mac):
   - download `omarchy-4-pi-20260923-393f48c3-minimal.img.xz` (v0.2.0-alpha.4) from
     <https://github.com/pkyanam/omarchy-4-pi/releases> into `omarchy/`
   - `mhs35/build.sh` → `mhs35/out/omarchy-4-pi-mhs35.img`
   - flash it (`sudo dd ... of=/dev/rdiskN bs=4m` from a real terminal, or Raspberry Pi Imager)
2. **First boot is headless-capable**: put `rpi-preseed.toml` on the boot partition
   (Raspberry Pi Imager format: user, hashed password, Wi-Fi, SSH key). Without it the first
   boot waits on an interactive form on HDMI tty1. Validator: `/usr/bin/omarchy-rpi4-imager-preseed`
   inside the image. SSH key used: `~/.ssh/rpie`.
3. **Customisations**: `pi/install.sh` (idempotent; copies radio, configs, offline music).
4. **Speaker**: pair once with `bluetoothctl` (scan on / pair / trust / connect) *after*
   install.sh set `AlwaysPairable`, otherwise no link key is stored.
5. **Offline music**: `media/<station>/` on the Mac is the source of truth (git-ignored).
   Re-download with yt-dlp, see "Offline stations".

## Layout

| Path | What |
|---|---|
| `mhs35/mhs35-drm-overlay.dts` | Device-tree overlay: ILI9486 panel (DRM) + ADS7846 touch |
| `mhs35/dkms/` | Upstream v7.2.9 `drm_mipi_dbi`, `ili9486`, `ads7846` as DKMS (ALARM kernel lacks them) |
| `mhs35/build.sh`, `inner.sh` | Patch the Omarchy image: kernel+headers+dkms, overlay via U-Boot, udev, Hyprland skel |
| `mhs35/files/` | udev card names, Hyprland monitor/touch/window snippet |
| `radio/radio.py` | The radio app (GTK4 + mpv). `radio --check` runs self-test |
| `radio/desktop-icon.qml` | Big "Radio" desktop tile (Quickshell layer, bottom) |
| `pi/` | Pi-side config + `install.sh` / `setup-on-pi.sh` |
| `LCD-show/`, `omarchy/`, `media/`, `mhs35/out/` | Git-ignored: vendor clone, base image, audio, built image |

## Hard-won facts (don't rediscover)

**Display / touch**
- LCD-show's `mhs35` overlay is fbtft (fbdev); Hyprland needs DRM. Mainline `ili9486` with
  `compatible = "waveshare,rpi-lcd-35"` matches the board (16-bit regs over 8-bit SPI, like
  vendor `regwidth=16`). DC=GPIO24, RST=GPIO25, touch IRQ=GPIO17, panel CS0, touch CS1.
- Omarchy 4 Pi boots via U-Boot loading its own mainline DTB → `config.txt` `dtoverlay=`
  is ignored. Overlay applied in `/boot/boot.txt` with `fdt apply`, then `mkimage` → `boot.scr`.
- `reset-gpios` must be active-high: `mipi_dbi_hw_reset` ends at logical 1.
- `spi-bcm2835` native-CS lookup hardcodes gpiochip `pinctrl-bcm2835`; Pi 4 chip is
  `pinctrl-bcm2711` → `-EPROBE_DEFER` forever. Overlay uses explicit `cs-gpios`.
- DRM ili9486 `rotation`: 0 = landscape 480x320 (MADCTL 0xE0); **180 = vendor rotate=90**
  (MADCTL 0x20). Hyprland transform on the SPI output crops, so rotate in the panel.
- Touch: raw portrait; Hyprland `touchdevice.transform = 1` = vendor 90° calibration.
  Calibration range baked into overlay (`ti,x-min` etc.) from `99-calibration.conf-mhs35-0`.
- mipi-dbi mode has no pixel clock → Hyprland sees 0.007 Hz and paces frames by it (huge
  UI lag). Force `mode = "480x320@30"` for `SPI-1`.
- Two DRM cards; udev names `/dev/dri/vc4-card`, `/dev/dri/mhs35-card` and
  `AQ_DRM_DEVICES` keep vc4 primary (card numbering changes between boots).
- Omarchy floats are fixed 875x600 → overflow 480x320; capped by window rules in monitors.lua.
- Chroot builds: mkinitcpio `autodetect` would detect Docker's hardware → build with `-S autodetect`.

**System**
- Kernel bumped 7.2.6 → 7.2.9 in the image because 7.2.6 headers were gone from the mirror.
  DKMS rebuilds modules on kernel updates; a jump to a new major series may need newer driver sources.
- Hyprland 0.56 uses Lua config (`hl.monitor`, `hl.config`, `o.window`, `hl.dsp.*`);
  `hyprctl dispatch` takes Lua too.
- BlueZ default `Pairable: no` → pairing stores no link key → speaker forgotten each reboot.
  Fix: `AlwaysPairable = true` in `/etc/bluetooth/main.conf`, then re-pair.
- Auto-login: `/etc/sddm.conf.d/20-autologin.conf` (session `omarchy.desktop`);
  idle lock off via `omarchy-toggle-idle stay-awake`.
- SSH from Mac: use `-4`; `rpie.local` resolves to IPv6 addresses that aren't routable.
- macOS can't write raw disks from the Claude/terminal-app sandbox; flash from a real terminal.
- `dm` had passwordless sudo during setup (`/etc/sudoers.d/10-dm-nopasswd`); remove when done.

**Radio app**
- Plays only while default sink is `bluez_output.*` (polled every 3 s). Speaker off →
  stops streaming, keeps intent; speaker on → resumes. User stop is sticky.
- State in `~/.local/state/rpie-radio.json`: last station, intent, offline positions
  (saved every 30 s + on stop, atomic write).
- Views (bottom-right button cycles): auto-radio card (online) → online list → offline list.
- Live info: NTS API (show + description, 60 s); others via ICY title over mpv IPC.
- Fan: 2-wire, on 5 V GPIO = always on, no software control. Options: 3.3 V pin, transistor, or none.

## Offline stations

Add a `dict(name=..., dir="~/Music/<folder>", desc=...)` to `STATIONS`, then download:

```sh
python3 -m venv /tmp/ytdlp && /tmp/ytdlp/bin/pip install -U "yt-dlp[default]"
cd media/home-alone && /tmp/ytdlp/bin/yt-dlp --js-runtimes node -f bestaudio -x --audio-format opus \
  --ignore-errors --download-archive archive.txt --embed-metadata \
  -o "%(playlist_index)03d - %(title)s [%(id)s].%(ext)s" \
  'https://www.youtube.com/playlist?list=PLF8-vI7hE9YPRTtyeMdeuDLqcRn_O16Jp'
```

(`--js-runtimes node`: local Deno 1.x is too old for yt-dlp; without a JS runtime YouTube returns 403.)
Then `pi/install.sh` rsyncs `media/` to `~/Music/`.
