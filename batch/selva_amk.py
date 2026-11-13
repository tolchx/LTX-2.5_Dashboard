"""Genera las imagenes de selva para las pantallas del club AMK en ComfyUI local.

Motor: Qwen-Image 2.1 (int8) con su VAE y el text encoder qwen3vl_8b. Los prompts
reusan el bloque de estilo de los videos NOMADE para que la paleta coincida (ambar y
oro fundido, sombras verde selva, neblina volumetrica, polvo en suspension).

Uso:
    python selva_amk.py --test                # 1 imagen 1024x1024 para validar
    python selva_amk.py --todo                # 6 biomas a 1152x2048
    python selva_amk.py --prompt "..." --n 2
"""
import argparse
import json
import os
import time
import urllib.request

COMFY = "http://127.0.0.1:8188"
BASE = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(BASE, "selva_amk")

ESTILO = (
    "Photoreal cinematic still, medium-format quality, 35mm lens, f/2.8, shallow depth of field, "
    "soft anamorphic bloom, fine 35mm grain, deep crushed blacks, warm amber and molten gold light, "
    "jungle-green shadows, volumetric haze, suspended dust and pollen, aged brass and raw bamboo, "
    "hand-woven macrame, tropical foliage silhouettes, hypnotic and ceremonial mood. "
    "No text, no lettering, no logo, no watermark, no interface. No neon cyberpunk, no cold blue "
    "light, no people, no faces."
)

NEG = ("text, letters, watermark, logo, ui, frame, border, people, hands, cartoon, anime, "
       "illustration, 3d render, plastic, oversaturated, blurry, low quality, extra limbs")

BIOMAS = {
    "01_dosel": (
        "Immersive interior of a tropical jungle at night seen from inside: a cathedral of raw bamboo "
        "trunks rising into a woven canopy of palm and monstera leaves far above, thin shafts of warm "
        "light cutting down through the haze, thousands of tiny suspended lights and glowing pollen, "
        "dark undergrowth at the bottom edge, deep green and molten gold palette."
    ),
    "02_helechos": (
        "Immersive jungle understory at night: dense fern fronds and giant monstera leaves filling the "
        "frame edge to edge, backlit by a warm low sun bleeding through the foliage, mist drifting between "
        "the leaves, wet moss on fallen bamboo, dark water reflecting gold at the bottom, no sky."
    ),
    "03_lianas": (
        "Curtain of hanging lianas, braided vines and trailing pothos crossing the frame from top to "
        "bottom, hand-woven macrame planters hanging among them, warm brass lanterns glowing behind the "
        "vines, dense dark jungle green receding into warm haze, suspended particles in the light beams."
    ),
    "04_raices": (
        "Ancient moss-covered roots and buttress trunks of a giant tree in a night jungle, glowing "
        "raw bamboo poles leaning against them, ferns growing out of the moss, warm candle-like light "
        "from the right, deep crushed blacks, volumetric haze, wet earthy textures."
    ),
    "05_bokeh": (
        "Night jungle seen almost out of focus: a field of warm bokeh lights between dark foliage "
        "silhouettes, hanging brass lanterns turning into soft golden orbs, drifting mist and floating "
        "pollen, deep green shadows, very shallow depth of field, no subject, atmospheric only."
    ),
    "06_pantano": (
        "Edge of a black still-water lagoon inside a tropical jungle at night, dark reflective water "
        "mirroring warm lantern light, bamboo and fern silhouettes framing both sides, mist over the "
        "surface, tiny lights suspended in the air, symmetrical horizon-led composition."
    ),
}


def api_post(path, payload):
    req = urllib.request.Request(COMFY + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def api_get(path):
    with urllib.request.urlopen(COMFY + path, timeout=60) as r:
        return json.loads(r.read())


def workflow(prompt, w, h, seed, steps=25, cfg=1.0):
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors",
                         "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors",
                         "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": NEG}},
        "6": {"class_type": "EmptyLatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": seed, "steps": steps,
                         "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": "selva_amk"}},
    }


def generar(nombre, prompt, w, h, seed):
    wf = workflow(prompt, w, h, seed)
    r = api_post("/prompt", {"prompt": wf})
    pid = r.get("prompt_id")
    print(f"  {nombre}: encolado {str(pid)[:8]} · {w}x{h} · seed {seed}", flush=True)
    t0 = time.time()
    while time.time() - t0 < 1800:
        time.sleep(6)
        try:
            h_ = api_get(f"/history/{pid}").get(pid) or {}
        except Exception:
            continue
        st = (h_.get("status") or {}).get("status_str")
        if st == "success":
            outs = []
            for _nid, o in (h_.get("outputs") or {}).items():
                for f in (o.get("images") or []):
                    outs.append(os.path.join(COMFY_OUT(), f.get("subfolder") or "", f["filename"]))
            seg = round(time.time() - t0, 1)
            print(f"  {nombre}: OK en {seg} s -> {outs}", flush=True)
            return outs
        if st == "error":
            print(f"  {nombre}: ERROR {json.dumps(h_.get('status'))[:200]}")
            return []
    print(f"  {nombre}: timeout")
    return []


def COMFY_OUT():
    return r"D:\ComfyUI\output"


ap = argparse.ArgumentParser()
ap.add_argument("--test", action="store_true")
ap.add_argument("--todo", action="store_true")
ap.add_argument("--prompt", default="")
ap.add_argument("--n", type=int, default=1)
ap.add_argument("--w", type=int, default=1152)
ap.add_argument("--h", type=int, default=2048)
ap.add_argument("--seed", type=int, default=770000)
a = ap.parse_args()

os.makedirs(SALIDA, exist_ok=True)
trabajos = []
if a.test:
    trabajos = [("test", BIOMAS["01_dosel"] + " " + ESTILO, 1024, 1024, a.seed)]
elif a.prompt:
    trabajos = [(f"libre_{i+1}", a.prompt + " " + ESTILO, a.w, a.h, a.seed + i * 7)
                for i in range(a.n)]
elif a.todo:
    for i, (k, txt) in enumerate(BIOMAS.items()):
        trabajos.append((k, txt + " " + ESTILO, a.w, a.h, a.seed + i * 13))
else:
    ap.error("elegí --test, --todo o --prompt")

print(f"{len(trabajos)} imagen(es) · salida {SALIDA}")
for nombre, prompt, w, h, seed in trabajos:
    generar(nombre, prompt, w, h, seed)
