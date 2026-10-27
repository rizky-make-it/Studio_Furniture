"""Tambah / perbarui lampu 'Tengah' (softbox rendah di depan rongga produk) pada semua rig angle.

Jalankan dari folder utama:
  blender -b --python 99_SISTEM/tambah_lampu_tengah.py -- apply [--reset-watt]
  blender -b --python 99_SISTEM/tambah_lampu_tengah.py -- check [produk.blend] [--reset-watt]

apply : pastikan setiap rig angle punya satu lampu Tengah dengan properti yang
        dikenali addon (ns_role 'Tengah · W', ns_studio_asset, ns_light_shot).
        Watt diambil dari LIGHTING_DEFAULTS addon hanya saat lampu baru dibuat
        (atau bila --reset-watt). Template dibackup sekali, lalu disimpan.
check : seperti apply, lalu render HERO dan FRONT produk (default
        02_PRODUK/Nakas/Doheny_Side_Table) dengan lampu Tengah mati dan nyala
        -> 04_HASIL_RENDER/_LAMPU_CHECK/<shot>_cek.png (kiri mati, kanan nyala).
Sesi di 03_PROYEK tidak disentuh. Idempoten: aman dijalankan berulang.
"""
import bpy, sys, shutil, math, importlib.util
import numpy as np
from pathlib import Path
from datetime import datetime
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / '01_STUDIO' / 'Studio_Nakas.blend'
CHECK = ROOT / '04_HASIL_RENDER' / '_LAMPU_CHECK' / 'tengah'
DEFAULT_PRODUCT = ROOT / '02_PRODUK' / 'Nakas' / 'Doheny_Side_Table' / 'Doheny_Side_Table.blend'

# Addon milik paket, bukan salinan di folder addon Blender.
_old = sys.modules.get('nakas_studio_tools')
if _old and hasattr(bpy.types.Scene, 'ns_studio'):
    _old.unregister()
_spec = importlib.util.spec_from_file_location('nakas_studio_tools', ROOT / '99_SISTEM' / 'nakas_studio_tools.py')
ns = importlib.util.module_from_spec(_spec)
sys.modules['nakas_studio_tools'] = ns
_spec.loader.exec_module(ns)
ns.register()

ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else ['apply']
MODE = ARGS[0] if ARGS and not ARGS[0].startswith('--') else 'apply'
RESET_WATT = '--reset-watt' in ARGS
PRODUCT = Path(next((a for a in ARGS[1:] if a.lower().endswith('.blend')), DEFAULT_PRODUCT))

# Spesifikasi lampu Tengah: softbox 0.7 x 0.45 m rendah tepat di depan produk
# (sumbu -Y, tinggi 0.45 m), diarahkan ke dalam rongga rak/laci (z 0.2 m).
# Spread 110° supaya cahaya masuk ke rongga tanpa menyapu backdrop dan lantai.
# Nilai watt per angle ada di LIGHTING_DEFAULTS addon (anggota ke-5, 'Tengah').
FRONT = {
    'location': Vector((0.0, -1.25, 0.45)), 'target': Vector((0.0, 0.0, 0.20)),
    'size': (0.7, 0.45), 'color': (1.0, 0.99, 0.975), 'spread': math.radians(110),
}


def front_light_of(rig):
    return next((o for o in rig.all_objects if o.type == 'LIGHT' and str(o.get('ns_role', '')).startswith('Tengah')), None)


