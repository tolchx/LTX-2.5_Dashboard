"""Encola y mide UN clip de MiniMax con la config barata (960x544, 12 pasos),
usando la imagen y el prompt del primer item pendiente del plan (escena 02, rol A).
Uso: python correr_barato.py [preset] [steps]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

API = "http://127.0.0.1:8899"
BATCH = os.path.dirname(os.path.abspath(__file__))
SAL = r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/camf"
PRESET = sys.argv[1] if len(sys.argv) > 1 else "960x544"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 12
DURACION = float(sys.argv[3]) if len(sys.argv) > 3 else None


def req(path, data=None, method="GET", timeout=120):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(API + path, data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read().decode() or "{}")


st = json.load(open(os.path.join(BATCH, "state.json"), encoding="utf-8"))
it = next(i for i in st["items"] if i["status"] == "pendiente")
print(f"item: {it['scene']} | {it['shot']} | rol {it['role']}", flush=True)
print(f"imagen: {os.path.basename(it['image'])}", flush=True)

payload = {
    "task": "i2v", "model_engine": "minimax_h3",
    "image": it["image"], "prompt": it["prompt"], "negative_prompt": it["negative"],
    "preset": PRESET, "aspect": "auto", "duration": DURACION or it.get("duration") or 10.0,
    "fps": it.get("fps") or 24, "two_stage": False, "vae_mode": "diff",
    "i2v_strength": 0.85, "stage2_strength": 1.0, "include_audio": False,
    "chunks": 1, "crossfade": 0.25, "seed": it.get("seed") or 777000,
    "steps": STEPS, "crf": 17,
}
t0 = time.time()
job = req("/api/generate", payload, method="POST")
jid = job["id"]
print(f"{time.strftime('%H:%M:%S')} encolado {jid[:8]} | {job.get('width')}x{job.get('height')} "
      f"| steps {job.get('steps')} | {job.get('duration_real')}s", flush=True)

etapas, ult = [], None
while time.time() - t0 < 7200:
    j = next((x for x in req("/api/jobs?limit=8")["items"] if x["id"] == jid), None)
    if j is None:
        print("job perdido", flush=True)
        break
    stage = j.get("stage") or ""
    clave = stage.split(" (")[0]
    if clave != ult or True:
        print(f"{time.strftime('%H:%M:%S')}  +{round(time.time()-t0)/60:5.1f}  {stage} {j.get('progress')}%", flush=True)
        if clave != ult:
            etapas.append({"hora": time.strftime("%H:%M:%S"), "min": round((time.time() - t0) / 60, 1), "etapa": stage})
            ult = clave
    if j["status"] in ("success", "failed", "error", "cancelled"):
        total = round((time.time() - t0) / 60, 1)
        print(f"\nFIN {j['status']} en {total} min", flush=True)
        out = {"job_id": jid, "status": j["status"], "preset": PRESET, "steps": STEPS,
               "total_min": total, "etapas": etapas, "error": j.get("error"), "outputs": j.get("outputs")}
        outs = j.get("outputs") or []
        if outs:
            src = outs[0] if outs[0].startswith("http") else "http://127.0.0.1:8899" + outs[0]
            dst = os.path.join(SAL, f"barato_{PRESET}.mp4")
            try:
                urllib.request.urlretrieve(src, dst)
                print("mp4:", dst, round(os.path.getsize(dst) / 1e6, 2), "MB", flush=True)
                g = os.path.join(SAL, f"barato_{PRESET}_grilla.jpg")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", dst, "-vf",
                                "select='eq(n\\,0)+eq(n\\,48)+eq(n\\,96)+eq(n\\,144)+eq(n\\,192)+eq(n\\,236)',"
                                "scale=480:-1,tile=3x2", "-frames:v", "1", g], check=True)
                a = os.path.join(SAL, "ba_a.png"); b = os.path.join(SAL, "ba_b.png")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.04", "-i", dst, "-frames:v", "1", a], check=True)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "9.85", "-i", dst, "-frames:v", "1", b], check=True)
                bl = os.path.join(SAL, f"barato_{PRESET}_blend.jpg")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a, "-i", b, "-filter_complex",
                                "[0]format=rgb24[x];[1]format=rgb24[y];[x][y]blend=all_mode=average,"
                                "eq=contrast=1.9:brightness=-0.05,scale=900:-1", bl], check=True)
                out["grilla"] = g; out["blend"] = bl
                print("grilla:", g, flush=True); print("blend:", bl, flush=True)
            except Exception as e:
                print("no pude bajar:", e, flush=True)
        json.dump(out, open(os.path.join(SAL, "correr_barato.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        break
    time.sleep(30)
