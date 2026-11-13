"""Aplica la config ganadora a los items PENDIENTES del plan NOMADE y reanuda.

Uso: python aplicar_config.py <preset> <steps> [i2v] [negativo_corto]
  ej: python aplicar_config.py 1280x704 25
      python aplicar_config.py 1280x704 25 1.0 corto
"""
import json
import os
import sys
import time

BATCH = os.path.dirname(os.path.abspath(__file__))
PRESET = sys.argv[1] if len(sys.argv) > 1 else "1280x704"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 25
I2V = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] not in ("corto",) else 0.85
NEG_CORTO = "corto" in sys.argv

NEG = ("camera movement, zoom, pan, dolly, handheld shake, morphing, warping, "
       "distorted geometry, deformed architecture, text, watermark, logo"
       ) if NEG_CORTO else None

st = json.load(open(os.path.join(BATCH, "state.json"), encoding="utf-8"))
n = 0
for it in st["items"]:
    if it["status"] != "pendiente":
        continue
    it["preset"] = PRESET
    it["steps"] = STEPS
    it["duration"] = 10.0
    it["i2v_strength"] = I2V
    if NEG:
        it["negative"] = NEG
    n += 1

st["nota"] = f"NOMADE — MiniMax H3 {PRESET} {STEPS} pasos 10 s (calidad verificada)"
json.dump(st, open(os.path.join(BATCH, "state.json.tmp"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
os.replace(os.path.join(BATCH, "state.json.tmp"), os.path.join(BATCH, "state.json"))
print(f"items actualizados: {n} -> {PRESET}, {STEPS} pasos, i2v {I2V}"
      + (", negative corto" if NEG else ""))

pausa = os.path.join(BATCH, "PAUSA.txt")
if os.path.isfile(pausa):
    os.remove(pausa)
    print("PAUSA liberada", time.strftime("%H:%M:%S"))
