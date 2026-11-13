"""Cierra items 'corriendo' cuyo mp4 ya esta en destino (idempotente)."""
import os
import sys

BATCH = r"C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch"
sys.path.insert(0, r"C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard")
sys.path.insert(0, BATCH)
os.environ.setdefault("LTXB_STATE", os.path.join(BATCH, "state_ltx_cam.json"))
import batch as B  # noqa: E402

st = B.cargar_state()
cambiados = 0
for it in st["items"]:
    if it["status"] != "corriendo":
        continue
    dst = B.destino(it)
    if not (os.path.isfile(dst) and os.path.getsize(dst) > 20000):
        print("sigue pendiente de render:", os.path.basename(it["image"])[:45])
        continue
    info, err = B.ffprobe_ok(dst)
    if not info or info.get("dur", 0) < float(it["duration"]) * 0.5:
        print("mp4 invalido:", info, err)
        continue
    it["status"] = "hecho"
    it["out"] = dst
    it["finished"] = B.now()
    it["job_id"] = None
    cambiados += 1
    B.registrar("grupo_cerrado_tarde", "OK", f"{info['w']}x{info['h']} {info['dur']:.1f}s",
                item=it["id"])
    print("hecho:", os.path.basename(dst)[:55], "|", info["dur"])
if cambiados:
    B.guardar_state(st)
from collections import Counter
print("cambiados:", cambiados, Counter(i["status"] for i in B.cargar_state()["items"]))
