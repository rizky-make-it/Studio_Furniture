"""Pemeriksaan paket Studio Furniture.

Jalankan dari folder utama:
  blender -b 01_STUDIO/Studio_Nakas.blend --python 99_SISTEM/uji_paket.py
Hasil ditulis ke 99_SISTEM/hasil_pemeriksaan.json. Semua cek harus lulus
sebelum paket dibagikan (buat_paket.py).
"""
import bpy, sys, json, hashlib, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
# Selalu uji addon milik paket, bukan salinan di folder addon Blender.
_old = sys.modules.get('nakas_studio_tools')
if _old and hasattr(bpy.types.Scene, 'ns_studio'):
    _old.unregister()
_spec = importlib.util.spec_from_file_location('nakas_studio_tools', ROOT / '99_SISTEM' / 'nakas_studio_tools.py')
ns = importlib.util.module_from_spec(_spec)
sys.modules['nakas_studio_tools'] = ns
_spec.loader.exec_module(ns)
ns.register()
checks = []


def check(name, ok, detail=''):
    assert ok, name + (' · ' + str(detail) if detail else '')
    checks.append(name)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


template = ROOT / '01_STUDIO/Studio_Nakas.blend'
product = ROOT / '02_PRODUK/Nakas/Nakas_Oak_2Laci.blend'
library = ROOT / '02_PRODUK/_FINISH/Finish_Library.blend'
manifest = ROOT / '02_PRODUK/_FINISH/finishes.json'
hashes = {str(p): sha(p) for p in [template, product, library]}

# --- Studio kosong -----------------------------------------------------------
s = bpy.context.scene
check('Studio starts empty', s.ns_studio.product is None and not ns.product_objects(s))
check('Five camera presets remain', sum(bool(o.get('ns_shot')) for o in s.objects) == 5)
check('Light rig complete (at least twenty lights)', sum(o.type == 'LIGHT' for o in s.objects) >= 20)
check('No product texture embedded in empty studio', not any('white_oak' in i.name for i in bpy.data.images))
rigs = [c for c in bpy.data.collections if c.get('ns_light_shot')]
check('Five light rigs exist', len(rigs) == 5)
for rig in rigs:
    roles = [str(o.get('ns_role', '')).split(' ')[0] for o in rig.all_objects if o.type == 'LIGHT']
    check('Rig ' + rig['ns_light_shot'] + ' has every light role once', sorted(roles) == sorted(ns.LIGHT_ROLES))
    check('Rig ' + rig['ns_light_shot'] + ' lights tagged as studio asset', all(o.get('ns_studio_asset') for o in rig.all_objects if o.type == 'LIGHT'))

# --- File produk contoh --------------------------------------------------------
bpy.ops.wm.open_mainfile(filepath=str(product))
s = bpy.context.scene
check('Product file has no lights or cameras', all(o.type not in {'LIGHT', 'CAMERA'} for o in s.objects))
check('Product has single root', sum(bool(o.get('ns_product_root')) for o in s.objects) == 1)
check('Product contains two drawer controls', sum(bool(o.get('ns_drawer')) for o in s.objects) == 2)
check('Product textures packed', all(i.packed_file for i in bpy.data.images if i.users))

# --- Library hardware + produk pipeline ----------------------------------------
bpy.ops.wm.open_mainfile(filepath=str(library))
catalog = json.loads(manifest.read_text(encoding='utf-8'))
hw_ids = [h['id'] for h in catalog['hardware']]
check('Finish library has TALA Kayu node group', 'TALA Kayu' in bpy.data.node_groups)
check('Finish library has every hardware finish', all(any(m.get('ns_finish_id') == fid for m in bpy.data.materials) for fid in hw_ids))
check('Finish library carries no wood finish (wood follows product data)', not any(m.get('ns_role') == 'WOOD_A' for m in bpy.data.materials))
check('Finish library has no objects or lights', len(bpy.data.objects) == 0)
doheny = ROOT / '02_PRODUK/Nakas/Doheny_Side_Table/Doheny_Side_Table.blend'
hashes[str(doheny)] = sha(doheny)
bpy.ops.wm.open_mainfile(filepath=str(doheny))
doheny_spec = json.loads((doheny.parent / 'sumber/produk.json').read_text(encoding='utf-8'))
doheny_ids = [f['id'] for f in doheny_spec['finish_kayu']]
check('Pipeline product embeds every finish from its produk.json', all(any(m.get('ns_finish_id') == fid and m.get('ns_role') == 'WOOD_A' for m in bpy.data.materials) for fid in doheny_ids))
check('Pipeline product textures packed', all(i.packed_file for i in bpy.data.images if i.users))
check('Pipeline product has UV meter on every mesh', all('UV meter' in o.data.uv_layers for o in bpy.data.objects if o.type == 'MESH'))

# --- Impor ke studio -----------------------------------------------------------
bpy.ops.wm.open_mainfile(filepath=str(template))
check('Example button imports separate file', bpy.ops.ns.load_example() == {'FINISHED'})
s = bpy.context.scene
lo, hi = ns.product_bounds(s)
check('Imported physical dimensions', all(abs(a - b) < .0001 for a, b in zip(hi - lo, (.5, .4, .55))))
check('Imported root unambiguous', sum(bool(o.get('ns_product_root')) for o in s.ns_studio.product.all_objects) == 1)
for d in [o for o in s.ns_studio.product.all_objects if o.get('ns_drawer')]:
    d['Open (m)'] = .1; d.update_tag(); bpy.context.view_layer.update()
    check('Drawer driver survives import ' + d.name, abs(d.location.y + .1) < .00001)
    d['Open (m)'] = 0; d.update_tag()
