"""Micron MT29F1G01 1 Gbit SPI NAND (128 MiB, 2048+128 byte pages, 64 pages per block) as a scripted SPI slave.

pyrite has no SPI NAND model (its flash models are NOR), so this is the nearest part that answers what a
SPI-NAND driver sends: 9F READ ID, 0F/1F GET/SET FEATURES, 06/04 WRITE ENABLE/DISABLE, 13 PAGE READ,
03 READ FROM CACHE, 02 PROGRAM LOAD, 10 PROGRAM EXECUTE, D8 BLOCK ERASE, FF RESET.
Used by tests/stm/nucleo-l4r5zi/cts-sat-1-obc (CTS-SAT-1 OBC: LittleFS on chip 0).

NAND rules kept: a program ANDs into the page (1 -> 0 only), a block erase sets it to 0xFF, a program or erase
without WRITE ENABLE sets P_FAIL / E_FAIL in the status register (feature 0xC0). Array operations finish
instantly (OIP always 0): a driver that polls OIP sees ready on the first read. ECC is not modelled (ECC status 0).
No ctx.* is needed; contents live in a sparse dict, so a fresh part is 0xFF everywhere and costs no memory.
Optional image: a shim sets IMAGE = "<path>" before exec to preload programmed pages, and SAVE = "<path>" to
write them back after every program/erase (how an image is made: run the firmware, let it format, keep the file).
Image format: repeated records of a 4-byte big-endian row number and PAGE + SPARE bytes of page content.
ponytail: no timing, no bad-block marks, no ECC spare area; add when a firmware tests them.
"""

PAGE = 2048
SPARE = 128
PAGES_PER_BLOCK = 64
BLOCKS = 1024

GET_FEAT, SET_FEAT, READ_ID, WREN, WRDI, RESET = 0x0F, 0x1F, 0x9F, 0x06, 0x04, 0xFF
PAGE_READ, READ_CACHE, PROG_LOAD, PROG_EXEC, BLOCK_ERASE = 0x13, 0x03, 0x02, 0x10, 0xD8
SR_WEL, SR_E_FAIL, SR_P_FAIL = 0x02, 0x04, 0x08
CONFIG = 0xB0


REC = PAGE + SPARE


class Slave:
    def __init__(self, ctx=None, image=None, save=None):
        self.ctx = ctx
        self.pages = {}  # row -> bytearray(PAGE + SPARE)
        self.save = save
        if image:
            with open(image, "rb") as f:
                data = f.read()
            for o in range(0, len(data), 4 + REC):
                self.pages[int.from_bytes(data[o:o + 4], "big")] = bytearray(data[o + 4:o + 4 + REC])
        self.cache = bytearray(b"\xff" * (PAGE + SPARE))
        self.feat = {0xA0: 0x7C, 0xB0: 0x10, 0xC0: 0x00}  # datasheet reset values
        self.wel = False
        self.sr_fail = 0
        self.erases = 0
        self.programs = 0
        self._frame()

    def _frame(self):
        self.buf = []  # bytes of this chip-select frame seen so far

    def on_select(self):
        self._frame()

    def on_deselect(self):
        self._frame()

    on_finish = on_deselect

    def _row(self):
        return (self.buf[1] << 16) | (self.buf[2] << 8) | self.buf[3]

    def _status(self):
        return (self.feat[0xC0] & ~0x0E) | (SR_WEL if self.wel else 0) | self.sr_fail

    def on_transmit(self, b):
        n = len(self.buf)
        self.buf.append(b)
        op = self.buf[0]
        if n == 0:
            self._opcode(b)
            return 0
        if op == READ_ID:
            return 0 if n == 1 else (0x2C if n == 2 else 0x14)  # dummy byte, then MID, DID
        if op == GET_FEAT:
            if n == 1:
                return 0
            a = self.buf[1]
            return self._status() if a == 0xC0 else self.feat.get(a, 0)
        if op == SET_FEAT:
            if n == 2 and self.buf[1] in (0xA0, 0xB0):
                self.feat[self.buf[1]] = b
            return 0
        if op == READ_CACHE:
            if n < 4:  # 2 column bytes, 1 dummy
                return 0
            col = ((self.buf[1] << 8) | self.buf[2]) & 0x0FFF
            return self.cache[(col + n - 4) % len(self.cache)]
        if op == PROG_LOAD:
            if n == 2:
                self.col = ((self.buf[1] << 8) | self.buf[2]) & 0x0FFF
            elif n > 2:
                i = self.col + n - 3
                if i < len(self.cache):
                    self.cache[i] = b
            return 0
        if n == 3 and op in (PAGE_READ, PROG_EXEC, BLOCK_ERASE):
            self._row_op(op, self._row())
        return 0

    def _opcode(self, op):
        if op == WREN:
            self.wel = True
        elif op == WRDI:
            self.wel = False
        elif op == RESET:
            self.wel = False
            self.sr_fail = 0
        elif op == PROG_LOAD:
            self.cache = bytearray(b"\xff" * (PAGE + SPARE))

    def _row_op(self, op, row):
        # row is 24 bits on the wire; the part decodes 16 (1024 blocks x 64 pages)
        row &= BLOCKS * PAGES_PER_BLOCK - 1
        if op == PAGE_READ:
            self.cache = bytearray(self.pages.get(row, b"\xff" * (PAGE + SPARE)))
            return
        if not self.wel:
            self.sr_fail |= SR_P_FAIL if op == PROG_EXEC else SR_E_FAIL
            return
        self.sr_fail = 0
        self.wel = False
        if op == PROG_EXEC:
            page = self.pages.setdefault(row, bytearray(b"\xff" * (PAGE + SPARE)))
            for i, v in enumerate(self.cache):
                page[i] &= v
            self.programs += 1
        else:
            first = row & ~(PAGES_PER_BLOCK - 1)
            for r in range(first, first + PAGES_PER_BLOCK):
                self.pages.pop(r, None)
            self.erases += 1
        if self.save:
            with open(self.save, "wb") as f:
                for r, pg in sorted(self.pages.items()):
                    f.write(r.to_bytes(4, "big") + pg)


# As a pyrite peer script the class must be called Slave and take (ctx); a shim may define IMAGE / SAVE first.
_Part = Slave


class Slave(_Part):  # noqa: F811
    def __init__(self, ctx):
        super().__init__(ctx, globals().get("IMAGE"), globals().get("SAVE"))
