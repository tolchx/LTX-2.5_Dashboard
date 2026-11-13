"""Pase de camara en post sobre los clips ya renderizados del lote.

Lee state_ltx_cam.json, y para cada clip hecho aplica el movimiento que le toca
(mov_post) o el modo loop/estatica, con camara_post.py. Idempotente: si el destino
existe y no es --forzar, lo saltea. Escribe un CSV indice.

Uso:
    python procesar_post.py --solo-muestra 3         # prueba con 3
    python procesar_post.py --workers 3             # todo (horas de CPU)
"""
import argparse
import csv
import json
import os
import queue
import subprocess
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "state_ltx_cam.json")
DEST = os.path.join(os.path.dirname(BASE), "outputs", "post")
LOG = os.path.join(BASE, "post.log")
PY = sys.executable

ap = argparse.ArgumentParser()
ap.add_argument("--workers", type=int, default=2)
ap.add_argument("--solo-muestra", type=int, default=0)
ap.add_argument("--forzar", action="store_true")
ap.add_argument("--wd", type=int, default=1280)
ap.add_argument("--hd", type=int, default=704)
a = ap.parse_args()

st = json.load(open(STATE, encoding="utf-8"))


def trabajo_de(it):
    """(entrada, salida, movimiento) o None si el item no corresponde."""
    src = it.get("out")
    if not src or not os.path.isfile(src):
        return None
    cam = it.get("camara") or ""
    mov = it.get("mov_post") or ("loop" if cam == "loop" else "estatica")
    if cam not in ("loop", "estatica", "estatica-limpia") and not it.get("mov_post"):
        return None
    stem = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(DEST, f"{stem}__post-{mov}.mp4")
    return (src, dst, mov)


tareas = []
for it in st["items"]:
    if it.get("status") != "hecho":
        continue
    t = trabajo_de(it)
    if t:
        tareas.append(t)
if a.solo_muestra:
    tareas = tareas[-a.solo_muestra:] if len(tareas) > a.solo_muestra else tareas

os.makedirs(DEST, exist_ok=True)
print(f"post: {len(tareas)} clips · workers {a.workers} · destino {DEST}")

cola = queue.Queue()
for t in tareas:
    cola.put(t)
hechos = []
lock = threading.Lock()


def worker(n):
    while True:
        try:
            src, dst, mov = cola.get_nowait()
        except queue.Empty:
            return
        if os.path.isfile(dst) and not a.forzar:
            with lock:
                hechos.append((src, dst, mov, "existia"))
            cola.task_done()
            continue
        t0 = time.time()
        cmd = [PY, os.path.join(BASE, "camara_post.py"), src, dst,
               "--mov", mov, "--wd", str(a.wd), "--hd", str(a.hd)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        seg = round(time.time() - t0, 1)
        estado = "ok" if r.returncode == 0 and os.path.isfile(dst) else f"error {r.returncode}"
        with lock, open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %T')} w{n} {estado} {seg}s {os.path.basename(dst)}"
                    f"{(chr(10) + r.stderr[-400:]) if estado != 'ok' else ''}\n")
            hechos.append((src, dst, mov, f"{estado} {seg}s"))
            print(f"  w{n} {estado:12s} {seg:6.1f}s  {mov:10s} {os.path.basename(dst)[:60]}")
        cola.task_done()


hilos = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(a.workers)]
[h.start() for h in hilos]
[h.join() for h in hilos]

idx = os.path.join(DEST, "indice_post.csv")
with open(idx, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["original", "post", "movimiento", "resultado"])
    w.writerows(hechos)
ok = sum(1 for h in hechos if h[3].startswith("ok") or h[3] == "existia")
print(f"\nlisto: {ok}/{len(tareas)} · indice {idx}")
