"""Cola de generación LTX-2.5 — concurrencia 1 con progreso WebSocket en tiempo real y multi-chunk."""

from __future__ import annotations

import datetime
import json
import os
import shutil
import threading
import time
import uuid
from typing import Any, Callable

from . import ltx_comfy, store

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
DATA = os.path.join(ROOT, "data")
BENCH = os.path.join(DATA, "bench.json")
POLL_INTERVAL = 2.0
CLIENT_ID = f"ltx25-dash-{uuid.uuid4().hex[:10]}"

_running = False
_paused = False
_thread: threading.Thread | None = None
_ws_thread: threading.Thread | None = None
_lock = threading.Lock()
_config_getter: Callable[[], dict[str, Any]] | None = None

_live_lock = threading.Lock()
_live_state: dict[str, dict[str, Any]] = {}


def set_config_getter(fn: Callable[[], dict[str, Any]]) -> None:
    global _config_getter
    _config_getter = fn


def _cfg() -> dict[str, Any]:
    if _config_getter is not None:
        return _config_getter()
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def _bench() -> dict[str, float]:
    try:
        with open(BENCH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _bench_key(job: dict[str, Any]) -> str:
    st = "2s" if job.get("two_stage", True) else "1s"
    vae = job.get("vae_mode", "diff")
    return f"{job.get('preset','704p')}|{job.get('duration',5)}s|{st}|{vae}"


def _bench_put(key: str, seconds: float) -> None:
    b = _bench()
    cur = b.get(key)
    b[key] = round(seconds, 1) if cur is None else round((cur * 2 + seconds) / 3, 1)
    os.makedirs(DATA, exist_ok=True)
    try:
        with open(BENCH, "w", encoding="utf-8") as f:
            json.dump(b, f, indent=2)
    except OSError:
        pass


def counts() -> dict[str, Any]:
    items = store.load_history()
    return {
        "active": len([j for j in items if j.get("status") == "running"]),
        "pending": len([j for j in items if j.get("status") == "pending"]),
        "done": len([j for j in items if j.get("status") == "success"]),
        "failed": len([j for j in items if j.get("status") == "failed"]),
        "cancelled": len([j for j in items if j.get("status") == "cancelled"]),
        "paused": _paused,
    }


def _ws_loop() -> None:
    try:
        import websocket  # websocket-client
    except Exception:
        return

    current_prompt_id: str | None = None
    while _running:
        comfy_url = _cfg().get("comfyui_url", "http://127.0.0.1:8188")
        ws_url = ltx_comfy.ws_url_for(comfy_url, CLIENT_ID)
        try:
            ws = websocket.WebSocket()
            ws.settimeout(5.0)
            ws.connect(ws_url)
            while _running:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw or not isinstance(raw, str):
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                data = msg.get("data") or {}
                pid = data.get("prompt_id") or current_prompt_id

                if mtype == "execution_start" and data.get("prompt_id"):
                    current_prompt_id = data["prompt_id"]
                    with _live_lock:
                        _live_state[current_prompt_id] = {
                            "stage": "Iniciando grafo en ComfyUI...",
                            "step": 0,
                            "max": 0,
                            "node": None,
                            "pct": 3,
                        }
                elif mtype == "executing":
                    if data.get("prompt_id"):
                        current_prompt_id = data["prompt_id"]
                    pid = data.get("prompt_id") or current_prompt_id
                    node = data.get("node")
                    if pid and node:
                        title = ltx_comfy.MINIMAX_NODE_TITLES.get(str(node)) or ltx_comfy.NODE_TITLES.get(str(node), f"Nodo {node}")
                        pct_hint = None
                        if str(node) in ("1", "2", "3", "4"):
                            pct_hint = 6
                        elif str(node) in ("5", "6", "7", "8", "9", "10", "11", "12", "13", "14"):
                            pct_hint = 12
                        elif str(node) in ("20", "21", "22", "23", "24"):
                            pct_hint = 58
                        elif str(node) in ("30", "31"):
                            pct_hint = 90
                        elif str(node) in ("32", "33"):
                            pct_hint = 95
                        elif str(node) == "34":
                            pct_hint = 97
                        with _live_lock:
                            st = _live_state.setdefault(pid, {})
                            st["node"] = str(node)
                            st["stage"] = title
                            if pct_hint is not None:
                                st["pct"] = max(int(st.get("pct") or 0), pct_hint)
                            st["step"] = 0
                            st["max"] = 0
                elif mtype == "progress":
                    pid = data.get("prompt_id") or current_prompt_id
                    if pid:
                        val = int(data.get("value") or 0)
                        mx = max(int(data.get("max") or 1), 1)
                        node = str(data.get("node") or "")
                        with _live_lock:
                            st = _live_state.setdefault(pid, {})
                            st["step"] = val
                            st["max"] = mx
                            if node == "10":
                                st["pct"] = round(15 + (val / mx) * 72)
                                st["stage"] = f"MiniMax H3 · Sampling ({val}/{mx})"
                            elif node == "19":
                                st["pct"] = round(15 + (val / mx) * 40)
                                st["stage"] = f"Etapa 1 · Sampling ({val}/{mx})"
                            elif node == "29":
                                st["pct"] = round(60 + (val / mx) * 28)
                                st["stage"] = f"Etapa 2 · Refinado HD ({val}/{mx})"
                            else:
                                st["stage"] = f"{st.get('stage', 'Procesando')} ({val}/{mx})"
                elif mtype in ("execution_success", "execution_error") and pid:
                    with _live_lock:
                        st = _live_state.setdefault(pid, {})
                        st["stage"] = "Completado" if mtype == "execution_success" else "Error"
                        if mtype == "execution_success":
                            st["pct"] = 99
            ws.close()
        except Exception:
            time.sleep(3.0)


def enrich_job(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("status") != "running":
        return job
    if job.get("started_ts"):
        elapsed = max(0.0, time.time() - float(job["started_ts"]))
        job["elapsed"] = round(elapsed, 1)
        est_single = _bench().get(_bench_key(job))
        total_chunks = max(int(job.get("chunks") or 1), 1)
        est = est_single * total_chunks if est_single else None
        job["eta"] = round(max(est - elapsed, 0), 0) if est else None
    else:
        elapsed = 0.0
        est = None

    pid = job.get("prompt_id")
    live = None
    if pid:
        with _live_lock:
            live = dict(_live_state.get(pid) or {})

    total_chunks = max(int(job.get("chunks") or 1), 1)
    chunk_idx = max(int(job.get("chunk_idx") or 1), 1)
    if live and (live.get("stage") or live.get("pct") is not None):
        raw_pct = float(live.get("pct") or 5)
        if not job.get("two_stage", True) and str(live.get("node") or "") == "19":
            mx = max(float(live.get("max") or 8), 1.0)
            st_val = float(live.get("step") or 0)
            raw_pct = 15 + (st_val / mx) * 72
        chunk_pct = ((chunk_idx - 1) + raw_pct / 100.0) / total_chunks * 100.0
        job["progress"] = min(99, max(2, round(chunk_pct)))
        prefix = f"[Chunk {chunk_idx}/{total_chunks}] " if total_chunks > 1 else ""
        job["stage"] = prefix + str(live.get("stage") or "Generando...")
        job["step"] = live.get("step") or 0
        job["max_steps"] = live.get("max") or 0
    elif est:
        job["progress"] = min(99, round(elapsed / est * 100))
        job["stage"] = job.get("stage") or "En ComfyUI..."
    return job


def _submit_chunk(job: dict[str, Any], image_path: str | None) -> str:
    cfg = _cfg()
    comfy_url = cfg["comfyui_url"]
    engine = (job.get("model_engine") or cfg.get("model_engine", "ltx25")).lower()

    chunk_idx = int(job.get("chunk_idx") or 1)
    base_seed = int(job.get("seed") or 0)
    if base_seed <= 0:
        base_seed = int(time.time() * 1000) % (2**62)
        job["seed"] = base_seed
    chunk_seed = (base_seed + (chunk_idx - 1) * 997) % (2**62)

    if engine == "minimax_h3" or "minimax" in engine:
        uploaded_first = None
        uploaded_last = None
        if job.get("task") != "t2v":
            if image_path:
                uploaded_first = ltx_comfy.upload_image(comfy_url, image_path)
            last_img = job.get("last_image")
            if last_img and os.path.isfile(last_img):
                uploaded_last = ltx_comfy.upload_image(comfy_url, last_img)

        # Minimax frame snapping (17k + 5)
        raw_len = int(job.get("length") or 124)
        while raw_len % 17 != 5:
            raw_len += 1

        mm_unet = job.get("unet_name") or ""
        if not mm_unet or "ltx" in mm_unet.lower():
            mm_unet = cfg.get("minimax_unet_name", "minimax_h3_fl2va_pruned_int8_convrot.safetensors")
        mm_clip = job.get("clip_name") or ""
        if not mm_clip or "gemma" in mm_clip.lower() or "ltx" in mm_clip.lower():
            mm_clip = cfg.get("minimax_clip_name", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")

        wf = ltx_comfy.build_minimax_workflow(
            unet_name=mm_unet,
            clip_name=mm_clip,
            video_vae_name=cfg.get("minimax_video_vae_name", "minimax_h3_video_vae_fp16.safetensors"),
            audio_vae_name=cfg.get("minimax_audio_vae_name", "minimax_h3_audio_vae_fp32.safetensors"),
            prompt=job.get("prompt") or "",
            negative_prompt=job.get("negative_prompt") or cfg.get("default_negative_prompt", ""),
            width=int(job["width"]),
            height=int(job["height"]),
            length=raw_len,
            fps=int(job.get("fps") or 24),
            seed=chunk_seed,
            first_frame_name=uploaded_first,
            last_frame_name=uploaded_last,
            task=job.get("task") or "i2v",
            steps=int(job.get("steps") or cfg.get("minimax_default_steps", 25)),
            cfg=float(job.get("cfg") or cfg.get("minimax_default_cfg", 3.5)),
            shift_video=float(job.get("shift_video") or cfg.get("minimax_shift_video", 12.0)),
            shift_audio=float(job.get("shift_audio") or cfg.get("minimax_shift_audio", 3.0)),
            include_audio=bool(job.get("include_audio", True)),
            crf=int(job.get("crf", cfg.get("default_crf", 17))),
            prefix=f"minimax/{job['id'][:10]}_c{chunk_idx}",
        )
    else:
        two_stage = bool(job.get("two_stage", True))
        vae_mode = job.get("vae_mode", "diff")
        video_vae = cfg["video_vae_conv_name"] if vae_mode == "conv" else cfg["video_vae_name"]

        uploaded_name = None
        if job.get("task") != "t2v" and image_path:
            uploaded_name = ltx_comfy.upload_image(comfy_url, image_path)

        ltx_unet = job.get("unet_name") or ""
        if not ltx_unet or "minimax" in ltx_unet.lower():
            ltx_unet = cfg["unet_name"]
        ltx_clip = job.get("clip_name") or ""
        if not ltx_clip or "qwen" in ltx_clip.lower():
            ltx_clip = cfg["clip_name"]

        wf = ltx_comfy.build_workflow(
            unet_name=ltx_unet,
            clip_name=ltx_clip,
            video_vae_name=video_vae,
            audio_vae_name=cfg["audio_vae_name"],
            upscale_model_name=cfg["upscale_model_name"],
            prompt=job.get("prompt") or "",
            negative_prompt=job.get("negative_prompt") or cfg.get("default_negative_prompt", ""),
            width=int(job["width"]),
            height=int(job["height"]),
            length=int(job["length"]),
            fps=int(job.get("fps") or 24),
            seed=chunk_seed,
            two_stage=two_stage,
            image_name=uploaded_name,
            task=job.get("task") or "i2v",
            i2v_strength=float(job.get("i2v_strength", 0.7)),
            stage2_strength=float(job.get("stage2_strength", 1.0)),
            include_audio=bool(job.get("include_audio", True)),
            img_compression=int(job.get("img_compression", cfg.get("default_img_compression", 18))),
            crf=int(job.get("crf", cfg.get("default_crf", 17))),
            prefix=f"ltx25/{job['id'][:10]}_c{chunk_idx}",
        )

    pid = ltx_comfy.submit(comfy_url, wf, CLIENT_ID)
    with _live_lock:
        _live_state[pid] = {"stage": "En cola de ComfyUI...", "step": 0, "max": 0, "node": None, "pct": 2}
    return pid


def _submit_next_pending() -> None:
    items = store.load_history()
    pending = [j for j in items if j.get("status") == "pending"]
    if not pending:
        return
    job = pending[-1]
    job["status"] = "running"
    job["started_at"] = _now()
    job["started_ts"] = time.time()
    job["attempts"] = int(job.get("attempts", 0)) + 1
    job["chunk_idx"] = 1
    job["chunk_files"] = []
    job["error"] = None
    job["stage"] = "Enviando a ComfyUI..."
    store.upsert_job(job)

    try:
        pid = _submit_chunk(job, job.get("image"))
        job["prompt_id"] = pid
        store.upsert_job(job)
    except Exception as e:
        job["status"] = "failed"
        job["error"] = {"message": f"No se pudo enviar a ComfyUI: {e}"}
        job["completed_at"] = _now()
        store.upsert_job(job)


def _finalize_success(job: dict[str, Any]) -> None:
    md = ltx_comfy.probe_video(job["output"])
    job["status"] = "success"
    job["outputs"] = [job["output"]]
    job["completed_at"] = _now()
    job["meta"] = md
    elapsed = round(time.time() - float(job.get("started_ts", time.time())), 1)
    job["elapsed"] = elapsed
    job["progress"] = 100
    job["stage"] = "Completado"
    total_chunks = max(int(job.get("chunks") or 1), 1)
    _bench_put(_bench_key(job), elapsed / total_chunks)
    store.upsert_job(job)


def _cleanup_chunks(job: dict[str, Any]) -> None:
    chunks_dir = os.path.join(_cfg()["output_dir"], ".chunks")
    for p in job.get("chunk_files") or []:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
    last_frame = os.path.join(chunks_dir, f"{job['id']}_last.jpg")
    if os.path.isfile(last_frame):
        try:
            os.remove(last_frame)
        except OSError:
            pass


def _process_running(job: dict[str, Any]) -> None:
    cfg = _cfg()
    comfy_url = cfg["comfyui_url"]
    comfy_out_dir = cfg["comfy_output_dir"]
    pid = job.get("prompt_id")

    if not pid:
        job["status"] = "failed"
        job["error"] = {"message": "Falta prompt_id del trabajo"}
        job["completed_at"] = _now()
        store.upsert_job(job)
        return

    try:
        st_str, outputs, err_msg = ltx_comfy.get_result(comfy_url, pid)
    except Exception:
        store.upsert_job(enrich_job(job))
        return

    if st_str is None:
        if not ltx_comfy.is_queued(comfy_url, pid):
            # Último chequeo por si acaba de moverse de queue a history entre calls
            try:
                st_str, outputs, err_msg = ltx_comfy.get_result(comfy_url, pid)
            except Exception:
                st_str = None
            if st_str is None:
                job["status"] = "failed"
                job["error"] = {"message": "El prompt desapareció de la cola de ComfyUI (¿se reinició ComfyUI?)"}
                job["completed_at"] = _now()
                _cleanup_chunks(job)
                store.upsert_job(job)
                return
        else:
            store.upsert_job(enrich_job(job))
            return

    if st_str != "success":
        job["status"] = "failed"
        job["error"] = {"message": err_msg or f"ComfyUI falló ({st_str})"}
        job["completed_at"] = _now()
        job["elapsed"] = round(time.time() - float(job.get("started_ts", time.time())), 1)
        _cleanup_chunks(job)
        store.upsert_job(job)
        return

    subfolder, filename = ltx_comfy.extract_video(outputs)
    if not filename:
        job["status"] = "failed"
        job["error"] = {"message": "ComfyUI terminó sin archivo MP4 en la salida"}
        job["completed_at"] = _now()
        _cleanup_chunks(job)
        store.upsert_job(job)
        return

    src_mp4 = ltx_comfy.resolve_comfy_output(comfy_out_dir, subfolder or "", filename)
    if not os.path.isfile(src_mp4):
        job["status"] = "failed"
        job["error"] = {"message": f"No se encontró el archivo generado en {src_mp4}"}
        job["completed_at"] = _now()
        _cleanup_chunks(job)
        store.upsert_job(job)
        return

    total_chunks = max(int(job.get("chunks") or 1), 1)
    chunk_idx = max(int(job.get("chunk_idx") or 1), 1)
    os.makedirs(os.path.dirname(job["output"]), exist_ok=True)

    if total_chunks == 1:
        shutil.move(src_mp4, job["output"])
        _finalize_success(job)
        return

    chunks_dir = os.path.join(cfg["output_dir"], ".chunks")
    os.makedirs(chunks_dir, exist_ok=True)
    chunk_dst = os.path.join(chunks_dir, f"{job['id']}_c{chunk_idx}.mp4")
    shutil.move(src_mp4, chunk_dst)
    chunk_files = list(job.get("chunk_files") or [])
    chunk_files.append(chunk_dst)
    job["chunk_files"] = chunk_files

    if chunk_idx < total_chunks:
        try:
            next_img = os.path.join(chunks_dir, f"{job['id']}_last.jpg")
            ltx_comfy.extract_last_frame(chunk_dst, next_img)
            job["chunk_idx"] = chunk_idx + 1
            job["task"] = "i2v"
            job["stage"] = f"Lanzando chunk {chunk_idx + 1}/{total_chunks}..."
            new_pid = _submit_chunk(job, next_img)
            job["prompt_id"] = new_pid
            store.upsert_job(job)
        except Exception as e:
            job["status"] = "failed"
            job["error"] = {"message": f"Error encadenando chunk {chunk_idx + 1}: {e}"}
            job["completed_at"] = _now()
            _cleanup_chunks(job)
            store.upsert_job(job)
        return

    # Último chunk recibido: concatenar
    try:
        job["stage"] = f"Concatenando {total_chunks} chunks con ffmpeg..."
        store.upsert_job(job)
        ltx_comfy.concat_videos(chunk_files, job["output"], crossfade=float(job.get("crossfade", 0.25)))
        _cleanup_chunks(job)
        _finalize_success(job)
    except Exception as e:
        job["status"] = "failed"
        job["error"] = {"message": f"Error concatenando chunks: {e}"}
        job["completed_at"] = _now()
        _cleanup_chunks(job)
        store.upsert_job(job)


def tick() -> dict[str, Any]:
    with _lock:
        if _paused:
            return counts()
        items = store.load_history()
        running = [j for j in items if j.get("status") == "running"]
        if running:
            _process_running(running[0])
        else:
            _submit_next_pending()
        return counts()


def _loop() -> None:
    while _running:
        try:
            tick()
        except Exception as e:
            print("LTX-2.5 queue tick error:", e)
        time.sleep(POLL_INTERVAL)


def start() -> None:
    global _running, _thread, _ws_thread
    if _running:
        return
    _running = True
    _recover()
    _ws_thread = threading.Thread(target=_ws_loop, daemon=True, name="ltx25-ws")
    _ws_thread.start()
    _thread = threading.Thread(target=_loop, daemon=True, name="ltx25-queue")
    _thread.start()


def _recover() -> None:
    comfy_url = _cfg().get("comfyui_url", "http://127.0.0.1:8188")
    for j in store.load_history():
        if j.get("status") != "running":
            continue
        pid = j.get("prompt_id")
        if pid and ltx_comfy.is_queued(comfy_url, pid):
            continue
        if pid:
            try:
                st, _, _ = ltx_comfy.get_result(comfy_url, pid)
                if st is not None:
                    continue
            except Exception:
                pass
        j["status"] = "failed"
        j["error"] = {"message": "Interrumpido (sesión reiniciada)"}
        j["completed_at"] = _now()
        store.upsert_job(j)


def pause() -> None:
    global _paused
    _paused = True


def resume() -> None:
    global _paused
    _paused = False


def cancel(job_id: str) -> None:
    rec = store.get_job(job_id)
    if rec and rec.get("prompt_id"):
        ltx_comfy.cancel_prompt(_cfg()["comfyui_url"], rec["prompt_id"])


def cancel_all() -> int:
    global _paused
    _paused = True
    comfy_url = _cfg().get("comfyui_url", "http://127.0.0.1:8188").rstrip("/")
    try:
        requests.post(f"{comfy_url}/interrupt", timeout=5)
    except Exception:
        pass
    try:
        requests.post(f"{comfy_url}/queue", json={"clear": True}, timeout=5)
    except Exception:
        pass
    count = store.cancel_all_pending()
    _paused = False
    return count
