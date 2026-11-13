"""Genera el FRAME FINAL sintetico de cada item: el mismo still con la ventana corrida.

Por que: el prompt no mueve la camara. Medido sobre 4 clips viejos, LTX-2.5 mete un
push-in de +3,5 % a +8 % de escala en todos, sin importar cuantas veces se pida
"paneo" o "camara fija" — y al final el encuadre termina metido dentro del bokeh.
La unica forma de fijar el movimiento es darle tambien el frame final
(LTXVAddGuide con frame_idx=-1): asi el clip arranca en A y tiene que llegar a B,
y la diferencia A→B es exactamente el paneo / tilt / descenso pedido.

B sale de correr la ventana sobre el mismo still. La franja que queda vacia se
rellena estirando el borde y difuminando: en estas tomas (humo, bokeh, follaje
fuera de foco) se lee como desenfoque, no como costura.

Uso:
    python endframes.py --state state_ltx_cam.json [--solo s02_t4] [--strength 0.75]
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(BASE, "endframes")

# Cuanto se corre la ventana entre el primer y el ultimo frame, en fraccion del
# cuadro. Lento y chico a proposito: son pantallas grandes, el movimiento tiene
# que leerse como deriva, no como reencuadre.
CAM_SHIFT = {
    "paneo-der": (0.055, 0.0),
    "paneo-izq": (-0.055, 0.0),
    "paneo-der-lento": (0.028, 0.0),
    "travelling-der": (0.065, 0.0),
    "travelling-izq": (-0.065, 0.0),
    "travelling-izq-lento": (-0.028, 0.0),
    "tilt-arriba": (0.0, 0.045),
    "tilt-abajo": (0.0, -0.045),
    "descenso": (0.0, -0.04),
    "arco-der": (0.04, 0.012),
    "arco-izq": (-0.04, 0.012),
    # Sin desplazamiento: el ultimo frame ES el primero.
    #   estatica -> camara fija (medido: zoom 0,0 %, dx/dy 0)
    #   loop     -> ademas el punto de loop queda invisible
    "estatica": (0.0, 0.0),
    "loop": (0.0, 0.0),
}

# Guia mas fuerte cuando el frame final es el mismo que el inicial: hay que
# sostener el encuadre 10 s, no llegar a el.
STRENGTH_FIJA = 0.4


def leer(path):
    """cv2.imread no abre rutas con acentos ni '·' en Windows: hay que pasar por bytes."""
    try:
        buf = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def escribir(path, img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError(f"no pude codificar PNG: {path}")
    buf.tofile(path)


def encuadrar(img, w, h):
    """Igual que ResizeImageMaskNode 'scale dimensions' + crop center de ComfyUI."""
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    nw, nh = max(w, int(round(iw * s))), max(h, int(round(ih * s)))
    r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    x0 = (nw - w) // 2
    y0 = (nh - h) // 2
    return r[y0:y0 + h, x0:x0 + w]


def correr_ventana(a, dxf, dyf):
    """Devuelve el frame final: contenido desplazado dx/dy px, borde estirado+borroso."""
    h, w = a.shape[:2]
    dx, dy = int(round(dxf * w)), int(round(dyf * h))
    if dx == 0 and dy == 0:
        return a.copy()
    M = np.array([[1.0, 0.0, -dx], [0.0, 1.0, -dy]], dtype=np.float32)
    mov = cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LANCZOS4,
                         borderMode=cv2.BORDER_REPLICATE)
    # mascara de la franja rellenada, con borde suave
    m = np.zeros((h, w), np.float32)
    if dx > 0:
        m[:, w - abs(dx):] = 1.0
    elif dx < 0:
        m[:, :abs(dx)] = 1.0
    if dy > 0:
        m[h - abs(dy):, :] = 1.0
    elif dy < 0:
        m[:abs(dy), :] = 1.0
    k = max(5, (abs(dx or dy) // 2) * 2 + 1)
    m = cv2.GaussianBlur(m, (k, k), 0)[:, :, None]
    borroso = cv2.GaussianBlur(mov, (0, 0), sigmaX=max(6, abs(dx) / 3 + abs(dy) / 3))
    return np.clip(mov * (1 - m) + borroso * m, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state_ltx_cam.json")
    ap.add_argument("--solo", default=None, help="filtra por codigo de toma (ej. s02_t4)")
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=704)
    ap.add_argument("--strength", type=float, default=0.4,
                    help="fuerza de la guia (0.4: suave, no inventa escena)")
    ap.add_argument("--strength-fija", type=float, default=STRENGTH_FIJA)
    ap.add_argument("--escala", type=float, default=1.0,
                    help="factor sobre los corrimientos (0.5 = mitad de amplitud)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    ruta = a.state if os.path.isabs(a.state) else os.path.join(BASE, a.state)
    st = json.load(open(ruta, encoding="utf-8"))
    os.makedirs(SALIDA, exist_ok=True)

    n = 0
    saltados = []
    for it in st["items"]:
        if it.get("status") != "pendiente":
            continue
        if a.solo and not it["shot"].startswith(a.solo):
            continue
        cam = it.get("camara")
        if cam not in CAM_SHIFT:
            saltados.append((it["id"], cam))
            continue
        dxf, dyf = CAM_SHIFT[cam]
        dxf, dyf = dxf * a.escala, dyf * a.escala
        if dxf == 0.0 and dyf == 0.0:
            # Sin desplazamiento: se le pasa el MISMO archivo del primer frame, sin
            # recomprimir nada. El modelo lo reescala igual que al frame inicial.
            it["last_image"] = it["image"]
            it["guide_strength"] = float(a.strength_fija)
            it["camara_shift"] = [0.0, 0.0]
            n += 1
            continue
        stem = os.path.splitext(os.path.basename(it["image"]))[0]
        dst = os.path.join(SALIDA, f"{stem}__{cam}.png")
        if not os.path.isfile(dst) and not a.dry:
            img = leer(it["image"])
            if img is None:
                print(f"!! no puedo leer {it['image']}")
                continue
            primero = encuadrar(img, a.w, a.h)
            final = correr_ventana(primero, dxf, dyf)
            escribir(dst, final)
        it["last_image"] = dst
        it["guide_strength"] = float(a.strength)
        it["camara_shift"] = [round(dxf, 4), round(dyf, 4)]
        n += 1

    print(f"items con frame final: {n}")
    if saltados:
        print(f"!! sin movimiento definido: {saltados[:5]}")
    print(f"carpeta: {SALIDA}")

    if a.dry:
        print("(dry run)")
        sys.exit(0)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)
    print("state guardado")


if __name__ == "__main__":
    main()
