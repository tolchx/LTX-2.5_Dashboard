"""A/B de calidad sobre la MISMA imagen (s01_t6 · Bamboo_portal_in_tropical_temple).

Sospecha: la deformacion de la estructura rigida (el triangulo de bambu se dobla y
se disuelve) viene de los 12 pasos; la segunda sospecha es 960x544.

Corre en serie, con el mismo seed y prompt:
  1) 960x544  · 25 pasos   -> aisla pasos
  2) 1280x704 · 25 pasos   -> config probada (clip de los faroles salio limpio)
Deja grilla de 6 frames por variante.
"""
import json
import os
import subprocess
import time
import urllib.request

API = "http://127.0.0.1:8899"
BATCH = r"C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch"
SAL = r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/camf"

VARIANTES = [("960x544_25p", "960x544", 25), ("1280x704_25p", "1280x704", 25)]


def req(path, data=None, method="GET", timeout=120):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(API + path, data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read().decode() or "{}")


st = json.load(open(os.path.join(BATCH, "state.json"), encoding="utf-8"))
it = next(i for i in st["items"] if "03e62d7f" in i["image"])
print("imagen:", os.path.basename(it["image"]), flush=True)

for nombre, preset, steps in VARIANTES:
    payload = {
        "task": "i2v", "model_engine": "minimax_h3", "image": it["image"],
        "prompt": it["prompt"], "negative_prompt": it["negative"],
        "preset": preset, "aspect": "auto", "duration": 10.0, "fps": 24,
        "two_stage": False, "vae_mode": "diff", "i2v_strength": 0.85,
        "stage2_strength": 1.0, "include_audio": False, "chunks": 1,
        "crossfade": 0.25, "seed": it.get("seed") or 777000, "steps": steps, "crf": 17,
    }
    t0 = time.time()
    j = req("/api/generate", payload, method="POST")
    jid = j["id"]
    print(f"\n{time.strftime('%H:%M:%S')} {nombre}: job {jid[:8]} | {j.get('width')}x{j.get('height')} "
          f"| steps {j.get('steps')}", flush=True)
    ult = None
    while time.time() - t0 < 5400:
        cur = next((x for x in req("/api/jobs?limit=8")["items"] if x["id"] == jid), None)
        if cur is None:
            print("  job perdido", flush=True)
            break
        etapa = (cur.get("stage") or "").split(" (")[0]
        if etapa != ult:
            print(f"  {time.strftime('%H:%M:%S')} +{(time.time()-t0)/60:5.1f} min  {cur.get('stage')} {cur.get('progress')}%", flush=True)
            ult = etapa
        if cur["status"] in ("success", "failed", "error", "cancelled"):
            dt = (time.time() - t0) / 60
            print(f"  FIN {cur['status']} en {dt:.1f} min | err {str(cur.get('error'))[:100]}", flush=True)
            outs = cur.get("outputs") or []
            if outs:
                src = outs[0]
                if not src.startswith("http"):
                    src = ("http://127.0.0.1:8899" + src) if src.startswith("/") else src
                dst = os.path.join(SAL, f"calidad_{nombre}.mp4")
                try:
                    if src.startswith("http"):
                        urllib.request.urlretrieve(src, dst)
                    else:
                        subprocess.run(["cp", src, dst], check=True)
                    g = os.path.join(SAL, f"calidad_{nombre}_grilla.jpg")
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", dst, "-vf",
                                    "select='eq(n\\,0)+eq(n\\,48)+eq(n\\,96)+eq(n\\,144)+eq(n\\,192)+eq(n\\,236)',"
                                    "scale=520:-1,tile=3x2", "-frames:v", "1", g], check=True)
                    print("  grilla:", g, flush=True)
                except Exception as e:
                    print("  no pude bajar/analizar:", e, flush=True)
            break
        time.sleep(30)
