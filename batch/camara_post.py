"""Camara en POST: estabiliza la deriva del modelo y reencuadra con el movimiento pedido.

Por que: la guia de ultimo frame (LTXVAddGuide) fija el movimiento pero le hace
inventar escena — medido a ojo sobre el clip de tilt: a los frames 150-200 el altar
desaparece y el modelo se inventa otra jungla. Sin guia el clip sale nitido y
coherente, pero el modelo mete un push-in de +3..8 % que es lo que hacia que todos
los clips se parecieran.

Solucion: generar sin guia (calidad original) y resolver la camara aca:
  1. se mide la deriva frame a frame con ECC afin incremental,
  2. se ajusta una curva suave (polinomio) — la deriva del modelo es lisa, el ruido no,
  3. se muestrea la ventana que pide el movimiento pedido (rampa lineal, velocidad
     constante) sobre la version estabilizada.
Si el render se hace a 1536x864 y la entrega es 1280x704, el margen (20 %) alcanza
para cancelar la deriva y para el paneo sin inventar un solo pixel.

Uso:
    python camara_post.py <entrada.mp4> <salida.mp4> --mov paneo-der
    python camara_post.py <in.mp4> <out.mp4> --mov estatica --k 1.18
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image

ANCHO_MEDICION = 640

# movimiento: (dx, dy) total en fraccion del ancho/alto ENTREGADO.
# dx>0 = la camara se corre a la derecha (el contenido se va a la izquierda).
MOVS = {
    "paneo-der": (0.040, 0.0),
    "paneo-izq": (-0.040, 0.0),
    "paneo-der-lento": (0.020, 0.0),
    "travelling-der": (0.045, 0.0),
    "travelling-izq": (-0.045, 0.0),
    "travelling-izq-lento": (-0.020, 0.0),
    "tilt-arriba": (0.0, -0.030),
    "tilt-abajo": (0.0, 0.030),
    "descenso": (0.0, 0.025),
    "arco-der": (0.030, -0.008),
    "arco-izq": (-0.030, -0.008),
    "estatica": (0.0, 0.0),
    "loop": (0.0, 0.0),
}


def probe(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height,r_frame_rate",
                          "-of", "json", p], capture_output=True, text=True).stdout
    d = json.loads(out)["streams"][0]
    n, dv = d["r_frame_rate"].split("/")
    return int(d["width"]), int(d["height"]), float(n) / float(dv)


def extraer(p, tmp):
    os.makedirs(tmp, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p,
                    os.path.join(tmp, "%05d.png")], check=True)
    return sorted(os.listdir(tmp))


def gris(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    h = int(round(img.shape[0] * ANCHO_MEDICION / img.shape[1]))
    g = cv2.resize(img, (ANCHO_MEDICION, h), interpolation=cv2.INTER_AREA)
    return g.astype(np.float32) / 255.0


def _gris8(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    h = int(round(img.shape[0] * ANCHO_MEDICION / img.shape[1]))
    return cv2.resize(img, (ANCHO_MEDICION, h), interpolation=cv2.INTER_AREA)


_ORB = cv2.ORB_create(nfeatures=3000, fastThreshold=8, edgeThreshold=15)
_BF = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)


def medir(rutas, min_pts=14):
    """Camera solve por features (ORB + RANSAC afin parcial: escala, rotacion, traslacion).

    Por que features y no ECC ni correlacion de fase: en estas tomas el humo y el bokeh
    dominan el gradiente y las dos tecnicas globales daban picos de 0.02 — o sea ruido.
    Los postes de bambu, los faroles y el macramé dan cientos de puntos repetibles.
    Devuelve, por frame, la matriz que aplicada con warpAffine al frame i lo deja en el
    encuadre del frame 0 (coordenadas de medicion).
    """
    ref = _gris8(rutas[0])
    kp0, des0 = _ORB.detectAndCompute(ref, None)
    cums = [np.eye(3)]
    detalle = [(1.0, 0.0, 0.0, len(kp0))]
    for r in rutas[1:]:
        cur = _gris8(r)
        kp, des = _ORB.detectAndCompute(cur, None)
        M = np.eye(3)
        inl = 0
        if des is not None and des0 is not None and len(kp) > 20:
            pares = _BF.match(des0, des)
            if len(pares) >= min_pts:
                src = np.float32([kp0[m.queryIdx].pt for m in pares]).reshape(-1, 1, 2)
                dst = np.float32([kp[m.trainIdx].pt for m in pares]).reshape(-1, 1, 2)
                A, mask = cv2.estimateAffinePartial2D(
                    src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0,
                    maxIters=4000, confidence=0.995)
                if A is not None:
                    # estimateAffinePartial2D devuelve ref->cur; warpAffine necesita
                    # el mapeo de coordenadas de SALIDA a pixeles del frame, o sea la
                    # inversa. Verificado: con A el residual era 25,2; con inv(A), 4,7.
                    M = np.linalg.inv(np.vstack([A, [0.0, 0.0, 1.0]]))
                    inl = int(mask.sum()) if mask is not None else 0
        cums.append(M)
        esc = float(np.sqrt(abs(np.linalg.det(M[:2, :2]))))
        detalle.append((esc, float(M[0, 2]), float(M[1, 2]), inl))
    return cums, detalle


def _mediana(y, k):
    """Filtro de mediana: mata los picos de RANSAC sin deformar la curva."""
    if k < 3:
        return y.copy()
    h = k // 2
    yp = np.pad(y, (h, h), mode="edge")
    return np.array([np.median(yp[i:i + k]) for i in range(len(y))])


def _media(y, k):
    """Media movil con borde replicado: no mueve los extremos."""
    if k < 2:
        return y.copy()
    h = k // 2
    yp = np.pad(y, (h, h), mode="edge")
    ker = np.ones(k) / k
    return np.convolve(yp, ker, mode="valid")[:len(y)]


def suavizar(cums, mediana=7, media=5):
    """Suavizado local (mediana + media movil) de los 6 elementos del afin.

    Un polinomio global NO sirve: el ultimo valor de la curva se va decenas de px y
    el clip queda con un residual mayor que el movimiento original. Mediana + media
    movil respetan los extremos y matan el jitter frame a frame.
    """
    n = len(cums)
    E = np.array([m[:2, :].ravel() for m in cums])
    S = np.zeros_like(E)
    for k in range(6):
        S[:, k] = _media(_mediana(E[:, k], mediana), media)
    out = []
    for i in range(n):
        v = S[i]
        out.append(np.array([[v[0], v[1], v[2]], [v[3], v[4], v[5]], [0.0, 0.0, 1.0]]))
    e0 = float(np.sqrt(abs(np.linalg.det(cums[0][:2, :2]))))
    e1 = float(np.sqrt(abs(np.linalg.det(cums[-1][:2, :2]))))
    return out, (e0, e1)


def a_origen(M, f):
    """Coordenadas de medicion (640 px) -> pixeles del archivo original."""
    Sf = np.array([[f, 0.0, 0.0], [0.0, f, 0.0], [0.0, 0.0, 1.0]])
    Sfi = np.array([[1 / f, 0.0, 0.0], [0.0, 1 / f, 0.0], [0.0, 0.0, 1.0]])
    return Sf @ M @ Sfi


def matriz_frame(i, n, M_src, k, W, H, wd, hd, dx, dy):
    """Muestreo final: pixel de salida -> pixel del frame i."""
    u = i / max(1, n - 1)
    ancho_ventana = k * wd
    alto_ventana = k * hd
    offx = (W - ancho_ventana) / 2 + dx * ancho_ventana * u
    offy = (H - alto_ventana) / 2 + dy * alto_ventana * u
    S = np.array([[k, 0.0, offx], [0.0, k, offy], [0.0, 0.0, 1.0]])
    return (M_src @ S)[:2, :].astype(np.float32)


def k_minimo(cums, W, H, wd, hd, dx, dy, techo):
    """Menor recorte que mantiene los 4 vertices de la salida dentro del cuadro."""
    n = len(cums)
    cand = 1.0
    while cand <= techo + 1e-9:
        ok = True
        for i in range(0, n, max(1, n // 24)):
            T = matriz_frame(i, n, cums[i], cand, W, H, wd, hd, dx, dy)
            for qx in (0.0, wd - 1.0):
                for qy in (0.0, hd - 1.0):
                    x = T[0, 0] * qx + T[0, 1] * qy + T[0, 2]
                    y = T[1, 0] * qx + T[1, 1] * qy + T[1, 2]
                    if not (0.0 <= x <= W - 1.0 and 0.0 <= y <= H - 1.0):
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                break
        if ok:
            return cand
        cand += 0.005
    return None


ap = argparse.ArgumentParser()
ap.add_argument("entrada")
ap.add_argument("salida")
ap.add_argument("--mov", default="estatica")
ap.add_argument("--wd", type=int, default=1280)
ap.add_argument("--hd", type=int, default=704)
ap.add_argument("--k", type=float, default=None)
ap.add_argument("--diag", action="store_true")
ap.add_argument("--crf", type=int, default=17)
a = ap.parse_args()

if a.mov not in MOVS:
    sys.exit(f"mov desconocido: {a.mov} (opciones: {', '.join(MOVS)})")

W, H, fps = probe(a.entrada)
dx, dy = MOVS[a.mov]
f = W / ANCHO_MEDICION
tmp = tempfile.mkdtemp(prefix="post_")
try:
    rutas = [os.path.join(tmp, x) for x in extraer(a.entrada, tmp)]
    n = len(rutas)
    cums_raw, detalle = medir(rutas)
    cums, (e0, e1) = suavizar(cums_raw)
    cums = [a_origen(m, f) for m in cums]

    k = a.k if a.k else k_minimo(cums, W, H, a.wd, a.hd, dx, dy, techo=max(1.0, W / a.wd))
    if k is None:
        k = max(1.0, W / a.wd)
        print(f"!! no entra: uso k={k:.3f} con bordes replicados")

    if a.diag:
        print(f"{os.path.basename(a.entrada)}: {W}x{H} · {n} frames")
        for q in (0, n // 4, n // 2, 3 * n // 4, n - 1):
            s, ttx, tty, pk = detalle[q]
            print(f"  frame {q:4d}: escala {s:.3f} · desplaz {ttx:+5.1f},{tty:+5.1f} · pico {pk:.3f}")
        print(f"deriva (ajuste suave): escala {e0:.4f} -> {e1:.4f} ({(e1/e0-1)*100:+.1f} %)")
        print(f"movimiento pedido: {a.mov} dx {dx*100:+.1f} % dy {dy*100:+.1f} % del frame")
        print(f"recorte k={k:.3f} · ventana {k*a.wd:.0f}x{k*a.hd:.0f} px de {W}x{H}")

    sal = os.path.join(tmp, "out")
    os.makedirs(sal)
    for i, r in enumerate(rutas):
        img = cv2.imread(r, cv2.IMREAD_COLOR)
        T = matriz_frame(i, n, cums[i], k, W, H, a.wd, a.hd, dx, dy)
        out = cv2.warpAffine(img, T, (a.wd, a.hd), flags=cv2.INTER_LANCZOS4,
                             borderMode=cv2.BORDER_REPLICATE)
        cv2.imwrite(os.path.join(sal, os.path.basename(r)), out)
        if a.diag and i % 60 == 0:
            print(f"  {i}/{n}")

    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", f"{fps:.6f}",
                    "-i", os.path.join(sal, "%05d.png"),
                    "-c:v", "libx264", "-preset", "slow", "-crf", str(a.crf),
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.salida], check=True)
    print(f"LISTO {a.salida} · k={k:.3f} · {n} frames")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
