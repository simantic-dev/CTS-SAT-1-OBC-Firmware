# Shim: CTS-SAT-1 OBC external flash = Micron MT29F1G01 SPI NAND on SPI1, CS PE7 (chip 0), preloaded with a
# freshly lfs_format()ted filesystem (the firmware only formats on the `fs_format_storage` telecommand, so a
# blank part fails lfs_mount with -84 at boot). Run from this directory.
# NAND_SAVE=<file> in the environment writes the part's contents back after every program/erase.
import os
SAVE = os.environ.get("NAND_SAVE")
IMAGE = "lfs-formatted.nand"
exec(compile(open("mt29f1g01.py").read(), "mt29f1g01.py", "exec"))
