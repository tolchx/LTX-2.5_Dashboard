"""Prueba: ultimo frame = primer frame (la misma imagen) para loop / camara fija.

La guia de ultimo frame acepta cualquier imagen; si le pasamos la MISMA que el
primer frame, el clip arranca y termina en el mismo encuadre. Dos usos:
  * fija  -> la camara no deberia moverse nada
  * loop  -> ademas el punto de loop queda invisible (frame final = inicial)

Manda el job directo al dashboard (no toca el state del lote) y espera el mp4.

Uso: python probar_fija_loop.py <imagen> fija|loop [--seed 777000]
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camara  # noqa: E402

DASH = "http://127.0.0.1:8899"
BASE = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(BASE, "endframes")


def post(path, payload):
    req = urllib.request.Request(DASH + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def get(path):
    with urllib.request.urlopen(DASH + path, timeout=60) as r:
        return json.loads(r.read())


ap = argparse.ArgumentParser()
ap.add_argument("imagen")
ap.add_argument("modo", choices=["fija", "loop"])
ap.add_argument("--seed", type=int, default=777000)
ap.add_argument("--strength", type=float, default=0.9)
ap.add_argument("--dx", type=float, default=0.0, help="corrimiento del frame final, fraccion del ancho")
ap.add_argument("--dy", type=float, default=0.0)
ap.add_argument("--mov", default=None, help="fuerza el movimiento del prompt")
a = ap.parse_args()

mov = a.mov or ("estatica" if a.modo == "fija" else "loop")

# La descripcion de escena sale del plan del lote (mismo still => mismo prompt base).
st = json.load(open(os.path.join(BASE, "state_ltx_cam.json"), encoding="utf-8"))
it = next((i for i in st["items"] if os.path.basename(i["image"]) == os.path.basename(a.imagen)), None)
base = camara.limpiar(it["prompt"]) if it else ""
if not base:
    sys.exit(f"no encontre el item para {a.imagen}")

prompt = camara.aplicar(base, mov)

# Frame final: el mismo still, con la ventana corrida si se pide un movimiento.
last = a.imagen
if a.dx or a.dy:
    import endframes as E  # noqa: E402
    img = E.leer(a.imagen)
    primero = E.encuadrar(img, 1280, 704)
    final = E.correr_ventana(primero, a.dx, a.dy)
    last = os.path.join(SALIDA, os.path.splitext(os.path.basename(a.imagen))[0][:40] + "__test.png")
    os.makedirs(SALIDA, exist_ok=True)
    E.escribir(last, final)

payload = {
    "task": "i2v",
    "model_engine": "ltx25",
    "image": a.imagen,
    "last_image": last,               # <-- guia: mismo still (o corrido) al final
    "guide_strength": a.strength,
    "prompt": prompt,
    "negative_prompt": "camera shake, handheld, zoom in, zoom out, push in, jump cut, morphing, flicker",
    "preset": "1280x704", "aspect": "auto", "duration": 10, "fps": 24,
    "two_stage": False, "vae_mode": "diff", "i2v_strength": 0.85,
    "include_audio": False, "chunks": 1, "seed": a.seed, "crf": 17,
    "category": f"pruebas_{a.modo}",
}
job = post("/api/generate", payload)
jid = job["id"]
print(f"{a.modo} strength {a.strength} dx {a.dx} dy {a.dy}: job {jid[:8]}")
t0 = time.time()
while True:
    time.sleep(10)
    js = get("/api/jobs")["items"]
    j = next((x for x in js if x["id"] == jid), None)
    if j is None:
        sys.exit("job desaparecio")
    print(f"  +{(time.time()-t0)/60:4.1f} min  {j['status']} {j.get('progress')}%  {j.get('stage')}")
    if j["status"] in ("success", "done", "completed"):
        print("LISTO:", j.get("output"))
        break
    if j["status"] in ("failed", "error", "cancelled"):
        print("FALLO:", j.get("error"))
        break
