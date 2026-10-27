param([switch]$Lanjutkan)
$ErrorActionPreference='Stop'
$studioRoot=Split-Path -Parent $PSScriptRoot
$blender='C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
if(-not (Test-Path -LiteralPath $blender)) {
    $found=Get-Command blender.exe -ErrorAction SilentlyContinue
    if($found){$blender=$found.Source}else{throw 'Blender tidak ditemukan. Atur lokasi blender.exe dalam 99_SISTEM\buka_studio.ps1.'}
}
$template=Join-Path $studioRoot '01_STUDIO\Studio_Nakas.blend'
$startup=Join-Path $PSScriptRoot 'mulai_sesi.py'
if($Lanjutkan){
    Add-Type -AssemblyName System.Windows.Forms
    $picker=New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title='Pilih proyek studio yang ingin dilanjutkan'
    $picker.InitialDirectory=Join-Path $studioRoot '03_PROYEK'
    $picker.Filter='Proyek Blender (*.blend)|*.blend'
    if($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK){exit 0}
    $template=$picker.FileName
    $startup=Join-Path $PSScriptRoot 'lanjutkan_sesi.py'
}
if(-not (Test-Path -LiteralPath $template)){throw 'Template studio tidak ditemukan.'}
Start-Process -FilePath $blender -ArgumentList @(('"'+$template+'"'),'--window-maximized','--python',('"'+$startup+'"')) -WindowStyle Normal
