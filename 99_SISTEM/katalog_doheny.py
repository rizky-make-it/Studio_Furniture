"""Studio Katalog Doheny — satu studio, hasil konsisten.

Pakai (Blender 5.2, headless):
  blender -b Studio_Katalog_Doheny.blend --python katalog_doheny.py -- <file_produk.blend> [--uji] [--keluar <folder>]

- Impor HANYA produk: koleksi 'PROD | ...' atau objek di bawah root produk. Objek studio,
  kamera, lampu, set lain ditolak (mencegah studio tergandakan).
- Produk diletakkan di tengah lantai (Z=0). Dinding diposisikan pada jarak tetap dari produk.
- 4 kamera (HERO, FRONT, SIDE, LIFESTYLE) dihitung dari ukuran produk: lensa tetap, margin tetap, 4:5.
- Cahaya: matahari (tak bergantung jarak) + fill + penerang dinding, nilai TETAP. Exposure TETAP.
- Render ke <keluar>/<Produk>/Doheny_<Produk>_<ANGLE>.png + lembar kontak + QC (L lantai & dinding).
"""
import bpy, sys, os, json, math
from mathutils import Vector

ANGLES = {   # arah kamera dari target (dinormalisasi), lensa mm, titik bidik (fraksi bbox), margin, skala jarak
    'HERO':      dict(dir=(0.62, -1.0, 0.42), lens=50, aim=(0.0, 0.0, 0.45), margin=1.14, dist=1.0),
    'FRONT':     dict(dir=(0.0, -1.0, 0.10),  lens=50, aim=(0.0, 0.0, 0.48), margin=1.14, dist=1.0),
    'SIDE':      dict(dir=(1.0, 0.0, 0.10),   lens=50, aim=(0.0, 0.0, 0.48), margin=1.14, dist=1.0),
    'LIFESTYLE': dict(dir=(0.85, -1.0, 0.55), lens=40, aim=(0.30, -0.10, 0.62), margin=1.0, dist=0.62),
}
RES = (2000, 2500)          # 4:5
SAMPLES = 256
STUDIO_COLS = ('STUDIO', 'LIGHTS', 'LIGHTING', 'CAMERAS', 'SET |', 'KATALOG |', 'RENDER |', 'EVAL')
BAD_MAT = ('Studio |', 'Equipment |', 'Architecture |', 'Katalog |', 'Set |', 'Studio Katalog |')

def log(*a): print('[katalog]', *a)

# Finish standar katalog Doheny: satu set tekstur (warna + relief + kilap cocok), dikalibrasi di studio ini.
FINISH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '02_PRODUK', '_FINISH', 'katalog_doheny')
FINISHES = {
    'natural_oak': dict(nama='Doheny Natural Oak', albedo='doheny_natural_oak_albedo.jpg', rough=(0.45, 0.62), coat=0.05),
    'oak_madu':    dict(nama='Doheny Oak Madu',    albedo='doheny_oak_madu_albedo.jpg',    rough=(0.45, 0.62), coat=0.05),
}

def _img(fn, cs):
    p = os.path.join(FINISH_DIR, fn)
    im = bpy.data.images.get(fn) or bpy.data.images.load(p, check_existing=True)
    im.colorspace_settings.name = cs; return im

def is_wood_mat(m):
    return m and (m.get('ns_role') == 'WOOD_A' or m.name.startswith('FIN |')) and m.use_nodes

