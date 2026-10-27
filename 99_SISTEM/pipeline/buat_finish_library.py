"""Bangun 02_PRODUK/_FINISH/Finish_Library.blend: node group 'TALA Kayu' + material hardware.

Jalankan:  blender -b --factory-startup --python buat_finish_library.py
Finish kayu TIDAK ada di sini; finish kayu mengikuti data tiap produk
(produk.json -> finish_kayu) dan ditanam ke file produk oleh bangun_produk.py.
Library hanya menyediakan material handle (HW | ...) yang bisa dipilih di studio.
"""
import bpy, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINISH = ROOT / '02_PRODUK' / '_FINISH'
LIB = FINISH / 'Finish_Library.blend'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import finish_kayu as fk


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    fk.build_group()
    made = [fk.hardware_material(item).name for item in fk.hardware_entries()]
    scene = bpy.context.scene
    scene.name = 'FINISH LIBRARY | Tala Living'
    text = bpy.data.texts.new('BACA'); text.use_fake_user = True
    text.write('Library hardware Tala Living (HW | ..., ns_role HANDLE) + node group TALA Kayu.\n'
               'Dibuat oleh 99_SISTEM/pipeline/buat_finish_library.py dari finishes.json (bagian hardware).\n'
               'Finish kayu ada di tiap file produk, mengikuti produk.json produk tersebut.\n')
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(LIB), compress=True)
    print('LIBRARY_OK', LIB, LIB.stat().st_size // 1024, 'KB', made)


main()
