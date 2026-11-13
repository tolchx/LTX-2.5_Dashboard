"""Reescribe el bloque de camara de los items PENDIENTES del state.

Camara estatica, sin zoom in/out, con movimiento lento solo dentro de la escena.
No toca hechos / parked / el que esta corriendo (ese ya salio con el prompt viejo).

Uso:  python update_camera_prompt.py [--dry]
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import batch as B  # noqa: E402  (STATIC_HEAD, STATIC_BLOCK, NEG_EXTRA, STATE)

DRY = "--dry" in sys.argv
MARCADORES = ("\n\nSTATIC SHOT.", "\n\nSTATIC CAMERA, FIXED FRAME.")
CABEZAS = (
    "Static locked-off camera, fixed framing: the shot holds the same distance, "
    "scale and framing from the first frame to the last, no zoom in or out, while "
    "the scene keeps its slow motion inside the frame. ",
)


def escena_de(prompt: str) -> str:
    """Prompt de escena sin la cabecera de camara y sin el bloque de camara (viejo o nuevo)."""
    t = prompt or ""
    for m in MARCADORES:
        if m in t:
            t = t.split(m)[0]
    t = t.strip()
    for cab in CABEZAS:
        c = cab.strip()
        if t.startswith(c):
            t = t[len(c):].strip()
    return t


st = json.load(open(B.STATE, encoding="utf-8"))
items = st["items"]

n = 0
ejemplo = None
for it in items:
    if it.get("status") != "pendiente":
        continue
    base = escena_de(it.get("prompt"))
    it["prompt"] = (B.STATIC_HEAD + base + "\n\n" + B.STATIC_BLOCK).strip()
    it["negative"] = B.NEG_EXTRA
    it["camara"] = "estatica-v3"
    n += 1
    if ejemplo is None:
        ejemplo = it

print(f"items reescritos: {n}")
if ejemplo:
    print("\n--- item de muestra ---")
    print("ID:", ejemplo["id"])
    print("\nHEAD (lo que muestra la tarjeta del Studio):")
    print(ejemplo["prompt"][:240])
    print("\n...escena...")
    print("\nbloque final:", B.STATIC_BLOCK[:150], "...")
    print("\nnegative:", B.NEG_EXTRA)

if DRY:
    print("\n(dry run: no se guardo nada)")
    sys.exit(0)

tmp = B.STATE + ".tmp"
json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(tmp, B.STATE)
print(f"\nguardado en {B.STATE} · {time.strftime('%H:%M:%S')}")