def apply_finish(coll, key):
    f = FINISHES[key]; alb = _img(f['albedo'], 'sRGB'); nor = _img('doheny_oak_normal.jpg', 'Non-Color'); rgh = _img('doheny_oak_roughness.jpg', 'Non-Color')
    mats = {s.material for o in coll.all_objects if o.type == 'MESH' for s in o.material_slots if is_wood_mat(s.material)}
    for m in mats:
        nt = m.node_tree; n = nt.nodes; l = nt.links
        texs = [x for x in n if x.type == 'TEX_IMAGE']
        for t in texs:
            lab = (t.label or '').lower(); img = (t.image.name.lower() if t.image else '')
            key = lab.split('(')[0] if lab else img                      # kata pertama label menentukan peran
            if 'swatch' in key: continue
            elif 'albedo' in key or 'warna' in key or 'diff' in key: t.image = alb
            elif 'nor' in key: t.image = nor
            elif 'rough' in key or 'kasar' in key: t.image = rgh
            elif t.image and t.image.colorspace_settings.name != 'sRGB':
                t.image = nor if 'nor' in img else rgh
            else: t.image = alb
        maps = [x for x in n if x.type == 'MAPPING']
        if maps:
            for mp in maps: mp.inputs['Rotation'].default_value = (0, 0, math.radians(90))   # serat gambar horizontal -> tegak di sisi
        else:
            uv = n.new('ShaderNodeUVMap'); uv.uv_map = 'UV meter'; mp = n.new('ShaderNodeMapping'); mp.inputs['Rotation'].default_value = (0, 0, math.radians(90))
            l.new(uv.outputs['UV'], mp.inputs['Vector'])
            for t in texs: l.new(mp.outputs['Vector'], t.inputs['Vector'])
        for x in n:
            if x.type == 'MIX' and x.data_type == 'RGBA': x.inputs[0].default_value = 0.0      # matikan campuran swatch
            if x.type == 'GROUP' and 'Tint Campur' in x.inputs:
                x.inputs['Tint Campur'].default_value = 0.0; x.inputs['Tint'].default_value = (1, 1, 1, 1)
                x.inputs['Kekasaran Min'].default_value, x.inputs['Kekasaran Max'].default_value = f['rough']; x.inputs['Coat'].default_value = f['coat']
        m['ns_finish_katalog'] = f['nama']
    log('finish', f['nama'], 'dipasang ke', len(mats), 'material kayu:', [m.name for m in mats])

def product_name(path):
    n = os.path.splitext(os.path.basename(path))[0]
    for cut in ('_Siap_Render', '_Sesi_Studio', '_Perbaikan', '_Look_Referensi', '_Realistis'):
        n = n.split(cut)[0]
    return n.replace(' ', '_')

def is_studio_obj(o):
    if o.type in {'CAMERA', 'LIGHT', 'LIGHT_PROBE', 'SPEAKER'}: return True
    if o.get('ns_equipment') or o.get('ns_guide') or o.get('ns_studio_asset'): return True
    if o.type in {'CURVE', 'FONT'}: return True
    if o.type == 'MESH' and o.material_slots and all(s.material and s.material.name.startswith(BAD_MAT) for s in o.material_slots): return True
    if o.name.startswith(('Cyclorama', 'Room', 'Ceiling', 'Katalog /', 'Set /', 'Studio /', 'Ruang /')): return True
    return False

def import_product(path):
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        prod_cols = [c for c in src.collections if c.startswith('PROD |') or c.startswith('PRODUK |')]
        dst.collections = prod_cols
        if not prod_cols: dst.objects = list(src.objects)
    objs = set()
    for c in dst.collections:
        if c: objs |= set(c.all_objects)
    if not dst.collections: objs = {o for o in dst.objects if o}
    keep = {o for o in objs if not is_studio_obj(o)}
    for o in objs - keep: bpy.data.objects.remove(o, do_unlink=True)
    for c in dst.collections:
        if c:
            for ch in list(c.children_recursive): bpy.data.collections.remove(ch)
            bpy.data.collections.remove(c)
    coll = bpy.data.collections.new('PRODUK | ' + product_name(path)); bpy.context.scene.collection.children.link(coll)
    for o in keep:
        for uc in list(o.users_collection): uc.objects.unlink(o)
        coll.objects.link(o)
    meshes = [o for o in keep if o.type == 'MESH']
    if not meshes: raise SystemExit('Tidak ada mesh produk di ' + path)
    log('impor', len(keep), 'objek produk;', len(objs) - len(keep), 'objek studio/kamera/lampu ditolak')
    return coll

def bounds(objs):
    dg = bpy.context.evaluated_depsgraph_get(); pts = []
    for o in objs:
        if o.type != 'MESH' or o.hide_render: continue
        e = o.evaluated_get(dg); pts += [e.matrix_world @ Vector(v) for v in e.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)]); hi = Vector([max(p[i] for p in pts) for i in range(3)])
    return lo, hi

def place_on_floor(coll):
    tops = [o for o in coll.objects if o.parent is None]
    lo, hi = bounds(coll.all_objects)
    off = Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))
    for o in tops: o.location += off
    bpy.context.view_layer.update()
    return bounds(coll.all_objects)

def place_walls(lo, hi):
    back = bpy.data.objects['Katalog / Dinding belakang']; left = bpy.data.objects['Katalog / Dinding kiri']
    gap = 0.9 + 0.35 * max(hi.x - lo.x, hi.y - lo.y)          # jarak dinding ikut skala produk
    back.location.y = hi.y + gap; left.location.x = lo.x - gap * 1.6
    bpy.context.view_layer.update()

