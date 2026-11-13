"""Batch runner LTX-2.5 / MiniMax H3 — un video a la vez, reanudable, con recuperacion.

Subcomandos:
  plan     construye state.json desde /api/images
  tick     un paso: arranca o vigila UN render. Pensado para cron.
  status   resumen legible
  report   regenera informe markdown desde evidence.jsonl

Reglas: estado en disco, evidencia JSONL append-only, tick silencioso salvo hallazgo.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "http://127.0.0.1:8899"
COMFY = "http://127.0.0.1:8188"
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT_DIR = os.path.join(ROOT, "outputs", "batch")
# STATE por env: el lote viejo (state.json, 20 items MiniMax) y el plan largo de
# LTX con camara nueva (state_ltx_cam.json) tienen que poder convivir sin pisarse.
STATE = os.environ.get("LTXB_STATE") or os.path.join(BASE, "state.json")
EVID = os.environ.get("LTXB_EVID") or os.path.join(BASE, "evidence.jsonl")
PAUSA = os.path.join(BASE, "PAUSA.txt")
DONE_MARK = os.path.join(BASE, "COMPLETO.txt")
STUCK_MARK = os.path.join(BASE, "TRABADO.txt")
REPORT = os.path.join(BASE, "informe.md")

# --- parametros de campaña -------------------------------------------------
ENGINE_MAIN = os.environ.get("LTXB_ENGINE", "ltx25")
ENGINE_ALT = os.environ.get("LTXB_ENGINE_ALT", "minimax_h3")
DURATION = float(os.environ.get("LTXB_DURATION", "10"))
FPS = 24
PRESET = os.environ.get("LTXB_PRESET", "1280x704")
TWO_STAGE = os.environ.get("LTXB_TWO_STAGE", "0") == "1"
INCLUDE_AUDIO = os.environ.get("LTXB_AUDIO", "0") == "1"
SEED = int(os.environ.get("LTXB_SEED", "777000"))
MAX_ATTEMPTS = int(os.environ.get("LTXB_MAX_ATTEMPTS", "3"))
STALL_MIN = float(os.environ.get("LTXB_STALL_MIN", "40"))
BENCH_SHOTS = int(os.environ.get("LTXB_BENCH", "3"))

NEG_EXTRA = ("camera shake, handheld, fast pan, whip pan, zoom in, zoom out, dolly in, "
             "dolly out, push in, pull back, orbit, crane, tracking shot, focus pull, "
             "cut, jump cut, scene change, morphing, warping, flicker, "
             "text, watermark, subtitles, logo")

# Linea corta AL PRINCIPIO: es lo primero que se ve en la tarjeta del Studio (que
# trunca el prompt) y lo primero que lee el modelo. El bloque largo va al final.
STATIC_HEAD = (
    "Static locked-off camera, fixed framing: the shot holds the same distance, "
    "scale and framing from the first frame to the last, no zoom in or out, while "
    "the scene keeps its slow motion inside the frame. "
)

# El bloque de camara va al FINAL del prompt: es lo ultimo que lee el modelo y lo que
# mas pesa. Para ltx25 el negative no se usa (video_cfg=1.0, sin guia negativa): todo
# lo que haya que evitar tiene que estar dicho en positivo aca.
STATIC_BLOCK = (
    "STATIC CAMERA, FIXED FRAME. A locked-off tripod shot held rock-steady for the "
    "whole clip: constant focal length, constant distance to the subject, and the "
    "same framing, horizon and subject size from the first frame to the last frame. "
    "The camera does not zoom in or zoom out, does not push in and does not pull back; "
    "no dolly, no pan, no tilt, no crane, no orbit, no parallax, no handheld shake, "
    "no focus pull, no change of lens. "
    "Slow motion happens INSIDE the scene, never in the camera: drifting mist, gently "
    "flickering lights, soft floating particles and pollen, slow water ripples, very "
    "slow sway of leaves, cloth and macrame, light breathing slowly brighter and "
    "dimmer, smoke and dust drifting through the beams. The scene keeps living while "
    "the frame stays perfectly still. "
    "No cuts, no scene change, no new objects entering or leaving the frame, no "
    "morphing, no warping, no speed ramp, no reframing. "
    "Lighting direction, palette and exposure remain constant throughout. "
    "Photoreal cinematic, shallow depth of field, fine 35mm film grain."
)

_MOVE = re.compile(
    r"\b(slow|steady|gentle|smooth|fast)?\s*camera\s+"
    r"(dolly|pan|orbit|track|tracking|truck|crane|push|pull|zoom|fly|glide|move|movement)"
    r"[^.,;]*", re.I)
_MOVE2 = re.compile(
    r"\b(smooth|steady|arcing|gliding|constant)\s+"
    r"(steady\s+)?(camera\s+)?(motion|movement|speed|glide|arc)\b[^.,;]*", re.I)


def neutralize_camera(text: str) -> str:
    """Quita las ordenes de movimiento de camara del prompt de origen."""
    if not text:
        return ""
    t = _MOVE.sub("static locked-off camera", text)
    t = _MOVE2.sub("", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([.,;])", r"\1", t)
    return t.strip()


# --- http ------------------------------------------------------------------
def _req(url, data=None, method=None, timeout=30):
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def api_get(path, timeout=30):
    return _req(API + path, timeout=timeout)


def api_post(path, data=None, timeout=60):
    return _req(API + path, data=data if data is not None else {}, method="POST", timeout=timeout)


def comfy_get(path, timeout=20):
    return _req(COMFY + path, timeout=timeout)


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --- estado ----------------------------------------------------------------
def cargar_state():
    if not os.path.isfile(STATE):
        return {"creado": now(), "items": []}
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def guardar_state(st):
    """Escritura atomica con reintentos: en Windows el archivo queda bloqueado un
    instante si otro proceso (otro driver, un script, el indexador) lo esta leyendo,
    y un PermissionError aca mataba el driver entero en medio del lote."""
    tmp = STATE + ".tmp"
    payload = json.dumps(st, ensure_ascii=False, indent=1)
    ultimo = None
    for intento in range(10):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, STATE)
            return
        except (PermissionError, OSError) as e:
            ultimo = e
            time.sleep(0.3 + 0.2 * intento)
    raise ultimo


def registrar(evento, veredicto, nota="", datos=None, item=None):
    rec = {"ts": now(), "evento": evento, "veredicto": veredicto,
           "item": item, "nota": nota, "datos": datos or {}}
    with open(EVID, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# --- plan ------------------------------------------------------------------
def build_plan():
    d = api_get("/api/images", timeout=120)
    grupos = d.get("groups", [])
    items = []
    shots_orden = []
    for g in grupos:
        scene = g.get("scene") or "sin-escena"
        shot = g.get("shot") or "sin-shot"
        pa = neutralize_camera(g.get("prompt_a") or "")
        imgs = g.get("images") or []
        shots_orden.append((scene, shot, pa, imgs))

    def slug(s):
        s = re.sub(r"[^\w\s·-]", "", s, flags=re.U)
        s = re.sub(r"\s+", " ", s).strip()
        return s[:90] or "x"

    bench = 0
    for scene, shot, pa, imgs in shots_orden:
        if not imgs:
            continue
        # ordenar A primero
        imgs = sorted(imgs, key=lambda i: (i.get("role") != "A", i.get("name") or ""))
        for im in imgs:
            stem = os.path.splitext(im.get("name") or "x")[0]
            for eng in ([ENGINE_MAIN, ENGINE_ALT] if bench < BENCH_SHOTS else [ENGINE_MAIN]):
                items.append({
                    "id": f"{slug(scene)}|{slug(shot)}|{stem}|{eng}",
                    "scene": scene, "shot": shot,
                    "image": im.get("path"), "role": im.get("role"),
                    "engine": eng,
                    "prompt": (STATIC_HEAD + pa + "\n\n" + STATIC_BLOCK).strip(),
                    "negative": NEG_EXTRA,
                    "duration": DURATION, "fps": FPS, "preset": PRESET,
                    "two_stage": TWO_STAGE, "include_audio": INCLUDE_AUDIO,
                    "chunks": 1, "seed": SEED,
                    "status": "pendiente", "attempts": 0, "job_id": None,
                    "out": None, "dur_s": None, "error": None,
                    "bench": bench < BENCH_SHOTS,
                })
        bench += 1

    # el bench primero, pero cada imagen en ltx y despues minimax
    def _k(x):
        return (not x["bench"], x["scene"], x["shot"],
                os.path.basename(x["image"] or ""), x["engine"])
    items.sort(key=_k)
    st = {"creado": now(), "items": items,
          "config": {"preset": PRESET, "duration": DURATION, "fps": FPS,
                     "two_stage": TWO_STAGE, "audio": INCLUDE_AUDIO,
                     "engine_main": ENGINE_MAIN, "engine_alt": ENGINE_ALT}}
    guardar_state(st)

    # carpetas
    for it in items:
        dest = os.path.join(OUT_DIR, slug(it["scene"]), slug(it["shot"]), it["engine"])
        os.makedirs(dest, exist_ok=True)
    return st


# --- comfy -----------------------------------------------------------------
def _pid_en_puerto(puerto):
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=30, errors="replace").stdout
    except Exception:
        return None
    for line in out.splitlines():
        if f":{puerto} " in line and "LISTENING" in line.upper():
            parts = line.split()
            if parts and parts[-1].isdigit():
                return int(parts[-1])
    return None


COMFY_ARGS = os.environ.get(
    "LTXB_COMFY_ARGS",
    # --disable-dynamic-vram NO es opcional en esta maquina: con la gestion dinamica
    # por defecto ComfyUI stagea los pesos en un cache de disco ("fast_disk=True"),
    # NO descarga el text encoder antes del unet y el sampler se queda en 100-110 W
    # (23 GB de VRAM, sin avanzar). Con el flag: "fast_disk=False", full load,
    # 18-19 GB usables -> 350 W y 8 pasos en 12 s.
    # Contrapartida: acumula commit en RAM entre jobs -> el tick lo reinicia cuando
    # pasa de MAX_COMMIT_GB.
    "--listen 127.0.0.1 --port 8188 --disable-dynamic-vram --cache-none "
    "--preview-method none --reserve-vram 1"
)


def comfy_online():
    try:
        h = api_get("/api/health", timeout=15)
        return bool(h.get("comfy", {}).get("online"))
    except Exception:
        return False


DASH = r"C:\Users\Tolch\Documents\AI_Code\LTX-2.5_Dashboard"


def dashboard_online():
    try:
        api_get("/api/health", timeout=8)
        return True
    except Exception:
        return False


def subir_dashboard():
    """Levanta uvicorn del Studio si se cerro (run.bat/stop.bat lo matan por PID)."""
    py = os.path.join(DASH, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(py):
        return False, "no hay .venv en el Studio"
    log = os.path.join(BASE, "dashboard.log")
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    with open(log, "ab") as lf:
        subprocess.Popen([py, "-m", "uvicorn", "server.main:app",
                          "--host", "127.0.0.1", "--port", "8899"],
                         cwd=DASH, stdout=lf, stderr=lf, creationflags=flags)
    for _ in range(30):
        if dashboard_online():
            return True, "online"
        time.sleep(2)
    return False, "no respondio en 60s"


def subir_comfy():
    """Levanta ComfyUI con los flags afinados (cache-none: no coexisten TE y UNET)."""
    py = r"D:\ComfyUI\.venv\Scripts\python.exe"
    mp = r"D:\ComfyUI\main.py"
    if not (os.path.isfile(py) and os.path.isfile(mp)):
        return False, "ComfyUI no encontrado en D:\\ComfyUI"
    log = os.path.join(BASE, "comfy.log")
    args = [py, mp] + COMFY_ARGS.split()
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    env = os.environ.copy()
    for var in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(var, None)
    env["PATH"] = r"D:\ComfyUI\.venv\Scripts;" + env.get("PATH", "")
    with open(log, "ab") as lf:
        subprocess.Popen(args, cwd=r"D:\ComfyUI", stdout=lf, stderr=lf,
                         creationflags=flags, env=env)
    return True, "lanzado"


def reiniciar_comfy():
    """Mata ComfyUI (si vive) y lo vuelve a levantar con los flags afinados."""
    try:
        _req(COMFY + "/interrupt", data={}, method="POST", timeout=15)
    except Exception:
        pass
    pid = _pid_en_puerto(8188)
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True, timeout=60)
    time.sleep(8)
    ok, det = subir_comfy()
    if not ok:
        return False, det
    for _ in range(40):
        if comfy_online():
            return True, "online"
        time.sleep(5)
    return False, "no volvio online en 200s"


def cancelar_job(job_id):
    if not job_id:
        return
    try:
        api_post(f"/api/jobs/{job_id}/cancel", timeout=30)
    except Exception:
        pass
    time.sleep(3)


# --- verificacion del archivo ---------------------------------------------
def ffprobe_ok(path):
    exe = shutil.which("ffprobe")
    if not exe:
        return None, "ffprobe ausente"
    try:
        r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,nb_frames:format=duration",
                            "-of", "json", path],
                           capture_output=True, text=True, timeout=120, errors="replace")
        if r.returncode != 0:
            return None, (r.stderr or "ffprobe fallo")[:200]
        d = json.loads(r.stdout)
        dur = float(d.get("format", {}).get("duration") or 0)
        streams = d.get("streams") or [{}]
        w = streams[0].get("width")
        h = streams[0].get("height")
        return {"dur": dur, "w": w, "h": h}, ""
    except Exception as e:
        return None, str(e)[:200]


def destino(it):
    def slug(s):
        s = re.sub(r"[^\w\s·-]", "", s, flags=re.U)
        s = re.sub(r"\s+", " ", s).strip()
        return s[:90] or "x"
    # Se conserva el hash del nombre original: sin el, las variantes A y B del
    # mismo par colapsan al mismo archivo y una pisa a la otra.
    stem = os.path.splitext(os.path.basename(it["image"] or "x"))[0]
    # Sufijo opcional (p. ej. "-cam"): distingue en el nombre los clips del lote con
    # camara nueva de los viejos, que viven en la misma carpeta.
    sufijo = it.get("sufijo") or ""
    nombre = f"{stem}__{it['engine']}{sufijo}.mp4"
    return os.path.join(OUT_DIR, slug(it["scene"]), slug(it["shot"]), it["engine"], nombre)


def ubicar_salida(it, job):
    """Devuelve el mp4 del job, venga del dashboard o del output de ComfyUI."""
    cand = []
    if isinstance(job, dict):
        o = job.get("output")
        if o:
            cand.append(o)
        for x in (job.get("outputs") or []):
            cand.append(x if isinstance(x, str) else x.get("path"))
    for c in cand:
        if c and os.path.isfile(c) and os.path.getsize(c) > 20000:
            return c
    # fallback: buscar en el output de ComfyUI por prefijo del job id
    jid = (job or {}).get("id") or it.get("job_id") or ""
    pref = str(jid).replace("-", "")[:10]
    raiz = [r"E:\ComfyUI_store\output", r"D:\ComfyUI\output"]
    for base in raiz:
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for f in files:
                if f.endswith(".mp4") and (pref and pref in f) and os.path.getsize(os.path.join(dirpath, f)) > 20000:
                    return os.path.join(dirpath, f)
    return None


# --- tick ------------------------------------------------------------------
def lanzar(it):
    payload = {
        "task": "i2v",
        "model_engine": it["engine"],
        "image": it["image"],
        # Frame final sintetico (crop corrido del mismo still): fija el movimiento
        # de camara de punta a punta via LTXVAddGuide(frame_idx=-1).
        "last_image": it.get("last_image"),
        "guide_strength": float(it.get("guide_strength") or 0.7),
        "prompt": it["prompt"],
        "negative_prompt": it["negative"],
        "preset": it["preset"],
        "steps": it.get("steps"),
        "aspect": "auto",
        "duration": it["duration"],
        "fps": it["fps"],
        "two_stage": it["two_stage"],
        "vae_mode": "diff",
        "i2v_strength": 0.85,
        "stage2_strength": 1.0,
        "include_audio": it["include_audio"],
        "chunks": it["chunks"],
        "crossfade": 0.25,
        "seed": it["seed"],
        "crf": 17,
    }
    r = api_post("/api/generate", payload, timeout=120)
    jid = r.get("id") or (r.get("ids") or [None])[0]
    return jid, r


def comfy_ram_libre_gb():
    """RAM libre que reporta ComfyUI (para detectar que acumulo commit)."""
    try:
        st = comfy_get("/system_stats", timeout=8)
        s = st.get("system") or {}
        return float(s.get("ram_free") or 0) / (1024 ** 3)
    except Exception:
        return None


def tick(max_seconds=600, verbose=False):
    t0 = time.time()
    if os.path.isfile(PAUSA):
        return 0
    # El Studio se cierra con stop.bat / su ventana: si no responde, lo levanto.
    if not dashboard_online():
        ok, det = subir_dashboard()
        registrar("dashboard_revivido", "HALLAZGO" if ok else "ERROR", det)
        if not ok:
            print(f"LTX BATCH: el Studio no levanta ({det})")
            return 1
        print(f"LTX BATCH: el Studio estaba cerrado, lo levante ({det})")
    st = cargar_state()
    items = st.get("items", [])
    if not items:
        print("SIN PLAN: correr `plan` primero")
        return 2

    # ComfyUI con --disable-dynamic-vram acumula commit en RAM entre clips: cuando
    # queda poca RAM libre, el siguiente render se arrastra a 100 W. Si no hay nada
    # corriendo, lo reiniciamos para empezar limpio.
    if not any(i["status"] == "corriendo" for i in items):
        libre = comfy_ram_libre_gb()
        if libre is not None and libre < 8:
            ok, det = reiniciar_comfy()
            registrar("comfy_limpio", "HALLAZGO",
                      f"RAM libre {libre:.1f} GB -> reinicio: {det}")
            if verbose:
                print(f"LTX BATCH: RAM libre {libre:.1f} GB, ComfyUI reiniciado")

    hechos = [i for i in items if i["status"] == "hecho"]
    errores = [i for i in items if i["status"] == "error"]
    pend = [i for i in items if i["status"] in ("pendiente",)]
    corr = [i for i in items if i["status"] == "corriendo"]

    # --- 1. vigilar el que corre
    if corr:
        it = corr[0]
        try:
            jobs = api_get("/api/jobs", timeout=30).get("items", [])
        except Exception as e:
            print(f"LTX BATCH: dashboard sin respuesta ({e})")
            return 1
        job = next((j for j in jobs if j.get("id") == it.get("job_id")), None)
        if job is None:
            it["status"] = "pendiente"
            guardar_state(st)
            registrar("job_perdido", "ERROR", "el job desaparecio del dashboard", item=it["id"])
            print(f"LTX BATCH: job perdido, reintento -> {os.path.basename(it['image'] or '')}")
            return 0

        est = job.get("status")
        prog = job.get("progress")
        if est in ("done", "success", "completed"):
            src = ubicar_salida(it, job)
            if not src:
                it["status"] = "pendiente" if it["attempts"] < MAX_ATTEMPTS else "error"
                it["attempts"] += 1
                guardar_state(st)
                registrar("sin_archivo", "HALLAZGO", "done sin mp4 localizable", item=it["id"])
                print(f"LTX BATCH: done sin archivo -> {os.path.basename(it['image'] or '')}")
                return 0
            info, err = ffprobe_ok(src)
            if info is None or info.get("dur", 0) < it["duration"] * 0.5:
                it["attempts"] += 1
                it["status"] = "pendiente" if it["attempts"] < MAX_ATTEMPTS else "error"
                guardar_state(st)
                registrar("video_invalido", "HALLAZGO", f"dur={info}", item=it["id"])
                print(f"LTX BATCH: mp4 invalido ({err or info}) -> reintento")
                return 0
            dst = destino(it)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.move(src, dst)
            except Exception:
                shutil.copy2(src, dst)
            it["status"] = "hecho"
            it["out"] = dst
            it["dur_s"] = round(time.time() - it.get("t0", time.time()), 1)
            it["finished"] = now()
            # MiniMax deja a ComfyUI con ~60 GB de commit acumulados despues de un clip:
            # el siguiente se arrastra a 100 W. Marcamos para reiniciarlo antes de lanzar.
            st["_comfy_dirty"] = True
            guardar_state(st)
            registrar("render_ok", "OK", f"{info['w']}x{info['h']} {info['dur']:.1f}s",
                      datos={"out": dst, "seg": it["dur_s"], "engine": it["engine"]}, item=it["id"])
            if verbose:
                print(f"OK {it['dur_s']}s -> {dst}")
            return 0

        if est in ("failed", "error", "cancelled", "canceled", "interrupted"):
            it["attempts"] += 1
            it["status"] = "pendiente" if it["attempts"] < MAX_ATTEMPTS else "error"
            it["error"] = str(job.get("error"))[:300]
            guardar_state(st)
            registrar("render_error", "HALLAZGO", it["error"], item=it["id"])
            print(f"LTX BATCH: fallo (intento {it['attempts']}/{MAX_ATTEMPTS}) "
                  f"{os.path.basename(it['image'] or '')}: {it['error'][:120]}")
            return 0

        # sigue corriendo -> ¿trabado?
        sin_avance = time.time() - it.get("ultimo_cambio", time.time())
        if prog != it.get("ultimo_prog") or job.get("stage") != it.get("ultimo_stage"):
            it["ultimo_prog"] = prog
            it["ultimo_stage"] = job.get("stage")
            it["ultimo_cambio"] = time.time()
            it["aviso_ajeno"] = False
            guardar_state(st)
            return 0

        # Si hay trabajo AJENO en la cola, mi job esta esperando turno: eso no es
        # un atasco mio y reiniciar ComfyUI solo mataria el render del otro.
        ajenos = [j for j in jobs
                  if j.get("id") != it.get("job_id")
                  and j.get("status") in ("pending", "running")]
        if ajenos and sin_avance > STALL_MIN * 60:
            it["ultimo_cambio"] = time.time()
            if not it.get("aviso_ajeno"):
                it["aviso_ajeno"] = True
                registrar("cola_ajena", "SALTADO",
                          f"{len(ajenos)} jobs ajenos activos: mi job espera turno",
                          item=it["id"])
                print(f"LTX BATCH: mi job espera detras de {len(ajenos)} jobs ajenos "
                      f"(no reinicio nada)")
            guardar_state(st)
            return 0

        if sin_avance > STALL_MIN * 60:
            registrar("atasco", "HALLAZGO",
                      f"sin avance {int(sin_avance/60)} min en '{job.get('stage')}'",
                      item=it["id"])
            cancelar_job(it.get("job_id"))
            ok, det = reiniciar_comfy()
            it["attempts"] += 1
            it["status"] = "pendiente" if it["attempts"] < MAX_ATTEMPTS else "error"
            guardar_state(st)
            msg = (f"LTX BATCH: atasco de {int(sin_avance/60)} min, ComfyUI reiniciado "
                   f"({det}) -> reanudo desde ahi ({hechos.__len__()}/{len(items)} hechos)")
            print(msg)
            return 0
        if verbose:
            print(f"... {job.get('stage')} {prog}%")
        return 0

    # --- 2. nada corriendo: arrancar el proximo
    if not comfy_online():
        ok, det = reiniciar_comfy()
        if not ok:
            print(f"LTX BATCH: ComfyUI no levanta ({det})")
            return 1
        registrar("comfy_revivido", "HALLAZGO", det)

    if not pend:
        if not os.path.isfile(DONE_MARK) and not errores:
            with open(DONE_MARK, "w", encoding="utf-8") as f:
                f.write(f"completo {now()} · {len(hechos)} videos\n")
            print(f"LTX BATCH COMPLETO: {len(hechos)} videos en {OUT_DIR}")
        return 0

    it = pend[0]
    # ComfyUI quedo sucio despues del clip anterior. Reiniciar SIEMPRE cuesta ~8 min de
    # recarga; solo lo hacemos si la RAM libre que reporta ComfyUI bajo del umbral,
    # que es la senal de que acumulo commit y el proximo clip se arrastraria.
    if st.get("_comfy_dirty"):
        libre = comfy_ram_libre_gb()
        st["_comfy_dirty"] = False
        guardar_state(st)
        if libre is None or libre < 8:
            ok, det = reiniciar_comfy()
            registrar("comfy_limpio", "HALLAZGO",
                      f"RAM libre {libre if libre is None else round(libre,1)} GB -> reinicio ({det})",
                      item=it["id"])
            if verbose:
                print(f"LTX BATCH: ComfyUI reiniciado antes de lanzar (RAM {libre})")
    try:
        jid, raw = lanzar(it)
    except Exception as e:
        it["attempts"] += 1
        it["status"] = "error" if it["attempts"] >= MAX_ATTEMPTS else "pendiente"
        guardar_state(st)
        registrar("lanzar_fallo", "ERROR", str(e)[:300], item=it["id"])
        print(f"LTX BATCH: no se pudo encolar ({str(e)[:120]})")
        return 0
    if not jid:
        it["attempts"] += 1
        it["status"] = "error" if it["attempts"] >= MAX_ATTEMPTS else "pendiente"
        guardar_state(st)
        registrar("sin_job_id", "ERROR", str(raw)[:300], item=it["id"])
        print("LTX BATCH: el dashboard no devolvio id de job")
        return 0

    it["job_id"] = jid
    it["status"] = "corriendo"
    it["t0"] = time.time()
    it["ultimo_cambio"] = time.time()
    it["ultimo_prog"] = 0
    it["ultimo_stage"] = "encolado"
    it["started"] = now()
    guardar_state(st)
    registrar("lanzado", "OK", f"{it['engine']} {it['preset']} {it['duration']}s",
              datos={"job": jid}, item=it["id"])
    if verbose:
        print(f"lanzado {it['engine']}: {os.path.basename(it['image'] or '')}")
    return 0


# --- status / report -------------------------------------------------------
def status():
    st = cargar_state()
    items = st.get("items", [])
    from collections import Counter
    c = Counter(i["status"] for i in items)
    hechos = [i for i in items if i["status"] == "hecho"]
    seg = [i["dur_s"] for i in hechos if i.get("dur_s")]
    media = sum(seg) / len(seg) / 60 if seg else None
    print(f"total {len(items)} | " + " ".join(f"{k}={v}" for k, v in c.items()))
    por_eng = Counter(i["engine"] for i in hechos)
    print("hechos por motor:", dict(por_eng))
    if media:
        faltan = len([i for i in items if i["status"] in ("pendiente", "corriendo")])
        print(f"ritmo medio: {media:.1f} min/video -> restante ~{media*faltan/60:.1f} h")
    if os.path.isfile(PAUSA):
        print("PAUSADO (existe PAUSA.txt)")
    err = [i for i in items if i["status"] == "error"]
    for i in err[:10]:
        print(" error:", i["id"][:70], "|", (i.get("error") or "")[:90])
    return 0


def report():
    st = cargar_state()
    items = st.get("items", [])
    from collections import Counter
    c = Counter(i["status"] for i in items)
    lineas = [f"# Batch LTX-2.5 / MiniMax H3", "",
              f"Actualizado: {now()}  ", f"Total: {len(items)} videos  ",
              f"Estado: " + ", ".join(f"**{k}** {v}" for k, v in c.items()), ""]
    por_eng = Counter()
    for i in items:
        if i["status"] == "hecho":
            por_eng[i["engine"]] += 1
    if por_eng:
        lineas += ["## Producidos por motor", ""]
        for k, v in por_eng.items():
            lineas.append(f"- {k}: {v}")
        lineas.append("")
    ev = []
    if os.path.isfile(EVID):
        with open(EVID, encoding="utf-8") as f:
            ev = [json.loads(l) for l in f if l.strip()]
    hall = [e for e in ev if e["veredicto"] != "OK"]
    if hall:
        lineas += ["## Ultimos hallazgos", ""]
        for e in hall[-15:]:
            lineas.append(f"- `{e['ts'][:16]}` {e['evento']}: {e['nota'][:120]}")
    salida = "\n".join(lineas)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(salida + "\n")
    print(salida)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    p = sub.add_parser("tick")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--max-seconds", type=int, default=600)
    sub.add_parser("status")
    sub.add_parser("report")
    a = ap.parse_args()
    if a.cmd == "plan":
        st = build_plan()
        print(f"plan: {len(st['items'])} items · bench {sum(1 for i in st['items'] if i['bench'])}")
        return 0
    if a.cmd == "tick":
        # candado: el cron y un tick manual no pueden pisarse (2 renders a la vez)
        lock = os.path.join(BASE, "tick.lock")
        try:
            if os.path.isfile(lock):
                edad = time.time() - os.path.getmtime(lock)
                # el lock solo bloquea si su dueno sigue vivo: si el proceso murio
                # (kill, reinicio, crash) el archivo queda y frenaria 40 min al pedo
                try:
                    pid_lock = int(open(lock, encoding="utf-8").read().split()[0])
                except Exception:
                    pid_lock = 0
                vivo = False
                if pid_lock:
                    try:
                        os.kill(pid_lock, 0)
                        vivo = True
                    except OSError:
                        vivo = False
                if edad < 2400 and vivo:
                    return 0          # otro tick esta trabajando: silencio
            with open(lock, "w", encoding="utf-8") as f:
                f.write(f"{os.getpid()} {now()}\n")
        except Exception:
            pass
        try:
            # Un tick trabaja hasta agotar su presupuesto: vigila, archiva y relanza
            # el siguiente, para no dejar huecos muertos entre corridas del cron.
            fin = time.time() + a.max_seconds
            while time.time() < fin:
                r = tick(a.max_seconds, a.verbose)
                if r != 0:
                    return r
                st = cargar_state()
                if not any(i["status"] in ("pendiente", "corriendo") for i in st["items"]):
                    return 0
                # 6 s: el hueco entre clips es lo unico que se puede recortar sin tocar
                # calidad. Con 20 s se perdian ~1,3 h en las 336 tomas.
                time.sleep(6)
            return 0
        finally:
            try:
                os.remove(lock)
            except Exception:
                pass
    if a.cmd == "status":
        return status()
    if a.cmd == "report":
        return report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
