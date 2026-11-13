"""LTX-2.5 Studio Dashboard — Backend FastAPI para ComfyUI (GGUF + Gemma4 + A/V).

Puerto por defecto: 8899 (ComfyUI en 8188).
Soporta generación por lotes por carpetas/categorías (I2V), Text-to-Video (T2V),
pipeline 2-Stage Distilled (8+3 pasos) y 1-Stage rápido, DiffVAE/ConvVAE,
audio sincronizado nativo, extensión multi-chunk y progreso WebSocket en vivo.
"""

from __future__ import annotations

import ctypes
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from typing import Any
from urllib.parse import quote

import requests
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ltx_comfy, queue, store

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
WEB_DIR = os.path.join(ROOT, "web")
MODELS_DIR = os.path.join(ROOT, "models")
CONFIG_PATH = os.path.join(BASE, "config.json")

_cfg_lock = threading.Lock()
_img_cache: dict[str, tuple[int, tuple[int, int] | None]] = {}


def _load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


CONFIG: dict[str, Any] = _load_config()


def get_config() -> dict[str, Any]:
    with _cfg_lock:
        return dict(CONFIG)


def _save_config(patch: dict[str, Any]) -> dict[str, Any]:
    with _cfg_lock:
        CONFIG.update(patch)
        tmp = CONFIG_PATH + f".tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
        return dict(CONFIG)


queue.set_config_getter(get_config)

app = FastAPI(title="LTX-2.5 Studio Dashboard")


@app.on_event("startup")
def _startup() -> None:
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    queue.start()


def _now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("_")[:60] or "out"


def _natsort_key(text: str) -> list[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(text))]


def _to_media_url(abs_path: str) -> str | None:
    out_dir = get_config()["output_dir"]
    try:
        rel = os.path.relpath(abs_path, out_dir).replace("\\", "/")
        if rel.startswith(".."):
            return None
        return "/media/" + quote(rel)
    except Exception:
        return None


def _safe_join(root_dir: str, rel_path: str) -> str | None:
    if not root_dir:
        return None
    root_abs = os.path.abspath(root_dir)
    clean_rel = os.path.normpath(rel_path.replace("/", os.sep)).lstrip("\\/")
    full = os.path.abspath(os.path.join(root_abs, clean_rel))
    try:
        if os.path.commonpath([root_abs, full]) != root_abs:
            return None
    except ValueError:
        return None
    return full


def _cached_image_dims(path: str) -> tuple[int, int] | None:
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return None
    hit = _img_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    dims = ltx_comfy.image_dimensions(path)
    _img_cache[path] = (mtime, dims)
    return dims


def _ram_status() -> dict[str, Any]:
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return {
            "ram_total_gb": round(m.ullTotalPhys / (1024**3), 1),
            "ram_free_gb": round(m.ullAvailPhys / (1024**3), 1),
            "commit_free_gb": round(m.ullAvailPageFile / (1024**3), 1),
        }
    except Exception:
        return {}


