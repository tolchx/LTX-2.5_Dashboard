@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Descargador de modelos LTX-2.5 (ComfyUI)
echo   Destino: E:\LTX-2.5_Dashboard\models
echo ============================================
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\download_models.py %*
) else (
    python scripts\download_models.py %*
)
if errorlevel 1 (
    echo.
    echo Hubo un error descargando algun modelo. Podes re-ejecutar este .bat para reanudar.
    pause
    exit /b 1
)
echo.
echo Todos los modelos LTX-2.5 listos. Si ComfyUI ya estaba abierto, reinicialo para detectarlos.
pause
