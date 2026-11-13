"""Zoom/paneo por correlacion de fase sobre el gradiente (robusta a cambios de luz).

Para cada escala s, achica/agranda el ULTIMO frame y busca el pico de correlacion
de fase contra el PRIMER frame. La escala con pico mas alto es la que mejor alinea
la geometria: s=1.000 significa que la camara no se acerco ni se alejo.

Uso: python medir_camara2.py <video> [...]
"""
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image


def first_last(path, w=480):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", path],
                               capture_output=True, text=True).stdout.strip() or 10)
    tmp = tempfile.mkdtemp(prefix="cam2_")
    fr = []
    for i, t in enumerate([0.04, max(0.5, dur - 0.15)]):
        o = os.path.join(tmp, f"f{i}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", path,
                        "-frames:v", "1", "-vf", f"scale={w}:-1", o], check=True)
        fr.append(np.asarray(Image.open(o).convert("L"), dtype=np.float32) / 255.0)
    return fr[0], fr[1], dur


def grad(img):
    gy, gx = np.gradient(img)
    g = np.hypot(gx, gy)
    g -= g.mean()
    g *= np.outer(np.hanning(g.shape[0]), np.hanning(g.shape[1]))
    return g


def pico(a, b):
    F = np.fft.fft2(a)
    G = np.fft.fft2(b)
    R = F * np.conj(G)
    R /= np.abs(R) + 1e-9
    r = np.abs(np.fft.ifft2(R))
    return float(r.max()), np.unravel_index(int(r.argmax()), r.shape), r.shape


def escalar(b, s):
    h, w = b.shape
    im = Image.fromarray((b * 255).astype(np.uint8))
    nw, nh = int(round(w / s)), int(round(h / s))
    im = im.resize((nw, nh), Image.BICUBIC)
    left, top = (nw - w) // 2, (nh - h) // 2
    return np.asarray(im.crop((left, top, left + w, top + h)), dtype=np.float32) / 255.0


def medir(path):
    a, b, dur = first_last(path)
    if a.shape != b.shape:
        h = min(a.shape[0], b.shape[0]); w = min(a.shape[1], b.shape[1])
        a, b = a[:h, :w], b[:h, :w]
    ga = grad(a)
    mejor = (-1, 1.0, (0, 0))
    for s in np.arange(0.94, 1.0601, 0.01):
        gb = grad(escalar(b, s))[:ga.shape[0], :ga.shape[1]]
        pk, pos, shp = pico(ga, gb)
        dy = pos[0] - (shp[0] - 1 if pos[0] > shp[0] // 2 else 0)
        dx = pos[1] - (shp[1] - 1 if pos[1] > shp[1] // 2 else 0)
        if pk > mejor[0]:
            mejor = (pk, float(s), (dx, dy))
    pk, s, (dx, dy) = mejor
    print(os.path.basename(path))
    print(f"  duracion {dur:.1f}s | ancho analisis {a.shape[1]}px")
    print(f"  mejor escala : {s:.2f}  ({(s-1)*100:+.1f}%)   pico correlacion {pk:.3f}")
    print(f"  desplazamiento en esa escala: dx={dx} dy={dy} px")
    print()


for p in sys.argv[1:]:
    medir(p)
