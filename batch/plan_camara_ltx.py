"""Arma el estado de reanudacion del lote LTX con CAMARA VARIADA.

Toma el plan largo (state_442_ltx.json, 418 items ltx25) y produce
state_ltx_cam.json:

  * los items ya hechos quedan tal cual (el tick los ignora),
  * desde la toma indicada (por defecto el primer pendiente del plan, que es
    s02_t4 · Faroles) cada item recibe un movimiento de camara distinto, rotando
    por la lista de camara.ORDEN, con el prompt reescrito en positivo,
  * misma config con la que se renderizaron los anteriores ltx: 1280x704, 10 s,
    24 fps, seed 777000, i2v 0.85, vae diff, crf 17, una sola pasada.

Uso:
    python plan_camara_ltx.py [--desde s02_t4] [--out state_ltx_cam.json] [--dry]
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camara  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
ORIGEN = os.path.join(BASE, "state_442_ltx.json")

ap = argparse.ArgumentParser()
ap.add_argument("--desde", default=None, help="codigo de toma donde reanudar (ej. s02_t4)")
ap.add_argument("--out", default="state_ltx_cam.json")
ap.add_argument("--dry", action="store_true")
a = ap.parse_args()

st = json.load(open(ORIGEN, encoding="utf-8"))
items = [i for i in st["items"] if i["engine"] == "ltx25"]
print(f"plan origen: {len(items)} items ltx25 · "
      f"{collections.Counter(i['status'] for i in items)}")

# --- punto de reanudacion --------------------------------------------------
hechos = [i for i in items if i["status"] == "hecho"]
pendientes = [i for i in items if i["status"] == "pendiente"]
if not pendientes:
    sys.exit("no hay items pendientes en el plan origen")

if a.desde:
    marca = [i for i in pendientes if i["shot"].startswith(a.desde)]
    if not marca:
        sys.exit(f"no encontre pendientes en la toma '{a.desde}'")
    primera = marca[0]
else:
    primera = pendientes[0]

# los pendientes anteriores al punto de reanudacion no se tocan (quedan fuera)
idx_primera = items.index(primera)
descartados = [i for i in pendientes if items.index(i) < idx_primera]
a_procesar = [i for i in items[idx_primera:] if i["status"] == "pendiente"]

print(f"reanudo en: {primera['shot']} · rol {primera['role']} "
      f"({os.path.basename(primera['image'])})")
print(f"pendientes a procesar: {len(a_procesar)} · "
      f"descartados (anteriores): {len(descartados)}")

# --- reescritura de prompts ------------------------------------------------
config = {
    "preset": "1280x704", "duration": 10.0, "fps": 24, "two_stage": False,
    "audio": False, "engine_main": "ltx25", "i2v_strength": 0.85,
    "vae_mode": "diff", "crf": 17, "seed": 777000,
    "camara": "variada-v1 (rotacion de 12 movimientos lentos, sin zoom)",
    "sufijo": "-cam",
}

nuevos = []
faltantes = []
for n, it in enumerate(a_procesar):
    mov = camara.por_indice(n)
    base = camara.limpiar(it.get("prompt"))
    if not base:
        faltantes.append(it["id"])
        continue
    nuevo = dict(it)
    nuevo.update({
        "prompt": camara.aplicar(base, mov),
        "negative": ("camera shake, handheld, jump cut, scene change, morphing, warping, "
                     "flicker, text, watermark, subtitles, logo"),
        "camara": mov,
        "sufijo": "-cam",
        "preset": "1280x704", "duration": 10.0, "fps": 24,
        "two_stage": False, "include_audio": False, "chunks": 1,
        "seed": 777000, "i2v_strength": 0.85, "vae_mode": "diff", "crf": 17,
        "engine": "ltx25",
        "status": "pendiente", "attempts": 0, "job_id": None, "t0": None,
        "out": None, "dur_s": None, "error": None, "bench": False,
    })
    nuevos.append(nuevo)

if faltantes:
    print(f"!! sin descripcion de escena ({len(faltantes)}): {faltantes[:5]}")

largos = [len(i["prompt"]) for i in nuevos]
print(f"prompt: min {min(largos)} · mediana {sorted(largos)[len(largos)//2]} · max {max(largos)} chars")
print("rotacion:", dict(collections.Counter(i["camara"] for i in nuevos)))

# los hechos se conservan como registro (no se re-renderizan)
hechos_prev = [i for i in items[:idx_primera] if i["status"] == "hecho"]
salida = {
    "creado": st.get("creado"),
    "motor": "ltx25",
    "nota": ("Reanudacion desde " + primera["shot"] +
             " con camara variada (sin zoom, movimientos lentos). Misma config que los ltx previos."),
    "config": config,
    "items": hechos_prev + nuevos,
}
print(f"state final: {len(hechos_prev)} hechos (registro) + {len(nuevos)} pendientes")

print("\n=== muestras")
for nombre in ("paneo-der", "travelling-izq", "descenso", "estatica"):
    it = next((i for i in nuevos if i["camara"] == nombre), None)
    if it:
        print(f"\n--- {nombre} · {it['shot']} · rol {it['role']} · {os.path.basename(it['image'])}")
        print(it["prompt"][:420] + " …")
        print("   [...] " + it["prompt"][-260:])

if a.dry:
    print("\n(dry run: no escribi nada)")
    sys.exit(0)

dest = os.path.join(BASE, a.out)
tmp = dest + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(salida, f, ensure_ascii=False, indent=1)
os.replace(tmp, dest)
print(f"\nguardado: {dest}")
