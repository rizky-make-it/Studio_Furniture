"""Latar studio konsisten + profil lampu seragam (28 Okt 2026).

Jalankan dari folder utama:
  blender -b --python 99_SISTEM/pasang_latar_studio.py -- apply
  blender -b --python 99_SISTEM/pasang_latar_studio.py -- check [produk.blend ...] [--shot=HERO]

apply : template dibackup sekali, lalu
        - cyclorama jadi shadow catcher (material abu netral, hanya untuk pantulan/bounce),
          ruang, balok plafon, dan perlengkapan tidak terlihat kamera;
        - film transparan, compositor 'NS | Latar' menempel latar abu terang netral bergradasi
          halus di belakang render; node Exposure latar diberi driver -exposure sehingga warna
          latar tetap walau exposure diubah di panel;
        - warna latar dikalibrasi lewat render sampai PNG keluaran = LATAR_HEX (atas/bawah);
        - standar studio di scene: ns_std_exposure, ns_std_view, ns_latar;
        - watt semua angle = profil V3 addon (satu profil untuk semua angle).
check : apply di memori (template tidak disimpan), impor tiap produk lewat addon, render
        satu angle -> 04_HASIL_RENDER/_LAMPU_CHECK/latar/<produk>.png + lembar_kontak.png,
        dan mencetak warna sudut latar tiap render (harus sama).
Sesi di 03_PROYEK tidak disentuh. Idempoten: aman dijalankan berulang.
"""
import bpy, sys, shutil, math, importlib.util
import numpy as np
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / '01_STUDIO' / 'Studio_Nakas.blend'
CHECK = ROOT / '04_HASIL_RENDER' / '_LAMPU_CHECK' / 'latar'
DEFAULT_PRODUCTS = [ROOT / '02_PRODUK' / p for p in (
    'Nakas/Doheny_Side_Table/Doheny_Side_Table.blend',
    'Nakas/Zuma_Tallboy/Zuma_Tallboy.blend',
    'Nakas/Doheny_Tallboy_4_Laci/Doheny_Tallboy_4_Laci.blend',
    'Meja/Doheny_Coffee_Table_Glass/Doheny_Coffee_Table_Glass.blend',
    'Tempat_Tidur/Zuma_Bed/Zuma_Bed.blend')]

# Standar studio. Exposure -2.5 + Khronos PBR Neutral: kartu abu 18% terender #757575 (uji_warna_studio.py).
STD_EXPOSURE = -2.5
STD_VIEW = ('Khronos PBR Neutral', 'None')
LATAR_NAMA = 'abu terang netral'
LATAR_HEX = {'atas': '#e8e7e5', 'bawah': '#dfdedc'}   # rata-rata ~#e4e3e1, sedikit lebih gelap ke bawah
CATCHER_ALBEDO = (0.45, 0.45, 0.45)                   # abu netral: bounce ke produk tanpa rona

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
PRODUCTS = [Path(a).resolve() for a in ARGS[1:] if a.lower().endswith('.blend')] or DEFAULT_PRODUCTS
SHOT = next((a.split('=', 1)[1] for a in ARGS if a.startswith('--shot=')), 'HERO')


