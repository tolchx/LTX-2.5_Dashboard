@echo off
setlocal
cd /d "%~dp0"
title LTX-2.5 Studio - Dashboard (:8899)

echo ==================================================
echo   LTX-2.5 Studio · Batch Video ^& Audio Dashboard
echo ==================================================
echo.

REM 1. Entorno virtual Python
if not exist ".venv\Scripts\python.exe" (
    echo [!] Creando entorno virtual .venv...
    if exist "C:\Program Files\Python312\python.exe" (
        "C:\Program Files\Python312\python.exe" -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 (
        echo [X] No se pudo crear .venv. Instala Python 3.11 o 3.12.
        pause
        exit /b 1
    )
)

REM 2. Dependencias livianas del dashboard
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, requests, websocket, imageio_ffmpeg, PIL" >nul 2>&1
if errorlevel 1 (
    echo [!] Instalando dependencias en .venv...
    ".venv\Scripts\python.exe" -m pip install --index-url https://pypi.org/simple -r requirements.txt
    if errorlevel 1 (
        echo [X] Fallo la instalacion de dependencias.
        pause
        exit /b 1
    )
)

REM 3. Verificar modelos LTX-2.5
".venv\Scripts\python.exe" "scripts\download_models.py" --only-check >nul 2>&1
if errorlevel 1 (
    echo [!] Faltan pesos base de LTX-2.5 o hay descargas incompletas.
    echo [i] Ejecutando verificacion / descarga reanudable...
    ".venv\Scripts\python.exe" "scripts\download_models.py"
    if errorlevel 1 (
        echo [X] No se pudieron verificar/descargar todos los modelos LTX-2.5.
        pause
        exit /b 1
    )
)

REM 4. Verificar o iniciar ComfyUI en :8188
".venv\Scripts\python.exe" -c "import requests; r=requests.get('http://127.0.0.1:8188/system_stats', timeout=3); r.raise_for_status()" >nul 2>&1
if errorlevel 1 (
    echo [i] ComfyUI no esta activo en :8188. Iniciando D:\ComfyUI...
    if not exist "D:\ComfyUI\.venv\Scripts\python.exe" (
        echo [X] No se encontro D:\ComfyUI\.venv\Scripts\python.exe
        pause
        exit /b 1
    )
    start "ComfyUI - LTX-2.5 (:8188)" /D "D:\ComfyUI" "D:\ComfyUI\.venv\Scripts\python.exe" "D:\ComfyUI\main.py" --listen 127.0.0.1 --port 8188
    echo [i] Esperando a que ComfyUI responda en :8188...
    powershell -NoProfile -Command "for($i=0;$i -lt 45;$i++){try{$r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2; if($r.StatusCode -eq 200){exit 0}}catch{}; Start-Sleep -Seconds 1}; exit 1"
    if errorlevel 1 (
        echo [!] ComfyUI sigue cargando o fallo al iniciar. Revisa la ventana 'ComfyUI - LTX-2.5'.
    ) else (
        echo [OK] ComfyUI listo en http://127.0.0.1:8188
    )
) else (
    echo [OK] ComfyUI detectado en http://127.0.0.1:8188
)

REM 5. Liberar puerto previo 8899 si quedo colgado
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8899 " ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM 6. Abrir navegador cuando el dashboard responda y levantar uvicorn
echo.
echo [OK] Iniciando LTX-2.5 Studio en http://127.0.0.1:8899
echo     Cierra esta ventana o ejecuta stop.bat para detener el dashboard.
echo.
start "" powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 30;$i++){try{$r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8899/api/health' -TimeoutSec 1; if($r.StatusCode -eq 200){Start-Process 'http://127.0.0.1:8899'; exit 0}}catch{}; Start-Sleep -Milliseconds 500}"
".venv\Scripts\python.exe" -m uvicorn server.main:app --host 127.0.0.1 --port 8899
