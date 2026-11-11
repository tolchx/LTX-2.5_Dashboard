"""Descargador resiliente de pesos LTX-2.5 hacia models/ (junction -> E:\\).

Usa curl.exe con reintentos y reanudación (-C -) en archivo temporal .part,
evitando el bug de hf_xet exit 127 y verificando el tamaño exacto en bytes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"

CORE_MODELS = [
    {
        "key": "vae_audio",
        "label": "Audio VAE + Vocoder BF16 (0.36 GB)",
        "rel": "vae/ltx-2.5-audio-vae-bf16.safetensors",
        "url": "https://huggingface.co/comfyicu/LTX-2.5/resolve/main/vae/ltx-2.5-audio-vae-bf16.safetensors",
        "size": 364866540,
    },
    {
        "key": "upscaler_x2",
        "label": "Spatial Latent Upscaler x2 BF16 (1.00 GB)",
        "rel": "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
        "url": "https://huggingface.co/comfyicu/LTX-2.5/resolve/main/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
        "size": 995778752,
    },
    {
        "key": "vae_conv",
        "label": "Video Conv VAE BF16 (1.45 GB · rápido / menor VRAM)",
        "rel": "vae/ltx-2.5-video-vae-conv-bf16.safetensors",
        "url": "https://huggingface.co/comfyicu/LTX-2.5/resolve/main/vae/ltx-2.5-video-vae-conv-bf16.safetensors",
        "size": 1452269922,
    },
    {
        "key": "vae_diff",
        "label": "Video DiffVAE BF16 (1.47 GB · máximo detalle)",
        "rel": "vae/ltx-2.5-video-vae-bf16.safetensors",
        "url": "https://huggingface.co/comfyicu/LTX-2.5/resolve/main/vae/ltx-2.5-video-vae-bf16.safetensors",
        "size": 1472223346,
    },
    {
        "key": "dit_distilled_q4",
        "label": "DiT LTX-2.5 22B Distilled UD-Q4_K_XL GGUF (14.00 GB)",
        "rel": "diffusion_models/ltx-2.5-22b-distilled-UD-Q4_K_XL.gguf",
        "url": "https://huggingface.co/unsloth/LTX-2.5-GGUF/resolve/main/distilled/ltx-2.5-22b-distilled-UD-Q4_K_XL.gguf",
        "size": 14000234880,
    },
    {
        "key": "te_gemma4_int8",
        "label": "Text Encoder Gemma4 12B INT8-ConvRot (15.37 GB)",
        "rel": "text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
        "url": "https://huggingface.co/comfyicu/LTX-2.5/resolve/main/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
        "size": 15372971786,
    },
]

EXTRA_MODELS = [
    {
        "key": "q5",
        "label": "DiT LTX-2.5 22B Distilled UD-Q5_K_XL GGUF (16.00 GB)",
        "rel": "diffusion_models/ltx-2.5-22b-distilled-UD-Q5_K_XL.gguf",
        "url": "https://huggingface.co/unsloth/LTX-2.5-GGUF/resolve/main/distilled/ltx-2.5-22b-distilled-UD-Q5_K_XL.gguf",
        "size": 16000033152,
    },
    {
        "key": "dev",
        "label": "DiT LTX-2.5 22B Dev UD-Q4_K_XL GGUF (14.00 GB · 30 pasos CFG 3)",
        "rel": "diffusion_models/ltx-2.5-22b-dev-UD-Q4_K_XL.gguf",
        "url": "https://huggingface.co/unsloth/LTX-2.5-GGUF/resolve/main/ltx-2.5-22b-dev-UD-Q4_K_XL.gguf",
        "size": None,
    },
    {
        "key": "int8_dit",
        "label": "DiT LTX-2.5 22B Distilled INT8-ConvRot Official (21.50 GB)",
        "rel": "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
        "url": "https://huggingface.co/comfyicu/LTX-2.5/resolve/main/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
        "size": 21504034224,
    },
    {
        "key": "te_bf16",
        "label": "Text Encoder Gemma4 12B BF16 completo (26.26 GB)",
        "rel": "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
        "url": "https://huggingface.co/unsloth/LTX-2.5-GGUF/resolve/main/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
        "size": 26263858182,
    },
]


def format_gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB"


def download_item(item: dict, force: bool = False) -> bool:
    dest = MODELS_DIR / item["rel"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    expected = item.get("size")

    if dest.exists() and not force:
        actual = dest.stat().st_size
        if expected is None or actual == expected:
            print(f"[OK] Ya existe ({format_gb(actual)}): {item['rel']}")
            return True
        print(f"[WARN] Tamaño distinto en {item['rel']} ({actual} vs {expected}), re-descargando...")
        dest.replace(part)

    curl_exe = shutil.which("curl.exe") or "curl"
    headers = []
    hf_token = os.environ.get("HF_TOKEN", "").strip()
    if hf_token:
        headers += ["-H", f"Authorization: Bearer {hf_token}"]

    print(f"\n[DL] {item['label']}")
    print(f"     -> {dest}")

    for attempt in range(1, 6):
        cmd = [
            curl_exe,
            "-fL",
            "-C", "-",
            "--retry", "8",
            "--retry-delay", "3",
            "--connect-timeout", "20",
            "--progress-bar",
            *headers,
            "-o", str(part),
            item["url"],
        ]
        rc = subprocess.run(cmd).returncode
        if rc == 0 and part.exists():
            actual = part.stat().st_size
            if expected is not None and actual != expected:
                print(f"[ERR] Tamaño incompleto ({actual} != {expected}) en intento {attempt}.")
                if actual > expected:
                    part.unlink(missing_ok=True)
                time.sleep(2)
                continue
            os.replace(part, dest)
            print(f"[DONE] {item['rel']} ({format_gb(actual)})")
            return True
        print(f"[RETRY {attempt}/5] curl salió con código {rc}")
        time.sleep(3)

    print(f"[FAIL] No se pudo completar: {item['rel']}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Descarga modelos LTX-2.5 para LTX-2.5_Dashboard")
    parser.add_argument("--extra", nargs="*", default=[], help="Claves extra opcionales: q5 dev int8_dit te_bf16")
    parser.add_argument("--only-check", action="store_true", help="Solo verifica archivos descargados")
    parser.add_argument("--force", action="store_true", help="Re-descarga aunque ya existan")
    args = parser.parse_args()

    items = list(CORE_MODELS)
    extra_map = {x["key"]: x for x in EXTRA_MODELS}
    for k in args.extra:
        if k in extra_map:
            items.append(extra_map[k])
        else:
            print(f"[WARN] Extra desconocido ignorado: {k}")

    print(f"Carpeta destino de modelos: {MODELS_DIR} (real: {MODELS_DIR.resolve()})")
    free_gb = shutil.disk_usage(MODELS_DIR.resolve()).free / 1e9
    print(f"Espacio libre en destino: {free_gb:.2f} GB\n")

    if args.only_check:
        ok_all = True
        for item in items:
            p = MODELS_DIR / item["rel"]
            ok = p.exists() and (item["size"] is None or p.stat().st_size == item["size"])
            status = "OK" if ok else "FALTA"
            sz = format_gb(p.stat().st_size) if p.exists() else "-"
            print(f"[{status:5}] {item['rel']} ({sz})")
            if not ok:
                ok_all = False
        return 0 if ok_all else 1

    ok_all = True
    for item in items:
        if not download_item(item, force=args.force):
            ok_all = False
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