def hex_to_srgb(h):
    h = h.lstrip('#')
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def srgb_to_linear(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def to_hex(rgb):
    return '#%02x%02x%02x' % tuple(int(round(max(0, min(1, v)) * 255)) for v in rgb)


# --- 1. Studio: cyclorama, ruang, film ----------------------------------------
def siapkan_objek(scene):
    cyc = next(o for o in scene.objects if o.type == 'MESH' and o.name.startswith('Cyclorama'))
    cyc.is_shadow_catcher = True
    mat = bpy.data.materials.get('Studio | Latar shadow catcher') or bpy.data.materials.new('Studio | Latar shadow catcher')
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = (*CATCHER_ALBEDO, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.85
    # Tanpa specular: shadow catcher juga menangkap pantulan (balok plafon hitam muncul sebagai garis gelap).
    bsdf.inputs['Specular IOR Level'].default_value = 0.0
    cyc.data.materials.clear(); cyc.data.materials.append(mat)
    cyc['ns_studio_asset'] = True
    for obj in scene.objects:
        if obj.type == 'MESH' and obj.name.startswith(('Room', 'Ceiling')):
            # Shadow catcher menangkap bayangan semua objek; dinding/balok yang dekat lampu
            # (produk besar, rig berskala) meninggalkan noda gelap di pojok latar.
            obj.visible_camera = False
            obj.visible_shadow = False
        if obj.get('ns_equipment') or obj.get('ns_guide'):
            # Juga tak terkena sinar diffuse/glossy: shadow catcher menghitungnya sebagai
            # penghalang cahaya world (kaki stand di lantai = bintik gelap di latar).
            for attr in ('visible_camera', 'visible_shadow', 'visible_diffuse', 'visible_glossy', 'visible_transmission'):
                setattr(obj, attr, False)
    scene.render.film_transparent = True
    ims = scene.render.image_settings
    ims.file_format = 'PNG'; ims.color_mode = 'RGB'
    return cyc


# --- 2. Compositor latar --------------------------------------------------------
def bangun_compositor(scene):
    tree = bpy.data.node_groups.get(ns.LATAR_GROUP)
    if tree is None:
        tree = bpy.data.node_groups.new(ns.LATAR_GROUP, 'CompositorNodeTree')
    tree.nodes.clear()
    if not any(i.item_type == 'SOCKET' and i.in_out == 'OUTPUT' for i in tree.interface.items_tree):
        tree.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    N, L = tree.nodes, tree.links
    rl = N.new('CompositorNodeRLayers'); rl.location = (-900, 200)
    coord = N.new('CompositorNodeImageCoordinates'); coord.location = (-700, -100)
    sep = N.new('ShaderNodeSeparateXYZ'); sep.location = (-500, -100)
    atas = N.new('CompositorNodeRGB'); atas.name = atas.label = 'Latar atas'; atas.location = (-500, -300)
    bawah = N.new('CompositorNodeRGB'); bawah.name = bawah.label = 'Latar bawah'; bawah.location = (-500, -480)
    mix = N.new('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.location = (-300, -200)
    expo = N.new('CompositorNodeExposure'); expo.name = expo.label = 'Netralkan exposure'; expo.location = (-100, -200)
    over = N.new('CompositorNodeAlphaOver'); over.location = (120, 100)
    out = N.new('NodeGroupOutput'); out.location = (340, 100)
    L.new(rl.outputs['Image'], coord.inputs['Image'])
    L.new(coord.outputs['Normalized'], sep.inputs['Vector'])
    L.new(sep.outputs['Y'], mix.inputs[0])
    L.new(bawah.outputs['Color'], mix.inputs[6])   # A (RGBA) = bawah
    L.new(atas.outputs['Color'], mix.inputs[7])    # B (RGBA) = atas
    L.new(mix.outputs[2], expo.inputs['Image'])
    L.new(expo.outputs['Image'], over.inputs['Background'])
    L.new(rl.outputs['Image'], over.inputs['Foreground'])
    L.new(over.outputs['Image'], out.inputs[0])
    # Exposure scene dikalikan ke seluruh gambar sebelum view transform; latar dibagi dulu
    # dengan faktor yang sama supaya warnanya tetap. Ekspresi sederhana: tanpa auto-run Python.
    fc = expo.inputs['Exposure'].driver_add('default_value')
    drv = fc.driver; drv.type = 'SCRIPTED'
    var = drv.variables[0] if drv.variables else drv.variables.new()
    var.name = 'e'; var.type = 'SINGLE_PROP'
    var.targets[0].id_type = 'SCENE'; var.targets[0].id = scene
    var.targets[0].data_path = 'view_settings.exposure'
    drv.expression = '-e'
    scene.compositing_node_group = tree
    scene.render.use_compositing = True
    return tree


def render_latar(scene, path, size=96):
    """Render tanpa produk (film transparan -> hanya latar compositor), kembalikan (atas, bawah) sRGB."""
    hidden = [o for o in scene.objects if o.type == 'MESH' and not o.hide_render and not o.is_shadow_catcher
              and not o.name.startswith(('Room', 'Ceiling', 'Cyclorama'))]
    for o in hidden:
        o.hide_render = True
    r = scene.render
    keep = (r.resolution_x, r.resolution_y, r.resolution_percentage, scene.cycles.samples, r.image_settings.color_depth, r.filepath)
    r.resolution_x = r.resolution_y = size; r.resolution_percentage = 100; scene.cycles.samples = 1
    r.image_settings.color_depth = '8'   # PNG 16-bit dimuat sebagai float linear; 8-bit = byte sRGB
    r.filepath = str(path); bpy.ops.render.render(write_still=True)
    r.resolution_x, r.resolution_y, r.resolution_percentage, scene.cycles.samples, r.image_settings.color_depth, r.filepath = keep
    for o in hidden:
        o.hide_render = False
    img = bpy.data.images.load(str(path), check_existing=False)
    a = np.array(img.pixels[:], dtype=np.float64).reshape(size, size, 4)[::-1, :, :3]
    bpy.data.images.remove(img)
    return a[1:4].reshape(-1, 3).mean(0), a[-4:-1].reshape(-1, 3).mean(0)


def kalibrasi_latar(scene, tree, tmp):
    """Nilai RGB latar (linear, sebelum Khronos) disetel sampai PNG = LATAR_HEX."""
    nodes = {'atas': tree.nodes['Latar atas'], 'bawah': tree.nodes['Latar bawah']}
    target = {k: [srgb_to_linear(v) for v in hex_to_srgb(h)] for k, h in LATAR_HEX.items()}
    for k, n in nodes.items():
        n.outputs['Color'].default_value = (*target[k], 1.0)
    for _ in range(5):
        got = dict(zip(('atas', 'bawah'), render_latar(scene, tmp)))
        err = max(abs(g - t) for k in got for g, t in zip(got[k], hex_to_srgb(LATAR_HEX[k])))
        print('LATAR', {k: to_hex(v) for k, v in got.items()}, 'target', LATAR_HEX, 'selisih maks', round(err * 255, 2), 'level')
        if err * 255 < 0.6:
            break
        for k, n in nodes.items():
            cur = list(n.outputs['Color'].default_value[:3])
            ratio = [max(t, 1e-4) / max(srgb_to_linear(g), 1e-4) for t, g in zip(target[k], got[k])]
            n.outputs['Color'].default_value = (*[c * r for c, r in zip(cur, ratio)], 1.0)
    tmp.unlink(missing_ok=True)
    return got


# --- 3. Standar exposure/view + lampu ---------------------------------------
def pasang_standar(scene):
    scene['ns_std_exposure'] = STD_EXPOSURE
    scene['ns_std_view'] = list(STD_VIEW)
    scene['ns_latar'] = LATAR_NAMA
    scene['ns_lighting_profile'] = 'V3'
    ns.apply_studio_standard(scene)
    _, defaults = ns.lighting_profile(scene)
    changed = 0
    for obj, shot, role in ns.rig_lights():
        if role in ns.LIGHT_ROLES and shot in defaults:
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            obj.data.energy = defaults[shot][ns.LIGHT_ROLES.index(role)] * float(scene.get('ns_rig_scale', 1.0)) ** 2
            changed += 1
    # Ukuran, warna, sebaran juga disamakan dari HERO (watt sudah sama per profil V3).
    changed += ns.copy_watts('HERO', props=('color', 'size', 'size_y', 'spread'))
    return changed


def apply(scene):
    siapkan_objek(scene)
    tree = bangun_compositor(scene)
    lampu = pasang_standar(scene)
    CHECK.mkdir(parents=True, exist_ok=True)
    got = kalibrasi_latar(scene, tree, CHECK / '_probe_latar.png')
    print('STANDAR exposure', STD_EXPOSURE, 'view', STD_VIEW, 'lampu diubah', lampu,
          'latar', {k: to_hex(v) for k, v in got.items()})


def load_rgb(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32); img.pixels.foreach_get(buf)
    srgb = not img.is_float
    bpy.data.images.remove(img)
    rgb = buf.reshape(h, w, 4)[::-1, :, :3]
    return rgb if srgb else np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(np.clip(rgb, 0, None), 1 / 2.4) - 0.055)


def save_rgb(path, rgb):
    h, w = rgb.shape[:2]
    img = bpy.data.images.new(path.stem, w, h, alpha=False)
    buf = np.ones((h, w, 4), dtype=np.float32); buf[:, :, :3] = np.clip(rgb[::-1], 0, 1)
    img.pixels.foreach_set(buf.ravel()); img.filepath_raw = str(path); img.file_format = 'PNG'; img.save()
    bpy.data.images.remove(img)


# --- main ------------------------------------------------------------------------
if MODE == 'apply' and not any(TEMPLATE.parent.glob('Studio_Nakas_sebelum_latar_*.blend')):
    backup = TEMPLATE.with_name('Studio_Nakas_sebelum_latar_%s.blend' % datetime.now().strftime('%Y%m%d_%H%M'))
    shutil.copy2(TEMPLATE, backup)
    print('BACKUP', backup.name)
bpy.ops.wm.open_mainfile(filepath=str(TEMPLATE))
apply(bpy.context.scene)

if MODE == 'apply':
    bpy.ops.wm.save_mainfile(filepath=str(TEMPLATE), compress=True)
    print('TEMPLATE_DISIMPAN', TEMPLATE)
elif MODE == 'check':
    tiles = []
    for blend in PRODUCTS:
        if not blend.is_file():
            print('LEWATI (tidak ada)', blend); continue
        bpy.ops.wm.open_mainfile(filepath=str(TEMPLATE))
        s = bpy.context.scene
        apply(s)
        assert bpy.ops.ns.import_product(filepath=str(blend)) == {'FINISHED'}
        ns.select_shot(s, SHOT); s.ns_studio.shot = SHOT
        s.render.resolution_x = s.render.resolution_y = 640; s.render.resolution_percentage = 100
        s.cycles.samples = int(next((a.split('=',1)[1] for a in ARGS if a.startswith('--samples=')), 64)); s.cycles.adaptive_threshold = 0.03
        s.render.image_settings.color_depth = '8'
        s.cycles.seed = int(next((a.split('=',1)[1] for a in ARGS if a.startswith('--seed=')), s.cycles.seed))
        path = CHECK / (blend.stem + '_' + SHOT.lower() + '.png')
        s.render.filepath = str(path); bpy.ops.render.render(write_still=True)
        rgb = load_rgb(path)
        print('CEK', blend.stem, 'exposure', round(s.view_settings.exposure, 2), s.view_settings.view_transform,
              'rig', round(float(s.get('ns_rig_scale', 1)), 2), 'sudut kiri-atas', to_hex(rgb[2:12, 2:12].reshape(-1, 3).mean(0)),
              'kanan-atas', to_hex(rgb[2:12, -12:-2].reshape(-1, 3).mean(0)))
        tiles.append(rgb)
    if tiles:
        gap = np.full((tiles[0].shape[0], 8, 3), 1.0)
        sheet = np.concatenate(sum([[t, gap] for t in tiles], [])[:-1], axis=1)
        save_rgb(CHECK / ('lembar_kontak_' + SHOT.lower() + '.png'), sheet)
        print('LEMBAR_KONTAK', CHECK / ('lembar_kontak_' + SHOT.lower() + '.png'))
