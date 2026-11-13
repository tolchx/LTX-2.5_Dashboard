"""Auditoria de camara: cuanto se acerca/aleja y cuanto se corre el encuadre.

Compara el primer frame contra el ultimo con correlacion de fase sobre el gradiente
(robusta a cambios de luz, que en estas escenas son fuertes: velas, humo, niebla).
Escala 1.00 = la camara no se acerco ni se alejo. dx en px sobre 480 de ancho.

Uso:
    python auditar_camara.py <video.mp4> [...]
    python auditar_camara.py --state state_ltx_cam.json [--n 10]
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "camara_audit.jsonl")


def first_last(path, w=480):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", path],
                               capture_output=True, text=True).stdout.strip() or 10)
    tmp = tempfile.mkdtemp(prefix="cam_")
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
        h = min(a.shape[0], b.shape[0])
        w = min(a.shape[1], b.shape[1])
        a, b = a[:h, :w], b[:h, :w]
    ga = grad(a)
    mejor = (-1, 1.0, (0, 0))
    for s in np.arange(0.90, 1.1001, 0.005):
        gb = grad(escalar(b, s))[:ga.shape[0], :ga.shape[1]]
        pk, pos, shp = pico(ga, gb)
        dy = pos[0] - (shp[0] - 1 if pos[0] > shp[0] // 2 else 0)
        dx = pos[1] - (shp[1] - 1 if pos[1] > shp[1] // 2 else 0)
        if pk > mejor[0]:
            mejor = (pk, float(s), (dx, dy))
    pk, s, (dx, dy) = mejor
    zoom = (s - 1.0) * 100.0
    ancho = a.shape[1]
    return {
        "archivo": os.path.basename(path),
        "path": path,
        "dur": round(dur, 2),
        "zoom_pct": round(zoom, 1),
        "dx_px": int(dx),
        "dy_px": int(dy),
        "dx_pct_ancho": round(100.0 * dx / ancho, 1),
        "dy_pct_alto": round(100.0 * dy / a.shape[0], 1),
        "pico": round(pk, 3),
    }


ap = argparse.ArgumentParser()
ap.add_argument("videos", nargs="*")
ap.add_argument("--state", default=None)
ap.add_argument("--n", type=int, default=0, help="en --state, cuantos de los ultimos hechos")
ap.add_argument("--no-log", action="store_true")
a = ap.parse_args()

paths = list(a.videos)
if a.state:
    st = json.load(open(os.path.join(BASE, a.state) if not os.path.isabs(a.state) else a.state,
                        encoding="utf-8"))
    hechos = [i for i in st["items"] if i["status"] == "hecho" and i.get("out")
              and os.path.isfile(i["out"])]
    if a.n:
        hechos = hechos[-a.n:]
    for i in hechos:
        paths.append(i["out"])

if not paths:
    sys.exit("nada para medir")

print(f"{'archivo':<62} {'zoom':>7} {'dx':>6} {'dy':>6} {'pico':>6}")
for p in paths:
    try:
        r = medir(p)
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR {os.path.basename(p)}: {e}")
        continue
    print(f"{r['archivo'][:60]:<62} {r['zoom_pct']:+6.1f}% {r['dx_px']:+6d} {r['dy_px']:+6d} {r['pico']:6.3f}")
    if not a.no_log:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
