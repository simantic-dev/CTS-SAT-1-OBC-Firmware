"""Animates run.log (sim's own UART captures) into timeline.gif: bytes per UART link over virtual time, and firmware log lines by tag.
usage: make_gif.py run.log out.gif "tag"   (matplotlib, pillow)"""
import re, sys, io
from collections import defaultdict
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image
by = defaultdict(list); logs = []
for line in open(sys.argv[1]):
    m = re.match(r"\[([\d.]+)s\] \((\w+) [←→] (\w+)\) (.*)", line)
    if not m: continue
    t, bus, rest = float(m[1]), m[2], m[4]
    if bus == "lpuart1":
        g = re.search(r"\[([A-Z]:[A-Z0-9]+):[A-Z]+\]", rest)
        if g: logs.append((t, g[1]))
        by[bus].append((t, len(rest.encode())))
    else:
        by[bus].append((t, len(rest.split())))
tags = sorted({g for _, g in logs}); end = 20.0; frames = []
for k in range(1, 41):
    tc = end * k / 40
    fig, (a, b) = plt.subplots(2, 1, figsize=(7, 4.6), dpi=70, sharex=True, gridspec_kw={"height_ratios": [2, 1.4]})
    for bus, ev in by.items():
        xs = [t for t, _ in ev if t <= tc]; cum = 0; ys = []
        for t, n in ev:
            if t <= tc: cum += n; ys.append(cum)
        a.step(xs, ys, where="post", label=bus)
    a.set_yscale("symlog"); a.set_ylabel("bytes captured so far", fontsize=7); a.legend(fontsize=6, loc="upper left"); a.set_ylim(0, 3000)
    for i, g in enumerate(tags):
        b.plot([t for t, x in logs if x == g and t <= tc], [i] * len([1 for t, x in logs if x == g and t <= tc]), "|", ms=10)
    b.set_yticks(range(len(tags))); b.set_yticklabels(tags, fontsize=6); b.set_xlim(0, end); b.set_xlabel("virtual time, s"); b.set_ylim(-.7, len(tags) - .3)
    a.set_title(f"CTS-SAT-1 OBC firmware on simulated L4R5, t={tc:.1f} s virtual, {sys.argv[3]}", fontsize=8)
    fig.tight_layout(); bf = io.BytesIO(); fig.savefig(bf, format="png"); plt.close(fig)
    frames.append(Image.open(bf).convert("RGB").quantize(colors=64, dither=Image.Dither.NONE))
frames[0].save(sys.argv[2], save_all=True, append_images=frames[1:], duration=[120] * 39 + [1500], loop=0, optimize=True)
