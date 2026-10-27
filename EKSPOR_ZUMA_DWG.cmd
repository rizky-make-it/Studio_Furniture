@echo off
setlocal
cd /d "%~dp0"
set "PY=C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe"
if not exist "%PY%" ( echo Python Blender 5.2 tidak ditemukan: %PY% & pause & exit /b 1 )
if not exist "C:\Program Files\Autodesk\AutoCAD 2021\accoreconsole.exe" ( echo AutoCAD 2021 accoreconsole.exe tidak ditemukan. & pause & exit /b 1 )
echo Mengekspor solid Zuma Bed dari DWG (AutoCAD 2021)... tunggu 1-3 menit.
"%PY%" "99_SISTEM\pipeline\dwg_ke_stl.py" "02_PRODUK\Ranjang\Zuma_Bed\sumber\zuma_bed.dwg" "02_PRODUK\Ranjang\Zuma_Bed\sumber\ekspor" > "02_PRODUK\Ranjang\Zuma_Bed\sumber\ekspor_log.txt" 2>&1
type "02_PRODUK\Ranjang\Zuma_Bed\sumber\ekspor_log.txt"
echo.
echo SELESAI. Kembali ke Claude dan bilang "sudah".
pause
