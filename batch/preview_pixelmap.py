"""Previsualiza el mural puesto en el pixelmap real del club AMK.

Toma el pixelmap (2160x4096) y reemplaza cada rectangulo de pantalla con la ventana
correspondiente del mural, escalada al tamano de esa pantalla. Sirve para ver si la
selva lee como un solo ambiente a traves de las tiras.

Uso:
    python preview_pixelmap.py <mural.png> [--salida preview.png]
    python preview_pixelmap.py <mural.png> --solo-rects      # sin fondo del plano
"""
import argparse
import json
import os

import cv2
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
PIXELMAP = r"C:\Users\Tolch\Desktop\AMK_2025_v1.png"


def leer(path, flags=cv2.IMREAD_COLOR):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), flags)


def escribir(path, img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("no pude codificar")
    buf.tofile(path)


ap = argparse.ArgumentParser()
ap.add_argument("mural")
ap.add_argument("--salida", default=None)
ap.add_argument("--json", default=os.path.join(BASE, "pantallas_amk.json"))
ap.add_argument("--plano", default=PIXELMAP)
ap.add_argument("--oscurecer", type=float, default=0.55,
                help="cuanto se apaga el plano de fondo para que se lean las pantallas")
a = ap.parse_args()

cfg = json.load(open(a.json, encoding="utf-8"))
plan = leer(a.plano)
if plan is None:
    raise SystemExit("no pude leer el pixelmap")
MH_p, MW_p = plan.shape[:2]
CW, CH = cfg["canvas"]
mural = leer(a.mural)
MH, MW = mural.shape[:2]

fondo = (plan.astype(np.float32) * a.oscurecer).astype(np.uint8)
salida = fondo.copy()

for p in cfg["pantallas"]:
    x, y, w, h = p["x"], p["y"], p["w"], p["h"]
    x0 = int(round(x / CW * MW)); y0 = int(round(y / CH * MH))
    x1 = min(int(round((x + w) / CW * MW)), MW)
    y1 = min(int(round((y + h) / CH * MH)), MH)
    trozo = mural[max(y0, 0):max(y1, y0 + 2), max(x0, 0):max(x1, x0 + 2)]
    if trozo.size == 0:
        continue
    salida[y:y + h, x:x + w] = cv2.resize(trozo, (w, h), interpolation=cv2.INTER_LANCZOS4)

dst = a.salida or os.path.join(os.path.dirname(os.path.abspath(a.mural)), "preview_pixelmap.png")
escribir(dst, salida)
print("preview:", dst)
