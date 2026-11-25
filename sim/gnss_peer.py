"""CTS-SAT-1 GNSS receiver (NovAtel OEM7 ASCII on USART3, 115200 8N1) as a scripted UART peer.

The OBC sends one ASCII command per line ("log timea once", "log bestxyza once", "unlogall"; firmware
gnss_internal_drivers.c / gnss_time.c) and reads until `*` + 8 hex digits + EOL. The reply is `<OK`, then the
log as `[COM1]#NAME,header;data*CRC32`, CRC32 as the OEM7 manual defines it (poly 0xEDB88320, no final xor,
over the text between '#' and '*').
Supported logs: TIMEA (UTC date/time, as GNSS_parse_timea_response_and_convert_to_unix_time_ms reads it) and
BESTXYZA (a fixed ECEF fix near Calgary). Any other `log` or command is answered `<OK` alone (accepted, no
data). MODELED SIMPLIFICATION: the receiver is always locked and its time is UTC_BASE plus virtual time; no
periodic logs (`ontime`) are produced.
"""
import calendar
import time

UTC_BASE = calendar.timegm((2026, 11, 16, 12, 0, 0))  # UTC at virtual t=0
GPS_EPOCH = 315964800
LEAP = 18


def crc32(text):
    c = 0
    for b in text.encode():
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
    return c


class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.line = b""

    def _now(self):
        return UTC_BASE + self.ctx.now_ns / 1e9

    def _log(self, name, body):
        t = self._now() + LEAP - GPS_EPOCH
        week, sow = int(t // 604800), t % 604800
        head = f"{name},COM1,0,50.0,FINESTEERING,{week},{sow:.3f},02000000,9924,16809"
        text = f"{head};{body}"
        return f"[COM1]#{text}*{crc32(text):08x}\r\n"

    def _timea(self):
        n = self._now()
        u = time.gmtime(n)
        ms = u.tm_sec * 1000 + int((n % 1) * 1000)
        return self._log("TIMEA", f"VALID,1.1e-09,2.4e-09,-18.00000000049,{u.tm_year},{u.tm_mon},{u.tm_mday},"
                                  f"{u.tm_hour},{u.tm_min},{ms},VALID")

    def _bestxyz(self):
        return self._log("BESTXYZA", "SOL_COMPUTED,SINGLE,-1641000.1234,-3562000.5678,4944000.9012,1.2,1.1,2.3,"
                                     "SOL_COMPUTED,DOPPLER_VELOCITY,0.001,-0.002,0.0005,0.02,0.02,0.04,"
                                     "\"\",0.250,1.000,0.000,GPS;GLONASS,18,15,15,15,0,01,0,33")

    def on_byte(self, b):
        if b not in (10, 13):
            self.line += bytes([b])
            return
        cmd, self.line = self.line.decode(errors="replace").strip().lower(), b""
        if not cmd:
            return
        out = "<OK\r\n"
        if cmd.startswith("log timea"):
            out += self._timea()
        elif cmd.startswith("log bestxyza"):
            out += self._bestxyz()
        self.ctx.info(f"GNSS cmd {cmd!r}")
        self.ctx.send(out.encode())
