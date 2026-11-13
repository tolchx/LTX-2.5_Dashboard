@echo off
setlocal
title NOMADE - reanudar lote
cd /d "%~dp0"

echo === 1/4  Dashboard LTX Studio (:8899) ===
start "" /min cmd /c "cd /d ""C:\Users\Tolch\Documents\AI_Code\LTX-2.5_Dashboard"" && .venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8899 >> batch\dashboard.log 2>&1"

echo === 2/4  esperando que responda ===
powershell -NoProfile -Command "$ok=$false; for($i=0;$i -lt 40;$i++){ try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:8899/api/queue' -TimeoutSec 3; $ok=$true; break } catch { Start-Sleep -Seconds 3 } }; if($ok){ 'dashboard OK' } else { 'ERROR: el dashboard no responde'; exit 1 }"

echo === 3/4  ComfyUI ===
powershell -NoProfile -Command "try { Invoke-RestMethod -Uri 'http://127.0.0.1:8899/api/comfy/start' -Method Post -TimeoutSec 40 | Out-Null; 'comfy arrancando' } catch { 'ERROR arrancando comfy' }"

echo === 4/4  sacar la pausa y arrancar el motor del lote ===
if exist "PAUSA.txt" del /q "PAUSA.txt"
start "" /min cmd /c "cd /d ""%~dp0"" && :loop & ""C:\Users\Tolch\Documents\AI_Code\LTX-2.5_Dashboard\.venv\Scripts\python.exe"" batch.py tick --max-seconds 1800 >> tick_loop.log 2>&1 & timeout /t 15 /nobreak >nul & goto loop"

echo.
echo Listo. El lote sigue solo. Cerrar esta ventana no lo detiene.
timeout /t 6 /nobreak >nul
