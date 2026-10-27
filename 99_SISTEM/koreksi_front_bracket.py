"""Koreksi finish + lampu Front/Shelf, lalu render FRONT 2K bracket 5 exposure.
Mode: -- check  → ubah produk/template/sesi, render cek FRONT 700px + ukur warna
      -- final  → render FRONT 2048px sekali, simpan 5 exposure (-1, -0.5, 0, +0.5, +1 EV)
"""
import bpy, sys, math, json
from pathlib import Path
from mathutils import Vector
ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / '01_STUDIO/Studio_Nakas.blend'
ASSET_DIR = ROOT / '02_PRODUK/Nakas/Doheny_B_Tan_Mindi'
ASSET = ASSET_DIR / 'Doheny_B_Tan_Mindi.blend'
SESSION = ROOT / '03_PROYEK/Doheny_B_Tan_Mindi_Studio.blend'
OUT = ROOT / '04_HASIL_RENDER/Doheny_B_Tan_Mindi'
sys.path.insert(0, str(ROOT / '99_SISTEM'))
import importlib, nakas_studio_tools as ns
importlib.reload(ns)
if not hasattr(bpy.types.Scene, 'ns_studio'):
    ns.register()
MODE = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'check'

SAT = 1.60
MULT = (0.78, 0.68, 0.56)
FRONT_LOC, FRONT_TARGET, FRONT_SIZE = Vector((0, -1.95, 1.10)), Vector((0, 0, 0.25)), (1.0, 0.75)
# Shelf fill: kecil, rendah, tepat di depan rongga rak, diarahkan ke dinding belakang rongga.
SHELF_LOC, SHELF_TARGET, SHELF_SIZE = Vector((0, -0.55, 0.21)), Vector((0, 0.15, 0.15)), (0.22, 0.10)
SHELF_W, FRONT_W = 0.4, 10
EXPOSURE = -0.65


def role_light(rig, role):
    return next((o for o in rig.all_objects if o.type == 'LIGHT' and str(o.get('ns_role', '')).startswith(role)), None)


def tune_rigs(scene):
    category, defaults = ns.lighting_profile(scene)
    for rig in bpy.data.collections:
        shot = rig.get('ns_light_shot')
        if not shot:
            continue
        watts = defaults.get(shot) if defaults else None
        # Front: turunkan, persempit
        f = role_light(rig, 'Front')
        if f is None:
            d = bpy.data.lights.new(shot + ' / Front fill', 'AREA'); f = bpy.data.objects.new(d.name, d)
            f['ns_role'] = 'Front · W'; f['ns_light_shot'] = shot; rig.objects.link(f)
        f.data.shape = 'RECTANGLE'; f.data.size, f.data.size_y = FRONT_SIZE
        f.data.color = (1.0, 0.985, 0.97); f.data.spread = math.radians(100)
        f.data.energy = watts[ns.LIGHT_ROLES.index('Front')] if watts else FRONT_W
        f.location = FRONT_LOC; ns.aim(f, FRONT_TARGET); f.visible_camera = False
        # Shelf
        sh = role_light(rig, 'Shelf')
        if sh is None:
            d = bpy.data.lights.new(shot + ' / Shelf fill', 'AREA'); sh = bpy.data.objects.new(d.name, d)
            sh['ns_role'] = 'Shelf · W'; sh['ns_light_shot'] = shot; rig.objects.link(sh)
        sh.data.shape = 'RECTANGLE'; sh.data.size, sh.data.size_y = SHELF_SIZE
        sh.data.color = (1.0, 0.97, 0.94); sh.data.spread = math.radians(40)
        sh.data.energy = watts[ns.LIGHT_ROLES.index('Shelf')] if watts else SHELF_W
        sh.location = SHELF_LOC; ns.aim(sh, SHELF_TARGET); sh.visible_camera = False


