"""Repara los 2 items del primer test de grupo (crash en dur_s despues del move)."""
import json
import os
import shutil
import sys
import time

BATCH = r"C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch"
sys.path.insert(0, r"C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard")
sys.path.insert(0, BATCH)
os.environ.setdefault("LTXB_STATE", os.path.join(BATCH, "state_ltx_cam.json"))
import batch as B  # noqa: E402

st = B.cargar_state()
items = st["items"]
grupo = [i for i in items if i["status"] == "corriendo" and "#" in str(i.get("job_id") or "")]
# los del grupo quedaron 'pendiente' tras el crash: los ubico por shot/imagen
cand = [i for i in items if i["status"] == "pendiente" and "s03_t1" in i["shot"]]
print("candidatos:", [(i["image"][-40:], i["status"]) for i in cand])

fuentes = {
    "Bamboo_tunnel_receding_into_dark": os.path.join(B.destino(cand[0]) if cand else "", ""),
}
# 1) item con la "A" (receding): el mp4 ya fue movido a su destino
for it in cand:
    dst = B.destino(it)
    ok = os.path.isfile(dst) and os.path.getsize(dst) > 20000
    print(f"{'DESTINO OK' if ok else 'sin destino'} {os.path.basename(dst)[:52]}")
    if ok:
        info, err = B.ffprobe_ok(dst)
        print("   ", info, err)
        if info and info.get("dur", 0) > 5:
            it["status"] = "hecho"
            it["out"] = dst
            it["dur_s"] = None
            it["finished"] = B.now()
            it.pop("job_id", None)
            B.registrar("grupo_reparado", "OK", f"movido antes del crash: {info}", item=it["id"])

# 2) el otro clip sigue en el output de ComfyUI
src = r"D:\ComfyUI\output\grupo\054934\c02_00001_.mp4"
restantes = [i for i in cand if i["status"] == "pendiente"]
if os.path.isfile(src) and restantes:
    it = restantes[0]
    info, err = B.ffprobe_ok(src)
    print("pendiente en comfy:", info, err, os.path.basename(it["image"])[:40])
    if info and info.get("dur", 0) > 5:
        dst = B.destino(it)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.move(src, dst)
        except Exception:
            shutil.copy2(src, dst)
        it["status"] = "hecho"
        it["out"] = dst
        it["dur_s"] = None
        it["finished"] = B.now()
        it.pop("job_id", None)
        B.registrar("grupo_reparado", "OK", f"movido a mano: {info}", item=it["id"])
        print("   movido ->", os.path.basename(dst))

# 3) liberar el job zombie del dashboard
for it in items:
    if it["status"] == "corriendo" and "#" not in str(it.get("job_id") or ""):
        jid = it.get("job_id")
        import urllib.request
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:8899/api/jobs/{jid}/cancel", method="POST"), timeout=15).read()
        except Exception as e:
            print("cancel:", e)
        it["status"] = "pendiente"
        it.pop("job_id", None)
        B.registrar("grupo_zombie_liberado", "HALLAZGO", "job en 'En cola' del dashboard", item=it["id"])
        print("zombie liberado:", os.path.basename(it["image"])[:40])

B.guardar_state(st)
from collections import Counter
print(Counter(i["status"] for i in B.cargar_state()["items"]))
