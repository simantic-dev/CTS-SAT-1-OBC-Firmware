#!/usr/bin/env python3
"""Decode the CTS-SAT-1 console that `sim run --ascii lpuart1` prints on stdin into one line of numbers per telecommand."""
import collections, json, re, sys

ROWS = 28  # on a terminal, redraw the last ROWS lines in place instead of scrolling
shown = collections.deque(maxlen=ROWS)


def emit(line):
    line = line[:120]
    if not sys.stdout.isatty():
        print(line, flush=True)
        return
    shown.append(line)
    sys.stdout.write("\033[H\033[J" + "\n".join(shown) + "\n")
    sys.stdout.flush()

LOG = re.compile(r"^\[([\d.]+)s\] \(lpuart1 → ground\) (.*)$")
STAMP = re.compile(r"^\d+\+\d+_[EN] \[")  # firmware log line; anything else is telecommand response text
cur, buf = None, []


def j(text):
    try:
        return json.loads(text)
    except ValueError:
        return {}


def show(cmd, body):
    name = cmd.split("(")[0]
    d = j(body)
    if name == "hello_world":
        out = "Hello, world"
    elif name == "eps_get_system_status_json":
        out = f"mode {d['mode']}  uptime {d['uptime_sec']} s  resets: power-on {d['rst_cnt_pwron']}, wdg {d['rst_cnt_wdg']}"
    elif name == "eps_set_channel_enabled":
        out = body.strip()
    elif name == "eps_get_enabled_channels_json":
        out = "enabled channels: " + ", ".join(re.findall(r'"(\w+)"', body))
    elif name == "eps_get_pbu_housekeeping_data_eng_json":
        v = d["vip_total_input"]
        out = (f"supply {d['voltage_internal_board_supply_mV']} mV  mcu {d['temperature_mcu_cC'] / 100:.2f} C  "
               f"input {v['mV']} mV {v['mA']} mA  batt {'/'.join(f'{t / 100:.2f}' for t in d['battery_pack']['battery_temperature_each_sensor_cC'])} C")
    elif name == "adcs_identification":
        out = f"node type {d['node_type']}  firmware {d['major_firmware_version']}.{d['minor_firmware_version']}"
    elif name == "adcs_program_status":
        out = f"boot cause {d['boot_cause']}  boot counter {d['boot_counter']}  program {d['boot_program_index']}"
    elif name == "adcs_set_run_mode":
        out = "run mode set"
    elif name == "adcs_get_current_state_1":
        out = f"run mode {d['adcs_run_mode']}  control mode {d['control_mode']}  estimation mode {d['attitude_estimation_mode']}"
    elif name == "gnss_send_cmd_ascii":
        m = re.search(r"TIMEA,\w+,\d+,[\d.]+,(\w+),(\d+),([\d.]+),.*?(\d{4}),(\d+),(\d+),(\d+),(\d+),(\d+),(\w+)\*", body)
        out = f"{m[1]} week {m[2]} tow {m[3]} s  UTC {m[4]}-{int(m[5]):02d}-{int(m[6]):02d} {m[7]}:{int(m[8]):02d}" if m else body[:70]
    elif name == "fs_write_file_str":
        out = "write ok"
    elif name == "fs_read_file_hex":
        h = body.strip()
        out = f"{h[:12]}...  = {bytes.fromhex(h).decode()!r}" if h else ""
    elif name == "fs_list_directory":
        out = "  ".join(re.findall(r"\]: (\S+/?(?: \(\d+ B\))?)$", body, re.M)[:6])
    else:
        out = body.strip()[:80]
    emit(f"  => {out}")


def flush():
    if cur:
        show(cur, "\n".join(buf) if cur.startswith(("gnss", "fs_list")) else "".join(buf))


for line in sys.stdin:
    line = line.rstrip("\n")
    if line.startswith("[ground] GROUND TX CTS1+"):
        flush()
        cur, buf = line[len("[ground] GROUND TX CTS1+"):].rstrip("!"), []
        emit(line)
        continue
    m = LOG.match(line)
    if not m:
        continue
    t, text = m.groups()
    # raw firmware console line, as printed; only the sim's "(lpuart1 → ground)" tag is dropped and the line cut to the screen width
    if text.strip() and not text.startswith(("AX100", "====")):
        emit(f"[{t}s] {text}")
    if cur is None:
        continue
    if STAMP.match(text):
        if cur.startswith("fs_list") and "[T:LFS" in text:
            buf.append(text)
        elif cur.startswith("fs_write") and "Successfully wrote" in text:
            buf.append(text)
    elif text and not text.startswith(("AX100", "====", "Hello, world", "LittleFS write")):
        buf.append(text)
flush()
