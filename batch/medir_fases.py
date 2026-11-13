"""Instrumenta comfy.log y timestampa el avance de UN clip (pasivo, no toca nada).

Uso: python medir_fases.py [segundos]
Deja el detalle en fases.jsonl y un resumen por consola.
"""
import json
import os
import re
import sys
import time

LOG = r"C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch/comfy.log"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fases.jsonl")
DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 300

MARKS = [
    ("got_prompt", re.compile(r"got prompt")),
    ("policy", re.compile(r"Model storage policy")),
    ("te_load_req", re.compile(r"Requested to load LTXAVTEModel_")),
    ("te_loaded", re.compile(r"loaded completely;.*loaded, full load")),
    ("te_encode", re.compile(r"Using MixedPrecisionOps for text encoder")),
    ("gguf", re.compile(r"gguf qtypes")),
    ("unet_load_req", re.compile(r"Requested to load LTXAV")),
    ("sampler_step", re.compile(r"\| *\d+%\|")),
    ("vae_req", re.compile(r"Requested to load CausalDiffusionVAE")),
    ("done", re.compile(r"Prompt executed in")),
    ("traceback", re.compile(r"Traceback|Error|error:")),
]


def classify(line):
    hits = []
    for name, rx in MARKS:
        if rx.search(line):
            hits.append(name)
    return hits


def tailer():
    # arrancar desde el final: solo lo nuevo
    f = open(LOG, "r", encoding="utf-8", errors="replace")
    f.seek(0, os.SEEK_END)
    # el log usa \r en las barras: leer byte a byte y cortar por \r o \n
    buf = ""
    t0 = time.time()
    last = {}
    with open(OUT, "a", encoding="utf-8") as out:
        while time.time() - t0 < DUR:
            chunk = f.read(65536)
            if not chunk:
                time.sleep(0.15)
                continue
            for ch in chunk:
                if ch in "\r\n":
                    line = buf.strip()
                    buf = ""
                    if not line:
                        continue
                    hits = [h for h in classify(line) if h != "sampler_step"]
                    step = None
                    m = re.search(r"(\d+)%\|", line)
                    if m and "it/s" in line:
                        step = int(m.group(1))
                    if step is not None:
                        # solo los cambios de paso
                        if last.get("step") == step:
                            continue
                        last["step"] = step
                        hits = hits + [f"step{step}"]
                    if hits:
                        rec = {"t": round(time.time() - t0, 2), "hits": hits,
                               "line": line[:160]}
                        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        out.flush()
                        print(f"{rec['t']:7.2f}s  {'+'.join(hits):28s} {line[:110]}", flush=True)
                else:
                    buf += ch
                    if len(buf) > 4000:
                        buf = ""
            if time.time() - t0 > DUR:
                break


if __name__ == "__main__":
    tailer()
