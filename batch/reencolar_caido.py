"""Reencola el item que quedo 'corriendo' cuando ComfyUI se cayo a mitad del render.
Cancela el job huerfano en el dashboard y devuelve el item del state a pendiente."""
import json, os, time, urllib.request

BASE = r"C:\Users\Tolch\Documents\AI_Code\LTX-2.5_Dashboard"
API = "http://127.0.0.1:8899"
STATE = os.path.join(BASE, "batch", "state.json")


def req(path, method="GET"):
    r = urllib.request.Request(API + path, method=method)
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


h = req("/api/health")
print("comfy online:", h["comfy"].get("online"))

jobs = req("/api/jobs")["items"]
vivos = [j for j in jobs if j.get("status") in ("running", "pending")]
print("jobs activos:", [(j["id"][:8], j["status"]) for j in vivos])
for j in vivos:
    img = (j.get("image") or "").lower()
    if "nomade_visuals" not in img.replace("/", "\\"):
        continue
    print("cancelando huerfano", j["id"][:8])
    print(" ", req("/api/jobs/%s/cancel" % j["id"], "POST"))

st = json.load(open(STATE, encoding="utf-8"))
n = 0
for it in st["items"]:
    if it["status"] == "corriendo":
        print("reencolando:", os.path.basename(it["image"]))
        it["status"] = "pendiente"
        it["job_id"] = None
        it["ultimo_prog"] = 0
        it["ultimo_stage"] = None
        it["ultimo_cambio"] = time.time()
        it["error"] = None
        n += 1
if n:
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("items reseteados:", n)
else:
    print("no habia items corriendo")

import collections
print(collections.Counter(i["status"] for i in st["items"]))
