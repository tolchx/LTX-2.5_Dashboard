"""Driver de lote AGRUPADO: K clips en un solo prompt de ComfyUI.

Por que: medido en esta maquina, cada clip suelto cuesta ~236 s, de los cuales
~126 s son cargas completas (TE 14,6 GB + UNET 13,6 GB + VAE). Agrupando K clips
dentro de UN prompt, ComfyUI no hace el GC entre ramas: el TE y el UNET quedan
parcialmente residentes y el costo marginal baja a ~150 s. Medido con el
prototipo (mismo clip, misma semilla, salida verificada):

    K=2 -> 372,1 s  (186,1 s/clip)
    K=4 -> 728,5 s  (182,1 s/clip)
    suelto -> 236 s/clip  (mediana de 15 clips de produccion)

Uso (una corrida = un grupo, igual que `batch.py tick`):
    LTXB_GRUPO=4 python batch_grupo.py            # procesa un grupo y sale
    LTXB_GRUPO=4 python batch_grupo.py --dry      # arma el grupo y muestra los items

Estado: usa el mismo STATE que batch.py (LTXB_STATE) y el mismo formato de item;
marca cada item como "corriendo" con job_id "<prompt_id>#<idx>" y al terminar lo
pasa a "hecho" con out/dur_s, moviendo el mp4 a `destino(it)`.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.dirname(AQUI)
sys.path.insert(0, DASH)
sys.path.insert(0, AQUI)

import batch as B                     # noqa: E402  (reusa state, destino, registrar)
import proto_2fases as P              # noqa: E402  (build_workflow + merge)
import server.ltx_comfy as ltx        # noqa: E402

COMFY = "http://127.0.0.1:8188"
K = int(os.environ.get("LTXB_GRUPO", "4"))
MAX_S = float(os.environ.get("LTXB_GRUPO_MAX_S", "5400"))
TAG = time.strftime("%H%M%S")
N_GRUPO = [1]   # tamaño del grupo en curso (para dur_s por clip)


def items_compatibles(items, k, verbose=False):
    """K pendientes con la MISMA config (el grafo agrupado comparte loaders)."""
    pend = [i for i in items if i.get("status") == "pendiente"]
    if not pend:
        return []
    base = pend[0]
    clave = lambda i: (i.get("engine"), float(i.get("duration") or 0), int(i.get("fps") or 0),
                       str(i.get("preset")), bool(i.get("two_stage")), bool(i.get("include_audio")),
                       bool(i.get("last_image")))
    grupo = [i for i in pend if clave(i) == clave(base)]
    return grupo[:k]


def _pid_vivo(pid: int) -> bool:
    """True si el proceso existe. En Windows os.kill(pid,0) MATA el proceso: no usar."""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=15).stdout
        return str(pid) in out
    except Exception:
        return False


def salida_por_nodo(hist):
    """{indice_clip: ruta_absoluta_en_comfy} desde el history de ComfyUI."""
    out = {}
    for nid, o in (hist.get("outputs") or {}).items():
        if not isinstance(o, dict) or not str(nid).startswith("c"):
            continue
        idx = str(nid).split("_")[0][1:]
        for _cat, lst in o.items():
            for f in (lst or []):
                if isinstance(f, dict) and f.get("filename"):
                    sub = f.get("subfolder") or ""
                    ruta = os.path.join(r"D:\ComfyUI\output", sub, f["filename"])
                    out[int(idx)] = ruta
    return out


def finalizar(st, it, prompt_id, idx, verbose=False):
    """Mira el history y cierra el item: hecho / pendiente."""
    hist = {}
    try:
        h = ltx.requests.get(f"{COMFY}/history/{prompt_id}", timeout=20).json()
        hist = h.get(prompt_id) or {}
    except Exception as e:
        print("  sin history:", e)
    st_str = (hist.get("status") or {}).get("status_str")
    salidas = salida_por_nodo(hist) if hist else {}
    src = salidas.get(idx)
    if st_str == "success" and src and os.path.isfile(src) and os.path.getsize(src) > 20000:
        info, err = B.ffprobe_ok(src)
        if info is None or info.get("dur", 0) < float(it["duration"]) * 0.5:
            it["attempts"] = it.get("attempts", 0) + 1
            it["status"] = "pendiente" if it["attempts"] < B.MAX_ATTEMPTS else "error"
            it["error"] = f"mp4 invalido {info} {err}"
            B.registrar("grupo_video_invalido", "HALLAZGO", it["error"], item=it["id"])
            print(f"  invalido c{idx}: {info} {err}")
        else:
            dst = B.destino(it)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.move(src, dst)
            except Exception:
                shutil.copy2(src, dst)
            it["status"] = "hecho"
            it["out"] = dst
            t0_ = it.get("t0")
            n = max(int(N_GRUPO[0] or 1), 1)
            it["dur_s"] = (round((time.time() - t0_) / n, 1)
                           if isinstance(t0_, (int, float)) else None)
            it["finished"] = B.now()
            it.pop("job_id", None)
            B.registrar("grupo_render_ok", "OK", f"{info['w']}x{info['h']} {info['dur']:.1f}s",
                        datos={"out": dst, "seg": it["dur_s"], "grupo": K}, item=it["id"])
            print(f"  OK c{idx} {it['dur_s']}s -> {os.path.basename(dst)}")
    else:
        # antes de dar por fallado: si el mp4 ya esta en destino (otro driver lo
        # cerro), marcarlo hecho y no re-renderizar
        dst_ya = B.destino(it)
        if os.path.isfile(dst_ya) and os.path.getsize(dst_ya) > 20000:
            info_ya, _ = B.ffprobe_ok(dst_ya)
            if info_ya and info_ya.get("dur", 0) > float(it["duration"]) * 0.5:
                it["status"] = "hecho"
                it["out"] = dst_ya
                it["finished"] = B.now()
                it.pop("job_id", None)
                B.registrar("grupo_cerrado", "OK", "mp4 ya estaba en destino", item=it["id"])
                print(f"  OK c{idx} (ya estaba en destino)")
                return st
        it["attempts"] = it.get("attempts", 0) + 1
        err = ltx.extract_error_message(hist.get("status") or {}) if hist else "sin history"
        it["error"] = str(err)[:300]
        it["status"] = "pendiente" if it["attempts"] < B.MAX_ATTEMPTS else "error"
        it.pop("job_id", None)
        B.registrar("grupo_render_error", "HALLAZGO", it["error"], item=it["id"])
        print(f"  fallo c{idx}: {it['error'][:120]}")
    return st


def main():
    dry = "--dry" in sys.argv
    verbose = "--verbose" in sys.argv or dry
    if os.path.isfile(B.PAUSA) and not dry:
        print("PAUSADO (existe PAUSA.txt)")
        return 0

    # lock: el watchdog.sh usa tick.lock para saber si hay driver vivo (mismo
    # contrato que batch.py). OJO: en Windows NO usar os.kill(pid, 0) para chequear
    # vida -> os.kill con sig=0 TERMINA el proceso. Se usa tasklist.
    lock = os.path.join(AQUI, "tick.lock")
    if not dry:
        try:
            if os.path.isfile(lock):
                try:
                    pid_viejo = int((open(lock, encoding="utf-8").read().strip() or "0"))
                except Exception:
                    pid_viejo = 0
                if pid_viejo > 0 and _pid_vivo(pid_viejo):
                    print(f"ya hay driver vivo (pid {pid_viejo}); salgo")
                    return 0
            with open(lock, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except Exception as e:
            print("lock:", e)
    try:
        return _run(dry, verbose)
    finally:
        if not dry:
            try:
                # solo borrar el lock si es mio (otro driver puede haberlo tomado)
                if os.path.isfile(lock):
                    dueno = (open(lock, encoding="utf-8").read().strip() or "")
                    if dueno == str(os.getpid()):
                        os.remove(lock)
            except Exception:
                pass


def _run(dry, verbose):
    st = B.cargar_state()
    items = st.get("items", [])

    # 1) si quedo un grupo a medias, adoptarlo antes de lanzar otro
    corr = [i for i in items if i.get("status") == "corriendo"]
    legacy = [i for i in corr if "#" not in str(i.get("job_id") or "")]
    mios = [i for i in corr if "#" in str(i.get("job_id") or "")]
    if legacy and not dry:
        # Items "corriendo" lanzados por batch.py (job del dashboard). NO llamar a
        # B.tick(): si no hay nada corriendo, tick LANZA otro clip y duplicamos
        # trabajo. Aca se cierra el item segun el job del dashboard:
        #   success + mp4  -> a destino y hecho
        #   failed/cancel  -> pendiente (se re-renderiza en el proximo grupo)
        #   "En cola"      -> se cancela en el dashboard y vuelve a pendiente
        import urllib.request
        print(f"LTX GRUPO: cierro {len(legacy)} item(s) que dejo batch.py")
        for it in legacy:
            jid = it.get("job_id")
            job = {}
            try:
                d = json.load(urllib.request.urlopen(
                    "http://127.0.0.1:8899/api/jobs?limit=250", timeout=30))
                job = next((j for j in d.get("items", []) if j.get("id") == jid), {})
            except Exception as e:
                print("   sin datos del job:", e)
            est = job.get("status")
            # si el mp4 ya esta en su destino (lo cerro otro antes), no re-renderizar
            dst_ya = B.destino(it)
            if os.path.isfile(dst_ya) and os.path.getsize(dst_ya) > 20000:
                info_ya, _ = B.ffprobe_ok(dst_ya)
                if info_ya and info_ya.get("dur", 0) > float(it["duration"]) * 0.5:
                    if est in ("pending", "queued", "running"):
                        try:
                            import urllib.request as _u
                            _u.urlopen(_u.Request(
                                f"http://127.0.0.1:8899/api/jobs/{jid}/cancel",
                                method="POST"), timeout=15).read()
                            print("   (cancele el job zombie del dashboard)")
                        except Exception as e:
                            print("   no pude cancelar el zombie:", e)
                    it["status"] = "hecho"
                    it["out"] = dst_ya
                    it["finished"] = B.now()
                    it.pop("job_id", None)
                    B.registrar("grupo_cerrado", "OK", "el mp4 ya estaba en destino",
                                item=it["id"])
                    print(f"   ya estaba hecho: {os.path.basename(dst_ya)[:50]}")
                    continue
            src = None
            for o in (job.get("outputs") or []):
                p = o if isinstance(o, str) else o.get("path")
                if p and os.path.isfile(p) and os.path.getsize(p) > 20000:
                    src = p
                    break
            if est in ("success", "done", "completed") and src:
                dst = B.destino(it)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    shutil.move(src, dst)
                except Exception:
                    shutil.copy2(src, dst)
                it["status"] = "hecho"
                it["out"] = dst
                it["finished"] = B.now()
                it.pop("job_id", None)
                B.registrar("grupo_cerrado", "OK", "job del dashboard ya tenia mp4", item=it["id"])
                print(f"   hecho: {os.path.basename(dst)[:50]}")
            else:
                if est in ("pending", "queued", "running"):
                    try:
                        urllib.request.urlopen(urllib.request.Request(
                            f"http://127.0.0.1:8899/api/jobs/{jid}/cancel",
                            method="POST"), timeout=15).read()
                    except Exception as e:
                        print("   no pude cancelar:", e)
                it["status"] = "pendiente"
                it.pop("job_id", None)
                B.registrar("grupo_zombie_liberado", "HALLAZGO",
                            f"job del dashboard en '{est}' sin mp4: a la cola", item=it["id"])
                print(f"   a pendiente: {os.path.basename(it['image'])[:40]}")
        B.guardar_state(st)
        items = st.get("items", [])
        mios = [i for i in items if i.get("status") == "corriendo"
                and "#" in str(i.get("job_id") or "")]
        corr = mios
    if mios and not dry:
        corr = mios
        pid = str(corr[0].get("job_id") or "").split("#")[0]
        if pid:
            print(f"LTX GRUPO: retomo prompt {pid[:8]} ({len(corr)} clips)")
            t0 = time.time()
            while time.time() - t0 < MAX_S:
                try:
                    h = ltx.requests.get(f"{COMFY}/history/{pid}", timeout=20).json()
                except Exception:
                    h = {}
                if pid in h:
                    break
                time.sleep(15)
            for it in corr:
                idx = int(str(it.get("job_id")).split("#")[1])
                finalizar(st, it, pid, idx, verbose)
            st["_comfy_dirty"] = True
            B.guardar_state(st)
            return 0
        for it in corr:          # job_id roto: devolver a la cola
            it["status"] = "pendiente"
        B.guardar_state(st)
        return 0

    # 2) armar grupo nuevo
    grupo = items_compatibles(items, K, verbose)
    if not grupo:
        print("SIN PENDIENTES")
        return 2
    print(f"LTX GRUPO: {len(grupo)} clips (de {len(items)} items en el plan)")
    for it in grupo:
        print("   -", it["shot"][:52], "|", os.path.basename(it["image"])[:40])
    if dry:
        return 0

    N_GRUPO[0] = len(grupo)
    P.MODELOS = P.modelos()
    wf, meta, pref, dims = P.armar(grupo, len(grupo), prefix_base=f"grupo/{TAG}")
    print(f"   grafo {len(wf)} nodos · {dims[0]}x{dims[1]} · {dims[2]} frames")
    pid = ltx.submit(COMFY, wf, "ltx-grupo")
    print(f"   prompt {pid[:8]} enviado")

    # 3) marcar corriendo con t0 y job_id indexado
    for it in grupo:
        it["status"] = "corriendo"
        it["t0"] = time.time()
        it["ultimo_cambio"] = time.time()
    for idx, it in enumerate(grupo, start=1):
        it["job_id"] = f"{pid}#{idx}"
    st["_comfy_dirty"] = True
    B.guardar_state(st)

    # 4) esperar
    t0 = time.time()
    ultimo = 0
    while time.time() - t0 < MAX_S:
        try:
            h = ltx.requests.get(f"{COMFY}/history/{pid}", timeout=20).json()
        except Exception:
            h = {}
        if pid in h:
            break
        if time.time() - t0 - ultimo > 60:
            ultimo = time.time() - t0
            print(f"   [{ultimo:5.0f}s] corriendo...", flush=True)
        time.sleep(10)
    print(f"LTX GRUPO: terminado en {time.time()-t0:.0f}s")

    # 5) cerrar cada item
    st = B.cargar_state()      # releer: nada mas lo toca, pero por las dudas
    corr = {i["id"]: i for i in st["items"] if i.get("status") == "corriendo"}
    for idx, it_viejo in enumerate(grupo, start=1):
        it = corr.get(it_viejo["id"]) or it_viejo
        finalizar(st, it, pid, idx, verbose)
    st["_comfy_dirty"] = True
    B.guardar_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
