"""5 opsi render FRONT: variasi saturasi / kontras / isi rongga. Mode: -- check (700px) | -- final (2048px).
Hasil: 04_HASIL_RENDER/Doheny_B_Tan_Mindi/OPSI_<mode>/opsi_<n>_<nama>.png + opsi.json
"""
import bpy, sys, json, math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / '01_STUDIO/Studio_Nakas.blend'
ASSET_DIR = ROOT / '02_PRODUK/Nakas/Doheny_B_Tan_Mindi'
ASSET = ASSET_DIR / 'Doheny_B_Tan_Mindi.blend'
SESSION = ROOT / '03_PROYEK/Doheny_B_Tan_Mindi_Studio.blend'
sys.path.insert(0, str(ROOT / '99_SISTEM'))
import importlib, nakas_studio_tools as ns
importlib.reload(ns)
if not hasattr(bpy.types.Scene, 'ns_studio'):
    ns.register()
MODE = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'check'
OUT = ROOT / '04_HASIL_RENDER/Doheny_B_Tan_Mindi' / ('OPSI_2K' if MODE == 'final' else 'OPSI_cek')
OUT.mkdir(parents=True, exist_ok=True)

# Semua: Front fill kecil, Shelf fill sangat kecil atau mati, exposure lebih rendah dari -0.65.
# sat/mult = material; key/fill/rim/top/front/shelf = pengali atau watt absolut; exp = exposure.
OPTIONS = [
    dict(nama='A_netral',        sat=1.25, mult=(0.80, 0.71, 0.60), fill=0.80, key=1.00, front=4.0, shelf=0.12, exp=-0.70),
    dict(nama='B_kontras',       sat=1.30, mult=(0.80, 0.71, 0.60), fill=0.60, key=1.10, front=0.0, shelf=0.12, exp=-0.75),
    dict(nama='C_rongga_alami',  sat=1.25, mult=(0.82, 0.73, 0.62), fill=0.75, key=1.00, front=3.0, shelf=0.0,  exp=-0.70),
    dict(nama='D_hangat',        sat=1.35, mult=(0.80, 0.70, 0.57), fill=0.70, key=1.05, front=3.0, shelf=0.08, exp=-0.70),
    dict(nama='E_lembut',        sat=1.20, mult=(0.84, 0.76, 0.66), fill=0.90, key=0.95, front=5.0, shelf=0.15, exp=-0.60),
]

# --- produk: simpan basis (opsi A) ke file produk sekali ------------------------
bpy.ops.wm.open_mainfile(filepath=str(ASSET))
wood = bpy.data.materials['B TAN MINDI | Asli PDF halaman 2']; n = wood.node_tree.nodes
n['B Tan | Saturasi serat'].inputs['Saturation'].default_value = OPTIONS[0]['sat']
n['B Tan | Satin stain calibration'].inputs[2].default_value = (*OPTIONS[0]['mult'], 1)
meta = json.loads((ASSET_DIR / 'INFORMASI.json').read_text(encoding='utf-8'))
meta['finish_calibration'].update(multiply_rgb=list(OPTIONS[0]['mult']), saturation=OPTIONS[0]['sat'])
(ASSET_DIR / 'INFORMASI.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
bpy.ops.file.pack_all(); bpy.ops.wm.save_as_mainfile(filepath=str(ASSET))

# --- sesi dari template -----------------------------------------------------------
bpy.ops.wm.open_mainfile(filepath=str(TEMPLATE))
assert bpy.ops.ns.import_product(filepath=str(ASSET)) == {'FINISHED'}
s = bpy.context.scene
s.ns_studio.output = '//../04_HASIL_RENDER/'
ns.select_shot(s, 'FRONT'); s.ns_studio.shot = 'FRONT'
rig = next(c for c in bpy.data.collections if c.get('ns_light_shot') == 'FRONT')
lights = {str(o.get('ns_role', '')).split(' ')[0]: o for o in rig.all_objects if o.type == 'LIGHT'}
base = {k: o.data.energy for k, o in lights.items()}
wood = bpy.data.materials['B TAN MINDI | Asli PDF halaman 2']; n = wood.node_tree.nodes
if MODE == 'final':
    s.render.resolution_x = s.render.resolution_y = 2048; s.cycles.samples = 128; s.cycles.adaptive_threshold = .03
else:
    s.render.resolution_x = s.render.resolution_y = 700; s.cycles.samples = 32; s.cycles.adaptive_threshold = .04
s.render.resolution_percentage = 100
rekap = []
for i, o in enumerate(OPTIONS, 1):
    n['B Tan | Saturasi serat'].inputs['Saturation'].default_value = o['sat']
    n['B Tan | Satin stain calibration'].inputs[2].default_value = (*o['mult'], 1)
    lights['Key'].data.energy = base['Key'] * o['key']
    lights['Fill'].data.energy = base['Fill'] * o['fill']
    lights['Front'].data.energy = o['front']
    lights['Shelf'].data.energy = o['shelf']
    s.view_settings.exposure = o['exp']
    name = f"opsi_{i}_{o['nama']}.png"
    s.render.filepath = str(OUT / name); bpy.ops.render.render(write_still=True)
    rekap.append(dict(file=name, **{k: v for k, v in o.items()}, key_w=round(lights['Key'].data.energy, 1), fill_w=round(lights['Fill'].data.energy, 1)))
    print('OPSI_SELESAI', name)
    if i == 1:
        # sesi tersimpan memakai opsi A sebagai basis
        bpy.ops.wm.save_as_mainfile(filepath=str(SESSION))
(OUT / 'opsi.json').write_text(json.dumps(rekap, indent=2), encoding='utf-8')
print('SEMUA_OPSI_SELESAI', str(OUT))
