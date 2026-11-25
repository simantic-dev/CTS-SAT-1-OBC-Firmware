"""CubeSpace CubeComputer / CubeACP I2C target (7-bit address 0x57 by default) as a scripted I2C slave.

A stand-in for a CubeSpace CubeComputer, built from what a flight OBC's driver sends and expects (CTS-SAT-1's
firmware/Core/Src/adcs_drivers, which follows CubeSpace's Firmware Reference Manual): NOT from CubeSpace's
firmware. The protocol is a register file, so the target side can be anything that speaks it, including a second
simulated MCU running stand-in firmware: `CubeComputer` below is plain Python with no simulator types, and
`CubeComputer.write(bytes)` / `.read(n)` are the whole interface.

Protocol (Manual section 5, "I2C"):
- Telecommand (TC), id 0..127: master writes [id, payload..., crc8?]. Acknowledge telemetry (id 240) then reads
  [last_id, processed, error_flag, error_index]; error_flag 0 ok, 1 invalid id, 2 wrong length, 3 invalid
  params, 4 CRC. A TC with a bad CRC is ignored and acknowledged with error_flag 4.
- Telemetry (TLM), id 128..255: master writes [id] then repeated-start reads N bytes, plus one CRC byte when it
  asked for N+1. CRC is CRC-8, polynomial 0x91 reflected, init 0 (the Manual's table code), empty buffer 0xFF.
- An id this model has no frame for answers zeros (a zero frame has CRC 0, so it passes the master's check) and
  a TC for an unknown id is acknowledged with error_flag 1, so the firmware logs it rather than hanging.

Implemented frames (layouts from the OBC's struct packers, adcs_struct_packers.c):
  TLM 128 identification (8) | 129 boot/running program status (6) | 130 boot index status (2, LAYOUT
  UNVERIFIED: the OBC never reads it) | 132 ADCS state (6) | 140 unix time (6) | 144 comm status (6) |
  145 unix-time save mode (2) | 147 estimated angular rates (6) | 151 magnetic field vector (6) |
  155 rate sensor rates (6) | 240 command ack (4)
  TC 1 reset (0x5A) | 2 set unix time (6) | 7 deploy magnetometer (1) | 10 run mode (1) | 12 clear errors (1) |
  13 control mode (3) | 14 estimation mode (1) | 18 trigger loop (0) | 63 save config (0) | 64 save orbit params (0)
MODELED SIMPLIFICATIONS: commands complete instantly (processed = 1 on the first ack read); no attitude
dynamics: vectors and rates are the values in `CubeComputer.env`, which a plant script may overwrite.
"""

CRC_POLY = 0x91
_TABLE = []
for _i in range(256):
    _v = _i
    for _ in range(8):
        if _v & 1:
            _v ^= CRC_POLY
        _v >>= 1
    _TABLE.append(_v)


def crc8(data):
    if not data:
        return 0xFF
    c = 0
    for b in data:
        c = _TABLE[c ^ b]
    return c


# TC id -> payload length (without CRC)
TC_LEN = {1: 1, 2: 6, 7: 1, 10: 1, 12: 1, 13: 3, 14: 1, 18: 0, 63: 0, 64: 0}


