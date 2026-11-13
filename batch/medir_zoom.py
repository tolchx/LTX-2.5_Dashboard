"""Detecta zoom midiendo el tamano aparente de estructuras fijas.

Toma 5 frames del clip, se queda con la mitad superior (donde viven los huecos
blancos de luz del templo), y mide el ancho y el centro del area brillante.
Si la camara hace zoom in/out, ese ancho crece o se encoge de forma monotona.
Si esta quieta, se queda igual (+-1-2 px por el re-render de la textura).

Uso: python medir_zoom.py <video> [...]
"""
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image


def frames(path, w=640):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", path],
                               capture_output=True, text=True).stdout.strip() or 10)
    tmp = tempfile.mkdtemp(prefix="zoom_")
    ts = [0.05, dur * 0.25, dur * 0.5, dur * 0.75, dur - 0.2]
    out = []
    for i, t in enumerate(ts):
        o = os.path.join(tmp, f"f{i}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", path,
                        "-frames:v", "1", "-vf", f"scale={w}:-1", o], check=True)
        out.append((t, np.asarray(Image.open(o).convert("L"), dtype=np.float32) / 255.0))
    return out


def medir_ancho(img):
    h, w = img.shape
    top = img[: int(h * 0.55), :]
    m = top > 0.62                      # pixeles de luz
    cols = m.sum(axis=0)
    keep = cols > (0.02 * top.shape[0])  # columnas con luz sostenida
    if keep.sum() < 10:
        return None
    idx = np.where(keep)[0]
    # ancho entre el primer y el ultimo grupo de columnas iluminadas
    return float(idx[-1] - idx[0] + 1), float(idx.mean())


for p in sys.argv[1:]:
    print(os.path.basename(p))
    res = []
    for t, img in frames(p):
        r = medir_ancho(img)
        if r:
            res.append((t, r[0], r[1]))
            print(f"  t={t:5.2f}s  ancho_luz={r[0]:6.1f}px  centro_x={r[1]:6.1f}")
    if len(res) >= 2:
        w0, w1 = res[0][1], res[-1][1]
        c0, c1 = res[0][2], res[-1][2]
        print(f"  -> variacion de ancho: {(w1-w0)/w0*100:+.2f}%  | "
              f"corrimiento de centro: {c1-c0:+.1f}px")
    print()
