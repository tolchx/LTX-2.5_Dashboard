@echo off
setlocal
cd /d "%~dp0"
title Detener LTX-2.5 Studio

echo Deteniendo LTX-2.5 Studio Dashboard (:8899)...
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8899 " ^| findstr LISTENING') do (
    set FOUND=1
    taskkill /F /PID %%a >nul 2>&1
    echo   Proceso PID %%a terminado.
)
if "%FOUND%"=="0" (
    echo   No habia ningun servidor escuchando en :8899.
)

echo.
echo Nota: ComfyUI (:8188) se mantiene activo para no perder modelos cacheados.
echo Si tambien quieres detener ComfyUI, ejecuta: stop.bat --all
if /i "%~1"=="--all" (
    echo Deteniendo ComfyUI (:8188)...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8188 " ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
        echo   ComfyUI PID %%a terminado.
    )
)
