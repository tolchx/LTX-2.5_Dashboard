"""Aplica el bloque de camara estatica v3 a TODOS los items del state actual,
sin importar el estado (los de escena 01 y 02 venian del plan viejo, sin bloque).
Idempotente. Uso: python fix_camara_todos.py [--dry]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import batch as B

DRY = "--dry" in sys.argv
MARCADORES = ("\n\nSTATIC SHOT.", "\n\nSTATIC CAMERA, FIXED FRAME.")
CABEZAS = (B.STATIC_HEAD.strip(),)


def escena_de(prompt):
    t = (prompt or "").strip()
    for m in MARCADORES:
        if m in t:
            t = t.split(m)[0]
    t = t.strip()
    for c in CABEZAS:
        if t.startswith(c):
            t = t[len(c):].strip()
    return t


st = json.load(open(B.STATE, encoding="utf-8"))
n = 0
for it in st["items"]:
    base = escena_de(it.get("prompt"))
    nuevo = (B.STATIC_HEAD + base + "\n\n" + B.STATIC_BLOCK).strip()
    if nuevo != it.get("prompt"):
        it["prompt"] = nuevo
        it["negative"] = B.NEG_EXTRA
        it["camara"] = "estatica-v3"
        n += 1
    print(f"  {it['status']:<10} {it['role']} {it['scene'][:22]:<24} len={len(it['prompt'])}")

print(f"\nitems tocados: {n} de {len(st['items'])}")
if DRY:
    print("(dry run)")
    sys.exit(0)
tmp = B.STATE + ".tmp"
json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(tmp, B.STATE)
print("guardado")
