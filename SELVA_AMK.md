# AMK 2025 — Pantallas del club: imágenes de selva

## Geometría real (medida del pixelmap `C:\Users\Tolch\Desktop\AMK_2025_v1.png`, 2160×4096)

| # | pantalla | px | aspecto | notas |
|---|---|---|---|---|
| 1 | tira VJ derecha | 306×2982 | 1:9,7 | |
| 2 | tira VJ borde izq. | 77×2884 | 1:37 | la más extrema |
| 3 | tira VJ izq. | 154×2284 | 1:14,8 | |
| 4 | tira central izq. | 221×2206 | 1:10 | |
| 5 | tira central der. | 225×2206 | 1:9,8 | |
| 6 | PORTAL FRONT + STAGE BACK | 1529×330 · 1066×767 | 4,6:1 · 1,4:1 | rótulos del pixelmap |
| 7 | tira alta | 268×1102 | 1:4,1 | |
| 8-9 | tiras laterales | 142×1019 · 136×1019 | 1:7,2 / 1:7,5 | |
| 10-11 | cuadrados laterales | 460×426 · 461×426 | 1,1:1 | |
| — | STAGE FLOOR | 2160×400 | 5,4:1 | rótulo del pixelmap |

Rectángulos detectados por script → `batch/pantallas_amk.json` (11 rects con x, y, w, h).

## Decisión
**Un mural maestro, cortado por pantalla.** No una imagen por tira: a 1:10 el modelo no
genera, y diez selvas distintas rompen la lectura de "un solo espacio". Con un mural, cada
tira es una ventana del mismo ambiente.

**Motor: local (ComfyUI)** — Qwen-Image 2.1 (`qwen_image_2.1_int8_convrot` + `qwen_image_2.1_vae_bf16`)
y FLUX.2 Klein 4B (`flux-2-klein-4b` + `flux2-vae`), ambos en `E:\video_creator_minimax\models`.
Se pueden usar los stills de NOMADE como referencia (img2img a denoise bajo o clip_vision)
para clavar la paleta. Krea queda como plan B.

## Flujo
1. Mural 1152×2048 (9:16, nativo de los modelos) — 4-6 variantes de bioma.
2. Upscale 2× → 2304×4096 (cubre 2160×4096 con margen; la tira más fina recibe 82 px).
3. `python cortar_mural.py <mural.png>` → 11 PNG del tamaño exacto de cada LED.
4. Opcional: capas de parallax con alfa (lianas en primer plano) y grano de 35 mm.

## Prompt del mural (base, misma paleta que los videos)
> Immersive interior of a tropical jungle at night, you are standing inside it: giant
> monstera and fern fronds framing both edges, hanging lianas and braided vines crossing
> the frame, woven macrame planters with trailing pothos, moss-covered roots and raw bamboo
> trunks, dense dark foliage receding into warm haze, thousands of tiny suspended lights and
> glowing pollen in the air, wet stones and dark reflective water at the bottom.
> Photoreal cinematic still, medium-format quality, 35mm lens, f/2.8, shallow depth of field,
> soft anamorphic bloom, fine 35mm grain, deep crushed blacks, warm amber and molten gold
> light, jungle-green shadows, volumetric haze, suspended dust and pollen, aged brass and raw
> bamboo, hand-woven macrame, tropical foliage silhouettes, hypnotic and ceremonial mood.
> No text, no lettering, no logo, no watermark, no interface. No neon cyberpunk, no cold blue
> light, no visible people.

Variantes de bioma (mismo cierre de estilo): `dosel` (canopy + cielo), `helechos` (sotobosque
cerrado), `lianas` (cortinas de enredaderas), `musgo y raíces`, `bokeh` (luces y partículas).

## Estado
- `batch/pantallas_amk.json` — rectángulos medidos.
- `batch/cortar_mural.py` — cortador (validado con un mural de prueba: los 11 recortes salen
  con el px exacto de cada pantalla).
- Falta: generar el mural (necesita ~10-12 GB de VRAM; el lote de video está usando 20 GB).
