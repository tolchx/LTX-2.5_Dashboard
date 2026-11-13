"""Reasigna el movimiento de camara a los items PENDIENTES del lote, sin tocarlos hechos.

Sirve cuando cambia la lista de movimientos (por ejemplo al sumar 'loop'). Toma los
pendientes en orden, les pone camara.ORDEN[n % len] y reescribe el prompt limpiando
el bloque anterior. Despues hay que correr endframes.py para regenerar las guias.

Uso: python reasignar_camara.py [--state state_ltx_cam.json] [--dry]
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camara  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--state", default="state_ltx_cam.json")
ap.add_argument("--dry", action="store_true")
a = ap.parse_args()

ruta = a.state if os.path.isabs(a.state) else os.path.join(BASE, a.state)
st = json.load(open(ruta, encoding="utf-8"))

n = 0
largos = []
for it in st["items"]:
    if it.get("status") != "pendiente":
        continue
    mov = camara.por_indice(n)
    base = camara.limpiar(it.get("prompt"))
    if not base:
        print("!! sin escena:", it["id"])
        continue
    it["prompt"] = camara.aplicar(base, mov)
    it["camara"] = mov
    it["last_image"] = None
    it["camara_shift"] = None
    it["guide_strength"] = None
    largos.append(len(it["prompt"]))
    n += 1

print(f"pendientes reasignados: {n}")
print("rotacion:", dict(collections.Counter(
    i["camara"] for i in st["items"] if i.get("status") == "pendiente")))
print(f"prompt: min {min(largos)} · mediana {sorted(largos)[len(largos)//2]} · max {max(largos)}")

if a.dry:
    print("(dry run)")
    sys.exit(0)
tmp = ruta + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(st, f, ensure_ascii=False, indent=1)
os.replace(tmp, ruta)
print("guardado")
