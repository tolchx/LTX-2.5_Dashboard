# 🎬 LTX-2.5 Studio · Batch Video & Native Audio Dashboard

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![ComfyUI](https://img.shields.io/badge/Engine-ComfyUI%200.39.0-brightgreen.svg?style=flat-square)](https://github.com/comfyanonymous/ComfyUI)
[![Model](https://img.shields.io/badge/Model-LTX--2.5%2022B%20Distilled-blue.svg?style=flat-square)](https://huggingface.co/Lightricks/LTX-2.5)
[![GPU](https://img.shields.io/badge/Hardware-NVIDIA%20RTX%204090%20(24GB)-76B900.svg?style=flat-square&logo=nvidia&logoColor=white)](https://www.nvidia.com)
[![License](https://img.shields.io/badge/License-MIT-orange.svg?style=flat-square)](LICENSE)

Dashboard web local de alto rendimiento y lanzadores por lotes (`.bat`) para generar secuencias de video cinematográficas con **audio ambiental sincronizado nativo** impulsado por el nuevo modelo **Lightricks LTX-2.5 (22B Distilled)** sobre **ComfyUI**.

Diseñado específicamente para flujos de trabajo profesionales de animación fotográfica (Image-to-Video) y generación por texto (Text-to-Video) en lotes organizados por carpetas conceptuales.

---

## 📑 Tabla de Contenidos

1. [Características Principales](#-características-principales)
2. [Arquitectura del Sistema](#-arquitectura-del-sistema)
3. [Requisitos de Hardware y Software](#-requisitos-de-hardware-y-software)
4. [Inicio Rápido](#-inicio-rápido)
5. [Pesos y Modelos LTX-2.5](#-pesos-y-modelos-ltx-25)
6. [Guía de la Interfaz Web](#-guía-de-la-interfaz-web)
7. [Parámetros del Pipeline](#-parámetros-del-pipeline)
8. [Estructura del Proyecto](#-estructura-del-proyecto)
9. [API REST Endpoints](#-api-rest-endpoints)
10. [Solución de Problemas (FAQ)](#-solución-de-problemas-faq)

---

## 🚀 Características Principales

- **Batch Inteligente por Carpetas Temáticas:**
  - Explora colecciones de imágenes agrupadas en acordeón (ej. escenarios, personajes, tomas macro, retratos).
  - Marcadores visuales `✓` para imágenes con video generado previamente.
  - Filtro instantáneo `✓ Pendientes` para renderizar únicamente tomas sin procesar.
  - Encolado masivo selectivo con un clic: **Encolar Batch** o **⚡ Encolar Categoría**.

- **Generación Audiovisual Sincronizada (LTX-2.5 Native Audio):**
  - Generación de pistas de sonido ambiental y foley directamente ligadas a la acción y prompt del video mediante el Audio VAE nativo de LTX-2.5.
  - Muxing automático de alta fidelidad H.264 + AAC vía FFmpeg.

- **Pipeline de 2 Etapas (High-Definition Latent Upscaling):**
  - **Stage 1 (Base Latent):** Generación del movimiento base a resolución nativa con el DiT 22B Distilled (8 pasos Euler/AYS).
  - **Stage 2 (Spatial Upscaler x2):** Remuestreo y refinado en el espacio latente (3 pasos adicionales) para texturas nítidas sin artefactos.
  - Opción de conmutar al vuelo a **1-Stage Rápido** para previsualización inmediata.

- **Doble Motor VAE Seleccionable:**
  - **DiffVAE (CausalDiffusionVAE BF16):** Máxima fidelidad cinematográfica, microcontrastes y texturas naturales.
  - **ConvVAE (Convolutional VAE BF16):** Alternativa ligera con menor huella de VRAM y decodificación ultra rápida.

- **Generación Extendida Multi-Chunk:**
  - Para duraciones superiores a 5 segundos, el motor divide la generación en segmentos temporales encadenados con mezcla suave de fotogramas (crossfade) sin saltos.

- **Telemetría y Control en Tiempo Real:**
  - Conexión WebSocket bidireccional continua con ComfyUI (`127.0.0.1:8188`).
  - Barra de progreso porcentual y seguimiento nodo por nodo (Text Encoding ➔ DiT Sampling ➔ Latent Upscale ➔ Audio Decode ➔ Video Mux).
  - Medidor de consumo de VRAM en vivo y botón para forzar recolección de memoria (`Liberar VRAM`).
  - Pausa, reanudación y reintentos automáticos.

- **Presets de Movimiento de Cámara:**
  - Inyección instantánea de directivas cinematográficas: *Dolly In*, *Dolly Out*, *Panorámica Horizontal*, *Órbita 360°*, *Tilt Vertical*, *Brisa Sutil* y *Audio Foley Atmosférico*.

---

## 🏛 Arquitectura del Sistema

```
                      ┌──────────────────────────────────────────┐
                      │    Navegador Web (UI Moderna / Dark)     │
                      │         http://127.0.0.1:8899            │
                      └────────────────────▲─────────────────────┘
                                           │ HTTP REST / WebSocket
                                           ▼
                      ┌──────────────────────────────────────────┐
                      │          FastAPI Backend Server          │
                      │  (Cola de jobs, parseo de prompts/EXIF)  │
                      └────────────────────▲─────────────────────┘
                                           │ HTTP Prompt API / WS
                                           ▼
                      ┌──────────────────────────────────────────┐
                      │          ComfyUI Server (:8188)          │
                      │       Nodos LTX-2.5 + GGUF Sampler       │
                      └─────────────▲───────────────▲────────────┘
                                    │               │
            ┌───────────────────────┴─┐   ┌─────────┴─────────────────────┐
            │   NVIDIA RTX 4090 GPU   │   │   Almacenamiento (Junctions)  │
            │   (VRAM DiT + Encoders) │   │   E:\LTX-2.5_Dashboard\models │
            └─────────────────────────┘   │   E:\LTX-2.5_Dashboard\outputs│
                                          └───────────────────────────────┘
```

---

## 💻 Requisitos de Hardware y Software

- **Sistema Operativo:** Windows 10 u 11 (64-bit).
- **GPU:** NVIDIA RTX 3090 / 4090 (24 GB VRAM recomendado para 2-Stage HD).
- **Python:** 3.10 o superior (manejado de forma aislada en `.venv/`).
- **ComfyUI:** Instalación funcional local (ej. `D:\ComfyUI`), con el nodo personalizado `ComfyUI-GGUF` instalado.
- **FFmpeg:** Disponible en el sistema o auto-detectado mediante `imageio-ffmpeg`.

---

## ⚡ Inicio Rápido

### 1. Clonar el repositorio
```bash
git clone https://github.com/tolchx/LTX-2.5_Dashboard.git
cd LTX-2.5_Dashboard
```

### 2. Ejecutar con un clic
Hacé doble clic en **`run.bat`**:
- Crea automáticamente el entorno virtual (`.venv`) e instala dependencias (`requirements.txt`) en la primera ejecución.
- Comprueba la presencia e integridad de los 6 modelos LTX-2.5 (si falta alguno, invoca el asistente de descarga).
- Detecta si ComfyUI está activo en `127.0.0.1:8188`; si no lo está, lo inicia en segundo plano.
- Levanta el servidor del Dashboard en `http://127.0.0.1:8899` y abre tu navegador por defecto.

### 3. Detener los servicios
- Hacé doble clic en **`stop.bat`** para cerrar el dashboard.
- Si querés cerrar también ComfyUI: ejecutá `stop.bat --all`.

---

## 📦 Pesos y Modelos LTX-2.5

Para evitar saturar la unidad de sistema `C:\`, el proyecto utiliza enlaces simbólicos tipo **Windows Directory Junction** hacia un disco secundario de gran capacidad (por defecto `E:\LTX-2.5_Dashboard\`):

```bat
mklink /J "C:\Users\...\LTX-2.5_Dashboard\models"  "E:\LTX-2.5_Dashboard\models"
mklink /J "C:\Users\...\LTX-2.5_Dashboard\outputs" "E:\LTX-2.5_Dashboard\outputs"
```

Los modelos se registran automáticamente en ComfyUI agregando la ruta al archivo `extra_model_paths.yaml`:
```yaml
ltx25:
  base_path: E:/LTX-2.5_Dashboard/models
  checkpoints: diffusion_models
  clip: text_encoders
  vae: vae
  upscale_models: latent_upscale_models
```

### Tabla de Modelos Principales (~33.65 GB)

| Archivo | Tamaño | Componente | Descripción |
| :--- | :--- | :--- | :--- |
| `diffusion_models/ltx-2.5-22b-distilled-UD-Q4_K_XL.gguf` | 14.00 GB | DiT 22B | Modelo de difusión cuantizado dinámico (Unsloth GGUF). Máxima calidad con encaje óptimo en 24 GB VRAM. |
| `text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | 15.37 GB | CLIP / Text | Codificador de texto Gemma 4 12B con proyector de atención integrado (INT8 ConvRot). |
| `vae/ltx-2.5-video-vae-bf16.safetensors` | 1.47 GB | Video VAE | **DiffVAE** (CausalDiffusionVAE BF16). Decodificación espacial de máxima fidelidad. |
| `vae/ltx-2.5-video-vae-conv-bf16.safetensors` | 1.45 GB | Video VAE | **ConvVAE** (Convolutional VAE BF16). Menor requerimiento computacional. |
| `vae/ltx-2.5-audio-vae-bf16.safetensors` | 0.36 GB | Audio VAE | Vocoder y descompresor latente de audio estéreo 24 kHz. |
| `latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | 1.00 GB | Upscaler | Escalador espacial x2 para la segunda etapa de refinamiento HD. |

### Descarga e Integridad con CLI
Para verificar los archivos descargados o incorporar cuantizaciones adicionales (Q5, FP8, INT8):
```bat
download_models.bat --only-check
download_models.bat --extra q5
```

---

## 🖥 Guía de la Interfaz Web

La interfaz ha sido diseñada para trabajo de producción intensivo:

1. **Panel Izquierdo (Explorador y Lotes):**
   - Buscador en tiempo real por nombre de archivo o categoría.
   - Listas colapsables con preview en miniatura de cada fotografía.
   - Selección múltiple de elementos o selección de lote completo.
   - Acceso rápido a prompts guardados por categoría en `data/prompts.json`.

2. **Panel Central (Parámetros y Prompts):**
   - Editor de prompt positivo visual + editor de prompt de audio ambiental.
   - Botonera de inyección de modificadores de cámara cinemáticos.
   - Selector de modo: **2-Stage HD** (calidad final) vs **1-Stage Rápido** (bocetado).
   - Ajustes de resolución con preservación de aspect ratio y alineación a bloques de 64/32 píxeles.

3. **Panel Derecho (Cola y Renderings):**
   - Lista interactiva de trabajos en curso con tiempo transcurrido, etapa del grafo y porcentaje.
   - Galería de videos terminados con reproducción directa, control de volumen y botón para abrir la carpeta contenedora en el Explorador de Windows.

4. **Visor Lightbox Integrado:**
   - Hacé clic sobre cualquier video renderizado para abrirlo en tamaño completo con bucle de audio.
   - **Atajos de Teclado:**
     - <kbd>Espacio</kbd>: Play / Pausa.
     - <kbd>→</kbd> / <kbd>←</kbd>: Siguiente / Anterior video de la galería.
     - <kbd>Esc</kbd>: Cerrar el visor.

---

## 🎛 Parámetros del Pipeline

Configurables desde la UI o editables de forma global en `server/config.json`:

```json
{
  "host": "127.0.0.1",
  "port": 8899,
  "comfyui_url": "http://127.0.0.1:8188",
  "output_dir": "outputs",
  "default_fps": 24,
  "default_duration": 5,
  "default_preset": "704p",
  "default_two_stage": true,
  "default_vae_mode": "diff",
  "default_i2v_strength": 0.70,
  "default_stage2_strength": 1.00,
  "default_include_audio": true,
  "default_crf": 17
}
```

- **`i2v_strength` (0.0 a 1.0):** Grado de adherencia a la imagen de entrada en la primera etapa. Un valor de `0.70` permite un balance ideal entre dinamismo de movimiento y fidelidad al sujeto.
- **`stage2_strength` (0.0 a 1.0):** Nivel de refinamiento en el pase de upscaling latente.
- **`default_crf` (0 a 51):** Nivel de compresión H.264 (`17` provee calidad visual prácticamente sin pérdidas).

---

## 📁 Estructura del Proyecto

```
LTX-2.5_Dashboard/
├── run.bat                 # Lanzador principal inteligente
├── stop.bat                # Script para finalizar procesos
├── download_models.bat     # Wrapper de descarga y validación
├── requirements.txt        # Dependencias de Python (FastAPI, uvicorn, pillow, etc.)
├── README.md               # Documentación general del proyecto
│
├── server/                 # Backend en Python / FastAPI
│   ├── main.py             # Rutas API, estáticos y WebSocket
│   ├── ltx_comfy.py        # Generador de flujos JSON para ComfyUI
│   ├── queue.py            # Orquestador asíncrono de tareas y telemetría
│   ├── store.py            # Gestión de imágenes, metadatos y categorías
│   └── config.json         # Configuración de rutas y presets por defecto
│
├── web/                    # Frontend nativo (Vanilla ES6 + CSS moderno)
│   ├── index.html          # Estructura del Dashboard y modales
│   ├── styles.css          # Estilos tema oscuro con diseño fluido
│   └── app.js              # Lógica de interacción, Websockets y Lightbox
│
├── scripts/                # Herramientas de soporte
│   └── download_models.py  # Script de descarga y verificación SHA/tamaño
│
├── data/                   # Datos locales y persistencia
│   ├── prompts.json        # Prompts y descriptores por carpeta
│   ├── bench.json          # Registro de benchmarks de rendimiento
│   └── history.json        # Historial de renders
│
├── models/ -> E:\...       # Junction a almacenamiento de pesos
└── outputs/ -> E:\...      # Junction a carpeta de renders finales
```

---

## 🔌 API REST Endpoints

| Método | Endpoint | Descripción |
| :--- | :--- | :--- |
| `GET` | `/api/status` | Estado de salud del servidor y conexión con ComfyUI. |
| `GET` | `/api/images/categories` | Lista de categorías, fotos disponibles y videos renderizados. |
| `GET` | `/api/prompts` | Lectura de los prompts guardados por categoría. |
| `POST` | `/api/prompts` | Actualización o guardado masivo de prompts. |
| `POST` | `/api/generate` | Encolar una tarea individual o batch de video. |
| `GET` | `/api/queue` | Inspección de la cola de procesamiento activa. |
| `POST` | `/api/queue/{id}/cancel` | Cancelación de un trabajo encolado. |
| `POST` | `/api/vram/clear` | Liberación forzada de memoria VRAM en PyTorch/ComfyUI. |
| `WS` | `/ws/progress` | Transmisión en tiempo real de logs y telemetría de muestreo. |

---

## ❓ Solución de Problemas (FAQ)

### ComfyUI indica falta de memoria virtual (Pagefile Commit Limit)
Si tenés abiertos varios modelos o aplicaciones de IA concurrentes (como MOSS-Image en `:8189`), Windows puede alcanzar el límite del archivo de paginación. 
- Cerrá las instancias secundarias que no estés usando.
- En el Dashboard, hacé clic en **Liberar VRAM**.
- Verificá que la memoria virtual de Windows esté configurada en "Tamaño administrado por el sistema" en un disco rápido (SSD/NVMe).

### El modelo de audio no genera sonido
Asegurate de tener el archivo `ltx-2.5-audio-vae-bf16.safetensors` en la carpeta `models/vae/` y que la casilla **Incluir Audio** esté tildada en los ajustes de generación.

### Se visualiza el error "ComfyUI node LTXVModelLoader not found"
Comprobá que ComfyUI esté actualizado a la versión `0.39.0` o superior y que el repositorio `ComfyUI-GGUF` esté presente en la carpeta `custom_nodes` de tu ComfyUI.

---

## 📄 Licencia

Este proyecto está distribuido bajo la licencia [MIT](LICENSE). El modelo LTX-2.5 y sus pesos están sujetos a los términos y licencias oficiales publicadas por Lightricks en [Hugging Face](https://huggingface.co/Lightricks/LTX-2.5).
