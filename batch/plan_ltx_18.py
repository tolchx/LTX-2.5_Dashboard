"""Arma el plan corto de 18 clips pero en LTX (motor rapido y estable en esta placa).

Toma las mismas 18 imagenes del plan corto (escenas 02..10, rol A y B de la primera
toma) desde el respaldo state_442_ltx.json y deja state.json listo para el tick.
Uso: python plan_ltx_18.py [--dry]
"""
import json
import os
import sys
import time

BATCH = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(BATCH, "state.json")
RESPALDO = os.path.join(BATCH, "state_442_ltx.json")
DRY = "--dry" in sys.argv

act = json.load(open(ESTADO, encoding="utf-8"))["items"]
comp = json.load(open(RESPALDO, encoding="utf-8"))["items"]

# las imagenes exactas del plan corto actual (no por rol: cada rol tiene 4 variantes)
claves = {os.path.normcase(i["image"]) for i in act}
print("objetivo:", len(claves), "imagenes")

nuevos = []
for i in comp:
    if os.path.normcase(i["image"]) in claves and i["engine"] == "ltx25":
        it = dict(i)
        it.update({"status": "pendiente", "attempts": 0, "job_id": None, "out": None,
                   "dur_s": None, "error": None, "bench": False, "t0": None,
                   "ultimo_cambio": time.time(), "ultimo_prog": 0, "ultimo_stage": None,
                   "started": None, "finished": None})
        nuevos.append(it)

nuevos.sort(key=lambda x: (x["scene"], x["role"]))
print("items LTX:", len(nuevos))
for it in nuevos:
    print(f"  {it['scene']:<24} {it['role']}  {os.path.basename(it['image'])[:44]}")

if DRY:
    print("(dry)")
    sys.exit(0)

json.dump({"creado": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "motor": "ltx25",
           "nota": "18 clips (2 por escena, 02..10) en LTX 1280x704 10s — camara estatica v3",
           "items": nuevos},
          open(ESTADO + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(ESTADO + ".tmp", ESTADO)
print("state.json reescrito con", len(nuevos), "items LTX")
