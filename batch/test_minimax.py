"""Prueba MiniMax H3 con el mismo prompt/imagen que el clip de LTX que se movio.

Espera a que no haya render corriendo, manda UN job con model_engine minimax_h3
y hace seguimiento hasta que termina (o falla). Escribe el resultado en
scratch/test_mm_resultado.json.
"""
import json
import time
import urllib.request

API = "http://127.0.0.1:8899"
CFG = r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/test_mm.json"
RES = r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/test_mm_resultado.json"


def req(path, data=None, method="GET", timeout=60):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(API + path, data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read().decode() or "{}")


def running():
    return [j for j in req("/api/jobs")["items"] if j["status"] in ("running", "pending")]


# 1. esperar a que el batch quede quieto (PAUSA ya esta puesta)
t0 = time.time()
while running() and time.time() - t0 < 900:
    r = running()[0]
    print(f"{time.strftime('%H:%M:%S')} esperando fin de {r['id'][:8]} "
          f"{r.get('stage')} {r.get('progress')}%", flush=True)
    time.sleep(30)
if running():
    print("ABORTO: sigue habiendo un render despues de 15 min")
    raise SystemExit(1)

cfg = json.load(open(CFG, encoding="utf-8"))
payload = {
    "task": "i2v",
    "model_engine": "minimax_h3",
    "image": cfg["image"],
    "prompt": cfg["prompt"],
    "negative_prompt": cfg["negative"],
    "preset": cfg["preset"],
    "aspect": "auto",
    "duration": cfg["duration"],
    "fps": cfg["fps"],
    "two_stage": False,
    "vae_mode": "diff",
    "i2v_strength": 0.85,
    "stage2_strength": 1.0,
    "include_audio": False,
    "chunks": 1,
    "crossfade": 0.25,
    "seed": cfg["seed"],
    "crf": 17,
}
job = req("/api/generate", payload, method="POST", timeout=120)
jid = job.get("id") or job.get("job_id")
print(f"{time.strftime('%H:%M:%S')} job enviado: {jid} ({job.get('model_engine')})", flush=True)
out = {"job_id": jid, "engine": "minimax_h3", "inicio": time.strftime("%H:%M:%S")}

# 2. seguimiento
ult = None
t0 = time.time()
while time.time() - t0 < 3000:
    j = next((x for x in req("/api/jobs")["items"] if x["id"] == jid), None)
    if j is None:
        print("el job desaparecio del dashboard", flush=True)
        break
    est = j.get("status")
    linea = f"{time.strftime('%H:%M:%S')} {est} {j.get('stage')} {j.get('progress')}%"
    if linea.split(" ", 1)[1] != ult:
        print(linea, flush=True)
        ult = linea.split(" ", 1)[1]
    if est in ("success", "failed", "error", "cancelled"):
        out.update({"status": est, "stage": j.get("stage"), "error": j.get("error"),
                    "outputs": j.get("outputs"), "fin": time.strftime("%H:%M:%S"),
                    "seg": round(time.time() - t0, 1)})
        break
    time.sleep(20)

json.dump(out, open(RES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1), flush=True)
