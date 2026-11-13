"""Espera el fin del job MiniMax, localiza el MP4 y saca la evidencia de camara
(grilla de 6 frames + superposicion primer/ultimo frame) para comparar con el de LTX.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.request

API = "http://127.0.0.1:8899"
JOB = "7c4064ad146e4bbb854bab99b2a46f7a"
SAL = r"C:/Users/Tolch/AppData/Local/hermes/cache/scratch/camf"
LTX = r"D:/LTX-2.5_Dashboard_outputs/batch/02 · ALTAR DE BAMBÚ/s02_t4 · Faroles/ltx25/Bamboo_altar_in_jungle_clearing_1c30f42e__ltx25.mp4"


def jobs():
    with urllib.request.urlopen(API + "/api/jobs?limit=5", timeout=30) as f:
        return json.loads(f.read().decode())["items"]


def grilla(video, salida, etiqueta):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf",
                    "select='eq(n\\,0)+eq(n\\,48)+eq(n\\,96)+eq(n\\,144)+eq(n\\,192)+eq(n\\,236)',"
                    "scale=560:-1,tile=3x2", "-frames:v", "1", salida], check=True)
    a = os.path.join(SAL, f"{etiqueta}_a.png")
    b = os.path.join(SAL, f"{etiqueta}_b.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.04", "-i", video, "-frames:v", "1", a], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "9.85", "-i", video, "-frames:v", "1", b], check=True)
    blend = os.path.join(SAL, f"{etiqueta}_blend.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a, "-i", b, "-filter_complex",
                    "[0]format=rgb24[x];[1]format=rgb24[y];[x][y]blend=all_mode=average,"
                    "eq=contrast=1.9:brightness=-0.05,scale=900:-1", blend], check=True)
    return salida, blend


t0 = time.time()
while time.time() - t0 < 3600:
    j = next((x for x in jobs() if x["id"] == JOB), None)
    if j is None:
        print("el job desaparecio del dashboard", flush=True)
        break
    if j["status"] in ("success", "failed", "error", "cancelled"):
        print(f"{time.strftime('%H:%M:%S')} FIN: {j['status']} | stage {j.get('stage')} | "
              f"{(time.time()-t0)/60:.1f} min", flush=True)
        print("outputs:", j.get("outputs"), flush=True)
        print("error:", (j.get("error") or "")[:300], flush=True)
        outs = j.get("outputs") or []
        if outs:
            src = outs[0]
            # el dashboard devuelve URL o ruta
            if src.startswith("http"):
                src = src.split("/media/")[-1]
                src = os.path.join(r"D:/LTX-2.5_Dashboard_outputs", src.replace("/", "\\"))
            dst = os.path.join(SAL, "minimax_faroles.mp4")
            try:
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                else:
                    urllib.request.urlretrieve(outs[0] if outs[0].startswith("http")
                                               else "http://127.0.0.1:8899" + outs[0], dst)
            except Exception as e:
                print("no pude copiar el mp4:", e, flush=True)
            if os.path.isfile(dst):
                print("mp4:", dst, round(os.path.getsize(dst) / 1e6, 2), "MB", flush=True)
                for p in grilla(dst, os.path.join(SAL, "minimax_grilla.jpg"), "minimax"):
                    print("evidencia:", p, flush=True)
                print("ltx de referencia:", LTX, flush=True)
        break
    print(f"{time.strftime('%H:%M:%S')} {j.get('stage')} {j.get('progress')}%", flush=True)
    time.sleep(45)
