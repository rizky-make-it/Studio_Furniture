"""Daftarkan set tekstur PBR (unduhan Poly Haven) ke finishes.json lewat baris perintah.

Jalankan di Blender (butuh bpy untuk konversi EXR):
  blender -b --factory-startup --python 99_SISTEM/pipeline/daftar_tekstur_dasar.py -- <zip|folder> [<zip|folder> ...]
Tanpa argumen: mendaftarkan ulang semua folder yang sudah ada di 02_PRODUK/_FINISH/tekstur_dasar/.
Lebih mudah lewat panel Blender: Nakas Studio > FINISH > Library finish > "Tambah tekstur dasar".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tekstur_dasar as td


def main():
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    sources = [Path(a) for a in args] or sorted(p for p in td.BASE.glob('*') if p.is_dir())
    for src in sources:
        ident, names = td.daftarkan(src)
        print('DAFTAR', ident, names)
    print('TEKSTUR_DASAR_TERDAFTAR', len(sources), 'tersedia:', ', '.join(sorted(td.manifest_load().get('tekstur_dasar', {}))))


main()
