"""Lote grande de biomas de selva para elegir: 10 familias x N semillas.

Salida: selva_amk/lote/<familia>_<nn>.png a 1152x2176 (aspecto 0.529, casi igual al
canvas del club 2160/4096 = 0.527, asi el corte por pantalla no estira nada).

Uso:
    python selva_lote.py --n 5            # 10 familias x 5 = 50 imagenes
    python selva_lote.py --n 5 --familias colgantes,lianas
"""
import argparse
import json
import os
import shutil
import time
import urllib.request

COMFY = "http://127.0.0.1:8188"
BASE = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(BASE, "selva_amk", "lote")

ESTILO = (
    "Photoreal cinematic still, medium-format quality, 35mm lens, f/2.8, shallow depth of field, "
    "soft anamorphic bloom, fine 35mm grain, deep crushed blacks, warm amber and molten gold light, "
    "jungle-green shadows, volumetric haze, suspended dust and pollen, aged brass and raw bamboo, "
    "hand-woven macrame, tropical foliage silhouettes, hypnotic and ceremonial mood. "
    "No text, no lettering, no logo, no watermark, no interface. No neon cyberpunk, no cold blue "
    "light, no people, no faces."
)
NEG = ("text, letters, watermark, logo, ui, frame, border, people, hands, cartoon, anime, "
       "illustration, 3d render, plastic, oversaturated, blurry, low quality")

FAMILIAS = {
    "01_colgantes": (
        "Immersive jungle interior made only of hanging plants: curtains of trailing pothos, "
        "string-of-pearls, ferns and air plants hanging from raw bamboo beams in dense layers from "
        "top to bottom of the frame, hand-woven macrame hangers among them, warm lantern light "
        "filtering between the leaves, dark green shadows, no ground visible."
    ),
    "02_lianas": (
        "Thick braided lianas and woody vines crossing the frame in every direction, hanging leaves "
        "and small epiphytes growing on the vines, backlit by a warm low sun, mist drifting between "
        "them, deep dark jungle behind, vertical composition, no ground, no sky."
    ),
    "03_vegetacion": (
        "Wall of dense tropical vegetation filling the entire frame: giant monstera, banana leaves, "
        "bird of paradise, ferns and moss, all overlapping and backlit at the edges, warm rim light, "
        "deep green interior shadows, wet leaves, volumetric haze."
    ),
    "04_dosel": (
        "Looking straight up into a cathedral of raw bamboo trunks and palm canopy far above, thin "
        "shafts of warm light cutting down through the haze, thousands of tiny suspended lights and "
        "glowing pollen, dark undergrowth at the bottom edge, deep perspective."
    ),
    "05_raices": (
        "Ancient moss-covered roots and buttress trunks of a giant tropical tree at night, glowing raw "
        "bamboo poles leaning against them, ferns and moss growing out of the bark, warm candle-like "
        "light from the right, wet earthy textures, deep crushed blacks."
    ),
    "06_helechos": (
        "Jungle understory of dense fern fronds and giant monstera leaves at night, backlit by a warm "
        "low sun bleeding through the foliage, mist between the leaves, wet moss on fallen bamboo, "
        "dark water reflecting gold at the bottom."
    ),
    "07_pantano": (
        "Edge of a black still-water lagoon inside a tropical jungle at night, dark reflective water "
        "mirroring warm lantern light, bamboo and fern silhouettes framing both sides, mist over the "
        "surface, tiny lights suspended in the air, horizon-led composition."
    ),
    "08_bokeh": (
        "Night jungle almost out of focus: a field of warm bokeh lights between dark foliage "
        "silhouettes, hanging brass lanterns turning into soft golden orbs, drifting mist and floating "
        "pollen, deep green shadows, very shallow depth of field, atmospheric only."
    ),
    "09_epifitas": (
        "Close view of tropical epiphytes on a jungle branch: orchids, bromeliads and ferns growing on "
        "mossy wood, warm light from the side, blurred dark jungle behind, suspended particles in the "
        "air, extremely shallow depth of field."
    ),
    "10_tunel": (
        "Vegetation tunnel seen from inside: giant ferns, bamboo and hanging vines forming a corridor "
        "that recedes into warm golden haze, light at the end of the tunnel, dark green edges, deep "
        "one-point perspective, floating particles."
    ),
}


def post(path, payload):
    req = urllib.request.Request(COMFY + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def get(path):
    with urllib.request.urlopen(COMFY + path, timeout=60) as r:
        return json.loads(r.read())


def workflow(prompt, w, h, seed, steps=25, cfg=1.0):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": NEG}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                                                   "latent_image": ["6", 0], "seed": seed, "steps": steps,
                                                   "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                                                   "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "selva_lote"}},
    }


def una(prompt, w, h, seed):
    pid = post("/prompt", {"prompt": workflow(prompt, w, h, seed)})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(4)
        try:
            h_ = get(f"/history/{pid}").get(pid) or {}
        except Exception:
            continue
        if (h_.get("status") or {}).get("status_str") == "success":
            for _n, o in (h_.get("outputs") or {}).items():
                for f in (o.get("images") or []):
                    return os.path.join(r"D:\ComfyUI\output", f.get("subfolder") or "", f["filename"]), round(time.time() - t0, 1)
            return None, None
    return None, None


ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=5)
ap.add_argument("--familias", default="")
ap.add_argument("--w", type=int, default=1152)
ap.add_argument("--h", type=int, default=2176)
ap.add_argument("--seed", type=int, default=910000)
a = ap.parse_args()

fams = FAMILIAS
if a.familias:
    pedidas = [f.strip() for f in a.familias.split(",")]
    fams = {k: v for k, v in FAMILIAS.items() if any(p in k for p in pedidas)}

os.makedirs(SALIDA, exist_ok=True)
total = len(fams) * a.n
print(f"{total} imagenes · {len(fams)} familias x {a.n} · {a.w}x{a.h} · salida {SALIDA}", flush=True)
hechas = 0
for fam, texto in fams.items():
    for i in range(a.n):
        seed = a.seed + (hash(fam) % 997) * 13 + i * 101
        dst = os.path.join(SALIDA, f"{fam}_{i+1:02d}.png")
        if os.path.isfile(dst):
            print(f"  {fam}_{i+1:02d}: ya esta", flush=True)
            hechas += 1
            continue
        src, seg = una(texto + " " + ESTILO, a.w, a.h, seed)
        if src and os.path.isfile(src):
            shutil.move(src, dst)
            hechas += 1
            print(f"  {fam}_{i+1:02d}: {seg}s -> {os.path.basename(dst)} ({hechas}/{total})", flush=True)
        else:
            print(f"  {fam}_{i+1:02d}: FALLO", flush=True)
print(f"listo: {hechas}/{total} en {SALIDA}", flush=True)