check('Auto framing selects product camera', s.camera.get('ns_shot') == 'HERO')
check('Watt reset still works', bpy.ops.ns.reset_lighting(scope='CATEGORY') == {'FINISHED'})
# --- Watt untuk semua angle --------------------------------------------------------
key = {shot: obj for obj, shot, role in ns.rig_lights() if role == 'Key'}
s.ns_studio.lighting_all_angles = False
ns.snapshot_watts()
key['HERO'].data.energy = 123.0
ns.propagate_watts(s)
check('Per-angle watt stays separate by default', key['FRONT'].data.energy != 123.0)
s.ns_studio.lighting_all_angles = True
ns.snapshot_watts()
key['HERO'].data.energy = 111.0
ns.propagate_watts(s)
check('All-angle mode copies a changed watt to every angle', all(abs(o.data.energy - 111.0) < 1e-6 for o in key.values()))
check('All-angle mode leaves other roles alone', len({round(o.data.energy, 3) for o, _, r in ns.rig_lights() if r == 'Fill'}) > 1)
key['HERO'].data.color = (0.9, 0.5, 0.5)
ns.propagate_watts(s)
check('All-angle mode copies light colour too', all(abs(o.data.color[1] - 0.5) < 1e-6 for o in key.values()))
s.ns_studio.lighting_all_angles = False
s.ns_studio.shot = 'FRONT'
check('Sync operator copies active angle to the others', bpy.ops.ns.sync_lighting() == {'FINISHED'}
      and len({round(o.data.energy, 3) for o, _, r in ns.rig_lights() if r == 'Fill'}) == 1)
bpy.ops.ns.reset_lighting(scope='CATEGORY')
s.ns_studio.shot = 'HERO'

# --- Ganti finish (mengikuti data produk) ---------------------------------------
check('Hardware catalog readable from package', 'HANDLE' in ns.finish_catalog())
check('Legacy product gets wood slots by heuristic', len(ns.product_slots(s).get('WOOD_A', [])) > 0)
check('Legacy product offers no wood finish of its own', ns.product_finish_materials(s, 'WOOD_A') == [])
check('Import pipeline product into studio', bpy.ops.ns.import_product(filepath=str(doheny)) == {'FINISHED'})
s = bpy.context.scene
offered = [fid for fid, _, _ in ns.available_finishes(s, 'WOOD_A')]
check('Studio offers exactly the finishes embedded in the product', offered == doheny_ids, str(offered))
check('Default finish is the one from produk.json', ns.current_finish(s, 'WOOD_A') == doheny_spec['finish']['default'])
before = len(bpy.data.materials)
other = next(fid for fid in doheny_ids if fid != doheny_spec['finish']['default'])
n_slots = ns.apply_finish(s, 'WOOD_A', other)
check('Apply finish touches every wood slot', n_slots == len(ns.product_slots(s)['WOOD_A']))
check('Embedded finish needs no append', len(bpy.data.materials) == before)
check('Current finish reads back', ns.current_finish(s, 'WOOD_A') == other)
check('Root records chosen finish', ns.root_for(s).get('ns_finish_wood_a') == other)
hw_other = next(h for h in hw_ids if h != ns.current_finish(s, 'HANDLE'))
ns.apply_finish(s, 'HANDLE', hw_other)
check('Handle finish appended from library', len(bpy.data.materials) == before + 1 and ns.current_finish(s, 'HANDLE') == hw_other)
ns.apply_finish(s, 'HANDLE', hw_other)
check('Re-applying a finish reuses the material', len(bpy.data.materials) == before + 1)
check('Apply finish operator works', bpy.ops.ns.apply_finish(role='WOOD_A', finish_id=doheny_spec['finish']['default']) == {'FINISHED'})
ns.sync_finish_props(s)
check('Dropdown follows applied finish', s.ns_studio.finish_wood == doheny_spec['finish']['default'])
ns.apply_finish(s, 'WOOD_A', other)
check('Source files untouched', all(sha(p) == h for p, h in hashes.items()))

# --- Lanjutkan sesi ------------------------------------------------------------
# Sesi uji disimpan di 99_SISTEM, bukan folder proyek pengguna.
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / '99_SISTEM/Uji_Impor.blend'))
exec(compile((ROOT / '99_SISTEM/lanjutkan_sesi.py').read_text(encoding='utf-8'), str(ROOT / '99_SISTEM/lanjutkan_sesi.py'), 'exec'))
s = bpy.context.scene
check('Resume keeps active imported product', s.ns_studio.product is not None)
check('Resume keeps chosen finish', ns.current_finish(s, 'WOOD_A') == other)
check('Resume still offers every product finish', [fid for fid, _, _ in ns.available_finishes(s, 'WOOD_A')] == doheny_ids)
(ROOT / '99_SISTEM/hasil_pemeriksaan.json').write_text(json.dumps({'passed': len(checks), 'checks': checks}, indent=2))
print('PACKAGE_VALIDATED', len(checks))
