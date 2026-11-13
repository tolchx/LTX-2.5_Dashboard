"""Inserta s01_t6 (rol A y B) al frente del plan actual, en MiniMax optimizado.

- Toma los prompts del respaldo state_442_ltx.json y les aplica el bloque de camara
  estatica v3 (esos items son del plan viejo y no lo tenian).
- Config optimizada: 960x544, 12 pasos, 10 s, sin audio.
Uso: python add_s01_t6.py [--dry]
"""
import json
import os
import sys
import time

BATCH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BATCH)
import batch as B  # noqa: E402

DRY = "--dry" in sys.argv
ESCENA = "01 · EL PORTAL"
TOMA = "s01_t6 · Muro de niebla"
PRESET = "960x544"
STEPS = 12
DURACION = 10.0

estado = json.load(open(os.path.join(BATCH, "state.json"), encoding="utf-8"))
resp = json.load(open(os.path.join(BATCH, "state_442_ltx.json"), encoding="utf-8"))["items"]

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


nuevos = []
for rol in ("A", "B"):
    base = next((i for i in resp if i["scene"] == ESCENA and i["shot"] == TOMA
                 and i["role"] == rol), None)
    if base is None:
        print("  !! falta", rol)
        continue
    stem = os.path.splitext(os.path.basename(base["image"]))[0]
    it = dict(base)
    it["engine"] = "minimax_h3"
    it["id"] = f"{ESCENA}|{TOMA}|{stem}|minimax_h3"
    it["prompt"] = (B.STATIC_HEAD + escena_de(base["prompt"]) + "\n\n" + B.STATIC_BLOCK).strip()
    it["negative"] = B.NEG_EXTRA
    it["preset"] = PRESET
    it["steps"] = STEPS
    it["duration"] = DURACION
    it["fps"] = 24
    it["two_stage"] = False
    it["include_audio"] = False
    it["seed"] = 777000
    it.update({"status": "pendiente", "attempts": 0, "job_id": None, "out": None,
               "dur_s": None, "error": None, "bench": False, "t0": None,
               "ultimo_cambio": time.time(), "ultimo_prog": 0, "ultimo_stage": None,
               "started": None, "finished": None, "camara": "estatica-v3"})
    nuevos.append(it)

print("items nuevos:", len(nuevos))
for it in nuevos:
    print(f"  {it['role']}  {os.path.basename(it['image'])}  | {it['preset']} {it['steps']} pasos {it['duration']}s")
    print(f"     prompt: {len(it['prompt'])} car · head={'SI' if it['prompt'].startswith('Static locked-off') else 'NO'}")

if DRY:
    print("(dry)")
    sys.exit(0)

ya = {(i["scene"], i["shot"]) for i in nuevos}
estado["items"] = nuevos + [i for i in estado["items"] if (i["scene"], i["shot"]) not in ya]
json.dump(estado, open(os.path.join(BATCH, "state.json.tmp"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
os.replace(os.path.join(BATCH, "state.json.tmp"), os.path.join(BATCH, "state.json"))
print("\nplan ahora:", len(estado["items"]), "items")
for i in estado["items"][:4]:
    print(f"  {i['scene']:<20} {i['role']} {i['engine']:<10} {i['preset']:<9} steps={i.get('steps')}")
