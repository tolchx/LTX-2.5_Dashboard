"""Prueba variantes de LTX para que respete la camara fija, sobre la misma imagen.

Corre variantes en serie (una por vez, respetando la cola del dashboard), guarda
cada mp4 con su etiqueta y arma la grilla de 6 frames para comparar a ojo.

Uso: python test_camara_ltx.py
"""
import json
import os
import subprocess
import time
import urllib.request

API = "http://127.0.0.1:8899"
SAL = r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/camf"
BASE = json.load(open(r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/test_mm.json", encoding="utf-8"))

VARIANTES = [
    # nombre,        overrides del payload
    ("v1_i2v100",    {"i2v_strength": 1.00}),
    ("v2_cfg16",     {"i2v_strength": 0.85, "video_cfg": 1.60}),
    ("v3_cfg20",     {"i2v_strength": 1.00, "video_cfg": 2.00}),
]


def req(path, data=None, method="GET", timeout=120):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(API + path, data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read().decode() or "{}")


def esperar(jid, limite=900):
    t0 = time.time()
    while time.time() - t0 < limite:
        j = next((x for x in req("/api/jobs?limit=6")["items"] if x["id"] == jid), None)
        if j and j["status"] in ("success", "failed", "error", "cancelled"):
            return j
        time.sleep(20)
    return None


def grilla(video, etiqueta):
    out = os.path.join(SAL, f"ltx_{etiqueta}.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf",
                    "select='eq(n\\,0)+eq(n\\,48)+eq(n\\,96)+eq(n\\,144)+eq(n\\,192)+eq(n\\,236)',"
                    "scale=480:-1,tile=3x2", "-frames:v", "1", out], check=True)
    return out


res = []
for nombre, ov in VARIANTES:
    payload = {
        "task": "i2v",
        "model_engine": "ltx25",
        "image": BASE["image"],
        "prompt": BASE["prompt"],
        "negative_prompt": BASE["negative"],
        "preset": BASE["preset"],
        "aspect": "auto",
        "duration": BASE["duration"],
        "fps": BASE["fps"],
        "two_stage": False,
        "vae_mode": "diff",
        "i2v_strength": ov.get("i2v_strength", 0.85),
        "video_cfg": ov.get("video_cfg", 1.0),
        "stage2_strength": 1.0,
        "include_audio": False,
        "chunks": 1,
        "crossfade": 0.25,
        "seed": BASE["seed"],
        "crf": 17,
    }
    j = req("/api/generate", payload, method="POST")
    jid = j.get("id")
    print(f"{time.strftime('%H:%M:%S')} {nombre}: job {jid[:8]} (cfg {payload['video_cfg']}, "
          f"i2v {payload['i2v_strength']})", flush=True)
    fin = esperar(jid)
    if not fin:
        print(f"  {nombre}: no termino en 15 min", flush=True)
        continue
    print(f"  {nombre}: {fin['status']} | {(fin.get('error') or '')[:120]}", flush=True)
    outs = fin.get("outputs") or []
    if outs:
        src = outs[0]
        if src.startswith("/"):
            src = "http://127.0.0.1:8899" + src
        dst = os.path.join(SAL, f"ltx_{nombre}.mp4")
        try:
            urllib.request.urlretrieve(src, dst)
        except Exception as e:
            print("  no pude bajar el mp4:", e, flush=True)
            continue
        print("  mp4:", dst, flush=True)
        print("  grilla:", grilla(dst, nombre), flush=True)
        res.append(nombre)

print("\nvariantes listas:", res, flush=True)
