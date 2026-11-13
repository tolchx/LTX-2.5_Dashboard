"""Hojas de contacto del lote de biomas para elegir a ojo.

Arma una grilla por familia (5 variantes) con el nombre de archivo debajo, y una
hoja general con las 50. Salida en selva_amk/lote/hojas/.

Uso: python hojas_lote.py [--carpeta selva_amk/lote] [--por-hoja 5]
"""
import argparse
import glob
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))


def fuente(size=18):
    for f in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.isfile(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
    return ImageFont.load_default()


ap = argparse.ArgumentParser()
ap.add_argument("--carpeta", default=os.path.join(BASE, "selva_amk", "lote"))
ap.add_argument("--por-hoja", type=int, default=5)
ap.add_argument("--alto", type=int, default=520)
ap.add_argument("--salida", default=None)
a = ap.parse_args()

archivos = sorted(glob.glob(os.path.join(a.carpeta, "*.png")))
archivos = [f for f in archivos if "hoja" not in os.path.basename(f)]
if not archivos:
    raise SystemExit("no hay imagenes en " + a.carpeta)

salida = a.salida or os.path.join(a.carpeta, "hojas")
os.makedirs(salida, exist_ok=True)
f = fuente(20)
pad, label = 12, 30

por_fam = {}
for p in archivos:
    fam = os.path.basename(p).rsplit("_", 1)[0]
    por_fam.setdefault(fam, []).append(p)

hechas = []
for fam, lista in sorted(por_fam.items()):
    lista = sorted(lista)[:a.por_hoja]
    thumbs = []
    for p in lista:
        im = Image.open(p).convert("RGB")
        r = a.alto / im.height
        thumbs.append((im.resize((max(8, int(im.width * r)), a.alto), Image.LANCZOS), os.path.basename(p)))
    w = sum(t.width for t, _ in thumbs) + pad * (len(thumbs) + 1)
    sheet = Image.new("RGB", (w, a.alto + label + pad * 2), (14, 14, 18))
    d = ImageDraw.Draw(sheet)
    x = pad
    for im, n in thumbs:
        sheet.paste(im, (x, pad))
        d.text((x, pad + a.alto + 4), n, fill=(215, 215, 225), font=f)
        x += im.width + pad
    dst = os.path.join(salida, f"hoja_{fam}.png")
    sheet.save(dst)
    hechas.append(dst)
    print("hoja:", os.path.basename(dst), sheet.size)

# hoja general: todas, mas chicas
if len(archivos) > a.por_hoja:
    alto = 240
    thumbs = []
    for p in archivos:
        im = Image.open(p).convert("RGB")
        r = alto / im.height
        thumbs.append(im.resize((max(6, int(im.width * r)), alto), Image.LANCZOS))
    cols = 10
    wcol = max(t.width for t in thumbs) + 8
    filas = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * wcol + 8, filas * (alto + 8) + 8), (14, 14, 18))
    for i, t in enumerate(thumbs):
        x = 8 + (i % cols) * wcol
        y = 8 + (i // cols) * (alto + 8)
        sheet.paste(t, (x, y))
    dst = os.path.join(salida, "hoja_todas.png")
    sheet.save(dst)
    print("hoja general:", dst, sheet.size)
print(f"{len(hechas)} hojas en {salida}")
