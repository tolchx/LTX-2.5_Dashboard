"""Quita el zoom (o push-in) de un clip ya renderizado, sin tocar el modelo.

1. Estima la escala aparente de cada frame respecto del primero (NCC sobre el
   gradiente, buscando la escala que mejor alinea).
2. Recorta centrado el excedente y reescala: el resultado conserva el encuadre
   del primer frame y la camara queda quieta.
3. Suaviza la curva para que no tiemble y reescribe el mp4 con la misma duracion.

Uso: python dezoom.py <video_entrada> [video_salida]
"""
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

ENT = sys.argv[1]
SAL = sys.argv[2] if len(sys.argv) > 2 else ENT.replace(".mp4", "__sinzoom.mp4")
ANCHO_BUSQUEDA = 480
PASO = 0.004
RANGO = np.arange(0.86, 1.021, PASO)   # el frame t (zoom in) hay que encogerlo
CADA = 3                               # estimar cada N frames e interpolar


def sh(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


tmp = tempfile.mkdtemp(prefix="dezoom_")
ent = os.path.join(tmp, "in")
sal = os.path.join(tmp, "out")
os.makedirs(ent)
os.makedirs(sal)

info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                       "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                       "-of", "json", ENT], capture_output=True, text=True).stdout
import json as _json
d = _json.loads(info)["streams"][0]
W, H = int(d["width"]), int(d["height"])
num, den = d["r_frame_rate"].split("/")
FPS = float(num) / float(den)
print(f"entrada {W}x{H} @ {FPS:.2f} fps")

sh(["ffmpeg", "-v", "error", "-y", "-i", ENT, os.path.join(ent, "%04d.png")])
frames = sorted(os.listdir(ent))
N = len(frames)
print("frames:", N)


def gris(path, ancho=ANCHO_BUSQUEDA):
    im = Image.open(path).convert("L")
    w, h = im.size
    im = im.resize((ancho, int(round(h * ancho / w))), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32) / 255.0
    g = np.hypot(*np.gradient(a))
    g -= g.mean()
    return g


def escalar(a, s):
    rng = float(a.max() - a.min()) or 1.0
    im = Image.fromarray(((a - a.min()) / rng * 255).astype(np.uint8))
    h, w = a.shape
    nw, nh = max(8, int(round(w * s))), max(8, int(round(h * s)))
    im = im.resize((nw, nh), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0


def ncc(a, b):
    m = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    a2, b2 = a[:m[0], :m[1]], b[:m[0], :m[1]]
    a2 = a2 - a2.mean(); b2 = b2 - b2.mean()
    den = np.sqrt((a2 * a2).sum() * (b2 * b2).sum())
    return float((a2 * b2).sum() / den) if den > 0 else 0.0


ref = gris(os.path.join(ent, frames[0]))
est = {0: 1.0}
for i in range(1, N, CADA):
    g = gris(os.path.join(ent, frames[i]))
    mejor, s_mejor = -2, 1.0
    for s in RANGO:
        v = ncc(ref, escalar(g, s))
        if v > mejor:
            mejor, s_mejor = v, float(s)
    est[i] = s_mejor
    if i % 30 == 0:
        print(f"  frame {i:4d}: escala {s_mejor:.3f} (ncc {mejor:.3f})")

xs = np.array(sorted(est.keys()), dtype=float)
ys = np.array([est[int(x)] for x in xs], dtype=float)
curva = np.interp(np.arange(N), xs, ys)

# suavizado (media movil) para matar el jitter frame a frame
k = 11
pad = np.pad(curva, (k // 2, k // 2), mode="edge")
curva = np.convolve(pad, np.ones(k) / k, mode="valid")[:N]
curva = np.clip(curva, 0.80, 1.0)
print(f"zoom total estimado: {(curva[-1]-1)*100:+.1f}% (min {curva.min():.3f})")

for i, f in enumerate(frames):
    s = float(curva[i])
    im = Image.open(os.path.join(ent, f)).convert("RGB")
    cw, ch = int(round(W * s)), int(round(H * s))
    left, top = (W - cw) // 2, (H - ch) // 2
    im = im.crop((left, top, left + cw, top + ch)).resize((W, H), Image.LANCZOS)
    im.save(os.path.join(sal, f))
    if i % 60 == 0:
        print(f"  escribiendo {i}/{N} (escala {s:.3f})")

sh(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", os.path.join(sal, "%04d.png"),
    "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", SAL])
print("listo:", SAL)
shutil.rmtree(tmp, ignore_errors=True)