def ensure_front_lights(scene):
    if 'Tengah' not in ns.LIGHT_ROLES:
        raise SystemExit('Addon belum mengenal peran Tengah; perbarui LIGHT_ROLES dan LIGHTING_DEFAULTS di nakas_studio_tools.py.')
    category, defaults = ns.lighting_profile(scene)
    index = ns.LIGHT_ROLES.index('Tengah')
    created, updated = [], []
    for rig in bpy.data.collections:
        shot = rig.get('ns_light_shot')
        if not shot:
            continue
        obj = front_light_of(rig)
        fresh = obj is None
        if fresh:
            data = bpy.data.lights.new(shot + ' / Tengah fill', 'AREA')
            obj = bpy.data.objects.new(shot + ' / Tengah fill', data)
            rig.objects.link(obj)
        data = obj.data
        if data.users > 1:
            obj.data = data = data.copy()
        data.type = 'AREA'; data.shape = 'RECTANGLE'
        data.size, data.size_y = FRONT['size']
        data.color = FRONT['color']; data.spread = FRONT['spread']
        if fresh or RESET_WATT:
            data.energy = defaults[shot][index] if defaults and shot in defaults and len(defaults[shot]) > index else 60
        obj['ns_role'] = 'Tengah · W'
        obj['ns_light_shot'] = shot
        obj['ns_studio_asset'] = True
        obj.location = FRONT['location']
        ns.aim(obj, FRONT['target'])
        obj.visible_camera = False
        (created if fresh else updated).append(obj.name)
    return created, updated


def load_rgb(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32); img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return np.ascontiguousarray(buf.reshape(h, w, 4)[::-1, :, :3])


def save_rgb(path, rgb):
    h, w = rgb.shape[:2]
    img = bpy.data.images.new(path.stem, w, h, alpha=False)
    buf = np.ones((h, w, 4), dtype=np.float32); buf[:, :, :3] = np.clip(rgb[::-1], 0, 1)
    img.pixels.foreach_set(buf.ravel()); img.filepath_raw = str(path); img.file_format = 'PNG'; img.save()
    bpy.data.images.remove(img)


def render(scene, shot, path, samples=32):
    ns.select_shot(scene, shot); scene.ns_studio.shot = shot
    scene.render.resolution_x = scene.render.resolution_y = 700
    scene.render.resolution_percentage = 100
    scene.cycles.samples = samples; scene.cycles.adaptive_threshold = 0.04
    scene.render.filepath = str(path); bpy.ops.render.render(write_still=True)


# --- 1. Template ---------------------------------------------------------------
if not any(TEMPLATE.parent.glob('Studio_Nakas_sebelum_tengah_*.blend')):
    backup = TEMPLATE.with_name('Studio_Nakas_sebelum_tengah_%s.blend' % datetime.now().strftime('%Y%m%d_%H%M'))
    shutil.copy2(TEMPLATE, backup)
    print('BACKUP', backup.name)
bpy.ops.wm.open_mainfile(filepath=str(TEMPLATE))
s = bpy.context.scene
created, updated = ensure_front_lights(s)
n_lights = sum(o.type == 'LIGHT' for o in s.objects)
bpy.ops.wm.save_as_mainfile(filepath=str(TEMPLATE))
print('TEMPLATE_DISIMPAN', 'baru', created, 'diperbarui', len(updated), 'total lampu', n_lights)

# --- 2. Render cek (mode check) ------------------------------------------------
if MODE == 'check':
    if not PRODUCT.is_file():
        raise SystemExit('Produk tidak ditemukan: ' + str(PRODUCT))
    CHECK.mkdir(parents=True, exist_ok=True)
    assert bpy.ops.ns.import_product(filepath=str(PRODUCT)) == {'FINISHED'}
    s = bpy.context.scene
    for shot in ('HERO', 'FRONT'):
        rig = next(c for c in bpy.data.collections if c.get('ns_light_shot') == shot)
        front = front_light_of(rig)
        watt = front.data.energy
        front.data.energy = 0
        render(s, shot, CHECK / f'{shot.lower()}_tengah_off.png')
        front.data.energy = watt
        render(s, shot, CHECK / f'{shot.lower()}_tengah_on.png')
        off = load_rgb(CHECK / f'{shot.lower()}_tengah_off.png'); on = load_rgb(CHECK / f'{shot.lower()}_tengah_on.png')
        gap = np.ones((off.shape[0], 20, 3), dtype=np.float32)
        save_rgb(CHECK / f'{shot.lower()}_cek.png', np.concatenate([off, gap, on], axis=1))
        print('CEK', shot, 'Tengah', watt, 'W ->', (CHECK / f'{shot.lower()}_cek.png').name)
print('TENGAH_LIGHT_OK')
