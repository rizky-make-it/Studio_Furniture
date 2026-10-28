@echo off
rem Seret (drag-drop) satu atau beberapa file produk .blend ke file ini.
rem Hasil: 04_HASIL_RENDER\Katalog_Doheny\<Produk>\ (HERO, FRONT, SIDE, LIFESTYLE, 2000x2500)
setlocal
set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
set "ROOT=%~dp0.."
set "FINISH=natural_oak"
if "%~1"=="" (echo Seret file produk .blend ke file ini. & pause & exit /b)
:loop
if "%~1"=="" goto done
echo === Render katalog: %~n1 ===
"%BLENDER%" -b "%ROOT%\01_STUDIO\Studio_Katalog_Doheny.blend" --python "%ROOT%\99_SISTEM\katalog_doheny.py" -- "%~1" --finish %FINISH%
shift
goto loop
:done
start "" "%ROOT%\04_HASIL_RENDER\Katalog_Doheny"
pause
