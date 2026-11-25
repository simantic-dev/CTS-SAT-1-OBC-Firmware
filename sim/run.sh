#!/bin/sh
# PASS/FAIL check: the flight firmware must boot, mount LittleFS and answer every telecommand (assertions from the
# fixture's test.yaml). Run from anywhere.
set -eu
cd "$(dirname "$0")"
sim run --scenario scenario.yaml --ascii lpuart1 --timeout 20 \
  --expect "LittleFS mounting successful!" --expect "Hello, world!" --expect "EPS enable channel 8 (3V3_GNSS) executed." \
  --expect '"voltage_internal_board_supply_mV":3300' --expect '"node_type":10' --expect "FINESTEERING,2445," \
  --expect "4354532D5341542D31207065727369737473" --expect "hello.txt (18 B)" \
  --expect-absent "[A:LFS:CRIT]" --expect-absent "[A:EPS:ERR]" --expect-absent "HardFault" >/dev/null 2>&1 || { echo FAIL; exit 1; }
echo PASS
