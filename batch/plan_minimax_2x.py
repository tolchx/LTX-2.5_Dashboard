"""Arma un plan corto para la campaña NOMADE con MiniMax H3:
2 visuales por escena (rol A y rol B de la primera toma) = 20 clips.

Deja el state anterior respaldado como state_442_ltx.json.
Uso: python plan_minimax_2x.py [--dry]
"""
import collections
import json
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "state.json")
BACKUP = os.path.join(BASE, "state_442_ltx.json")

DRY = "--dry" in sys.argv
ENGINE = "minimax_h3"

st = json.load(open(STATE, encoding="utf-8"))
its = st["items"]

# primera toma de cada escena, en orden alfabetico de escena
primera = {}
orden = sorted({i["scene"] for i in its})
for s in orden:
    tomas = sorted({i["shot"] for i in its if i["scene"] == s})
    primera[s] = tomas[0]

nuevos = []
for s in orden:
    toma = primera[s]
    for rol in ("A", "B"):
        # clonar el item ltx25 de esa imagen como item minimax
        base = next((i for i in its
                     if i["scene"] == s and i["shot"] == toma and i["role"] == rol
                     and i["engine"] == "ltx25"), None)
        if base is None:
            print("  !! falta", s, toma, rol)
            continue
        stem = base["id"].split("|")[2]
        it = dict(base)
        it["engine"] = ENGINE
        it["id"] = f"{base['scene']}|{base['shot']}|{stem}|{ENGINE}"
        it.update({
            "status": "pendiente", "attempts": 0, "job_id": None, "out": None,
            "dur_s": None, "error": None, "bench": False,
            "t0": None, "ultimo_cambio": time.time(), "ultimo_prog": 0,
            "ultimo_stage": None, "started": None, "finished": None,
            "camara": "estatica-v3", "corto": "nomade-2x-escena",
        })
        nuevos.append(it)

print(f"items en el plan corto: {len(nuevos)}")
for it in nuevos:
    print(f"  {it['scene']:<24} {it['shot']:<28} rol {it['role']}  ->  {os.path.basename(it['image'])}")

nuevo_state = {
    "creado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "motor": ENGINE,
    "nota": "2 visuales por escena (A y B de la primera toma) — camara estatica v3",
    "items": nuevos,
}

if DRY:
    print("\n(dry run)")
    sys.exit(0)

if not os.path.exists(BACKUP):
    shutil.copy2(STATE, BACKUP)
    print("\nbackup:", BACKUP)
else:
    print("\nbackup ya existia:", BACKUP)

tmp = STATE + ".tmp"
json.dump(nuevo_state, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(tmp, STATE)
print("state.json reescrito con", len(nuevos), "items ·", time.strftime("%H:%M:%S"))
