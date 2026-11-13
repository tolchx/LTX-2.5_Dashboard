#!/usr/bin/env bash
# Upscale 4x de los 6 biomas de selva con Topaz Video AI (tvai_up).
#
# Pitfall del skill: tvai_up NO procesa un PNG suelto ("No filtered frames for output").
# Hay que armar un mp4 corto con el still y despues extraer el frame. Se hace 3 frames
# y se toma el del medio.
set -e
TV="/c/Program Files/Topaz Labs LLC/Topaz Video AI"
FF="/c/Users/Tolch/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.0.1-full_build/bin/ffmpeg.exe"
B="C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch/selva_amk"
OUT="$B/topaz_4x"
TMP="$B/.tvai_tmp"
export TVAI_MODEL_DIR='C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models'
mkdir -p "$OUT" "$TMP"

for f in 01_dosel 02_helechos 03_lianas 04_raices 05_bokeh 06_pantano; do
  if [ -f "$OUT/$f.png" ]; then echo "$f: ya esta"; continue; fi
  echo "== $f"
  "$FF" -v error -y -loop 1 -framerate 25 -t 0.24 -i "$B/$f.png" \
        -c:v libx264 -crf 1 -pix_fmt yuv444p "$TMP/$f.mp4"
  rm -f "$TMP/${f}_"*.png
  "$TV/ffmpeg.exe" -hide_banner -loglevel error -y -i "$TMP/$f.mp4" \
        -vf "tvai_up=model=prob-4:scale=4:device=0:vram=1:instances=1" \
        -frames:v 3 -f image2 "$TMP/${f}_%02d.png"
  if [ -f "$TMP/${f}_02.png" ]; then
    "$FF" -v error -y -i "$TMP/${f}_02.png" -compression_level 6 "$OUT/$f.png"
    echo "   ok: $(du -h "$OUT/$f.png" | cut -f1)"
  else
    echo "   FALLO $f"
  fi
done
rm -f "$TMP"/*.png "$TMP"/*.mp4
echo "listo en $OUT"
