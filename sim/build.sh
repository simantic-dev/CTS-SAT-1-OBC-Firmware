#!/usr/bin/env bash
# Rebuild CTS-SAT-1_FW.elf from upstream at the pinned commit. Nothing is patched: the fixture runs the flight firmware.
# Needs arm-none-eabi-gcc (the committed ELF used Arm GNU Toolchain 15.2.1) and make.
# Upstream's default Makefile does not link at this commit (its source list is stale); CI's Makefile.GitHub.mk does.
# The result matches the committed ELF in every byte of code and data except the __DATE__/__TIME__ stamp.
#
# Usage: ./build.sh     env: CTS_WORK (default ~/.cache/simantic-fixtures/cts-sat-1-obc)
set -euo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
WORK=${CTS_WORK:-$HOME/.cache/simantic-fixtures/cts-sat-1-obc}
REV=1c98525a7b97f48ddef94b91df14d91b9fa3518a
mkdir -p "$WORK"
[ -d "$WORK/.git" ] || git init -q "$WORK"
git -C "$WORK" fetch -q --depth 1 https://github.com/CalgaryToSpace/CTS-SAT-1-OBC-Firmware.git "$REV"
git -C "$WORK" checkout -q -f FETCH_HEAD
make -C "$WORK/firmware" -f Makefile.GitHub.mk -j"$(getconf _NPROCESSORS_ONLN)"
cp "$WORK/firmware/build/CTS-SAT-1_FW.elf" "$HERE/CTS-SAT-1_FW.elf"
echo "wrote $HERE/CTS-SAT-1_FW.elf"
