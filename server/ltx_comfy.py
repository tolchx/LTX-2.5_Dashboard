"""Cliente ComfyUI y constructor de grafos oficiales para LTX-2.5 (GGUF / Safetensors).

Incluye:
- Cálculo automático de dimensiones compatibles (múltiplos de 64 en 2-Stage, 32 en 1-Stage)
- Conteo exacto de frames (8k + 1) respetando orientación EXIF
- Grafos ComfyUI 0.39.0 para LTX-2.5 I2V / T2V (2-Stage Distilled 8+3 pasos y 1-Stage 8 pasos)
- WebSocket / polling de progreso en tiempo real + captura detallada de errores
- Extracción de último frame y concatenación ffmpeg para múltiples chunks
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid
from typing import Any

import requests
from PIL import Image

try:
    import imageio_ffmpeg
except Exception:  # pragma: no cover
    imageio_ffmpeg = None

AREA_MAP = {
    "512p": 832 * 512,
    "576p": 1024 * 576,
    "704p": 1280 * 704,
    "768p": 1344 * 768,
    "832p": 1472 * 832,
}

ASPECT_RATIOS = {
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "1:1": 1.0,
    "21:9": 21 / 9,
}

STAGE1_DISTILLED_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
STAGE2_DISTILLED_SIGMAS = "0.85, 0.7250, 0.4219, 0.0"

NODE_TITLES = {
    "1": "Cargando DiT LTX-2.5",
    "2": "Cargando Gemma 4 Text Encoder",
    "3": "Cargando Video VAE",
    "4": "Cargando Audio VAE",
    "5": "Codificando Prompt (+)",
    "6": "Codificando Prompt (-)",
    "7": "Condicionando LTX-2.5",
    "8": "Cargando Imagen",
    "9": "Redimensionando Imagen",
    "10": "Preprocesando Frame",
    "11": "Creando Latente Video",
    "12": "Inyectando Imagen (Stage 1)",
    "13": "Creando Latente Audio",
    "14": "Uniendo Latentes A/V",
    "19": "Etapa 1 · Sampling (8 pasos)",
    "20": "Separando Audio/Video",
    "21": "Cargando Upscaler x2",
    "22": "Upscaling Latente x2",
    "23": "Reforzando Imagen (Stage 2)",
    "24": "Uniendo Latentes Stage 2",
    "29": "Etapa 2 · Refinado HD (3 pasos)",
    "30": "Separando Latentes Final",
    "31": "Decodificando Video (VAE Tiled)",
    "32": "Decodificando Audio (Vocoder)",
    "33": "Ensamblando A/V",
    "34": "Codificando y Guardando MP4",
}

MINIMAX_NODE_TITLES = {
    "1": "Cargando DiT MiniMax H3 (INT8)",
    "2": "Cargando Qwen3-VL 32B CLIP",
    "3": "Cargando Video VAE MiniMax",
    "4": "Cargando Audio VAE MiniMax",
    "5": "Ajustando Sigma Shift (Video 12 / Audio 3)",
    "6": "Cargando Frame Inicial (A)",
    "7": "Cargando Frame Final (B)",
    "8": "Codificando FL2VA / Keyframes",
    "9": "Codificando Prompt Negativo",
    "10": "Sampling DiT (MiniMax H3)",
    "11": "Decodificando Video (ViT3D VAE)",
    "12": "Decodificando Audio (Vocoder MiniMax)",
    "13": "Ensamblando Video + Audio",
    "14": "Codificando MP4 Final",
}


def calc_minimax_frames(duration_sec: float, fps: int = 24) -> int:
    """MiniMax H3 exige frame_count en la grilla 17k + 5 (124 = ~5.16s @ 24fps)."""
    raw_frames = max(5, round(float(duration_sec) * int(fps)))
    while raw_frames % 17 != 5:
        raw_frames += 1
    return raw_frames


def ffmpeg_exe() -> str:
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    if imageio_ffmpeg is not None:
        return imageio_ffmpeg.get_ffmpeg_exe()
    raise RuntimeError("No se encontró ffmpeg en el sistema ni imageio_ffmpeg")


def ffprobe_exe() -> str | None:
    return shutil.which("ffprobe")


def image_dimensions(image_path: str) -> tuple[int, int] | None:
    """Lee ancho y alto sin decodificar píxeles, respetando orientación EXIF."""
    if not image_path or not os.path.isfile(image_path):
        return None
    try:
        with Image.open(image_path) as im:
            w, h = int(im.width), int(im.height)
            try:
                orient = im.getexif().get(274)
                if orient in (5, 6, 7, 8):
                    w, h = h, w
            except Exception:
                pass
            return w, h
    except Exception:
        return None


def aspect_for_image(image_path: str) -> str:
    dims = image_dimensions(image_path)
    if not dims:
        return "16:9"
    w, h = dims
    ratio = w / max(h, 1)
    best_name, best_diff = "16:9", 1e9
    for name, val in ASPECT_RATIOS.items():
        d = abs(ratio - val)
        if d < best_diff:
            best_diff = d
            best_name = name
    return best_name


def snap_dims(
    src_w: int = 1280,
    src_h: int = 704,
    preset: str = "704p",
    aspect: str = "auto",
    two_stage: bool = True,
) -> tuple[int, int]:
    """Calcula (width, height) alineados a 64px (2-stage) o 32px (1-stage)."""
    align = 64 if two_stage else 32
    min_side = 256

    m = re.fullmatch(r"\s*(\d{3,4})\s*[xX×]\s*(\d{3,4})\s*", str(preset or ""))
    if m:
        raw_w, raw_h = int(m.group(1)), int(m.group(2))
        w = max(min_side, round(raw_w / align) * align)
        h = max(min_side, round(raw_h / align) * align)
        return int(w), int(h)

    budget = AREA_MAP.get(preset, AREA_MAP["704p"])
    if aspect and aspect != "auto" and aspect in ASPECT_RATIOS:
        ratio = ASPECT_RATIOS[aspect]
    else:
        ratio = max(0.35, min(2.8, src_w / max(src_h, 1)))

    raw_h = math.sqrt(budget / ratio)
    raw_w = raw_h * ratio
    w = max(min_side, int(round(raw_w / align)) * align)
    h = max(min_side, int(round(raw_h / align)) * align)
    return w, h


def calc_frames(duration_sec: float, fps: int = 24) -> int:
    """LTX-2.5 exige num_frames = 8k + 1 (mínimo 9)."""
    target = max(9, round(float(duration_sec) * int(fps)) + 1)
    k = max(1, round((target - 1) / 8))
    return k * 8 + 1


def real_seconds(frames: int, fps: int = 24) -> float:
    return round(max(frames - 1, 1) / max(int(fps), 1), 2)


def build_workflow(
    *,
    unet_name: str,
    clip_name: str,
    video_vae_name: str,
    audio_vae_name: str,
    upscale_model_name: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    length: int,
    fps: int = 24,
    seed: int = 0,
    two_stage: bool = True,
    image_name: str | None = None,
    task: str = "i2v",
    i2v_strength: float = 0.7,
    stage2_strength: float = 1.0,
    include_audio: bool = True,
    img_compression: int = 18,
    crf: int = 17,
    video_cfg: float = 1.0,
    prefix: str = "ltx25/clip",
    last_image_name: str | None = None,
    guide_strength: float = 0.7,
) -> dict[str, Any]:
    """Construye el grafo API oficial de LTX-2.5 para ComfyUI 0.39.0."""
    if not seed or int(seed) <= 0:
        seed = int(time.time() * 1000) % (2**62)
    else:
        seed = int(seed)

    is_i2v = (task != "t2v") and bool(image_name)
    align = 64 if two_stage else 32
    width = max(256, (int(width) // align) * align)
    height = max(256, (int(height) // align) * align)

    # Garantizar 8k + 1 frames
    length = max(9, ((int(length) - 1) // 8) * 8 + 1)

    wf: dict[str, Any] = {}

    if unet_name.lower().endswith(".gguf"):
        wf["1"] = {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": unet_name},
            "_meta": {"title": NODE_TITLES["1"]},
        }
    else:
        wf["1"] = {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": unet_name, "weight_dtype": "default"},
            "_meta": {"title": NODE_TITLES["1"]},
        }

    wf["2"] = {
        "class_type": "CLIPLoader",
        "inputs": {"clip_name": clip_name, "type": "ltxv", "device": "default"},
        "_meta": {"title": NODE_TITLES["2"]},
    }
    wf["3"] = {
        "class_type": "VAELoader",
        "inputs": {"vae_name": video_vae_name},
        "_meta": {"title": NODE_TITLES["3"]},
    }
    wf["4"] = {
        "class_type": "VAELoader",
        "inputs": {"vae_name": audio_vae_name},
        "_meta": {"title": NODE_TITLES["4"]},
    }
    wf["5"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["2", 0], "text": prompt or "Smooth natural cinematic motion"},
        "_meta": {"title": NODE_TITLES["5"]},
    }
    wf["6"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["2", 0], "text": negative_prompt or "blurry, low quality, ugly"},
        "_meta": {"title": NODE_TITLES["6"]},
    }
    wf["7"] = {
        "class_type": "LTXVConditioning",
        "inputs": {"positive": ["5", 0], "negative": ["6", 0], "frame_rate": float(fps)},
        "_meta": {"title": NODE_TITLES["7"]},
    }

    if is_i2v:
        wf["8"] = {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
            "_meta": {"title": NODE_TITLES["8"]},
        }
        wf["9"] = {
            "class_type": "ResizeImageMaskNode",
            "inputs": {
                "input": ["8", 0],
                "resize_type": "scale dimensions",
                "resize_type.width": width,
                "resize_type.height": height,
                "resize_type.crop": "center",
                "scale_method": "lanczos",
            },
            "_meta": {"title": NODE_TITLES["9"]},
        }
        wf["10"] = {
            "class_type": "LTXVPreprocess",
            "inputs": {"image": ["9", 0], "img_compression": int(img_compression)},
            "_meta": {"title": NODE_TITLES["10"]},
        }

    s1_w = width // 2 if two_stage else width
    s1_h = height // 2 if two_stage else height

    wf["11"] = {
        "class_type": "EmptyLTXVLatentVideo",
        "inputs": {"width": s1_w, "height": s1_h, "length": length, "batch_size": 1},
        "_meta": {"title": NODE_TITLES["11"]},
    }

    if is_i2v:
        wf["12"] = {
            "class_type": "LTXVImgToVideoInplace",
            "inputs": {
                "vae": ["3", 0],
                "image": ["10", 0],
                "latent": ["11", 0],
                "strength": float(i2v_strength),
                "bypass": False,
            },
            "_meta": {"title": NODE_TITLES["12"]},
        }
        s1_video_latent = ["12", 0]
    else:
        s1_video_latent = ["11", 0]

    # --- guia de ULTIMO frame (LTXVAddGuide, frame_idx=-1) --------------------
    # El modelo tiene un sesgo fortisimo a hacer push-in pase lo que diga el prompt
    # (medido: +2 % a +8 % de escala por clip, y al final el encuadre termina metido
    # en el bokeh). Con un frame final sintetico —otro crop del mismo still— el clip
    # esta obligado a llegar a ese encuadre, y ese salto es el paneo/tilt que pide el
    # prompt. Solo una pasada: en dos etapas el latent cambia de forma.
    guide_node = None
    cond_pos, cond_neg = ["7", 0], ["7", 1]
    if is_i2v and last_image_name and not two_stage:
        wf["40"] = {
            "class_type": "LoadImage",
            "inputs": {"image": last_image_name},
            "_meta": {"title": "Ultimo frame (guia)"},
        }
        wf["41"] = {
            "class_type": "ResizeImageMaskNode",
            "inputs": {
                "input": ["40", 0],
                "resize_type": "scale dimensions",
                "resize_type.width": s1_w,
                "resize_type.height": s1_h,
                "resize_type.crop": "center",
                "scale_method": "lanczos",
            },
            "_meta": {"title": "Ultimo frame · resize"},
        }
        wf["42"] = {
            "class_type": "LTXVPreprocess",
            "inputs": {"image": ["41", 0], "img_compression": int(img_compression)},
            "_meta": {"title": "Ultimo frame · preprocess"},
        }
        wf["43"] = {
            "class_type": "LTXVAddGuide",
            "inputs": {
                "positive": ["7", 0],
                "negative": ["7", 1],
                "vae": ["3", 0],
                "latent": s1_video_latent,
                "image": ["42", 0],
                "frame_idx": -1,
                "strength": float(guide_strength),
            },
            "_meta": {"title": "Guia ultimo frame"},
        }
        s1_video_latent = ["43", 2]
        cond_pos, cond_neg = ["43", 0], ["43", 1]
        guide_node = "43"

    wf["13"] = {
        "class_type": "LTXVEmptyLatentAudio",
        "inputs": {
            "frames_number": length,
            "frame_rate": float(fps),
            "batch_size": 1,
            "audio_vae": ["4", 0],
        },
        "_meta": {"title": NODE_TITLES["13"]},
    }
    wf["14"] = {
        "class_type": "LTXVConcatAVLatent",
        "inputs": {"video_latent": s1_video_latent, "audio_latent": ["13", 0]},
        "_meta": {"title": NODE_TITLES["14"]},
    }
    wf["15"] = {
        "class_type": "KSamplerSelect",
        "inputs": {"sampler_name": "euler_ancestral"},
    }
    wf["16"] = {
        "class_type": "ManualSigmas",
        "inputs": {"sigmas": STAGE1_DISTILLED_SIGMAS},
    }
    wf["17"] = {
        "class_type": "RandomNoise",
        "inputs": {"noise_seed": seed},
    }
    wf["18"] = {
        "class_type": "LTXVDualCFGGuider",
        "inputs": {
            "model": ["1", 0],
            "positive": cond_pos,
            "negative": cond_neg,
            "video_cfg": float(video_cfg),
            "audio_cfg": 1.0,
        },
    }
    wf["19"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["17", 0],
            "guider": ["18", 0],
            "sampler": ["15", 0],
            "sigmas": ["16", 0],
            "latent_image": ["14", 0],
        },
        "_meta": {"title": NODE_TITLES["19"]},
    }
    wf["20"] = {
        "class_type": "LTXVSeparateAVLatent",
        "inputs": {"av_latent": ["19", 0]},
        "_meta": {"title": NODE_TITLES["20"]},
    }

    if two_stage:
        wf["21"] = {
            "class_type": "LatentUpscaleModelLoader",
            "inputs": {"model_name": upscale_model_name},
            "_meta": {"title": NODE_TITLES["21"]},
        }
        wf["22"] = {
            "class_type": "LTXVLatentUpsampler",
            "inputs": {"samples": ["20", 0], "upscale_model": ["21", 0], "vae": ["3", 0]},
            "_meta": {"title": NODE_TITLES["22"]},
        }
        if is_i2v:
            wf["23"] = {
                "class_type": "LTXVImgToVideoInplace",
                "inputs": {
                    "vae": ["3", 0],
                    "image": ["10", 0],
                    "latent": ["22", 0],
                    "strength": float(stage2_strength),
                    "bypass": False,
                },
                "_meta": {"title": NODE_TITLES["23"]},
            }
            s2_video_latent = ["23", 0]
        else:
            s2_video_latent = ["22", 0]

        wf["24"] = {
            "class_type": "LTXVConcatAVLatent",
            "inputs": {"video_latent": s2_video_latent, "audio_latent": ["20", 1]},
            "_meta": {"title": NODE_TITLES["24"]},
        }
        wf["25"] = {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "euler_ancestral"},
        }
        wf["26"] = {
            "class_type": "ManualSigmas",
            "inputs": {"sigmas": STAGE2_DISTILLED_SIGMAS},
        }
        wf["27"] = {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": (seed + 42) % (2**62)},
        }
        wf["28"] = {
            "class_type": "LTXVDualCFGGuider",
            "inputs": {
                "model": ["1", 0],
                "positive": ["7", 0],
                "negative": ["7", 1],
                "video_cfg": 1.0,
                "audio_cfg": 1.0,
            },
        }
        wf["29"] = {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["27", 0],
                "guider": ["28", 0],
                "sampler": ["25", 0],
                "sigmas": ["26", 0],
                "latent_image": ["24", 0],
            },
            "_meta": {"title": NODE_TITLES["29"]},
        }
        wf["30"] = {
            "class_type": "LTXVSeparateAVLatent",
            "inputs": {"av_latent": ["29", 0]},
            "_meta": {"title": NODE_TITLES["30"]},
        }
        final_sep_node = "30"
    else:
        final_sep_node = "20"

    # Las guias agregan frames al latent: hay que sacarlas antes de decodificar.
    if guide_node:
        wf["44"] = {
            "class_type": "LTXVCropGuides",
            "inputs": {
                "positive": [guide_node, 0],
                "negative": [guide_node, 1],
                "latent": [final_sep_node, 0],
            },
            "_meta": {"title": "Crop de guias"},
        }
        decode_samples = ["44", 2]
    else:
        decode_samples = [final_sep_node, 0]

    wf["31"] = {
        "class_type": "VAEDecodeTiled",
        "inputs": {
            "samples": decode_samples,
            "vae": ["3", 0],
            "tile_size": 512,
            "overlap": 64,
            "temporal_size": 64,
            "temporal_overlap": 16,
        },
        "_meta": {"title": NODE_TITLES["31"]},
    }

    create_inputs: dict[str, Any] = {
        "images": ["31", 0],
        "fps": float(fps),
        "bit_depth": 8,
        "color_space": "sRGB",
        "codec": "none",
    }
    if include_audio:
        wf["32"] = {
            "class_type": "LTXVAudioVAEDecode",
            "inputs": {"samples": [final_sep_node, 1], "audio_vae": ["4", 0]},
            "_meta": {"title": NODE_TITLES["32"]},
        }
        create_inputs["audio"] = ["32", 0]

    wf["33"] = {
        "class_type": "CreateVideo",
        "inputs": create_inputs,
        "_meta": {"title": NODE_TITLES["33"]},
    }
    wf["34"] = {
        "class_type": "SaveVideo",
        "inputs": {
            "video": ["33", 0],
            "filename_prefix": prefix,
            "format": "mp4",
            "format.codec": "h264",
            "format.codec.encoding": "re-encode",
            "format.codec.encoding.crf": float(crf),
        },
        "_meta": {"title": NODE_TITLES["34"]},
    }
    return wf


def build_minimax_workflow(
    *,
    unet_name: str,
    clip_name: str,
    video_vae_name: str,
    audio_vae_name: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    length: int,
    fps: int = 24,
    seed: int = 0,
    first_frame_name: str | None = None,
    last_frame_name: str | None = None,
    task: str = "i2v",
    steps: int = 25,
    cfg: float = 3.5,
    shift_video: float = 12.0,
    shift_audio: float = 3.0,
    include_audio: bool = True,
    crf: int = 17,
    prefix: str = "minimax/clip",
) -> dict[str, Any]:
    """Construye el grafo API oficial de MiniMax H3 (FL2VA / I2V / T2VA) con audio nativo."""
    if not seed or int(seed) <= 0:
        seed = int(time.time() * 1000) % (2**62)
    else:
        seed = int(seed)

    align = 32
    width = max(256, (int(width) // align) * align)
    height = max(256, (int(height) // align) * align)

    # Frame count en la grilla 17k + 5 de MiniMax
    raw_len = int(length) if length and int(length) > 5 else 124
    while raw_len % 17 != 5:
        raw_len += 1
    length = raw_len

    wf: dict[str, Any] = {}

    wf["1"] = {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": unet_name, "weight_dtype": "default"},
        "_meta": {"title": MINIMAX_NODE_TITLES["1"]},
    }
    wf["2"] = {
        "class_type": "CLIPLoader",
        "inputs": {"clip_name": clip_name, "type": "minimax", "device": "default"},
        "_meta": {"title": MINIMAX_NODE_TITLES["2"]},
    }
    wf["3"] = {
        "class_type": "VAELoader",
        "inputs": {"vae_name": video_vae_name},
        "_meta": {"title": MINIMAX_NODE_TITLES["3"]},
    }
    wf["4"] = {
        "class_type": "VAELoader",
        "inputs": {"vae_name": audio_vae_name},
        "_meta": {"title": MINIMAX_NODE_TITLES["4"]},
    }
    wf["5"] = {
        "class_type": "MiniMaxH3SigmaShift",
        "inputs": {"model": ["1", 0], "shift_video": float(shift_video), "shift_audio": float(shift_audio)},
        "_meta": {"title": MINIMAX_NODE_TITLES["5"]},
    }

    cond_inputs: dict[str, Any] = {
        "clip": ["2", 0],
        "vae": ["3", 0],
        "prompt": prompt or "Smooth cinematic motion with atmospheric golden lighting",
        "width": width,
        "height": height,
        "length": length,
    }

    if task != "t2v" and first_frame_name:
        wf["6"] = {
            "class_type": "LoadImage",
            "inputs": {"image": first_frame_name},
            "_meta": {"title": MINIMAX_NODE_TITLES["6"]},
        }
        cond_inputs["first_frame"] = ["6", 0]

    if task != "t2v" and last_frame_name:
        wf["7"] = {
            "class_type": "LoadImage",
            "inputs": {"image": last_frame_name},
            "_meta": {"title": MINIMAX_NODE_TITLES["7"]},
        }
        cond_inputs["last_frame"] = ["7", 0]

    wf["8"] = {
        "class_type": "MiniMaxH3ImageToVideo",
        "inputs": cond_inputs,
        "_meta": {"title": MINIMAX_NODE_TITLES["8"]},
    }

    wf["9"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["2", 0], "text": negative_prompt or "ugly, blurry, distorted, jitter, cartoon"},
        "_meta": {"title": MINIMAX_NODE_TITLES["9"]},
    }

    wf["10"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["5", 0],
            "positive": ["8", 0],
            "negative": ["9", 0],
            "latent_image": ["8", 1],
            "seed": seed,
            "steps": int(steps),
            "cfg": float(cfg),
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0,
        },
        "_meta": {"title": MINIMAX_NODE_TITLES["10"]},
    }

    wf["11"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["10", 0], "vae": ["3", 0]},
        "_meta": {"title": MINIMAX_NODE_TITLES["11"]},
    }

    create_inputs: dict[str, Any] = {
        "images": ["11", 0],
        "fps": float(fps),
    }

    if include_audio:
        wf["12"] = {
            "class_type": "VAEDecodeAudio",
            "inputs": {"samples": ["10", 0], "vae": ["4", 0]},
            "_meta": {"title": MINIMAX_NODE_TITLES["12"]},
        }
        create_inputs["audio"] = ["12", 0]

    wf["13"] = {
        "class_type": "CreateVideo",
        "inputs": create_inputs,
        "_meta": {"title": MINIMAX_NODE_TITLES["13"]},
    }

    wf["14"] = {
        "class_type": "SaveVideo",
        "inputs": {
            "video": ["13", 0],
            "filename_prefix": prefix,
            "format": "mp4",
            "format.codec": "h264",
            "format.codec.encoding": "re-encode",
            "format.codec.encoding.crf": float(crf),
        },
        "_meta": {"title": MINIMAX_NODE_TITLES["14"]},
    }
    return wf


def ping_comfy(comfy_url: str) -> dict[str, Any]:
    try:
        r = requests.get(f"{comfy_url.rstrip('/')}/system_stats", timeout=4)
        r.raise_for_status()
        data = r.json()
        devices = data.get("devices") or []
        return {
            "online": True,
            "version": (data.get("system") or {}).get("comfyui_version"),
            "devices": devices,
        }
    except Exception as e:
        return {"online": False, "error": str(e)}


def list_comfy_models(comfy_url: str) -> dict[str, list[str]]:
    base = comfy_url.rstrip("/")
    mapping = {
        "gguf_unets": ("UnetLoaderGGUF", "unet_name"),
        "safetensors_unets": ("UNETLoader", "unet_name"),
        "clips": ("CLIPLoader", "clip_name"),
        "vaes": ("VAELoader", "vae_name"),
        "upscalers": ("LatentUpscaleModelLoader", "model_name"),
    }
    res: dict[str, list[str]] = {k: [] for k in mapping}
    for key, (node_name, field_name) in mapping.items():
        try:
            r = requests.get(f"{base}/object_info/{node_name}", timeout=5)
            r.raise_for_status()
            info = r.json().get(node_name, {})
            spec = ((info.get("input") or {}).get("required") or {}).get(field_name)
            if isinstance(spec, list) and spec:
                if isinstance(spec[0], list):
                    res[key] = list(spec[0])
                elif spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
                    res[key] = list(spec[1].get("options") or [])
        except Exception:
            pass
    return res


def upload_image(comfy_url: str, path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime = "image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg")
    with open(path, "rb") as f:
        r = requests.post(
            f"{comfy_url.rstrip('/')}/upload/image",
            files={"image": (os.path.basename(path), f, mime)},
            data={"type": "input", "overwrite": "true"},
            timeout=30,
        )
    r.raise_for_status()
    return r.json()["name"]


def submit(comfy_url: str, workflow: dict[str, Any], client_id: str) -> str:
    r = requests.post(
        f"{comfy_url.rstrip('/')}/prompt",
        json={"prompt": workflow, "client_id": client_id},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI /prompt HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    if data.get("node_errors"):
        raise RuntimeError(f"Errores de nodos en ComfyUI: {json.dumps(data['node_errors'], ensure_ascii=False)[:600]}")
    return data["prompt_id"]


def extract_error_message(status_obj: dict[str, Any]) -> str:
    msgs = status_obj.get("messages") or []
    for entry in msgs:
        if isinstance(entry, list) and len(entry) >= 2 and entry[0] == "execution_error":
            payload = entry[1] if isinstance(entry[1], dict) else {}
            ntype = payload.get("node_type") or "?"
            nid = payload.get("node_id") or "?"
            exc = payload.get("exception_message") or "Error desconocido en ComfyUI"
            return f"Nodo {nid} ({ntype}): {str(exc).strip()[:600]}"
    return f"ComfyUI terminó con estado '{status_obj.get('status_str', 'error')}'"


def get_result(comfy_url: str, prompt_id: str) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """Devuelve (status_str, outputs, error_msg) o (None, None, None) si sigue en curso."""
    r = requests.get(f"{comfy_url.rstrip('/')}/history/{prompt_id}", timeout=10)
    r.raise_for_status()
    data = r.json()
    if prompt_id in data:
        h = data[prompt_id]
        st = h.get("status") or {}
        st_str = st.get("status_str")
        err = extract_error_message(st) if st_str == "error" else None
        return st_str, h.get("outputs") or {}, err
    return None, None, None


def is_queued(comfy_url: str, prompt_id: str) -> bool:
    try:
        r = requests.get(f"{comfy_url.rstrip('/')}/queue", timeout=6)
        q = r.json()
        for item in (q.get("queue_running") or []) + (q.get("queue_pending") or []):
            if isinstance(item, list) and len(item) > 1 and item[1] == prompt_id:
                return True
        return False
    except Exception:
        return True


def cancel_prompt(comfy_url: str, prompt_id: str) -> None:
    base = comfy_url.rstrip("/")
    try:
        requests.post(f"{base}/queue", json={"delete": [prompt_id]}, timeout=5)
    except Exception:
        pass
    try:
        r = requests.get(f"{base}/queue", timeout=5)
        running = (r.json().get("queue_running") or [])
        for item in running:
            if isinstance(item, list) and len(item) > 1 and item[1] == prompt_id:
                requests.post(f"{base}/interrupt", json={"prompt_id": prompt_id}, timeout=5)
                break
    except Exception:
        pass


def extract_video(outputs: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """Extrae (subfolder, filename) del archivo de video generado por SaveVideo."""
    for _nid, out in (outputs or {}).items():
        if not isinstance(out, dict):
            continue
        for bucket in ("images", "videos", "gifs"):
            for item in out.get(bucket) or []:
                fn = str(item.get("filename") or "")
                if fn.lower().endswith((".mp4", ".webm", ".mkv", ".mov")):
                    return item.get("subfolder", ""), fn
    return None, None


def resolve_comfy_output(comfy_output_dir: str, subfolder: str, filename: str) -> str:
    return os.path.join(comfy_output_dir, subfolder, filename) if subfolder else os.path.join(comfy_output_dir, filename)


def buscar_por_prefijo(comfy_output_dir: str, base: str, subfolder: str = "ltx25") -> str | None:
    """Ultimo MP4 cuyo nombre empiece con `base`.

    Red de seguridad para el job que queda en 99 %: cuando ComfyUI se reinicia (los
    reinicios por RAM del lote) el prompt_id desaparece del /history y el dashboard
    no tiene como cerrar el trabajo, aunque el clip ya este escrito en disco. El
    prefijo del archivo es f"{job_id[:10]}_c{chunk}", asi que se puede recuperar.
    """
    import glob

    patrones = [
        os.path.join(comfy_output_dir, subfolder, f"{base}*.mp4"),
        os.path.join(comfy_output_dir, "**", f"{base}*.mp4"),
    ]
    vistos: list[str] = []
    for pat in patrones:
        vistos.extend(glob.glob(pat, recursive=True))
    if not vistos:
        return None
    vistos = [p for p in set(vistos) if os.path.getsize(p) > 100_000]
    if not vistos:
        return None
    return max(vistos, key=os.path.getmtime)


def extract_last_frame(video_abs: str, out_abs: str) -> None:
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    subprocess.run(
        [ffmpeg_exe(), "-y", "-sseof", "-0.15", "-i", video_abs, "-frames:v", "1", "-q:v", "2", out_abs],
        check=True,
        capture_output=True,
    )


def _duration_seconds(video_abs: str) -> float:
    probe = subprocess.run([ffmpeg_exe(), "-i", video_abs], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr)
    if not m:
        raise RuntimeError(f"No pude leer duración de {video_abs}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def concat_videos(video_abs_list: list[str], out_abs: str, crossfade: float = 0.25) -> None:
    """Concatena múltiples chunks en un MP4 fluido (con fundido cruzado o copy directo)."""
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    n = len(video_abs_list)
    if n == 1:
        shutil.move(video_abs_list[0], out_abs)
        return

    ff = ffmpeg_exe()
    if crossfade > 0:
        durs = [_duration_seconds(v) for v in video_abs_list]
        cmd = [ff, "-y"]
        for v in video_abs_list:
            cmd += ["-i", v]
        fc = [f"[{i}:v]settb=AVTB[v{i}]" for i in range(n)]
        prev = "v0"
        offset = max(0.1, durs[0] - crossfade)
        total = durs[0]
        for i in range(1, n):
            total = total + durs[i] - crossfade
            out_lbl = "vout" if i == n - 1 else f"v0{i}"
            fc.append(f"[{prev}][v{i}]xfade=transition=fade:duration={crossfade}:offset={offset:.4f}[{out_lbl}]")
            prev = out_lbl
            offset = max(0.1, total - crossfade)

        has_audio = []
        for v in video_abs_list:
            p = subprocess.run([ff, "-i", v], capture_output=True, text=True)
            has_audio.append("Audio:" in p.stderr)

        audio_map: list[str] = []
        if all(has_audio):
            prev_a = "0:a"
            for i in range(1, n):
                out_lbl = "aout" if i == n - 1 else f"a0{i}"
                fc.append(f"[{prev_a}][{i}:a]acrossfade=d={crossfade}[{out_lbl}]")
                prev_a = out_lbl
            audio_map = ["-map", "[aout]"]

        cmd += [
            "-filter_complex",
            ";".join(fc),
            "-map",
            "[vout]",
            *audio_map,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "17",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            out_abs,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return

    list_file = out_abs + ".concat.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for v in video_abs_list:
            safe_v = v.replace("'", "'\\''")
            f.write(f"file '{safe_v}'\n")
    try:
        subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out_abs], check=True, capture_output=True)
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)


def probe_video(video_abs: str) -> dict[str, Any]:
    if not os.path.isfile(video_abs):
        return {}
    size_mb = round(os.path.getsize(video_abs) / (1024 * 1024), 2)
    ffp = ffprobe_exe()
    if ffp:
        try:
            r = subprocess.run(
                [
                    ffp,
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    video_abs,
                ],
                capture_output=True,
                text=True,
                timeout=8,
            )
            info = json.loads(r.stdout or "{}")
            streams = info.get("streams") or []
            v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
            fmt = info.get("format") or {}
            fps_val = None
            if v_stream and v_stream.get("r_frame_rate") and "/" in v_stream["r_frame_rate"]:
                num, den = v_stream["r_frame_rate"].split("/", 1)
                if float(den) > 0:
                    fps_val = round(float(num) / float(den), 2)
            return {
                "size_mb": size_mb,
                "width": v_stream.get("width") if v_stream else None,
                "height": v_stream.get("height") if v_stream else None,
                "fps": fps_val,
                "duration": round(float(fmt.get("duration", 0)), 2) if fmt.get("duration") else None,
                "video_codec": v_stream.get("codec_name") if v_stream else None,
                "has_audio": a_stream is not None,
                "audio_codec": a_stream.get("codec_name") if a_stream else None,
            }
        except Exception:
            pass
    return {"size_mb": size_mb}


def ws_url_for(comfy_url: str, client_id: str) -> str:
    p = urllib.parse.urlparse(comfy_url)
    scheme = "wss" if p.scheme == "https" else "ws"
    return f"{scheme}://{p.netloc}/ws?clientId={client_id}"