class CubeComputer:
    def __init__(self, now_s=lambda: 0.0, firmware=(1, 12), node_type=10):
        self.now_s = now_s
        self.firmware = firmware
        self.node_type = node_type
        self.boot_counter = 1
        self.reset_cause = 0  # power on
        self.boot_cause = 3  # commanded
        self.running_program = 1  # 1 = ADCS, 2 = bootloader
        self.run_mode = 0
        self.control_mode = 0
        self.estimation_mode = 0
        self.unix = (0, 0)  # (seconds, ms) set by TC 2, advanced by now_s
        self.unix_set_at = 0.0
        self.cmd_counter = 0
        self.tlm_counter = 0
        self.errors_cmd_overrun = 0
        self.ack = [0, 1, 0, 0]
        self.ptr = 0x80
        # vectors in raw counts, int16 x3, as the OBC's packers read them
        self.env = {147: (0, 0, 0), 151: (0, 0, 0), 155: (0, 0, 0)}
        self.log = []  # (kind, id, payload) per accepted frame, for a test or a plant to read

    # -- master writes ------------------------------------------------------------------------------
    def write(self, data):
        data = bytes(data)
        if not data:
            return
        i = data[0]
        if i >= 128:  # telemetry pointer; any extra bytes are ignored
            self.ptr = i
            return
        self.cmd_counter += 1
        self.log.append(("tc", i, data[1:]))
        want = TC_LEN.get(i)
        if want is None:
            self.ack = [i, 1, 1, 0]
            return
        payload = data[1:]
        if len(payload) == want + 1 and crc8(payload[:want]) != payload[want]:
            self.ack = [i, 1, 4, 0]
            return
        if len(payload) not in (want, want + 1):
            self.ack = [i, 1, 2, 0]
            return
        payload = payload[:want]
        self.ack = [i, 1, 0, 0]
        if i == 1 and payload[0] == 0x5A:
            self.boot_counter += 1
            self.reset_cause, self.boot_cause = 4, 3
            self.run_mode = self.control_mode = self.estimation_mode = 0
        elif i == 2:
            self.unix = (int.from_bytes(payload[:4], "little"), int.from_bytes(payload[4:6], "little"))
            self.unix_set_at = self.now_s()
        elif i == 10:
            if payload[0] > 3:
                self.ack = [i, 1, 3, 0]
            else:
                self.run_mode = payload[0]
        elif i == 13:
            self.control_mode = payload[0] & 0x0F
        elif i == 14:
            self.estimation_mode = payload[0] & 0x0F

    # -- master reads -------------------------------------------------------------------------------
    def read(self, count):
        self.tlm_counter += 1
        frame = self._frame(self.ptr)
        if frame is None:
            return bytes(count)  # unknown frame: zeros, CRC 0
        out = bytes(frame)[:count].ljust(count, b"\0")
        if count == len(frame) + 1:
            out = bytes(frame) + bytes([crc8(frame)])
        return out

    def _vec(self, i):
        return b"".join(int(v).to_bytes(2, "little", signed=True) for v in self.env[i])

    def _frame(self, i):
        t = self.now_s()
        if i == 128:
            s = int(t)
            return bytes([self.node_type, 1, *self.firmware]) + s.to_bytes(2, "little") + int((t - s) * 1000).to_bytes(2, "little")
        if i == 129:
            return bytes([self.reset_cause << 4 | self.boot_cause]) + self.boot_counter.to_bytes(2, "little") + bytes(
                [self.running_program, *self.firmware])
        if i == 130:
            return bytes([self.running_program, 0])
        if i == 132:
            return bytes([self.control_mode << 4 | self.estimation_mode, self.run_mode, 0, 0, 0, 0])
        if i == 140:
            sec = self.unix[0] + int(t - self.unix_set_at)
            return sec.to_bytes(4, "little") + self.unix[1].to_bytes(2, "little")
        if i == 144:
            return self.cmd_counter.to_bytes(2, "little") + self.tlm_counter.to_bytes(2, "little") + bytes([0, 0])
        if i == 145:
            return bytes([0, 0])
        if i in self.env:
            return self._vec(i)
        if i == 240:
            return bytes(self.ack)
        return None


class Slave:
    """pyrite I2C peer: on_write(data) sets the telemetry pointer or runs a TC; on_read(count) answers it."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.dev = CubeComputer(now_s=lambda: ctx.now_ns / 1e9)

    def on_write(self, data):
        self.dev.write(data)
        if data and data[0] < 128:
            self.ctx.info(f"ADCS TC {data[0]} payload={bytes(data[1:]).hex()} ack={self.dev.ack}")
        return len(data)

    def on_read(self, count):
        return self.dev.read(count)
