"""Mide si la camara se movio: compara primer frame vs ultimo frame de un mp4.

Busca la escala (zoom) y el desplazamiento (paneo) que mejor alinean el ultimo
frame con el primero.  Escala 1.000 y desplazamiento 0 = camara fija.

Uso: python medir_camara.py <video1> [video2 ...]
"""
import subprocess
import sys
import tempfile
import os
import numpy as np
from PIL import Image

FF = "ffmpeg"


def frames(path, times):
    tmp = tempfile.mkdtemp(prefix="cam_")
    outs = []
    for t in times:
        o = os.path.join(tmp, f"f_{t}.png")
        subprocess.run([FF, "-v", "error", "-y", "-ss", str(t), "-i", path,
                        "-frames:v", "1", "-vf", "scale=640:-1", o], check=True)
        outs.append(np.asarray(Image.open(o).convert("L"), dtype=np.float32))
    return outs


def zoom_about_center(img, s):
    h, w = img.shape
    im = Image.fromarray(img.astype(np.uint8))
    nw, nh = int(round(w / s)), int(round(h / s))
    im = im.resize((nw, nh), Image.BICUBIC)
    left, top = (nw - w) // 2, (nh - h) // 2
    return np.asarray(im.crop((left, top, left + w, top + h)), dtype=np.float32)


def mejor_escala(a, b, rango=np.arange(0.92, 1.085, 0.005)):
    best = (1e9, 1.0)
    for s in rango:
        bb = zoom_about_center(b, s)
        d = np.abs(a[20:-20, 20:-20] - bb[20:-20, 20:-20]).mean()
        if d < best[0]:
            best = (d, float(s))
    return best


def mejor_shift(a, b, r=18):
    best = (1e9, 0, 0)
    for dy in range(-r, r + 1, 2):
        for dx in range(-r, r + 1, 2):
            bb = np.roll(np.roll(b, dy, axis=0), dx, axis=1)
            m = 20 + r
            d = np.abs(a[m:-m, m:-m] - bb[m:-m, m:-m]).mean()
            if d < best[0]:
                best = (d, dx, dy)
    return best


def medir(path):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", path],
                               capture_output=True, text=True).stdout.strip() or 10)
    t0, t1 = 0.04, max(0.5, dur - 0.15)
    a, b = frames(path, [t0, t1])
    if a.shape != b.shape:
        b = b[:a.shape[0], :a.shape[1]]
    d1 = np.abs(a - b).mean()
    dzoom, s = mejor_escala(a, b)
    dshift, dx, dy = mejor_shift(a, b)
    print(os.path.basename(path))
    print(f"  diff cruda 1er vs ultimo frame : {d1:6.2f}")
    print(f"  mejor escala (zoom)            : {s:.3f}  -> {(s-1)*100:+.1f}%   (residuo {dzoom:.2f})")
    print(f"  mejor desplazamiento (paneo)   : dx={dx:+d} dy={dy:+d} px  (residuo {dshift:.2f})")
    print()


for p in sys.argv[1:]:
    medir(p)
