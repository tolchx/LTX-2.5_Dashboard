@echo off
setlocal
title NOMADE - pausar y liberar GPU
cd /d "%~dp0"

echo === 1/3  pausa (ningun tick arranca nada nuevo) ===
echo pausa manual> PAUSA.txt
if exist tick.lock del /q tick.lock

echo === 2/3  cortar el motor del lote y los watchers ===
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*batch.py tick*' -or $_.CommandLine -like '*test_minimax*' -or $_.CommandLine -like '*compare_minimax*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; 'parado ' + $_.ProcessId } catch {} }"

echo === 3/3  apagar ComfyUI (es lo que ocupa la VRAM) ===
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*ComfyUI*' -and $_.CommandLine -like '*main.py*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; 'comfy parado ' + $_.ProcessId } catch {} }"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn*server.main*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; 'dashboard parado ' + $_.ProcessId } catch {} }"

echo.
echo GPU libre. Para volver: reanudar.bat
powershell -NoProfile -Command "nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader"
timeout /t 8 /nobreak >nul
