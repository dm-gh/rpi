#!/bin/sh
# Bake MHS-3.5" screen support into the Omarchy 4 Pi image. Run on host with Docker.
set -eu
cd "$(dirname "$0")"
SRC=../omarchy/omarchy-4-pi-20260923-393f48c3-minimal.img.xz
OUT=out/omarchy-4-pi-mhs35.img
mkdir -p out
printf 'FROM debian:trixie-slim\nRUN apt-get -qq update && DEBIAN_FRONTEND=noninteractive apt-get -qq install -y device-tree-compiler fdisk mount xz-utils kmod u-boot-tools >/dev/null && rm -rf /var/lib/apt/lists/*\n' \
  | docker build -q -t rpie-tools - >/dev/null
echo "== decompress"; xz -dcT0 "$SRC" > "$OUT"
docker run --rm --privileged -v "$PWD:/m" rpie-tools sh /m/inner.sh "/m/$OUT"
echo "== done: $OUT"
