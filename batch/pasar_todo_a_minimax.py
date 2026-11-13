"""Pasa TODO el plan corto a MiniMax H3 optimizado (960x544, 12 pasos, 10 s).

- Reescribe el prompt con el bloque de camara estatica v3 (algunos venian sin el).
- Respeta el item que este corriendo: no lo toca.
Uso: python pasar_todo_a_minimax.py [--dry]
"""
import json
import os
import sys
import time

BATCH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BATCH)
import batch as B  # noqa: E402

DRY = "--dry" in sys.argv
PRESET, STEPS, DUR = "960x544", 12, 10.0
MARCADORES = ("\n\nSTATIC SHOT.", "\n\nSTATIC CAMERA, FIXED FRAME.")


def escena_de(p):
    t = (p or "").strip()
    for m in MARCADORES:
        if m in t:
            t = t.split(m)[0]
    t = t.strip()
    c = B.STATIC_HEAD.strip()
    if t.startswith(c):
        t = t[len(c):].strip()
    return t


st = json.load(open(B.STATE, encoding="utf-8"))
n = 0
for it in st["items"]:
    if it["status"] == "corriendo":
        print(f"  (salteo el que corre) {it['role']} {it['scene'][:18]} steps={it.get('steps')}")
        continue
    stem = it["id"].split("|")[2]
    it["engine"] = "minimax_h3"
    it["id"] = f"{it['scene']}|{it['shot']}|{stem}|minimax_h3"
    it["prompt"] = (B.STATIC_HEAD + escena_de(it.get("prompt")) + "\n\n" + B.STATIC_BLOCK).strip()
    it["negative"] = B.NEG_EXTRA
    it.update({"preset": PRESET, "steps": STEPS, "duration": DUR, "fps": 24,
               "two_stage": False, "include_audio": False, "seed": it.get("seed") or 777000,
               "camara": "estatica-v3"})
    n += 1

st["motor"] = "minimax_h3"
st["nota"] = "NOMADE — MiniMax H3 optimizado 960x544 12 pasos 10 s, 2 visuales (A y B) por escena desde s01_t6"
st["items"].sort(key=lambda x: (x["scene"], x["shot"], x["role"]))

print(f"\nitems convertidos: {n} de {len(st['items'])}")
for it in st["items"]:
    print(f"  {it['status']:<10} {it['scene'][:22]:<23} {it['role']} {it['preset']} {it.get('steps')}p {it['duration']}s")

if DRY:
    print("(dry)")
    sys.exit(0)

tmp = B.STATE + ".tmp"
json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(tmp, B.STATE)
print("\nguardado", time.strftime("%H:%M:%S"))
