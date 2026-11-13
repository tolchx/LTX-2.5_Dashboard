"""Quita el zoom / push-in de un clip ya renderizado (sin tocar el modelo).

Estima, frame a frame, la transformacion euclidiana (escala + desplazamiento)
que lleva cada frame al primero, con ECC de OpenCV. Despues aplica la inversa y
listo: la camara queda tan quieta como el frame 0.

Uso: python dezoom2.py <entrada.mp4> [salida.mp4] [--crop 0.97]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
CROP = 1.0
for a in sys.argv[1:]:
    if a.startswith("--crop="):
        CROP = float(a.split("=")[1])

ENT = ARGS[0]
SAL = ARGS[1] if len(ARGS) > 1 else ENT.replace(".mp4", "__sinzoom.mp4")
ANCHO = 640


def probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height,r_frame_rate",
                          "-of", "json", p], capture_output=True, text=True).stdout
    d = json.loads(out)["streams"][0]
    n, den = d["r_frame_rate"].split("/")
    return int(d["width"]), int(d["height"]), float(n) / float(den)


W, H, FPS = probe(ENT)
tmp = tempfile.mkdtemp(prefix="dz2_")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", ENT, "-vf", f"scale={ANCHO}:-2",
                os.path.join(tmp, "%04d.png")], check=True)
frames = sorted(os.listdir(tmp))
N = len(frames)
print(f"{W}x{H} @ {FPS:.2f} fps · {N} frames · analisis a {ANCHO}px")

ref = cv2.imread(os.path.join(tmp, frames[0]), cv2.IMREAD_GRAYSCALE).astype(np.float32)
ref /= 255.0
h, w = ref.shape
escalas, trasl = [], []
crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)

for i, f in enumerate(frames):
    cur = cv2.imread(os.path.join(tmp, f), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        _cc, warp = cv2.findTransformECC(ref, cur, warp, cv2.MOTION_AFFINE, crit, None, 5)
    except cv2.error:
        if escalas:
            warp[0, 0], warp[0, 1] = escalas[-1], 0.0
            warp[1, 0], warp[1, 1] = 0.0, escalas[-1]
            warp[0, 2], warp[1, 2] = 0.0, 0.0
    s = float(np.sqrt(abs(np.linalg.det(warp[:, :2]))))
    escalas.append(s)
    trasl.append((float(warp[0, 2]), float(warp[1, 2])))
    if i % 40 == 0:
        print(f"  frame {i:4d}: escala {s:.4f}  desplaz {warp[0,2]:+.1f},{warp[1,2]:+.1f}")

esc = np.array(escalas, dtype=np.float64)
# suavizado: ECC puede saltar en frames oscuros
k = 9
esc = np.convolve(np.pad(esc, (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")[:N]
print(f"\nescala: inicio {esc[0]:.4f} · fin {esc[-1]:.4f} · min {esc.min():.4f} · max {esc.max():.4f}")
print(f"zoom a corregir: {(esc[-1]/esc[0]-1)*100:+.1f}%")

# recorte extra opcional para no dejar bordes negros si el warp agranda
s_min = float(esc.min())
sal = os.path.join(tmp, "out")
os.makedirs(sal)
frames_out = []
for i, f in enumerate(frames):
    img = cv2.imread(os.path.join(tmp, f), cv2.IMREAD_COLOR)
    s = float(esc[i])
    # llevar el frame actual al encuadre del primero: escalar por 1/s
    M = np.array([[1.0 / s, 0, (w / 2) * (1 - 1.0 / s)],
                  [0, 1.0 / s, (h / 2) * (1 - 1.0 / s)]], dtype=np.float32)
    out = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LANCZOS4,
                         borderMode=cv2.BORDER_REPLICATE)
    if CROP < 1.0:
        cw, ch = int(w * CROP), int(h * CROP)
        x0, y0 = (w - cw) // 2, (h - ch) // 2
        out = cv2.resize(out[y0:y0 + ch, x0:x0 + cw], (w, h), interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(os.path.join(sal, f), out)
    if i % 60 == 0:
        print(f"  escribiendo {i}/{N}")

subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", os.path.join(sal, "%04d.png"),
                "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", SAL], check=True)
print("listo:", SAL)
shutil.rmtree(tmp, ignore_errors=True)
