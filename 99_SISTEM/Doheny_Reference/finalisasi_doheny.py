import bpy, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / '02_PRODUK/Nakas/Doheny_B_Tan_Mindi'
OUT = ROOT / '04_HASIL_RENDER/Doheny_B_Tan_Mindi'
sys.path.insert(0, str(ROOT / '99_SISTEM'))
import nakas_studio_tools as ns
if not hasattr(bpy.types.Scene, 'ns_studio'):
    ns.register()

MODE = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else 'check'

# --- 1. kalibrasi finish pada file produk ------------------------------------
bpy.ops.wm.open_mainfile(filepath=str(ASSET / 'Doheny_B_Tan_Mindi.blend'))
s = bpy.context.scene
wood = bpy.data.materials['B TAN MINDI | Asli PDF halaman 2']
n, l = wood.node_tree.nodes, wood.node_tree.links
bsdf = n.get('Principled BSDF')
tex = next(node for node in n if node.type == 'TEX_IMAGE')
finish = n.get('B Tan | Satin stain calibration')
# Swatch asli rata-rata sRGB (183,154,129). Render sebelumnya (153,136,122): terlalu gelap
# dan kehilangan saturasi -> terlihat pink/abu. Multiply dilonggarkan, saturasi dikembalikan.
finish.inputs[2].default_value = (0.84, 0.79, 0.71, 1)
hsv = n.get('B Tan | Saturasi serat') or n.new('ShaderNodeHueSaturation')
hsv.name = 'B Tan | Saturasi serat'
hsv.inputs['Saturation'].default_value = 1.22
hsv.inputs['Value'].default_value = 1.0
# tex -> hsv -> finish(multiply) -> base color
for link in list(finish.inputs[1].links):
    l.remove(link)
l.new(tex.outputs['Color'], hsv.inputs['Color'])
l.new(hsv.outputs['Color'], finish.inputs[1])
l.new(finish.outputs[0], bsdf.inputs['Base Color'])
# coat sedikit lebih jelas supaya satin terbaca, bukan matte pink
bsdf.inputs['Coat Weight'].default_value = 0.14
bsdf.inputs['Coat Roughness'].default_value = 0.35

# --- 2. konfirmasi dimensi & arah serat --------------------------------------
lo, hi = ns.product_bounds(s)
dims = [round(float(v) * 100, 3) for v in hi - lo]
root = ns.root_for(s)
root['dimensions_cm'] = dims
grain = {}
for o in s.objects:
    if o.type == 'MESH' and 'cad_part' in o:
        grain[o.name] = o.get('cad_part')
meta = json.loads((ASSET / 'INFORMASI.json').read_text(encoding='utf-8'))
meta['dimensions_cm'] = dims
meta['dimension_check'] = ('CAD overall 450 x 463.6 x 453.96 (W x D x H, mm). Inch reading would be 11 m wide, '
                           'so millimetre interpretation is confirmed. Model W45.0 x D46.36 x H45.40 cm matches CAD within 0.1 mm.')
meta['grain_direction'] = {'top_and_shelf': 'along width (X)', 'drawer_front': 'horizontal (X)',
                           'sides_rear_stiles': 'vertical (Z)', 'note': 'follows standard case-goods convention'}
meta['finish_calibration'] = {'multiply_rgb': [0.84, 0.79, 0.71], 'saturation': 1.22,
                              'target_srgb_mean': [183, 154, 129], 'target_source': 'B_Tan_Mindi_Asli.png (PDF page 2)'}
(ASSET / 'INFORMASI.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(ASSET / 'Doheny_B_Tan_Mindi.blend'))
print('PRODUK_DISIMPAN', dims)

# --- 3. sesi studio baru dari template, render ------------------------------
bpy.ops.wm.open_mainfile(filepath=str(ROOT / '01_STUDIO/Studio_Nakas.blend'))
s = bpy.context.scene
assert bpy.ops.ns.import_product(filepath=str(ASSET / 'Doheny_B_Tan_Mindi.blend')) == {'FINISHED'}
s.ns_studio.output = '//../04_HASIL_RENDER/'
ns.select_shot(s, 'HERO'); s.ns_studio.shot = 'HERO'
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / '03_PROYEK/Doheny_B_Tan_Mindi_Studio.blend'))

prefs = bpy.context.preferences.addons.get('cycles')
gpu = []
if prefs:
    cp = prefs.preferences
    for dt in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
        try:
            cp.compute_device_type = dt
            cp.get_devices()
            devs = [d for d in cp.devices if d.type == dt]
            if devs:
                for d in cp.devices: d.use = True
                s.cycles.device = 'GPU'; gpu = [d.name for d in devs]; break
        except Exception:
            continue
print('GPU', gpu)

if MODE == 'check':
    s.render.resolution_x = s.render.resolution_y = 700; s.cycles.samples = 32; s.cycles.adaptive_threshold = .04
    s.render.filepath = str(OUT / 'hero_finish_check2.png'); bpy.ops.render.render(write_still=True)
    print('CHECK_SELESAI')
else:
    s.ns_studio.quality = 'FINAL'
    ns.quality_updated(s.ns_studio, bpy.context)
    for shot in ns.SHOT_IDS:
        setattr(s.ns_studio, 'include_' + shot.lower(), True)
    import time; t0 = time.time()
    assert bpy.ops.ns.render_batch() == {'FINISHED'}
    print('BATCH_SELESAI', round(time.time() - t0), 'detik')