def frame_camera(name, cfg, lo, hi, scene):
    cam = bpy.data.objects['CAM KATALOG | ' + name]; cd = cam.data; cd.lens = cfg['lens']; cd.sensor_width = 36; cd.sensor_fit = 'AUTO'
    size = hi - lo; ctr = (lo + hi) / 2
    a = cfg['aim']; tgt = Vector((ctr.x + size.x * a[0], ctr.y + size.y * a[1], lo.z + size.z * a[2]))
    d = Vector(cfg['dir']).normalized()
    cam.location = tgt + d; cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler()
    asp = RES[0] / RES[1]; tx = cd.sensor_width / (2 * cd.lens)
    tx, ty = (tx, tx / asp) if asp >= 1 else (tx * asp, tx)
    inv = cam.rotation_euler.to_matrix().transposed(); dist = 0.05
    for x in (lo.x, hi.x):
        for y in (lo.y, hi.y):
            for z in (lo.z, hi.z):
                p = inv @ (Vector((x, y, z)) - tgt)
                dist = max(dist, p.z + abs(p.x) / tx * cfg['margin'], p.z + abs(p.y) / ty * cfg['margin'])
    dist *= cfg['dist']
    cam.location = tgt + d * dist; cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cd.dof.use_dof = True; cd.dof.focus_distance = dist; cd.dof.aperture_fstop = 11 if name != 'LIFESTYLE' else 5.6
    cd.clip_end = 200
    return cam

def qc(path):
    try:
        import numpy as np
        img = bpy.data.images.load(path); w, h = img.size
        px = np.array(img.pixels[:]).reshape(h, w, 4)[:, :, :3]  # baris bawah dulu
        def lab_L(r):  # sRGB 0-1 -> L*
            lin = np.where(r <= 0.04045, r / 12.92, ((r + 0.055) / 1.055) ** 2.4)
            Y = (lin * [0.2126, 0.7152, 0.0722]).sum(-1)
            return float(np.mean(np.where(Y > 0.008856, 116 * np.cbrt(Y) - 16, 903.3 * Y)))
        floor = lab_L(px[int(h*0.02):int(h*0.06), int(w*0.05):int(w*0.95)])
        wall = lab_L(px[int(h*0.92):int(h*0.98), int(w*0.05):int(w*0.95)])
        bpy.data.images.remove(img)
        return {'L_lantai_bawah': round(floor, 1), 'L_dinding_atas': round(wall, 1)}
    except Exception as e:
        return {'qc_error': str(e)}

def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    if not argv: raise SystemExit('Berikan path file produk .blend')
    src = argv[0]; uji = '--uji' in argv
    out_root = argv[argv.index('--keluar') + 1] if '--keluar' in argv else os.path.join(os.path.dirname(bpy.data.filepath), '..', '04_HASIL_RENDER', 'Katalog_Doheny')
    scene = bpy.context.scene
    coll = import_product(src)
    if '--finish' in argv: apply_finish(coll, argv[argv.index('--finish') + 1])
    lo, hi = place_on_floor(coll); place_walls(lo, hi)
    log('ukuran produk cm', [round((hi[i] - lo[i]) * 100, 1) for i in range(3)])
    name = argv[argv.index('--nama') + 1] if '--nama' in argv else product_name(src); outdir = os.path.abspath(os.path.join(out_root, name)); os.makedirs(outdir, exist_ok=True)
    scale = 0.32 if uji else 1.0
    scene.render.resolution_x = int(RES[0] * scale); scene.render.resolution_y = int(RES[1] * scale); scene.render.resolution_percentage = 100
    scene.cycles.samples = 32 if uji else SAMPLES; scene.cycles.use_denoising = True
    report = {'produk': name, 'sumber': src, 'ukuran_cm': [round((hi[i] - lo[i]) * 100, 1) for i in range(3)], 'render': {}}
    for ang, cfg in ANGLES.items():
        scene.camera = frame_camera(ang, cfg, lo, hi, scene)
        f = os.path.join(outdir, f'Doheny_{name}_{ang}.png'); scene.render.filepath = f
        bpy.ops.render.render(write_still=True); report['render'][ang] = {'file': f, **qc(f)}
        log(ang, report['render'][ang])
    json.dump(report, open(os.path.join(outdir, 'QC_katalog.json'), 'w'), indent=2)
    if '--simpan-sesi' in argv:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(outdir, f'Sesi_Katalog_{name}.blend'), compress=True)
    log('selesai ->', outdir)

if __name__ == '__main__':
    main()
