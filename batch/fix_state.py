import json, os

ST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
st = json.load(open(ST, encoding="utf-8"))
n = 0
for it in st["items"]:
    base = os.path.basename(it.get("image") or "")
    if it["status"] == "error" and not it.get("out"):
        it["status"] = "pendiente"
        it["attempts"] = 0
        it["error"] = None
        n += 1
        print("re-encolado (error de infra):", base)
    elif it["status"] == "corriendo" and not it.get("job_id"):
        it["status"] = "pendiente"
        it["attempts"] = 0
        n += 1
        print("huerfano -> pendiente:", base)
with open(ST, "w", encoding="utf-8") as f:
    json.dump(st, f, ensure_ascii=False, indent=1)
print("ajustes:", n)
