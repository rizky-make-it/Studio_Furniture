@echo off
setlocal
cd /d "%~dp0"
echo Menggabungkan Doheny_Tallboy_4_Laci.blend (tekstur referensi silver oak 01)...
if not exist "Doheny_Tallboy_4_Laci.blend.part0" ( echo File part tidak ditemukan. & pause & exit /b 1 )
copy /b "Doheny_Tallboy_4_Laci.blend.part0"+"Doheny_Tallboy_4_Laci.blend.part1"+"Doheny_Tallboy_4_Laci.blend.part2" "Doheny_Tallboy_4_Laci_baru.tmp" >nul
for %%A in ("Doheny_Tallboy_4_Laci_baru.tmp") do set UKURAN=%%~zA
if not "%UKURAN%"=="62029949" ( echo GAGAL: ukuran %UKURAN%, seharusnya 62029949. File lama tidak diubah. & del "Doheny_Tallboy_4_Laci_baru.tmp" & pause & exit /b 1 )
if exist "Doheny_Tallboy_4_Laci.blend" if not exist "Doheny_Tallboy_4_Laci_sebelum_referensi.blend" ren "Doheny_Tallboy_4_Laci.blend" "Doheny_Tallboy_4_Laci_sebelum_referensi.blend"
if exist "Doheny_Tallboy_4_Laci.blend" del "Doheny_Tallboy_4_Laci.blend"
ren "Doheny_Tallboy_4_Laci_baru.tmp" "Doheny_Tallboy_4_Laci.blend"
del "Doheny_Tallboy_4_Laci.blend.part0" "Doheny_Tallboy_4_Laci.blend.part1" "Doheny_Tallboy_4_Laci.blend.part2"
echo Selesai. File lama disimpan sebagai Doheny_Tallboy_4_Laci_sebelum_referensi.blend
pause
del "%~f0"
