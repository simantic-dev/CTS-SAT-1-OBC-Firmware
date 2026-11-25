# Provenance of CTS-SAT-1_FW.elf

- Upstream: https://github.com/CalgaryToSpace/CTS-SAT-1-OBC-Firmware (CalgaryToSpace, University of Calgary)
- Commit: `1c98525a7b97f48ddef94b91df14d91b9fa3518a` ("Blob: Extended Beacon v4 (tiny fixes) (#668)")
- Licence: MIT, Copyright (c) 2024 CalgaryToSpace. The licence text is `LICENSE-CTS-SAT-1-OBC-Firmware` in this directory;
  the ELF is a build of their unmodified source and is redistributed under it.
- Build: `make -f Makefile.GitHub.mk` in `firmware/` with Arm GNU Toolchain 15.2.1 (`-Og -g`, Cortex-M4F hard float);
  `build.sh` repeats it. sha256 of the committed ELF:
  `3eb8578540d448475521c3c319d321e6b5a4515bf9c497770878f7a65b5534ad`. A rebuild differs only in the
  `__DATE__`/`__TIME__` stamp and the checkout path in the debug info.
- Target: STM32L4R5ZI (their OBC is a NUCLEO-L4R5ZI-class board). No firmware change is needed or made.
