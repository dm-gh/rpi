#!/bin/sh
# Runs in privileged Debian container. Pi 4 + Docker both arm64, so chroot runs natively.
set -eu
I=$1 R=/r
# partition offsets from image's sfdisk table
LR=$(losetup -f --show -o $((2105344*512)) "$I")
LB=$(losetup -f --show -o $((8192*512)) --sizelimit $((2097152*512)) "$I")
mkdir -p $R; mount "$LR" $R; mount "$LB" $R/boot
cleanup() {
  [ -f /tmp/resolv.bak ] && cp /tmp/resolv.bak $R/etc/resolv.conf
  umount -R $R/dev $R/proc $R/sys 2>/dev/null || true
  umount $R/boot $R; losetup -d "$LB" "$LR"
}
trap cleanup EXIT
mount --rbind /dev $R/dev; mount -t proc proc $R/proc; mount --rbind /sys $R/sys
cp $R/etc/resolv.conf /tmp/resolv.bak; cat /etc/resolv.conf > $R/etc/resolv.conf

echo "== dkms source"
mkdir -p $R/usr/src/mhs35-drm-1.0
cp /m/dkms/* $R/usr/src/mhs35-drm-1.0/

echo "== kernel + headers + dkms (7.2.6 headers gone from mirror, so kernel moves too)"
chroot $R pacman -Sy --noconfirm --needed --disable-sandbox linux-aarch64 linux-aarch64-headers dkms
KV=$(ls $R/usr/lib/modules | grep -- '-ARCH$')
echo "kernel: $KV"
chroot $R dkms status
chroot $R sh -c "dkms status mhs35-drm/1.0 -k $KV | grep -q installed || dkms install mhs35-drm/1.0 -k $KV"
for m in drm_mipi_dbi ili9486 ads7846; do chroot $R modinfo -k "$KV" -F filename $m; done

echo "== initramfs (no autodetect: chroot would detect Docker's hardware)"
chroot $R mkinitcpio -k "$KV" -g /boot/initramfs-linux.img -S autodetect

echo "== overlay via U-Boot (firmware dtoverlay= unused, U-Boot loads its own dtb)"
dtc -@ -q -I dts -O dtb -o $R/boot/mhs35-drm.dtbo /m/mhs35-drm-overlay.dts
fdtoverlay -i $R/boot/dtbs/broadcom/bcm2711-rpi-4-b.dtb -o /tmp/check.dtb $R/boot/mhs35-drm.dtbo
dtc -q -I dtb -O dts /tmp/check.dtb | grep -q 'waveshare,rpi-lcd-35'
grep -q mhs35-drm $R/boot/boot.txt || sed -i '/fdt_addr_r} \/dtbs\/\${fdtfile}; then/a\
    # MHS-3.5" screen; ramdisk addr free until initramfs load below\
    if load ${devtype} ${devnum}:${bootpart} ${ramdisk_addr_r} /mhs35-drm.dtbo; then\
      fdt addr ${fdt_addr_r}; fdt resize 8192; fdt apply ${ramdisk_addr_r};\
    fi;' $R/boot/boot.txt
grep -q 'fdt apply' $R/boot/boot.txt
(cd $R/boot && mkimage -A arm -O linux -T script -C none -n "U-Boot boot script" -d boot.txt boot.scr >/dev/null)

echo "== udev + hyprland skel"
cp /m/files/90-mhs35-drm.rules $R/etc/udev/rules.d/
grep -q mhs35 $R/etc/skel/.config/hypr/monitors.lua || cat /m/files/monitors.lua.append >> $R/etc/skel/.config/hypr/monitors.lua
sync
