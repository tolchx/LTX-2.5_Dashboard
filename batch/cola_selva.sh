#!/usr/bin/env bash
# Encadena: espera a que termine la generacion del lote -> hojas de contacto -> 4x Topaz.
set -u
B="/c/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch"
PY="$B/../.venv/Scripts/python.exe"
cd "$B" || exit 1

echo "$(date '+%T') esperando que termine selva_lote.py"
for i in $(seq 1 240); do
  if ! powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object {\$_.CommandLine -like '*selva_lote*'} | Measure-Object).Count" 2>/dev/null | tr -d '\r' | grep -q '^[1-9]'; then
    break
  fi
  sleep 30
done
echo "$(date '+%T') lote terminado: $(ls "$B/selva_amk/lote"/*.png 2>/dev/null | wc -l) imagenes"

echo "$(date '+%T') hojas de contacto"
"$PY" hojas_lote.py 2>&1 | tail -14

echo "$(date '+%T') upscale 4x con Topaz"
bash upscale_lote.sh 2>&1 | tail -8

echo "$(date '+%T') listo"
