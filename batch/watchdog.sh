#!/usr/bin/env bash
# Watchdog del lote LTX. Mantiene UN driver vivo y nada mas.
#
# Criterio: batch.py crea tick.lock al arrancar y lo borra al salir, asi que la
# existencia del archivo es la senal de "hay driver". Si no hay lock, espera 25 s
# y vuelve a mirar (el loop normal deja un hueco de pocos segundos entre bloques:
# sin la segunda mirada se levantaban drivers de mas).
# MODO AGRUPADO: si existe GRUPO.txt con un numero K>1 corre batch_grupo.py
# (K clips por prompt de ComfyUI: 182 s/clip medidos, contra 236 s suelto).
# Sin GRUPO.txt (o con 1) sigue el driver clasico, clip por clip.
cd "/c/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch" || exit 1
PY="../.venv/Scripts/python.exe"
STATE="C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch/state_ltx_cam.json"
LOG="watchdog.log"

K_GRUPO=""
if [ -f GRUPO.txt ]; then
  K_GRUPO="$(tr -dc '0-9' < GRUPO.txt)"
fi

echo "$(date '+%F %T') watchdog arriba (pid $$) grupo=${K_GRUPO:-clasico}" >> "$LOG"
while true; do
  if [ -f PAUSA.txt ]; then
    sleep 300
    continue
  fi
  # La cola del dashboard se queda en pausa si alguien cancela o si quedo de un stop:
  # sin esto el lote se queda mirando el vacio con los jobs "en cola".
  curl -s -m 8 -X POST http://127.0.0.1:8899/api/queue/resume >/dev/null 2>&1
  if [ ! -f tick.lock ]; then
    sleep 25
    if [ ! -f tick.lock ]; then
      echo "$(date '+%F %T') sin driver: levantando" >> "$LOG"
      if [ -n "$K_GRUPO" ] && [ "$K_GRUPO" -gt 1 ] 2>/dev/null; then
        LTXB_GRUPO="$K_GRUPO" LTXB_STATE="$STATE" "$PY" batch_grupo.py >> tick_cam_loop.log 2>&1 &
      else
        LTXB_STATE="$STATE" LTXB_ENGINE=ltx25 "$PY" batch.py tick --max-seconds 1500 --verbose >> tick_cam_loop.log 2>&1 &
      fi
      sleep 40
    fi
  fi
  sleep 200
done
