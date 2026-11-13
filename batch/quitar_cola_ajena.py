"""Baja de la cola los jobs ajenos (catalogo Gio) y guarda sus payloads para re-encolar despues.
Solo actua sobre jobs cuya imagen NO vive en Nomade_Visuals."""
import json, os, time, urllib.request

BASE = r"C:\Users\Tolch\Documents\AI_Code\LTX-2.5_Dashboard"
API = "http://127.0.0.1:8899"
GUARDADO = os.path.join(BASE, "batch", "cola_gio_guardada.json")


def req(path, method="GET"):
    r = urllib.request.Request(API + path, method=method)
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


jobs = req("/api/jobs")["items"]
print("jobs totales:", len(jobs))
ajenos = []
mios = []
for j in jobs:
    img = (j.get("image") or "").replace("/", "\\").lower()
    if "nomade_visuals" in img:
        mios.append(j)
    elif j.get("status") in ("pending", "running"):
        ajenos.append(j)

print("NOMADE activos:", len(mios), [(j["status"], j["id"][:8]) for j in mios])
print("AJENOS activos:", len(ajenos))

prev = []
if os.path.exists(GUARDADO):
    try:
        prev = json.load(open(GUARDADO, encoding="utf-8"))
    except Exception:
        prev = []
prev_ids = {p.get("id") for p in prev}

for j in ajenos:
    if j["id"] not in prev_ids:
        prev.append({
            "id": j["id"], "image": j.get("image"), "prompt": j.get("prompt"),
            "duration": j.get("duration"), "fps": j.get("fps"), "preset": j.get("preset"),
            "two_stage": j.get("two_stage"), "model_engine": j.get("model_engine"),
            "category": j.get("category"), "guardado": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
json.dump(prev, open(GUARDADO, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("payloads guardados:", len(prev), "->", GUARDADO)

for j in ajenos:
    try:
        r = req("/api/jobs/%s/cancel" % j["id"], "POST")
        print("cancelado", j["id"][:8], j["status"], r)
    except Exception as e:
        print("ERROR cancelando", j["id"][:8], e)

print("--- despues ---")
jobs2 = req("/api/jobs")["items"]
import collections
print(collections.Counter(j["status"] for j in jobs2))
for j in jobs2:
    if j.get("status") in ("pending", "running"):
        print(" activo:", j["status"], j["id"][:8], os.path.basename((j.get("image") or "")))
