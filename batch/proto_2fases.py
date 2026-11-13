"""Prototipo 2 fases: N clips en UN solo prompt de ComfyUI con los loaders compartidos.

Hipotesis a medir: si el TE (14,6 GB) y el UNET (13,6 GB) se cargan UNA vez para
N clips en vez de una vez por clip, cada clip deberia bajar de ~236 s a ~180 s.

No toca el lote: escribe en prefijo `proto2f/` y no modifica state_*.json.

Uso:
  python proto_2fases.py --k 2                 # 2 clips de los ya hechos
  python proto_2fases.py --k 4 --dry            # solo arma el grafo y lo imprime
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.dirname(AQUI)
sys.path.insert(0, DASH)

import server.ltx_comfy as ltx  # noqa: E402

COMFY = "http://127.0.0.1:8188"
LOG_COMFY = os.path.join(AQUI, "comfy.log")
STATE = os.path.join(AQUI, "state_ltx_cam.json")
RES = os.path.join(AQUI, "proto_resultados.jsonl")

# nodos que se comparten entre todos los clips (los grandes)
LOADERS = {"1", "2", "3", "4"}
NEG = None  # se toma del item


def req(url, data=None, timeout=60):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(url, data=body, headers=h,
                               method="POST" if data is not None else "GET")
    with urllib.request.urlopen(r, timeout=timeout) as f:
        raw = f.read().decode()
    return json.loads(raw) if raw.strip() else {}


# --- config del dashboard (nombres de modelos) -------------------------------
def cfg_dashboard():
    h = req("http://127.0.0.1:8899/api/health", timeout=15)
    d = h["comfy"]["devices"][0]
    return {
        "unet": h["active_unet"],
        "clip": h["active_clip"],
        "vram_total": d["vram_total"],
    }


def cfg_modelos():
    """Nombres exactos como los usa queue.py (desde la config del server)."""
    import server.store as store
    c = store.load_config() if hasattr(store, "load_config") else {}
    return c


# --- merge de N grafos -------------------------------------------------------
def merge(grafos: list[dict]) -> tuple[dict, dict]:
    """Comparte loaders. Devuelve (grafo, mapa de prefijos por clip)."""
    out: dict = {}
    for nid, node in grafos[0].items():
        if nid in LOADERS:
            out[nid] = json.loads(json.dumps(node))
    prefijos = {}
    for i, g in enumerate(grafos, start=1):
        for nid, node in g.items():
            if nid in LOADERS:
                continue
            nn = {"class_type": node["class_type"], "inputs": {}, "_meta": node.get("_meta", {})}
            for k, v in node["inputs"].items():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                    ref = v[0]
                    nn["inputs"][k] = [ref if ref in LOADERS else f"c{i}_{ref}", v[1]]
                else:
                    nn["inputs"][k] = v
            out[f"c{i}_{nid}"] = nn
            if node["class_type"] == "SaveVideo":
                prefijos[i] = nn["inputs"]["filename_prefix"]
    return out, prefijos


def armar(items, k, prefix_base="proto2f"):
    w, h = preset_dims(items[0]["preset"])
    fps = int(items[0]["fps"])
    length = ltx.calc_frames(float(items[0]["duration"]), fps)
    grafos, meta = [], []
    for idx, it in enumerate(items, start=1):
        img1 = ltx.upload_image(COMFY, it["image"])
        img2 = None
        if it.get("last_image") and os.path.isfile(it["last_image"]):
            img2 = ltx.upload_image(COMFY, it["last_image"])
        g = ltx.build_workflow(
            unet_name=MODELOS["unet"], clip_name=MODELOS["clip"],
            video_vae_name=MODELOS["video_vae"], audio_vae_name=MODELOS["audio_vae"],
            upscale_model_name=MODELOS["upscale"],
            prompt=it["prompt"], negative_prompt=it.get("negative") or "",
            width=w, height=h, length=length, fps=fps,
            seed=int(it.get("seed") or 777000),
            two_stage=bool(it.get("two_stage", False)),
            image_name=img1, task="i2v",
            i2v_strength=float(it.get("i2v_strength") or 0.85),
            stage2_strength=1.0,
            include_audio=bool(it.get("include_audio", False)),
            img_compression=18, crf=17, video_cfg=1.0,
            prefix=f"{prefix_base}/c{idx:02d}",
            last_image_name=img2,
            guide_strength=float(it.get("guide_strength") or 0.7),
        )
        grafos.append(g)
        meta.append({"i": idx, "id": it["id"], "last": bool(img2), "nodos": len(g)})
    wf, pref = merge(grafos)
    return wf, meta, pref, (w, h, length, fps)


def preset_dims(preset: str):
    m = re.match(r"(\d+)\s*x\s*(\d+)", str(preset))
    if not m:
        return 1280, 704
    return int(m.group(1)), int(m.group(2))


def contar_log(desde_bytes):
    with open(LOG_COMFY, "rb") as f:
        f.seek(desde_bytes)
        txt = f.read().decode("utf-8", "replace")
    txt = txt.replace("\r", "\n")
    return {
        "te_loads": txt.count("Requested to load LTXAVTEModel_"),
        "unet_loads": len(re.findall(r"Requested to load LTXAV(?!TEModel)", txt)),
        "vae_loads": txt.count("Requested to load CausalDiffusionVAE"),
        "pasos": len(re.findall(r"\|\s*8/8", txt)),
        "prompt_exec": len(re.findall(r"Prompt executed in", txt)),
        "tam": len(txt),
    }


def esperar(pid, limite=3600):
    t0 = time.time()
    ultimo = None
    while time.time() - t0 < limite:
        h = req(f"{COMFY}/history/{pid}", timeout=30)
        if pid in h:
            return h[pid], time.time() - t0
        q = req(f"{COMFY}/queue", timeout=30)
        run = [x for x in q.get("queue_running", []) if x[1] == pid]
        pen = [x for x in q.get("queue_pending", []) if x[1] == pid]
        estado = "corriendo" if run else ("en cola" if pen else "?")
        if estado != ultimo:
            print(f"  [{time.time()-t0:6.1f}s] {estado}", flush=True)
            ultimo = estado
        time.sleep(5)
    raise TimeoutError("tiempo agotado")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--source", default="hecho", choices=["hecho", "pendiente"])
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--sin-guia", action="store_true",
                    help="no exigir last_image (por defecto se exige, como en produccion)")
    args = ap.parse_args()

    global MODELOS
    MODELOS = modelos()
    st = json.load(open(STATE, encoding="utf-8"))
    pool = [i for i in st["items"] if i["status"] == args.source]
    pool = [i for i in pool if i.get("image") and os.path.isfile(i["image"])]
    if not args.sin_guia:
        pool = [i for i in pool if i.get("last_image") and os.path.isfile(i["last_image"])]
    sel = pool[args.skip:args.skip + args.k]
    if len(sel) < args.k:
        sys.exit(f"no hay {args.k} items '{args.source}' (hay {len(pool)})")

    print(f"=== armando grafo para {args.k} clips ===")
    for it in sel:
        print("  -", it["shot"][:60], "| last:", bool(it.get("last_image")))
    wf, meta, pref, dims = armar(sel, args.k)
    print(f"dims {dims[0]}x{dims[1]} len={dims[2]} fps={dims[3]}  nodos en el grafo: {len(wf)}")

    if args.dry:
        with open(os.path.join(AQUI, "proto_grafo.json"), "w", encoding="utf-8") as f:
            json.dump(wf, f, indent=1, ensure_ascii=False)
        print("grafo en proto_grafo.json; no se envio nada")
        # chequeo: todos los links apuntan a nodos existentes
        faltan = []
        for nid, n in wf.items():
            for k, v in n["inputs"].items():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in wf:
                    faltan.append((nid, k, v[0]))
        print("links rotos:", faltan or "ninguno")
        return

    antes = os.path.getsize(LOG_COMFY)
    pid = ltx.submit(COMFY, wf, "proto2f")
    print(f"prompt_id {pid[:8]} enviado; esperando...", flush=True)
    t0 = time.time()
    hist, _ = esperar(pid)
    dur = time.time() - t0
    marca = contar_log(antes)

    status = hist.get("status", {})
    print(f"\n=== resultado: {status.get('status_str')} en {dur:.1f}s "
          f"({dur/args.k:.1f}s por clip) ===")
    print(f"cargas en el log: TE={marca['te_loads']}  UNET={marca['unet_loads']}  "
          f"VAE={marca['vae_loads']}  samplers completos={marca['pasos']}")
    if status.get("status_str") != "success":
        msgs = [m for m in status.get("messages", []) if m[0] in ("execution_error", "execution_interrupted")]
        print("ERROR:", json.dumps(msgs, ensure_ascii=False)[:1500])

    salidas = []
    for nid, o in (hist.get("outputs") or {}).items():
        for cat, lst in o.items():
            for it in lst:
                if isinstance(it, dict) and it.get("filename"):
                    salidas.append(f"{it.get('subfolder','')}/{it['filename']}")
    print("salidas:", salidas)
    rec = {"ts": time.strftime("%F %T"), "k": args.k, "dur": round(dur, 1),
           "por_clip": round(dur / args.k, 1), "status": status.get("status_str"),
           "cargas": marca, "salidas": salidas, "items": [m["id"] for m in meta]}
    with open(RES, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def modelos():
    """Nombres de modelos que usa el dashboard (server/config.json)."""
    try:
        with open(os.path.join(DASH, "server", "config.json"), encoding="utf-8") as f:
            c = json.load(f)
        return {
            "unet": c["unet_name"], "clip": c["clip_name"],
            "video_vae": c["video_vae_name"], "audio_vae": c["audio_vae_name"],
            "upscale": c["upscale_model_name"],
        }
    except Exception as e:
        print("no pude leer la config del server:", e)
        h = req("http://127.0.0.1:8899/api/health", timeout=15)
        return {"unet": h["active_unet"], "clip": h["active_clip"],
                "video_vae": "ltx-2.5-video-vae-bf16.safetensors",
                "audio_vae": "ltx-2.5-audio-vae-bf16.safetensors",
                "upscale": "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"}


if __name__ == "__main__":
    main()
