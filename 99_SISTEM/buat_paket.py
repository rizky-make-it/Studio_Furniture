"""Kemas seluruh paket Studio_Furniture menjadi satu zip siap pindah komputer.

Jalankan:  python 99_SISTEM/buat_paket.py   (Python mana pun)
Hasil:     ../Studio_Furniture_Siap_Pakai.zip (di sebelah folder Studio_Furniture)
Tidak ikut: sesi di 03_PROYEK, file .blend1, __pycache__, folder kerja/arsip
(99_SISTEM/_kerja, 99_SISTEM/_arsip), pydeps lama, dan file uji (Uji_*).
"""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'__pycache__', '_kerja', '_arsip', 'pydeps'}


def wanted(p):
    if not p.is_file() or p.suffix in {'.blend1', '.pyc'} or p.name.startswith('Uji_'):
        return False
    if SKIP_DIRS & set(p.relative_to(root).parts):
        return False
    if '03_PROYEK' in p.parts and p.suffix == '.blend':
        return False
    return True


files = [p for p in root.rglob('*') if wanted(p)]
archive = root.parent / 'Studio_Furniture_Siap_Pakai.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for p in files:
        z.write(p, Path(root.name) / p.relative_to(root))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
print('CLEAN_PACKAGE_OK', archive, archive.stat().st_size, 'bytes', len(files), 'file')
