"""Prueba 'barata' con LA MISMA imagen y EL MISMO prompt del clip 1280x704/25 pasos
que se esta renderizando: 960x544 y 12 pasos.

El job se encola ya, asi arranca primero que el resto del plan cuando termine el actual.
Al terminar mide tiempos y deja grilla + blend para comparar la camara.

Uso: python test_barato_misma_imagen.py
"""
import json
import os
import subprocess
import time
import urllib.request

API = "http://127.0.0.1:8899"
SAL = r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/camf"
RES = os.path.join(SAL, "test_barato.json")


def req(path, data=None, method="GET", timeout=120):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(API + path, data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read().decode() or "{}")


jobs = req("/api/jobs?limit=6")["items"]
ref = next((j for j in jobs if j["status"] == "running"), None)
if ref is None:
    print("no hay job corriendo; uso el ultimo de referencia", flush=True)
    ref = jobs[0]
print(f"referencia: {ref['id'][:8]} {ref.get('width')}x{ref.get('height')} steps {ref.get('steps')}", flush=True)
print(f"imagen: {os.path.basename(ref.get('image') or '')}", flush=True)

payload = {
    "task": "i2v",
    "model_engine": "minimax_h3",
    "image": ref["image"],
    "prompt": ref["prompt"],
    "negative_prompt": ref.get("negative_prompt") or "",
    "preset": "960x544",
    "aspect": "auto",
    "duration": ref.get("duration") or 10.0,
    "fps": ref.get("fps") or 24,
    "two_stage": False,
    "vae_mode": "diff",
    "i2v_strength": 0.85,
    "stage2_strength": 1.0,
    "include_audio": False,
    "chunks": 1,
    "crossfade": 0.25,
    "seed": ref.get("seed") or 777000,
    "steps": 12,
    "crf": 17,
}
job = req("/api/generate", payload, method="POST")
jid = job["id"]
t_envio = time.time()
print(f"{time.strftime('%H:%M:%S')} encolado barato: {jid[:8]} | {job.get('width')}x{job.get('height')} "
      f"| steps {job.get('steps')} | ref {ref['id'][:8]}", flush=True)

etapas, ult = [], None
while time.time() - t_envio < 12000:
    j = next((x for x in req("/api/jobs?limit=8")["items"] if x["id"] == jid), None)
    if j is None:
        print("job perdido", flush=True)
        break
    stage = j.get("stage") or ""
    clave = stage.split(" (")[0]
    if clave != ult:
        etapas.append({"hora": time.strftime("%H:%M:%S"), "min": round((time.time() - t_envio) / 60, 1),
                       "etapa": stage})
        print(f"{time.strftime('%H:%M:%S')}  +{round(time.time()-t_envio)/60:5.1f} min  {stage} {j.get('progress')}%", flush=True)
        ult = clave
    if j["status"] in ("success", "failed", "error", "cancelled"):
        total = round(time.time() - t_envio, 1)
        out = {"job_id": jid, "ref_job": ref["id"], "status": j["status"],
               "config": "960x544_12pasos", "total_min": round(total / 60, 1),
               "etapas": etapas, "error": j.get("error"), "outputs": j.get("outputs")}
        print(f"\nFIN {j['status']} en {total/60:.1f} min", flush=True)
        outs = j.get("outputs") or []
        if outs:
            src = outs[0] if outs[0].startswith("http") else "http://127.0.0.1:8899" + outs[0]
            dst = os.path.join(SAL, "barato_960.jpg.mp4")
            try:
                urllib.request.urlretrieve(src, dst)
                print("mp4:", dst, round(os.path.getsize(dst) / 1e6, 2), "MB", flush=True)
                g = os.path.join(SAL, "barato_960_grilla.jpg")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", dst, "-vf",
                                "select='eq(n\\,0)+eq(n\\,48)+eq(n\\,96)+eq(n\\,144)+eq(n\\,192)+eq(n\\,236)',"
                                "scale=480:-1,tile=3x2", "-frames:v", "1", g], check=True)
                a = os.path.join(SAL, "b_a.png"); b = os.path.join(SAL, "b_b.png")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.04", "-i", dst, "-frames:v", "1", a], check=True)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "9.85", "-i", dst, "-frames:v", "1", b], check=True)
                bl = os.path.join(SAL, "barato_960_blend.jpg")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a, "-i", b, "-filter_complex",
                                "[0]format=rgb24[x];[1]format=rgb24[y];[x][y]blend=all_mode=average,"
                                "eq=contrast=1.9:brightness=-0.05,scale=900:-1", bl], check=True)
                out["grilla"] = g; out["blend"] = bl
                print("grilla:", g, flush=True)
                print("blend:", bl, flush=True)
            except Exception as e:
                print("no pude bajar/analizar:", e, flush=True)
        json.dump(out, open(RES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        break
    time.sleep(20)
