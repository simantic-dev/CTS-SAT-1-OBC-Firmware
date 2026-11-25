"""CTS-SAT-1 EPS (EnduroSat-style 'EPS_SICD' UART protocol) as a scripted UART peer on the OBC's UART5.

Frame, both ways (firmware/Core/Src/eps_drivers/eps_internal_drivers.c):
    "<cmd>" STID IVID CC BID [args] "</cmd>"      OBC -> EPS   (STID 0x1A, IVID 0x07, BID 0x00)
    "<rsp>" STID IVID CC BID STAT [data] "</rsp>" EPS -> OBC   (STAT 0x00 = ok)
The OBC reads an exact length per command (eps_commands.c `rx_len`, the table below), so every reply is
padded to it. Data layouts are the packed structs of Inc/eps_drivers/eps_types.h, little endian.

State kept: output-bus channel on/off bits (CC 0x10/0x12/0x16/0x18, reported by 0x42/0x52/0xA2), mode
(0x30/0x32), configuration parameters written with 0x84. Housekeeping values are fixed, plausible figures
(8.1 V battery, 21.6 C); MODELED SIMPLIFICATION: no load/solar dynamics. Unknown command codes get a
5-byte reply with STAT 0x01 ("unknown command") so the firmware logs it rather than timing out.
"""
import struct

STID, IVID, BID = 0x1A, 0x07, 0x00
# command code -> total reply length without tags (header 5 + data), from eps_commands.c
RX_LEN = {0x40: 36, 0x42: 78, 0x44: 8, 0x52: 258, 0x54: 258, 0x62: 84, 0x64: 84, 0x72: 72, 0x74: 72,
          0x82: 16, 0x84: 16, 0x86: 16, 0xA2: 274, 0xA4: 274}
# Turnaround from the last command byte to the first reply byte. MODELED SIMPLIFICATION: the EPS SICD gives no
# figure. The firmware needs it: after its TX it clears a 310-byte buffer before arming RX, and a reply that
# starts at once loses its first ~4 bytes to that window.
REPLY_DELAY_NS = 2_000_000
NCH = 17  # channels present on the CTS-SAT-1 PDU (0..16)


def vpid(v, i, p):
    return struct.pack("<hhh", v, i, p)


class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.rx = b""
        self.ch_on = 0  # bit i = channel i (0..31)
        self.mode = 1
        self.cfg = {}
        self.cmds = 0
        self.out = b""

    # ---- data blocks ------------------------------------------------------------------------------
    def _status(self):
        up = int(self.ctx.now_ns // 1_000_000_000) + 20
        unix = 1_790_000_000 + up
        return struct.pack("<BBBIHHHHHHHIBBBBBB", self.mode, 0, 0, up, 0, 1, 0, 0, 0, 0, 3, unix,
                           26, 9, 21, 12, 0, up % 60)

    def _channels(self):
        return b"".join(vpid(3300, 40, 13) if self.ch_on >> i & 1 else vpid(0, 0, 0) for i in range(32))

    def _data(self, cc):
        on = self.ch_on & 0xFFFF
        if cc == 0x40:
            return self._status()
        if cc == 0x42:  # reserved byte + on/ext-on/ocp/ext-ocp + 32 fault counters
            return b"\0" + struct.pack("<HHHH", on, self.ch_on >> 16, 0, 0) + bytes(64)
        if cc == 0x44:
            return struct.pack("<BB", 0xAB, 0xAB)  # both ABF pins applied
        if cc in (0x52, 0x54):
            return (b"\0" + struct.pack("<hh", 3300, 2160) + vpid(8117, 190, 1540)
                    + struct.pack("<HHHH", on, self.ch_on >> 16, 0, 0)
                    + b"".join(vpid(v, 20, v * 20 // 1000) for v in (8117, 5040, 3312, 3312, 12000, 5040, 28600))
                    + self._channels())
        if cc in (0x62, 0x64):
            pack = (vpid(8117, -419, -340) + struct.pack("<H4h3h", 0, 4058, 4059, 4060, 4061, 2160, 2170, 2150))
            return b"\0" + struct.pack("<hh", 3300, 2160) + vpid(8117, -419, -340) + struct.pack("<H", 0) + pack + bytes(2 * 22)
        if cc in (0x72, 0x74):
            return b"\0" + struct.pack("<hh", 3300, 2160) + vpid(0, 0, 0) + bytes(4 * 14)
        if cc in (0xA2, 0xA4):
            return (b"\0" + struct.pack("<hh", 3300, 2160) + vpid(8117, 190, 1540) + vpid(8117, -419, -340)
                    + struct.pack("<HHHhhHHH", on, 0, 0, 2170, 2150, 8117, 5040, 3312)
                    + self._channels() + bytes(8 * 5) + struct.pack("<HH", self.ch_on >> 16, 0))
        return b""

    # ---- protocol ---------------------------------------------------------------------------------
    def _reply(self, cc, stat=0, data=b""):
        body = bytes([STID, IVID, cc, BID, stat]) + data
        body = body.ljust(RX_LEN.get(cc, 5), b"\0")[: RX_LEN.get(cc, 5)]
        self.out = b"<rsp>" + body + b"</rsp>"
        self.ctx.schedule_oneshot_ns(REPLY_DELAY_NS)

    def on_timer(self):
        out, self.out = self.out, b""
        if out:
            self.ctx.send(out)

    def _command(self, f):
        cc, args = f[2], f[4:]
        self.cmds += 1
        if len(f) < 4 or f[0] != STID or f[1] != IVID:
            return self._reply(cc, 0x02)  # invalid frame header
        if cc in (0x10, 0x12) and len(args) >= 4:
            bits = args[0] | args[1] << 8 | args[2] << 16 | args[3] << 24
            self.ch_on = (self.ch_on | bits) if cc == 0x10 else (self.ch_on & ~bits)
        elif cc in (0x16, 0x18) and args:
            bit = 1 << (args[0] & 31)
            self.ch_on = (self.ch_on | bit) if cc == 0x16 else (self.ch_on & ~bit)
        elif cc in (0x30, 0x32):
            self.mode = 1 if cc == 0x30 else 2
        elif cc == 0x84 and len(args) >= 2:
            self.cfg[args[0] | args[1] << 8] = bytes(args[2:10])
        elif cc in (0x82, 0x86) and len(args) >= 2:
            pid = args[0] | args[1] << 8
            if cc == 0x86:
                self.cfg.pop(pid, None)
            return self._reply(cc, 0, args[:2] + self.cfg.get(pid, bytes(8)))
        elif cc not in (0x02, 0x04, 0x06, 0x14, 0x90, 0x92, 0x94, 0xAA, 0xC4, 0xC6) and cc not in RX_LEN:
            return self._reply(cc, 0x01)
        self.ctx.info(f"EPS cc=0x{cc:02x} args={bytes(args).hex()} ch_on=0x{self.ch_on:08x}")
        self._reply(cc, 0, self._data(cc))

    def on_byte(self, b):
        self.rx += bytes([b])
        while self.rx and not (b"<cmd>".startswith(self.rx) or self.rx.startswith(b"<cmd>")):
            self.rx = self.rx[1:]  # resync on line noise
        if self.rx.endswith(b"</cmd>") and len(self.rx) >= 5 + 4 + 6:
            frame, self.rx = self.rx[5:-6], b""
            self._command(frame)