def _find_model_path(subfolder: str, filename: str) -> str:
    candidates = [
        os.path.join(MODELS_DIR, subfolder, filename),
        os.path.join(r"E:\video_creator_minimax\models", subfolder, filename),
        os.path.join(r"D:\ComfyUI\models", subfolder, filename),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return candidates[0]


def _check_disk_models(cfg: dict[str, Any]) -> dict[str, Any]:
    required = {
        "unet": _find_model_path("diffusion_models", cfg["unet_name"]),
        "clip": _find_model_path("text_encoders", cfg["clip_name"]),
        "vae_diff": _find_model_path("vae", cfg["video_vae_name"]),
        "vae_conv": _find_model_path("vae", cfg["video_vae_conv_name"]),
        "audio_vae": _find_model_path("vae", cfg["audio_vae_name"]),
        "upscaler": _find_model_path("latent_upscale_models", cfg["upscale_model_name"]),
        "minimax_unet": _find_model_path("diffusion_models", cfg.get("minimax_unet_name", "minimax_h3_fl2va_pruned_int8_convrot.safetensors")),
        "minimax_clip": _find_model_path("text_encoders", cfg.get("minimax_clip_name", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")),
        "minimax_vvae": _find_model_path("vae", cfg.get("minimax_video_vae_name", "minimax_h3_video_vae_fp16.safetensors")),
        "minimax_avae": _find_model_path("vae", cfg.get("minimax_audio_vae_name", "minimax_h3_audio_vae_fp32.safetensors")),
    }
    status = {k: os.path.isfile(p) for k, p in required.items()}
    downloading = [os.path.basename(p) for p in required.values() if os.path.isfile(p + ".part")]
    has_any_vvae = status["vae_diff"] or status["vae_conv"]
    ltx_ready = status["unet"] and status["clip"] and status["audio_vae"] and has_any_vvae
    minimax_ready = status["minimax_unet"] and status["minimax_clip"] and status["minimax_vvae"] and status["minimax_avae"]
    ready = ltx_ready or minimax_ready
    missing = [os.path.basename(p) for k, p in required.items() if not status[k] and not (k == "vae_conv" and status["vae_diff"])]
    return {
        "ready": ready,
        "ltx_ready": ltx_ready,
        "minimax_ready": minimax_ready,
        "files": status,
        "missing": missing,
        "downloading": downloading,
    }


# ------------------------------------------------------------------- schemas
class GenerateReq(BaseModel):
    task: str = "i2v"                # "i2v" | "t2v"
    model_engine: str = "ltx25"      # "ltx25" | "minimax_h3"
    image: str = ""
    last_image: str | None = None
    category: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    preset: str = "704p"             # "512p" | "576p" | "704p" | "768p" | "1280x704" etc.
    aspect: str = "auto"             # "auto" | "16:9" | "9:16" | "1:1" | "4:3" | "3:4"
    duration: float = 5.0
    fps: int = 24
    two_stage: bool = True
    vae_mode: str = "diff"           # "diff" | "conv"
    i2v_strength: float = 0.7
    stage2_strength: float = 1.0
    include_audio: bool = True
    chunks: int = 1
    crossfade: float = 0.25
    seed: int = 0
    unet_name: str = ""
    steps: int | None = None
    cfg: float | None = None
    video_cfg: float = 1.0           # solo ltx25: 1.0 = sin guia negativa (destilado)
    guide_strength: float | None = None  # fuerza de la guia de ultimo frame
    crf: int = 17


class BatchItem(BaseModel):
    image: str
    last_image: str | None = None
    category: str = ""
    prompt: str | None = None
    model_engine: str | None = None


class BatchReq(BaseModel):
    model_engine: str = "ltx25"      # "ltx25" | "minimax_h3"
    images: list[str] = []
    items: list[BatchItem] = []
    category: str = ""
    prompt: str = ""
    use_category_prompts: bool = True
    negative_prompt: str = ""
    preset: str = "704p"
    aspect: str = "auto"
    duration: float = 5.0
    fps: int = 24
    two_stage: bool = True
    vae_mode: str = "diff"
    i2v_strength: float = 0.7
    stage2_strength: float = 1.0
    include_audio: bool = True
    chunks: int = 1
    crossfade: float = 0.25
    seed: int = 0
    unet_name: str = ""
    steps: int | None = None
    cfg: float | None = None
    guide_strength: float | None = None
    crf: int = 17


class ConcatReq(BaseModel):
    files: list[str]
    output_name: str = "concatenated_scene"
    crossfade: float = 0.25


class PromptsReq(BaseModel):
    prompts: dict[str, str]


class ConfigReq(BaseModel):
    images_dir: str | None = None
    unet_name: str | None = None
    clip_name: str | None = None
    default_negative_prompt: str | None = None
    default_vae_mode: str | None = None
    default_two_stage: bool | None = None
    default_preset: str | None = None
    default_duration: float | None = None


class OpenFolderReq(BaseModel):
    path: str = ""


# ------------------------------------------------------------------- status & hw
@app.get("/api/health")
def health() -> dict[str, Any]:
    cfg = get_config()
    out_dir = cfg["output_dir"]
    try:
        free_gb = round(shutil.disk_usage(out_dir).free / 1e9, 1)
    except Exception:
        free_gb = None
    comfy = ltx_comfy.ping_comfy(cfg["comfyui_url"])
    disk_models = _check_disk_models(cfg)
    ram = _ram_status()
    return {
        "ok": True,
        "time": time.time(),
        "port": cfg.get("port", 8899),
        "output_dir": out_dir,
        "images_dir": cfg.get("images_dir", ""),
        "free_gb": free_gb,
        "comfy": comfy,
        "models": disk_models,
        "ram": ram,
        "active_unet": cfg["unet_name"],
        "active_clip": cfg["clip_name"],
    }


@app.get("/api/gpu")
def gpu() -> dict[str, Any]:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=6,
        )
        line = out.stdout.strip().splitlines()[0]
        parts = [x.strip() for x in line.split(",")]
        return {
            "name": parts[0],
            "used_mb": int(parts[1]),
            "total_mb": int(parts[2]),
            "util": int(parts[3]),
            "temp": int(parts[4]) if len(parts) > 4 else None,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/models")
def models() -> dict[str, Any]:
    cfg = get_config()
    comfy_lists = ltx_comfy.list_comfy_models(cfg["comfyui_url"])

    def _scan_dir(sub: str, exts: tuple[str, ...]) -> list[str]:
        found = set()
        for base in [MODELS_DIR, r"E:\video_creator_minimax\models", r"D:\ComfyUI\models"]:
            p = os.path.join(base, sub)
            if os.path.isdir(p):
                for fn in os.listdir(p):
                    if fn.lower().endswith(exts):
                        found.add(fn)
        return sorted(list(found), key=_natsort_key)

    local = {
        "unets": _scan_dir("diffusion_models", (".gguf", ".safetensors")),
        "clips": _scan_dir("text_encoders", (".safetensors", ".gguf")),
        "vaes": _scan_dir("vae", (".safetensors",)),
        "upscalers": _scan_dir("latent_upscale_models", (".safetensors",)),
    }
    return {
        "local": local,
        "comfy": comfy_lists,
        "active": {
            "unet_name": cfg["unet_name"],
            "clip_name": cfg["clip_name"],
            "video_vae_name": cfg["video_vae_name"],
            "video_vae_conv_name": cfg["video_vae_conv_name"],
            "audio_vae_name": cfg["audio_vae_name"],
            "upscale_model_name": cfg["upscale_model_name"],
            "vae_mode": cfg.get("default_vae_mode", "diff"),
        },
        "comfy_sees_unet": cfg["unet_name"] in (comfy_lists["gguf_unets"] + comfy_lists["safetensors_unets"]),
        "comfy_sees_clip": cfg["clip_name"] in comfy_lists["clips"],
    }


@app.post("/api/comfy/free")
def comfy_free() -> dict[str, Any]:
    cfg = get_config()
    try:
        r = requests.post(
            f"{cfg['comfyui_url'].rstrip('/')}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=10,
        )
        r.raise_for_status()
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": str(e)})


@app.post("/api/comfy/start")
def comfy_start() -> dict[str, Any]:
    cfg = get_config()
    if ltx_comfy.ping_comfy(cfg["comfyui_url"]).get("online"):
        return {"ok": True, "already_running": True}
    comfy_dir = cfg.get("comfy_dir", r"D:\ComfyUI")
    py = os.path.join(comfy_dir, ".venv", "Scripts", "python.exe")
    main_py = os.path.join(comfy_dir, "main.py")
    if not (os.path.isfile(py) and os.path.isfile(main_py)):
        return JSONResponse(status_code=400, content={"ok": False, "error": f"No se encontró ComfyUI en {comfy_dir}"})
    subprocess.Popen(
        [py, main_py, "--listen", "127.0.0.1", "--port", "8188"],
        cwd=comfy_dir,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    return {"ok": True, "started": True}


# ------------------------------------------------------------------- images & prompts
@app.get("/api/images")
def images() -> dict[str, Any]:
    cfg = get_config()
    images_dir = cfg.get("images_dir", "")
    groups: list[dict[str, Any]] = []
    if not images_dir or not os.path.isdir(images_dir):
        return {"groups": groups, "root": images_dir, "exists": False}

    exts = (".jpg", ".jpeg", ".png", ".webp")

    # Detección de estructura de tomas (Flow-Nanobanana: Scene / Shot / A & B)
    has_shot_structure = False
    for _, dirs, _ in os.walk(images_dir):
        subdirs_lower = [d.lower() for d in dirs]
        if "a" in subdirs_lower and "b" in subdirs_lower:
            has_shot_structure = True
            break

    if has_shot_structure:
        for scene in sorted(os.listdir(images_dir), key=_natsort_key):
            scene_path = os.path.join(images_dir, scene)
            if not os.path.isdir(scene_path):
                continue
            for shot in sorted(os.listdir(scene_path), key=_natsort_key):
                shot_path = os.path.join(scene_path, shot)
                if not os.path.isdir(shot_path):
                    continue
                a_dir = os.path.join(shot_path, "A")
                b_dir = os.path.join(shot_path, "B")
                if not (os.path.isdir(a_dir) or os.path.isdir(b_dir)):
                    continue

                pa_file = os.path.join(shot_path, "prompt_A.txt")
                pb_file = os.path.join(shot_path, "prompt_B.txt")
                prompt_a = open(pa_file, encoding="utf-8", errors="ignore").read().strip() if os.path.isfile(pa_file) else ""
                prompt_b = open(pb_file, encoding="utf-8", errors="ignore").read().strip() if os.path.isfile(pb_file) else ""

                a_files = sorted([f for f in os.listdir(a_dir) if f.lower().endswith(exts)], key=_natsort_key) if os.path.isdir(a_dir) else []
                b_files = sorted([f for f in os.listdir(b_dir) if f.lower().endswith(exts)], key=_natsort_key) if os.path.isdir(b_dir) else []

                shot_imgs = []
                for idx, fn in enumerate(a_files):
                    p = os.path.join(a_dir, fn)
                    rel = os.path.relpath(p, images_dir).replace("\\", "/")
                    dims = _cached_image_dims(p)
                    w, h = dims if dims else (1280, 704)
                    pair_path = os.path.join(b_dir, b_files[min(idx, len(b_files) - 1)]) if b_files else None
                    shot_imgs.append({
                        "name": f"A · {fn}",
                        "path": p,
                        "url": f"/images/{quote(rel, safe='/')}",
                        "width": w,
                        "height": h,
                        "aspect": round(w / max(h, 1), 3),
                        "role": "A",
                        "pair_path": pair_path,
                        "shot": shot,
                        "scene": scene,
                        "prompt": prompt_a,
                    })
                for idx, fn in enumerate(b_files):
                    p = os.path.join(b_dir, fn)
                    rel = os.path.relpath(p, images_dir).replace("\\", "/")
                    dims = _cached_image_dims(p)
                    w, h = dims if dims else (1280, 704)
                    pair_path = os.path.join(a_dir, a_files[min(idx, len(a_files) - 1)]) if a_files else None
                    shot_imgs.append({
                        "name": f"B · {fn}",
                        "path": p,
                        "url": f"/images/{quote(rel, safe='/')}",
                        "width": w,
                        "height": h,
                        "aspect": round(w / max(h, 1), 3),
                        "role": "B",
                        "pair_path": pair_path,
                        "shot": shot,
                        "scene": scene,
                        "prompt": prompt_b or prompt_a,
                    })

                if shot_imgs:
                    groups.append({
                        "category": f"{scene} / {shot}",
                        "scene": scene,
                        "shot": shot,
                        "is_shot": True,
                        "prompt_a": prompt_a,
                        "prompt_b": prompt_b,
                        "a_count": len(a_files),
                        "b_count": len(b_files),
                        "images": shot_imgs,
                    })
        return {"groups": groups, "root": images_dir, "exists": True, "is_shots_catalog": True}

    # Escaneo estándar 1 nivel (Gio Visuals, etc.)
    root_imgs: list[dict[str, Any]] = []
    entries = sorted(os.listdir(images_dir), key=_natsort_key)
    for fn in entries:
        full = os.path.join(images_dir, fn)
        if os.path.isfile(full) and fn.lower().endswith(exts):
            dims = _cached_image_dims(full)
            w, h = dims if dims else (1280, 704)
            root_imgs.append({
                "name": fn,
                "path": full,
                "url": f"/images/{quote(fn)}",
                "width": w,
                "height": h,
                "aspect": round(w / max(h, 1), 3),
            })
        elif os.path.isdir(full):
            imgs = []
            for sub in sorted(os.listdir(full), key=_natsort_key):
                if not sub.lower().endswith(exts):
                    continue
                sub_full = os.path.join(full, sub)
                if not os.path.isfile(sub_full):
                    continue
                dims = _cached_image_dims(sub_full)
                w, h = dims if dims else (1280, 704)
                imgs.append({
                    "name": sub,
                    "path": sub_full,
                    "url": f"/images/{quote(fn)}/{quote(sub)}",
                    "width": w,
                    "height": h,
                    "aspect": round(w / max(h, 1), 3),
                })
            if imgs:
                groups.append({"category": fn, "images": imgs})

    if root_imgs:
        groups.insert(0, {"category": "(raíz)", "images": root_imgs})
    return {"groups": groups, "root": images_dir, "exists": True, "is_shots_catalog": False}


@app.get("/api/prompts")
def get_prompts() -> dict[str, Any]:
    pfile = get_config().get("prompts_file", os.path.join(ROOT, "data", "prompts.json"))
    try:
        with open(pfile, encoding="utf-8") as f:
            return {"prompts": json.load(f)}
    except (OSError, json.JSONDecodeError):
        return {"prompts": {}}


@app.post("/api/prompts")
def set_prompts(req: PromptsReq) -> dict[str, Any]:
    pfile = get_config().get("prompts_file", os.path.join(ROOT, "data", "prompts.json"))
    os.makedirs(os.path.dirname(pfile), exist_ok=True)
    tmp = pfile + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(req.prompts, f, ensure_ascii=False, indent=2)
    os.replace(tmp, pfile)
    return {"ok": True}


@app.get("/api/config")
def api_get_config() -> dict[str, Any]:
    return get_config()


@app.post("/api/config")
def api_set_config(req: ConfigReq) -> Any:
    patch: dict[str, Any] = {}
    if req.images_dir is not None:
        d = req.images_dir.strip().strip('"')
        if not os.path.isdir(d):
            return JSONResponse(status_code=400, content={"error": f"Carpeta no encontrada: {d}"})
        patch["images_dir"] = d
    if req.unet_name is not None and req.unet_name.strip():
        patch["unet_name"] = req.unet_name.strip()
    if req.clip_name is not None and req.clip_name.strip():
        patch["clip_name"] = req.clip_name.strip()
    if req.default_negative_prompt is not None:
        patch["default_negative_prompt"] = req.default_negative_prompt
    if req.default_vae_mode in ("diff", "conv"):
        patch["default_vae_mode"] = req.default_vae_mode
    if req.default_two_stage is not None:
        patch["default_two_stage"] = req.default_two_stage
    if req.default_preset is not None:
        patch["default_preset"] = req.default_preset
    if req.default_duration is not None:
        patch["default_duration"] = req.default_duration

    updated = _save_config(patch) if patch else get_config()
    return {"ok": True, "config": updated}


@app.get("/api/folder-presets")
def folder_presets() -> dict[str, Any]:
    candidates = [
        ("NOMADE · Flow-Nanobanana (418 imgs · 60 tomas)", r"C:\Users\Tolch\Documents\AI_Code\Nomade_Visuals\Flow-Nanobanana"),
        ("Gio Visuals · Primera tanda", r"D:\Proyectos_Activos\2026-12-08 Gio Visuals\Primera tanda imagenes"),
        ("Gio Visuals · Catálogo Web", r"D:\Proyectos_Activos\2026-12-08 Gio Visuals\Catalogo_web\assets\imagenes"),
        ("ComfyUI Input", r"D:\ComfyUI\input"),
        ("Imágenes Usuario", os.path.join(os.path.expanduser("~"), "Pictures")),
    ]
    valid = [{"label": lbl, "path": p} for lbl, p in candidates if os.path.isdir(p)]
    return {"presets": valid}


@app.post("/api/browse-folder")
def browse_folder() -> Any:
    try:
        import tkinter as tk
        from tkinter import filedialog

        cur = get_config().get("images_dir", "")
        initial = cur if cur and os.path.isdir(cur) else os.path.expanduser("~")
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(initialdir=initial, title="Seleccionar carpeta raíz con subcarpetas de imágenes")
        root.destroy()
        if not selected:
            return {"cancelled": True}
        selected = os.path.normpath(selected)
        _save_config({"images_dir": selected})
        return {"ok": True, "images_dir": selected}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"No se pudo abrir el selector: {e}"})


@app.post("/api/open-outputs")
def open_outputs(req: OpenFolderReq | None = None) -> dict[str, Any]:
    cfg = get_config()
    target = (req.path.strip() if req and req.path else "") or cfg["output_dir"]
    if os.path.isfile(target):
        subprocess.Popen(["explorer.exe", f'/select,"{os.path.abspath(target)}"'])
    elif os.path.isdir(target):
        subprocess.Popen(["explorer.exe", os.path.abspath(target)])
    else:
        os.makedirs(cfg["output_dir"], exist_ok=True)
        subprocess.Popen(["explorer.exe", os.path.abspath(cfg["output_dir"])])
    return {"ok": True}


# ------------------------------------------------------------------- generation
def _make_job(
    req: GenerateReq,
    image_path: str | None = None,
    category: str | None = None,
    prompt_override: str | None = None,
    last_image_path: str | None = None,
) -> dict[str, Any] | None:
    cfg = get_config()
    task = "t2v" if req.task == "t2v" else "i2v"
    img = (image_path if image_path is not None else req.image).strip()
    last_img = (last_image_path if last_image_path is not None else getattr(req, "last_image", None))
    if last_img:
        last_img = str(last_img).strip()

    if task == "i2v" and (not img or not os.path.isfile(img)):
        return None

    engine = (getattr(req, "model_engine", None) or cfg.get("model_engine", "ltx25")).lower()

    dims = _cached_image_dims(img) if (task == "i2v" and img) else None
    src_w, src_h = dims if dims else (1280, 704)
    fps = max(8, min(60, int(req.fps or cfg.get("default_fps", 24))))

    if "minimax" in engine:
        w, h = ltx_comfy.snap_dims(src_w, src_h, preset=req.preset, aspect=req.aspect, two_stage=False)
        length = ltx_comfy.calc_minimax_frames(req.duration, fps)
        real_s = round(length / fps, 2)
        tag_engine = "minimax"
        steps_val = int(req.steps or cfg.get("minimax_default_steps", 25))
        cfg_val = float(req.cfg or cfg.get("minimax_default_cfg", 3.5))
    else:
        w, h = ltx_comfy.snap_dims(src_w, src_h, preset=req.preset, aspect=req.aspect, two_stage=req.two_stage)
        length = ltx_comfy.calc_frames(req.duration, fps)
        real_s = ltx_comfy.real_seconds(length, fps)
        tag_engine = "ltx2s" if req.two_stage else "ltx1s"
        steps_val = None
        cfg_val = None

    chunks = max(1, min(12, int(req.chunks or 1)))
    cat_val = category if category is not None else req.category
    cat_slug = _slug(cat_val or ("text_to_video" if task == "t2v" else "sin_categoria"))
    prompt_val = (prompt_override if prompt_override is not None else req.prompt).strip()
    if not prompt_val:
        prompt_val = "Slow steady cinematic camera movement, realistic motion, crisp lighting"

    seed_val = int(req.seed or 0)
    if seed_val <= 0:
        seed_val = int(time.time() * 1000 + uuid.uuid4().int % 100000) % (2**62)

    job_id = uuid.uuid4().hex
    stem = _slug(os.path.splitext(os.path.basename(img))[0]) if img else _slug(prompt_val[:36])
    fname = f"{stem}_{w}x{h}_{req.duration:g}s_{tag_engine}_s{seed_val}_{job_id[:6]}.mp4"
    out_abs = os.path.join(cfg["output_dir"], cat_slug, fname)

    req_unet = (req.unet_name or "").strip()
    if "minimax" in engine:
        if not req_unet or "ltx" in req_unet.lower():
            resolved_unet = cfg.get("minimax_unet_name", "minimax_h3_fl2va_pruned_int8_convrot.safetensors")
        else:
            resolved_unet = req_unet
        resolved_clip = cfg.get("minimax_clip_name", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
    else:
        if not req_unet or "minimax" in req_unet.lower():
            resolved_unet = cfg["unet_name"]
        else:
            resolved_unet = req_unet
        resolved_clip = cfg["clip_name"]

    return {
        "id": job_id,
        "task": task,
        "model_engine": engine,
        "image": img if task == "i2v" else "",
        "image_name": os.path.basename(img) if img else "",
        "last_image": last_img if (last_img and os.path.isfile(last_img)) else None,
        "last_image_name": os.path.basename(last_img) if (last_img and os.path.isfile(last_img)) else None,
        "category": cat_val or ("Text-to-Video" if task == "t2v" else "General"),
        "prompt": prompt_val,
        "negative_prompt": req.negative_prompt or cfg.get("default_negative_prompt", ""),
        "preset": req.preset,
        "aspect": req.aspect or ("auto" if task == "i2v" else "16:9"),
        "width": w,
        "height": h,
        "fps": fps,
        "duration": req.duration,
        "length": length,
        "duration_real": round(real_s * chunks, 2),
        "two_stage": bool(req.two_stage),
        "vae_mode": req.vae_mode if req.vae_mode in ("diff", "conv") else cfg.get("default_vae_mode", "diff"),
        "i2v_strength": max(0.0, min(1.0, float(req.i2v_strength))),
        "guide_strength": max(0.0, min(1.0, float(
            req.guide_strength if req.guide_strength is not None
            else cfg.get("guide_strength", 0.7)))),
        "stage2_strength": max(0.0, min(1.0, float(req.stage2_strength))),
        "include_audio": bool(req.include_audio),
        "img_compression": int(cfg.get("default_img_compression", 18)),
        "crf": max(10, min(32, int(req.crf or cfg.get("default_crf", 17)))),
        "chunks": chunks,
        "crossfade": max(0.0, min(1.0, float(req.crossfade))),
        "seed": seed_val,
        "steps": steps_val,
        "cfg": cfg_val,
        "video_cfg": float(req.video_cfg or 1.0),
        "unet_name": resolved_unet,
        "clip_name": resolved_clip,
        "output": out_abs,
        "outputs": [],
        "status": "pending",
        "progress": 0,
        "stage": "En cola",
        "created_at": _now(),
        "completed_at": None,
        "error": None,
    }


@app.post("/api/generate")
def generate(req: GenerateReq) -> Any:
    job = _make_job(req)
    if job is None:
        return JSONResponse(status_code=400, content={"error": "Imagen no encontrada en disco"})
    store.upsert_job(job)
    queue.tick()
    return job


@app.post("/api/generate-batch")
def generate_batch(req: BatchReq) -> dict[str, Any]:
    created: list[str] = []
    skipped: list[str] = []
    cat_prompts: dict[str, str] = {}
    if req.use_category_prompts:
        cat_prompts = get_prompts().get("prompts") or {}

    base_req = GenerateReq(
        task="i2v",
        model_engine=req.model_engine,
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        preset=req.preset,
        aspect=req.aspect,
        duration=req.duration,
        fps=req.fps,
        two_stage=req.two_stage,
        vae_mode=req.vae_mode,
        i2v_strength=req.i2v_strength,
        stage2_strength=req.stage2_strength,
        include_audio=req.include_audio,
        chunks=req.chunks,
        crossfade=req.crossfade,
        seed=req.seed,
        steps=req.steps,
        cfg=req.cfg,
        unet_name=req.unet_name,
        crf=req.crf,
    )

    work_items: list[BatchItem] = list(req.items)
    if not work_items and req.images:
        work_items = [BatchItem(image=p, category=req.category, model_engine=req.model_engine) for p in req.images]

    for idx, item in enumerate(work_items):
        cat = item.category or req.category
        chosen_prompt = item.prompt
        if chosen_prompt is None or not chosen_prompt.strip():
            if req.use_category_prompts and cat:
                cat_key_norm = re.sub(r"[\s_-]+", "_", cat.strip().lower())
                match = cat_prompts.get(cat) or cat_prompts.get(cat.strip().lower())
                if not match:
                    for k, v in cat_prompts.items():
                        if re.sub(r"[\s_-]+", "_", k.strip().lower()) == cat_key_norm:
                            match = v
                            break
                chosen_prompt = match or req.prompt
            else:
                chosen_prompt = req.prompt

        per_seed = (req.seed + idx) if req.seed > 0 else 0
        item_engine = item.model_engine or req.model_engine
        item_req = base_req.model_copy(update={"seed": per_seed, "model_engine": item_engine, "last_image": item.last_image})
        job = _make_job(item_req, image_path=item.image, category=cat, prompt_override=chosen_prompt, last_image_path=item.last_image)
        if job is None:
            skipped.append(item.image)
            continue
        store.upsert_job(job)
        created.append(job["id"])

    queue.tick()
    return {"created": len(created), "skipped": skipped, "ids": created}


@app.post("/api/scenes/concat")
def concat_scene(req: ConcatReq) -> Any:
    cfg = get_config()
    files = [f for f in req.files if os.path.isfile(f)]
    if len(files) < 2:
        return JSONResponse(status_code=400, content={"error": "Se requieren al menos 2 videos para concatenar"})
    out_dir = os.path.join(cfg["output_dir"], "escenas_completas")
    os.makedirs(out_dir, exist_ok=True)
    out_name = _slug(req.output_name) or "escena_unida"
    stamp = int(time.time())
    dest = os.path.join(out_dir, f"{out_name}_{stamp}.mp4")
    try:
        if req.crossfade > 0.05 and len(files) <= 12:
            ltx_comfy.concatenate_chunks_crossfade(files, dest, crossfade_sec=req.crossfade)
        else:
            ltx_comfy.concatenate_chunks(files, dest)
        return {"ok": True, "output": dest, "url": _to_media_url(dest)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Error al concatenar videos: {e}"})


# ------------------------------------------------------------------- queue & jobs
_LOTE_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}


@app.get("/api/lote")
def lote_status() -> dict[str, Any]:
    """Progreso del LOTE real (batch/state_ltx_cam.json).

    El dashboard solo conoce los jobs que pasan por su cola; cuando el lote lo maneja
    un driver externo (batch_grupo.py, batch.py tick) sus contadores quedan clavados.
    Esto lee el state del lote y devuelve los numeros de verdad, con cache corta para
    no parsear 700 KB en cada poll.
    """
    import time as _t

    if _LOTE_CACHE["data"] is not None and _t.time() - _LOTE_CACHE["ts"] < 4:
        return _LOTE_CACHE["data"]

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ruta = os.environ.get("LTXB_STATE") or os.path.join(base, "batch", "state_ltx_cam.json")
    data: dict[str, Any] = {"ok": False, "archivo": ruta}
    try:
        with open(ruta, encoding="utf-8") as f:
            st = json.load(f)
        items = st.get("items") or []
        cnt: dict[str, int] = {}
        for it in items:
            cnt[it.get("status") or "?"] = cnt.get(it.get("status") or "?", 0) + 1
        hechos = [i for i in items if i.get("status") == "hecho"]
        segs = [float(i.get("dur_s")) for i in hechos if i.get("dur_s") and float(i.get("dur_s")) < 1200]
        ritmo = round(sum(segs) / len(segs), 1) if segs else None
        faltan = cnt.get("pendiente", 0) + cnt.get("corriendo", 0)
        hecho_ahora = [i for i in items if i.get("status") == "corriendo"]
        fin = [i.get("finished") for i in hechos if i.get("finished")]
        data = {
            "ok": True,
            "archivo": ruta,
            "total": len(items),
            "hecho": len(hechos),
            "pendiente": cnt.get("pendiente", 0),
            "corriendo": cnt.get("corriendo", 0),
            "error": cnt.get("error", 0),
            "pct": round(100.0 * len(hechos) / max(len(items), 1), 1),
            "ritmo_s": ritmo,
            "eta_h": round(ritmo * faltan / 3600.0, 1) if ritmo else None,
            "ultimo": max(fin) if fin else None,
            "en_curso": [
                {"shot": i.get("shot"), "camara": i.get("camara"), "rol": i.get("role")}
                for i in hecho_ahora[:8]
            ],
        }
    except Exception as e:  # noqa: BLE001
        data["error"] = str(e)[:200]
    _LOTE_CACHE.update({"ts": _t.time(), "data": data})
    return data


@app.get("/api/queue")
def queue_status() -> dict[str, Any]:
    return queue.counts()


@app.post("/api/queue/pause")
def queue_pause() -> dict[str, Any]:
    queue.pause()
    return {"ok": True}


@app.post("/api/queue/resume")
def queue_resume() -> dict[str, Any]:
    queue.resume()
    return {"ok": True}


@app.post("/api/queue/cancel-all")
def queue_cancel_all() -> dict[str, Any]:
    cnt = queue.cancel_all()
    return {"ok": True, "cancelled": cnt}


@app.get("/api/jobs")
def jobs(limit: int = 250) -> dict[str, Any]:
    items = store.load_history()[:limit]
    for j in items:
        j["urls"] = [u for u in (_to_media_url(o) for o in (j.get("outputs") or [])) if u]
        queue.enrich_job(j)
    return {"items": items}


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str) -> Any:
    rec = store.get_job(job_id)
    if not rec:
        return JSONResponse(status_code=404, content={"error": "not found"})
    if rec.get("status") == "pending":
        store.remove_job(job_id)
        return {"ok": True, "removed": True}
    queue.cancel(job_id)
    rec["status"] = "cancelled"
    rec["completed_at"] = _now()
    rec["stage"] = "Cancelado"
    store.upsert_job(rec)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def retry(job_id: str, new_seed: bool = False) -> Any:
    rec = store.get_job(job_id)
    if not rec:
        return JSONResponse(status_code=404, content={"error": "not found"})
    if new_seed:
        rec["seed"] = int(time.time() * 1000 + uuid.uuid4().int % 100000) % (2**62)

    cfg = get_config()
    engine = (rec.get("model_engine") or cfg.get("model_engine", "ltx25")).lower()
    if "minimax" in engine:
        u = rec.get("unet_name") or ""
        if not u or "ltx" in u.lower():
            rec["unet_name"] = cfg.get("minimax_unet_name", "minimax_h3_fl2va_pruned_int8_convrot.safetensors")
        c = rec.get("clip_name") or ""
        if not c or "gemma" in c.lower() or "ltx" in c.lower():
            rec["clip_name"] = cfg.get("minimax_clip_name", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
    else:
        u = rec.get("unet_name") or ""
        if not u or "minimax" in u.lower():
            rec["unet_name"] = cfg["unet_name"]
        c = rec.get("clip_name") or ""
        if not c or "qwen" in c.lower():
            rec["clip_name"] = cfg["clip_name"]

    rec["status"] = "pending"
    rec["error"] = None
    rec["prompt_id"] = None
    rec["completed_at"] = None
    rec["progress"] = 0
    rec["stage"] = "En cola (reintento)"
    store.upsert_job(rec)
    queue.tick()
    return {"ok": True, "job": rec}


@app.delete("/api/jobs/{job_id}")
def delete(job_id: str) -> dict[str, Any]:
    rec = store.get_job(job_id)
    if rec and rec.get("status") == "running":
        queue.cancel(job_id)
    store.remove_job(job_id)
    return {"ok": True}


@app.post("/api/jobs/clear")
def clear_finished() -> dict[str, Any]:
    removed = store.clear_jobs(("success", "failed", "cancelled"))
    return {"ok": True, "removed": removed}


# ------------------------------------------------------------------- dynamic media & images (always current!)
@app.get("/images/{rel_path:path}")
def serve_image(rel_path: str) -> Any:
    cfg = get_config()
    candidate_roots = [
        cfg.get("images_dir", ""),
        r"C:\Users\Tolch\Documents\AI_Code\Nomade_Visuals\Flow-Nanobanana",
        r"D:\Proyectos_Activos\2026-12-08 Gio Visuals\Catalogo_web\assets\imagenes",
    ]
    from urllib.parse import unquote
    unq = unquote(rel_path)
    for root in candidate_roots:
        if not root:
            continue
        for target in (unq, rel_path):
            full = _safe_join(root, target)
            if full and os.path.isfile(full):
                return FileResponse(full)
    return JSONResponse(status_code=404, content={"error": "image not found"})


@app.get("/media/{rel_path:path}")
def serve_media(rel_path: str) -> Any:
    out_dir = get_config()["output_dir"]
    full = _safe_join(out_dir, rel_path)
    if not full or not os.path.isfile(full):
        from urllib.parse import unquote
        full_unquoted = _safe_join(out_dir, unquote(rel_path))
        if full_unquoted and os.path.isfile(full_unquoted):
            return FileResponse(full_unquoted, media_type="video/mp4")
        return JSONResponse(status_code=404, content={"error": "media not found"})
    return FileResponse(full, media_type="video/mp4")


# Frontend estático (siempre último)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


@app.middleware("http")
async def _sin_cache_estaticos(request, call_next):
    """La UI se quedaba vieja en el navegador: app.js cacheado y el header con numeros
    del lote que nunca aparecian. Los estaticos de la app van sin cache."""
    resp = await call_next(request)
    ruta = request.url.path
    if ruta.endswith((".js", ".css", ".html")) or ruta == "/":
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
    return resp
