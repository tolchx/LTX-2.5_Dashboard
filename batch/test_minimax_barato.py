"""MiniMax H3 'barato': 10 s, 960x544, 12 pasos. Mide tiempos por etapa y deja evidencia.

Misma imagen, prompt y seed que la prueba anterior, para comparar contra:
  - LTX 1280x704 10s  -> 4,4 min
  - MiniMax 1280x704 10s 25 pasos -> 70 min
"""
import json
import os
import subprocess
import time
import urllib.request

API = "http://127.0.0.1:8899"
SAL = r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/camf"
BASE = json.load(open(r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/test_mm.json", encoding="utf-8"))
RES = os.path.join(SAL, "minimax_barato.json")


def req(path, data=None, method="GET", timeout=120):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(API + path, data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read().decode() or "{}")


payload = {
    "task": "i2v",
    "model_engine": "minimax_h3",
    "image": BASE["image"],
    "prompt": BASE["prompt"],
    "negative_prompt": BASE["negative"],
    "preset": "960x544",
    "aspect": "auto",
    "duration": 10.0,
    "fps": 24,
    "two_stage": False,
    "vae_mode": "diff",
    "i2v_strength": 0.85,
    "stage2_strength": 1.0,
    "include_audio": False,
    "chunks": 1,
    "crossfade": 0.25,
    "seed": BASE["seed"],
    "steps": 12,
    "crf": 17,
}

t_envio = time.time()
job = req("/api/generate", payload, method="POST")
jid = job["id"]
print(f"{time.strftime('%H:%M:%S')} enviado {jid[:8]} | {job.get('width')}x{job.get('height')} | "
      f"steps {job.get('steps')} | {job.get('duration_real')}s", flush=True)

etapas = []
ult = None
t0 = time.time()
while time.time() - t0 < 3600:
    j = next((x for x in req("/api/jobs?limit=6")["items"] if x["id"] == jid), None)
    if j is None:
        print("job perdido", flush=True)
        break
    est, stage = j.get("status"), (j.get("stage") or "")
    clave = stage.split(" (")[0]
    if clave != ult:
        etapas.append({"t": round(time.time() - t_envio, 1), "hora": time.strftime("%H:%M:%S"), "etapa": stage})
        print(f"{time.strftime('%H:%M:%S')}  +{round(time.time()-t_envio)/60:5.1f} min  {stage} {j.get('progress')}%", flush=True)
        ult = clave
    if est in ("success", "failed", "error", "cancelled"):
        total = round(time.time() - t_envio, 1)
        print(f"\nFIN: {est} en {total/60:.1f} min", flush=True)
        out = {"job_id": jid, "status": est, "total_s": total, "total_min": round(total / 60, 1),
               "resolucion": f"{j.get('width')}x{j.get('height')}", "steps": j.get("steps"),
               "duracion": j.get("duration_real"), "modelo": j.get("model_engine"),
               "error": j.get("error"), "outputs": j.get("outputs"), "etapas": etapas}
        json.dump(out, open(RES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        outs = j.get("outputs") or []
        if outs:
            src = outs[0]
            if src.startswith("/"):
                src = "http://127.0.0.1:8899" + src
            dst = os.path.join(SAL, "minimax_barato.mp4")
            try:
                urllib.request.urlretrieve(src, dst)
                print("mp4:", dst, round(os.path.getsize(dst) / 1e6, 2), "MB", flush=True)
                g = os.path.join(SAL, "minimax_barato_grilla.jpg")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", dst, "-vf",
                                "select='eq(n\\,0)+eq(n\\,48)+eq(n\\,96)+eq(n\\,144)+eq(n\\,192)+eq(n\\,236)',"
                                "scale=480:-1,tile=3x2", "-frames:v", "1", g], check=True)
                a = os.path.join(SAL, "mb_a.png"); b = os.path.join(SAL, "mb_b.png")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.04", "-i", dst, "-frames:v", "1", a], check=True)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "9.85", "-i", dst, "-frames:v", "1", b], check=True)
                bl = os.path.join(SAL, "minimax_barato_blend.jpg")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a, "-i", b, "-filter_complex",
                                "[0]format=rgb24[x];[1]format=rgb24[y];[x][y]blend=all_mode=average,"
                                "eq=contrast=1.9:brightness=-0.05,scale=900:-1", bl], check=True)
                print("grilla:", g, flush=True)
                print("blend:", bl, flush=True)
            except Exception as e:
                print("no pude bajar/analizar:", e, flush=True)
        break
    time.sleep(20)
