"""Corta un mural de selva en las pantallas reales del club AMK.

El pixelmap (2160x4096) define donde esta cada LED. En vez de generar una imagen
por pantalla (imposible: las tiras son 1:10 y cada una seria una selva distinta),
se genera UN mural y se recorta la ventana de cada pantalla, escalada a su tamano
exacto. Asi el club lee un solo ambiente continuo.

Uso:
    python cortar_mural.py <mural.png> [--salida DIR] [--json pantallas_amk.json]
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))


def leer(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def escribir(path, img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError(f"no pude codificar {path}")
    buf.tofile(path)


ap = argparse.ArgumentParser()
ap.add_argument("mural")
ap.add_argument("--salida", default=None)
ap.add_argument("--json", default=os.path.join(BASE, "pantallas_amk.json"))
ap.add_argument("--escala", type=float, default=1.0, help="multiplica el tamano final")
a = ap.parse_args()

cfg = json.load(open(a.json, encoding="utf-8"))
CW, CH = cfg["canvas"]
mural = leer(a.mural)
if mural is None:
    sys.exit(f"no pude leer {a.mural}")
MH, MW = mural.shape[:2]
salida = a.salida or os.path.join(os.path.dirname(os.path.abspath(a.mural)), "pantallas")
os.makedirs(salida, exist_ok=True)

print(f"mural {MW}x{MH} · canvas {CW}x{CH} · {len(cfg['pantallas'])} pantallas")
for n, p in enumerate(cfg["pantallas"], 1):
    x, y, w, h = p["x"], p["y"], p["w"], p["h"]
    # misma ventana relativa en el mural
    x0 = int(round(x / CW * MW)); y0 = int(round(y / CH * MH))
    x1 = int(round((x + w) / CW * MW)); y1 = int(round((y + h) / CH * MH))
    x1 = min(max(x1, x0 + 2), MW); y1 = min(max(y1, y0 + 2), MH)
    trozo = mural[y0:y1, x0:x1]
    wd, hd = int(round(w * a.escala)), int(round(h * a.escala))
    out = cv2.resize(trozo, (wd, hd), interpolation=cv2.INTER_LANCZOS4)
    nombre = f"pantalla_{n:02d}_{w}x{h}.png"
    escribir(os.path.join(salida, nombre), out)
    print(f"  {nombre:<28} ventana mural {x1-x0}x{y1-y0} -> {wd}x{hd}")
print(f"listo en {salida}")
