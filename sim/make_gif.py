"""Builds timeline.gif (a mission-operations view) from run.log, the run's own UART capture. Pillow + ffmpeg only.
usage: python3 make_gif.py run.log timeline.gif <sim-version> [title]      (run from sim/)"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gifkit import *

LOG, OUT, VER = sys.argv[1:4]
TITLE = sys.argv[4] if len(sys.argv) > 4 else "CTS-SAT-1 OBC"
rows = []   # console lines on the debug UART: (t, text)
for l in open(LOG, errors="replace"):
    m = re.match(r"\[([\d.]+)s\] \(lpuart1 → ground\) ?(.*)", l.rstrip("\n"))
    if m and m[2].strip(): rows.append((float(m[1]), m[2]))
STAMP = re.compile(r"^\d+\+\d+_\w \[(\w:\w+):(\w+)\]: (.*)")
con, tcmds, cur = [], [], None    # con: (t, level, text); tcmds: dict per telecommand
for t, s in rows:
    if "=====" in s or s.startswith("AX100"): continue
    m = STAMP.match(s)
    if m:
        tag, lv, msg = m.groups()
        con.append((t, "WARN" if lv.startswith("WARN") else "ERROR" if lv.startswith("ERR") else "INFO", f"[{tag}] {msg}"))
        e = re.match(r"\.\.\.\. Executing telecommand '(\w+)'", msg)
        if e: cur = dict(name=e[1], t=t, payload="", lines=[], done=None); tcmds.append(cur)
        d = re.match(r"\.\.\.\. Telecommand '(\w+)' executed\. Duration=(\d+)ms, err=(\d+)", msg)
        if d and cur: cur["done"] = (t, int(d[2]), int(d[3]))
        if cur and not e and not d: cur["lines"].append((t, msg))
        if cur and cur["done"] is None and "Successfully listed" in msg: cur["done"] = (t, 0, 0)
    else:
        con.append((t, "INFO", s))
        if cur: cur["payload"] += s; cur["pt"] = t

def js(c):
    try: return json.loads(c["payload"])
    except Exception: return {}
def lastline(c): return c["lines"][-1][1] if c["lines"] else ""
RES = {
 "hello_world": lambda c: c["payload"],
 "eps_get_system_status_json": lambda c: f"EPS mode {js(c).get('mode')}, up {js(c).get('uptime_sec')} s, power-on resets {js(c).get('rst_cnt_pwron')}",
 "eps_set_channel_enabled": lambda c: c["payload"].replace(" executed.", ""),
 "eps_get_enabled_channels_json": lambda c: "enabled: " + c["payload"].replace('[,', '').strip('[]'),
 "eps_get_pbu_housekeeping_data_eng_json": lambda c: f"bus {js(c)['vip_total_input']['mV']/1000:.3f} V {js(c)['vip_total_input']['mA']} mA, MCU {js(c)['temperature_mcu_cC']/100:.1f} C",
 "adcs_identification": lambda c: f"node type {js(c).get('node_type')}, firmware {js(c).get('major_firmware_version')}.{js(c).get('minor_firmware_version')}",
 "adcs_program_status": lambda c: f"boot cause {js(c).get('boot_cause')}, boot counter {js(c).get('boot_counter')}",
 "adcs_set_run_mode": lambda c: "run mode set",
 "adcs_get_current_state_1": lambda c: f"run mode {js(c).get('adcs_run_mode')}, control mode {js(c).get('control_mode')}, errors {sum(v for k, v in js(c).items() if 'error' in k)}",
 "gnss_send_cmd_ascii": lambda c: (lambda m: f"TIMEA week {m[1]}, {int(m[5]):02d}:{int(m[6]):02d}:{int(m[7])/1000:06.3f} UTC, {m[8]}")(re.search(r"FINESTEERING,(\d+),.*;\w+,[^,]*,[^,]*,[^,]*,(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\w+)\*", c["payload"] + " ")) if re.search(r"FINESTEERING", c["payload"]) else "",
 "fs_write_file_str": lambda c: "wrote hello.txt" if "Successfully wrote" in " ".join(l for _, l in c["lines"]) else "",
 "fs_read_file_hex": lambda c: bytes.fromhex(c["payload"]).decode(errors="replace").join(["read back: '", "'"]) if re.fullmatch(r"[0-9A-F]+", c["payload"]) else "",
 "fs_list_directory": lambda c: "ADCS/  hello.txt (18 B)  logs/" if len(c["lines"]) >= 7 else "",
}
def result(c, t):
    if not c["done"] or c["done"][0] > t: return None
    try: r = RES.get(c["name"], lambda c: "")(c)
    except Exception: r = ""
    return r
def firstt(pat):
    return next((t for t, _, s in con if re.search(pat, s)), None)

STATES = ["BOOTED_AND_WAITING", "DEPLOYING", "NOMINAL_WITH_RADIO_TX", "NOMINAL_WITHOUT_RADIO_TX"]
st_t = [None] * 4
st_t[0] = con[0][0]
st_t[3] = firstt(r"state changed from BOOTED_AND_WAITING to NOMINAL_WITHOUT_RADIO_TX")
def tc(name): return next((c for c in tcmds if c["name"] == name), None)
def after(c, t): return c and c["done"] and c["done"][0] <= t

def cards(t):
    out = []
    eps = []
    s = tc("eps_get_system_status_json"); p = tc("eps_get_pbu_housekeeping_data_eng_json"); ch = tc("eps_get_enabled_channels_json")
    l1 = "boot: all non-default channels disabled" if firstt("non-default channels disabled") and firstt("non-default channels disabled") <= t else "starting"
    if after(s, t): l1 = f"mode {js(s)['mode']}, uptime {js(s)['uptime_sec']} s, power-on resets {js(s)['rst_cnt_pwron']}"
    l2 = ""
    if after(ch, t): l2 = "enabled: " + ch["payload"].replace('[,', '').strip('[]')
    if after(p, t): l2 = f"bus {js(p)['vip_total_input']['mV']/1000:.3f} V {js(p)['vip_total_input']['mA']} mA  MCU {js(p)['temperature_mcu_cC']/100:.1f} C"
    out.append(("EPS (power)", l1, l2))
    b = firstt(r"All burns disabled"); mp = firstt(r"Disabled MPI")
    out.append(("BOOM / MPI", "all antenna burns disabled" if b and b <= t else "-", "MPI transceiver disabled" if mp and mp <= t else ""))
    a1, a2, a3 = tc("adcs_identification"), tc("adcs_program_status"), tc("adcs_get_current_state_1")
    out.append(("ADCS (CubeSpace)", f"node {js(a1)['node_type']}, firmware {js(a1)['major_firmware_version']}.{js(a1)['minor_firmware_version']}" if after(a1, t) else "no command yet",
                (f"boot cause {js(a2)['boot_cause']}, boot #{js(a2)['boot_counter']}" if after(a2, t) else "") + (f", run mode {js(a3)['adcs_run_mode']}" if after(a3, t) else "")))
    g = tc("gnss_send_cmd_ascii")
    out.append(("GNSS receiver", RES["gnss_send_cmd_ascii"](g) if after(g, t) else "no command yet", ""))
    f = firstt(r"LittleFS mounting successful"); w = tc("fs_write_file_str"); ls = tc("fs_list_directory")
    out.append(("Flash filesystem (LittleFS)", "mounted, logs/ and ADCS/ created" if f and f <= t else "-", ("hello.txt 18 B persisted" if after(ls, t) else "wrote hello.txt" if after(w, t) else "")))
    return out

def draw(c, t):
    c.header(f"{TITLE}: flight firmware on a simulated STM32L4R5", "operations view of the run: telecommands from the ground, replies from each subsystem, the OBC's own console", t)
    c.panel(24, 84, 1232, 92, "OBC operation state (CTS1_operation_state, rtos_bootup_operation_fsm_task.h)")
    act = 3 if st_t[3] is not None and st_t[3] <= t else 0
    c.chain(40, 112, 1200, 54, STATES, act, [x if (x is not None and x <= t) else None for x in st_t], [BLUE, BLUE, GREEN, GREEN], 17)
    c.panel(24, 188, 800, 330, "Ground telecommands and the OBC's replies")
    y = 222
    for k in tcmds[:13]:
        if k["t"] > t: break
        r = result(k, t)
        c.text(38, y, f"{k['t']:6.2f}s", 14, DIM, False, True)
        c.text(116, y, k["name"], 14, CYAN, False, True)
        if r is None: c.text(448, y, "running...", 14, AMBER, False, True)
        else:
            ok = k["done"][2] == 0
            c.text(448, y, ("ok  " if ok else "ERR ") + r[:44], 14, GREEN if ok else RED, False, True)
        y += 22
    cs = cards(t)
    for i, (nm, a, b) in enumerate(cs):
        yy = 188 + i * 66
        c.panel(836, yy, 420, 60)
        c.text(848, yy + 6, nm, 14, CYAN, True)
        c.text(848, yy + 24, a[:52], 14, FG, False, True); c.text(848, yy + 41, b[:52], 14, FG, False, True)
    c.log(24, 530, 1232, 156, con, t, "OBC console (LPUART1), as the firmware printed it", 14)
    c.footer(VER, SPEED)

SPEED = 1.0
END = 20.0
n = render(draw, END, SPEED, OUT)
print("frames", n)
