#!/usr/bin/env bash
# Upscale 4x del lote de biomas con Topaz Video AI (prob-4).
#
# tvai_up no acepta PNG suelto: se arma un mp4 de 3 frames por imagen y se toma el
# del medio (pitfall documentado en el skill topaz-video-ai-cli).
# Salida en JPG q95 (un PNG 4608x8192 son ~155 MB; 50 serian 7,7 GB).
#
# Uso: bash upscale_lote.sh [carpeta_entrada] [carpeta_salida]
set -e
TV="/c/Program Files/Topaz Labs LLC/Topaz Video AI"
FF="/c/Users/Tolch/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.0.1-full_build/bin/ffmpeg.exe"
IN="${1:-C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch/selva_amk/lote}"
OUT="${2:-C:/Users/Tolch/Documents/AI_Code/LTX-2.5_Dashboard/batch/selva_amk/lote_4k}"
TMP="$IN/.tvai_tmp"
export TVAI_MODEL_DIR='C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models'
mkdir -p "$OUT" "$TMP"

n=0
for f in "$IN"/*.png; do
  base=$(basename "$f" .png)
  case "$base" in hoja*) continue;; esac
  if [ -f "$OUT/$base.png" ] || [ -f "$OUT/$base.jpg" ]; then continue; fi
  echo "== $base"
  "$FF" -v error -y -loop 1 -framerate 25 -t 0.24 -i "$f" -c:v libx264 -crf 1 -pix_fmt yuv444p "$TMP/$base.mp4"
  rm -f "$TMP/${base}_"*.png
  "$TV/ffmpeg.exe" -hide_banner -loglevel error -y -i "$TMP/$base.mp4" \
        -vf "tvai_up=model=prob-4:scale=4:device=0:vram=1:instances=1" \
        -frames:v 3 -f image2 "$TMP/${base}_%02d.png"
  if [ -f "$TMP/${base}_02.png" ]; then
    "$FF" -v error -y -i "$TMP/${base}_02.png" -q:v 2 "$OUT/$base.jpg"
    rm -f "$TMP/${base}_"*.png "$TMP/$base.mp4"
    n=$((n+1))
    echo "   ok $base.jpg ($n)"
  else
    echo "   FALLO $base"
  fi
done
rm -rf "$TMP"
echo "listo: $n imagenes en $OUT"