# --- 1. produk: saturasi & kedalaman warna --------------------------------------
bpy.ops.wm.open_mainfile(filepath=str(ASSET))
wood = bpy.data.materials['B TAN MINDI | Asli PDF halaman 2']
n = wood.node_tree.nodes
n['B Tan | Saturasi serat'].inputs['Saturation'].default_value = SAT
n['B Tan | Satin stain calibration'].inputs[2].default_value = (*MULT, 1)
b = n['Principled BSDF']; b.inputs['Coat Weight'].default_value = 0.10
meta = json.loads((ASSET_DIR / 'INFORMASI.json').read_text(encoding='utf-8'))
meta['finish_calibration'].update(multiply_rgb=list(MULT), saturation=SAT, coat_weight=0.10)
(ASSET_DIR / 'INFORMASI.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
bpy.ops.file.pack_all(); bpy.ops.wm.save_as_mainfile(filepath=str(ASSET))
print('PRODUK_DISIMPAN')

# --- 2. template: lampu Front & Shelf -------------------------------------------
bpy.ops.wm.open_mainfile(filepath=str(TEMPLATE))
s = bpy.context.scene
tune_rigs(s)
bpy.ops.wm.save_as_mainfile(filepath=str(TEMPLATE))
print('TEMPLATE_DISIMPAN total lampu', sum(o.type == 'LIGHT' for o in s.objects))

# --- 3. sesi dari template --------------------------------------------------------
assert bpy.ops.ns.import_product(filepath=str(ASSET)) == {'FINISHED'}
s = bpy.context.scene
s.ns_studio.output = '//../04_HASIL_RENDER/'
ns.select_shot(s, 'FRONT'); s.ns_studio.shot = 'FRONT'
s.view_settings.exposure = EXPOSURE
bpy.ops.wm.save_as_mainfile(filepath=str(SESSION))
print('SESI_DISIMPAN exposure', s.view_settings.exposure, 'view', s.view_settings.view_transform, 'look', s.view_settings.look, 'world', s.world.name if s.world else None)
for o in s.objects:
    if o.type=='LIGHT' and not o.hide_render and o.users_collection and not o.users_collection[0].hide_render: print('LAMPU_AKTIF', o.name, round(o.data.energy,1))

if MODE == 'check':
    s.render.resolution_x = s.render.resolution_y = 700
    s.cycles.samples = 32; s.cycles.adaptive_threshold = .04
    s.render.filepath = str(OUT / 'cek_front_koreksi.png'); bpy.ops.render.render(write_still=True)
    sys.path.insert(0, str(ROOT / '99_SISTEM/pydeps'))
    from PIL import Image, ImageStat
    im = Image.open(OUT / 'cek_front_koreksi.png').convert('RGB'); w, h = im.size
    drawer = [round(v) for v in ImageStat.Stat(im.crop((int(w * .25), int(h * .14), int(w * .75), int(h * .28)))).mean]
    shelf = [round(v) for v in ImageStat.Stat(im.crop((int(w * .3), int(h * .45), int(w * .7), int(h * .65)))).mean]
    print('UKUR drawer_front', drawer, 'shelf_cavity', shelf, 'target_swatch [183,154,129]')
    print('CHECK_SELESAI')
else:
    folder = OUT / '2K_bracket_front'; folder.mkdir(exist_ok=True)
    s.render.resolution_x = s.render.resolution_y = 2048; s.render.resolution_percentage = 100
    s.cycles.samples = 160; s.cycles.adaptive_threshold = .02
    base = s.view_settings.exposure
    bpy.ops.render.render(write_still=False)
    rr = bpy.data.images['Render Result']
    for ev in (-1.0, -0.5, 0.0, 0.5, 1.0):
        s.view_settings.exposure = base + ev
        p = folder / ('front_2k_ev%+.1f.png' % ev)
        rr.save_render(filepath=str(p), scene=s)
        print('SIMPAN', p.name)
    s.view_settings.exposure = base
    print('BRACKET_SELESAI', str(folder))
