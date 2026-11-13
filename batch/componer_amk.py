"""Compone la entrega de pantallas del club AMK con un bioma por zona.

Lee pantallas_amk.json (geometria + bioma asignado por pantalla), toma el mural de
cada bioma de selva_amk/, lo escala 2x con lanczos y recorta la ventana relativa que
le corresponde a cada pantalla. Deja los PNG con el px exacto de cada LED y un
preview sobre el pixelmap.

Uso:
    python componer_amk.py [--json pantallas_amk.json] [--salida selva_amk/entrega]
"""
import argparse
import json
import os

import cv2
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
BIOMAS = os.path.join(BASE, "selva_amk")
PIXELMAP = r"C:\Users\Tolch\Desktop\AMK_2025_v1.png"


def leer(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def escribir(path, img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError(f"no pude codificar {path}")
    buf.tofile(path)


def upscale_2x(img, grano=3.0):
    """Lanczos 2x + grano fino: no hay modelo ESRGAN instalado y para LED a distancia
    el grano tapa el suavizado del reescalado."""
    h, w = img.shape[:2]
    up = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_LANCZOS4)
    rng = np.random.default_rng(7)
    ruido = rng.normal(0, grano, up.shape[:2]).astype(np.float32)[:, :, None]
    return np.clip(up.astype(np.float32) + ruido, 0, 255).astype(np.uint8)


def ventana(mural, x, y, w, h, CW, CH):
    MH, MW = mural.shape[:2]
    x0 = int(round(x / CW * MW)); y0 = int(round(y / CH * MH))
    x1 = min(int(round((x + w) / CW * MW)), MW)
    y1 = min(int(round((y + h) / CH * MH)), MH)
    trozo = mural[max(y0, 0):max(y1, y0 + 2), max(x0, 0):max(x1, x0 + 2)]
    return cv2.resize(trozo, (w, h), interpolation=cv2.INTER_LANCZOS4)


ap = argparse.ArgumentParser()
ap.add_argument("--json", default=os.path.join(BASE, "pantallas_amk.json"))
ap.add_argument("--salida", default=os.path.join(BIOMAS, "entrega"))
ap.add_argument("--preview", default=os.path.join(BIOMAS, "preview_zona.png"))
ap.add_argument("--plano", default=PIXELMAP)
ap.add_argument("--dir", default=BIOMAS, help="carpeta de los murales")
ap.add_argument("--sin-upscale", action="store_true",
                help="usar el mural tal cual (ya viene 4x de Topaz)")
a = ap.parse_args()

cfg = json.load(open(a.json, encoding="utf-8"))
CW, CH = cfg["canvas"]
os.makedirs(a.salida, exist_ok=True)

# cargar y 2x cada bioma usado
usados = sorted({p["bioma"] for p in cfg["pantallas"]})
murales = {}
for b in usados:
    ruta = os.path.join(a.dir, f"{b}.png")
    if not os.path.isfile(ruta):
        print(f"!! falta {ruta}")
        continue
    m = leer(ruta)
    murales[b] = m if a.sin_upscale else upscale_2x(m)
    print(f"{b}: {m.shape[1]}x{m.shape[0]}" +
          ("" if a.sin_upscale else f" -> {murales[b].shape[1]}x{murales[b].shape[0]} (2x)"))

plan = leer(a.plano)
if plan is None:
    raise SystemExit("no pude leer el pixelmap")
preview = (plan.astype(np.float32) * 0.5).astype(np.uint8)

print(f"\n{len(cfg['pantallas'])} pantallas:")
for p in cfg["pantallas"]:
    b = p["bioma"]
    if b not in murales:
        continue
    out = ventana(murales[b], p["x"], p["y"], p["w"], p["h"], CW, CH)
    nombre = f"{p['n']:02d}_{p['nombre']}_{p['w']}x{p['h']}.png"
    escribir(os.path.join(a.salida, nombre), out)
    preview[p["y"]:p["y"] + p["h"], p["x"]:p["x"] + p["w"]] = out
    print(f"  {nombre:<42} bioma {b}")

escribir(a.preview, preview)
print(f"\npreview: {a.preview}")
print(f"entrega: {a.salida}")
