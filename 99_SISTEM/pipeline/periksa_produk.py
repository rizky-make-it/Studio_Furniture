"""Periksa file produk dan buat render QC di studio.

Jalankan:  blender -b --python periksa_produk.py -- <folder_produk> [--tanpa-render | --qc-cepat]
--qc-cepat: hanya kalibrasi exposure/warna + render hero dan front (cepat).
Studio berstandar (scene['ns_std_exposure'], sejak 28 Okt 2026): exposure tidak dikalibrasi per
produk; hanya tint kayu (membawa terang) yang disamakan dengan swatch, ns_exposure lama dihapus.
Cek: satu root, tanpa lampu/kamera, tekstur packed, semua slot punya peran,
dimensi vs extents DWG (toleransi 1 mm), driver laci. Hasil -> <folder_produk>/PEMERIKSAAN.json.
Render QC -> 04_HASIL_RENDER/<NamaFolder>/qc/: hero.png, front.png, side.png,
front_ortho.png dan side_ortho.png (ortografis dengan label L/D/T).
"""
import bpy, json, sys, math, importlib.util
from pathlib import Path
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('nakas_studio_tools', ROOT / '99_SISTEM' / 'nakas_studio_tools.py')
ns = importlib.util.module_from_spec(spec)
sys.modules['nakas_studio_tools'] = ns
spec.loader.exec_module(ns)
UNIT = {'mm': 0.001, 'cm': 0.01, 'm': 1.0, 'inch': 0.0254, 'ft': 0.3048}
INSUNITS = {1: 'inch', 2: 'ft', 4: 'mm', 5: 'cm', 6: 'm'}


def axis_vector(label):
    sign = -1 if label.strip().startswith('-') else 1
    v = Vector((0, 0, 0)); v['XYZ'.index(label.strip()[-1].upper())] = sign
    return v


def srgb_to_linear(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance_srgb(rgb):
    r, g, b = (srgb_to_linear(float(c)) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _render_rgb(scene, path, size, samples):
    """Render probe kecil, kembalikan array sRGB 0..1 (H, W, 3). Probe dipaksa PNG 8-bit:
    PNG 16-bit dimuat Blender sebagai float LINEAR sehingga Image.pixels bukan sRGB dan
    kalibrasi membandingkan ruang warna yang berbeda (render jadi ~2 EV terlalu terang)."""
    import numpy as np
    rx, ry, pct, smp = scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage, scene.cycles.samples
    ims = scene.render.image_settings
    fmt, depth, mode = ims.file_format, ims.color_depth, ims.color_mode
    ims.file_format = 'PNG'; ims.color_depth = '8'; ims.color_mode = 'RGB'
    scene.render.resolution_x = scene.render.resolution_y = size; scene.render.resolution_percentage = 100; scene.cycles.samples = samples
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage, scene.cycles.samples = rx, ry, pct, smp
    ims.file_format = fmt; ims.color_depth = depth; ims.color_mode = mode
    img = bpy.data.images.load(str(path), check_existing=False)
    assert not img.is_float, 'probe harus 8-bit agar Image.pixels = sRGB'
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32); img.pixels.foreach_get(buf)
    is_float = img.is_float
    bpy.data.images.remove(img)
    rgb = buf.reshape(h, w, 4)[:, :, :3]
    if is_float:
        # PNG 16-bit/float dimuat Blender sebagai linear (bukan byte/255 sRGB seperti 8-bit).
        # Kembalikan ke sRGB tampilan supaya kalibrasi (yang mengasumsikan nilai sRGB) tidak
        # mengonversi dua kali -> render dikira terlalu gelap -> exposure didorong naik, hasil pucat.
        rgb = np.where(rgb <= 0.0031308, rgb * 12.92,
                       1.055 * np.power(np.clip(rgb, 0, None), 1 / 2.4) - 0.055).astype(np.float32)
    return rgb


def render_mean(scene, path, size=320, samples=16, role='WOOD_A'):
    """Rata-rata RGB piksel yang benar-benar ditutupi bagian berperan `role` (default kayu utama).
    Dua render kecil: (A) hanya bagian berperan itu, (B) tanpa produk; piksel yang berbeda = bagian tersebut.
    Dengan begitu kasur/kain/backdrop tidak ikut mengacaukan kalibrasi."""
    import numpy as np
    meshes = [o for o in scene.ns_studio.product.all_objects if o.type == 'MESH']
    state = {o.name: o.hide_render for o in meshes}
    for o in meshes:
        o.hide_render = not any(slot.material and slot.material.get('ns_role') == role for slot in o.material_slots)
    a = _render_rgb(scene, path, size, samples)
    for o in meshes:
        o.hide_render = True
    b = _render_rgb(scene, path, size, samples)
    for o in meshes:
        o.hide_render = state[o.name]
    mask = np.abs(a - b).max(axis=2) > 0.02
    if mask.sum() < 200:
        h, w = a.shape[:2]
        mask = np.zeros((h, w), dtype=bool); mask[int(h * 0.3):int(h * 0.7), int(w * 0.3):int(w * 0.7)] = True
    return [float(v) for v in a[mask].reshape(-1, 3).mean(0)]


# View transform untuk kalibrasi dan render QC. AgX menekan saturasi warna kayu hangat
# (oak emas #d7a56c terender #c5ae9a, saturasi 0.50 -> 0.22) sehingga kalibrasi tint lari ke
# nilai ekstrem dan hasilnya pink/pucat. Khronos PBR Neutral mempertahankan rona dan saturasi
# material (dibuat untuk foto produk), jadi tint cukup kecil. Disimpan ke root produk
# (ns_view_transform, ns_look) dan dipakai addon saat impor.
VIEW_TRANSFORM = ('Khronos PBR Neutral', 'None')


def pakai_view_transform(scene):
    try:
        scene.view_settings.view_transform = VIEW_TRANSFORM[0]
        scene.view_settings.look = VIEW_TRANSFORM[1]
    except TypeError as exc:
        print('PERINGATAN view transform', VIEW_TRANSFORM, 'tidak tersedia:', exc)


def kalibrasi_exposure(scene, produk_dir, produk, qc):
    """Samakan luminans front (tampak depan) dengan luminans swatch finish default lewat Exposure.
    Dua iterasi; hasil disimpan ke root produk (ns_exposure) oleh pemanggil."""
    default = produk.get('finish', {}).get('default') or (produk.get('finish_kayu') or [{}])[0].get('id')
    stats_path = produk_dir / 'sumber' / 'finish' / (str(default).upper() + '_statistik.json')
    if not stats_path.is_file():
        return None
    target = luminance_srgb(json.loads(stats_path.read_text(encoding='utf-8'))['swatch_mean_srgb'])
    ns.select_shot(scene, 'FRONT'); scene.ns_studio.shot = 'FRONT'
    tmp = qc / '_exposure_probe.png'
    for _ in range(2):
        measured = luminance_srgb(render_mean(scene, tmp))
        delta = max(-2.5, min(1.5, math.log2(max(target, 1e-4) / max(measured, 1e-4))))
        scene.view_settings.exposure = max(-3.0, min(1.0, scene.view_settings.exposure + delta))
        if abs(delta) < 0.05:
            break
    tmp.unlink(missing_ok=True)
    return round(float(scene.view_settings.exposure), 2)


def group_node_of(mat):
    return next((n for n in mat.node_tree.nodes if n.type == 'GROUP' and n.node_tree and n.node_tree.name.startswith('TALA Kayu')), None) if mat and mat.use_nodes else None


def kalibrasi_warna(scene, produk_dir, produk, qc, tint_awal=None, iterasi=2, normalisasi=True):
    """Setelah exposure cocok, samakan rona: Tint (multiply) di node group finish diatur
    supaya rata-rata RGB front hasil render = rata-rata swatch (AgX/lampu cenderung
    menggeser rona). Tint dinormalkan agar luminans tidak berubah. Berlaku ke semua
    material FIN produk. Kembalikan tint atau None.
    normalisasi=False (studio berstandar, exposure tetap): tint ikut membawa terang, jadi
    albedo kayu sendiri yang disamakan dengan swatch."""
    default = produk.get('finish', {}).get('default') or (produk.get('finish_kayu') or [{}])[0].get('id')
    stats_path = produk_dir / 'sumber' / 'finish' / (str(default).upper() + '_statistik.json')
    mats = [m for m in bpy.data.materials if m.get('ns_role') == 'WOOD_A' and m.get('ns_finish_id') and not m.library]
    groups = [g for g in (group_node_of(m) for m in mats) if g is not None]
    if not stats_path.is_file() or not groups:
        return None
    target = [srgb_to_linear(float(v)) for v in json.loads(stats_path.read_text(encoding='utf-8'))['swatch_mean_srgb']]
    tint = list(tint_awal) if tint_awal else [1.0, 1.0, 1.0]
    tmp = qc / '_warna_probe.png'
    for _ in range(iterasi):
        for g in groups:
            g.inputs['Tint'].default_value = (*tint, 1.0)
            g.inputs['Tint Campur'].default_value = 1.0
        measured = [srgb_to_linear(v) for v in render_mean(scene, tmp)]
        ratio = [max(t, 1e-4) / max(m, 1e-4) for t, m in zip(target, measured)]
        lum = 0.2126 * ratio[0] + 0.7152 * ratio[1] + 0.0722 * ratio[2] if normalisasi else 1.0
        # Batas sempit: tint hanya koreksi kecil (lampu/latar); selisih besar = masalah view transform/tekstur.
        lo, hi = (0.6, 1.6) if normalisasi else (0.4, 1.8)
        tint = [max(lo, min(hi, tint[i] * ratio[i] / lum)) for i in range(3)]
    for g in groups:
        g.inputs['Tint'].default_value = (*tint, 1.0)
        g.inputs['Tint Campur'].default_value = 1.0
    tmp.unlink(missing_ok=True)
    return [round(v, 4) for v in tint]


def kalibrasi_optimasi(scene, produk_dir, produk, qc, exposure0, tint0, maks_eval=36):
    """Penyetelan akhir: Nelder-Mead sederhana pada (exposure, tint R, tint B) dengan tint G = 1
    meminimalkan selisih sRGB rata-rata kayu utama (render FRONT) terhadap swatch. Dipakai karena
    AgX menekan saturasi warna hangat terang sehingga heuristik rasio-per-kanal berhenti di warna
    pucat/pink. Mengembalikan (exposure, tint, hex_render)."""
    default = produk.get('finish', {}).get('default') or (produk.get('finish_kayu') or [{}])[0].get('id')
    stats_path = produk_dir / 'sumber' / 'finish' / (str(default).upper() + '_statistik.json')
    mats = [m for m in bpy.data.materials if m.get('ns_role') == 'WOOD_A' and m.get('ns_finish_id') and not m.library]
    groups = [g for g in (group_node_of(m) for m in mats) if g is not None]
    if not stats_path.is_file() or not groups or exposure0 is None or tint0 is None:
        return exposure0, tint0, None
    target = [float(v) for v in json.loads(stats_path.read_text(encoding='utf-8'))['swatch_mean_srgb']]
    ns.select_shot(scene, 'FRONT'); scene.ns_studio.shot = 'FRONT'
    tmp = qc / '_optim_probe.png'
    lo = [-3.0, 0.6, 0.6]; hi = [1.0, 1.6, 1.6]
    g_tint = float(tint0[1])
    cache = {}

    def f(x):
        x = tuple(max(lo[i], min(hi[i], float(x[i]))) for i in range(3))
        if x in cache:
            return cache[x]
        scene.view_settings.exposure = x[0]
        for g in groups:
            g.inputs['Tint'].default_value = (x[1], g_tint, x[2], 1.0); g.inputs['Tint Campur'].default_value = 1.0
        m = render_mean(scene, tmp)
        err = sum((m[i] - target[i]) ** 2 for i in range(3))
        cache[x] = (err, m)
        return cache[x]

    x0 = [float(exposure0), float(tint0[0]), float(tint0[2])]
    simplex = [x0, [x0[0] - 0.4, x0[1], x0[2]], [x0[0], x0[1] * 0.8, x0[2]], [x0[0], x0[1], min(hi[2], x0[2] * 1.5)]]
    vals = [f(x)[0] for x in simplex]
    evals = len(simplex)
    while evals < maks_eval:
        order = sorted(range(4), key=lambda i: vals[i])
        simplex = [simplex[i] for i in order]; vals = [vals[i] for i in order]
        if vals[3] - vals[0] < 1e-5:
            break
        c = [sum(simplex[i][k] for i in range(3)) / 3 for k in range(3)]
        xr = [c[k] + (c[k] - simplex[3][k]) for k in range(3)]; fr = f(xr)[0]; evals += 1
        if fr < vals[0]:
            xe = [c[k] + 2 * (c[k] - simplex[3][k]) for k in range(3)]; fe = f(xe)[0]; evals += 1
            simplex[3], vals[3] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[2]:
            simplex[3], vals[3] = xr, fr
        else:
            xc = [c[k] + 0.5 * (simplex[3][k] - c[k]) for k in range(3)]; fc = f(xc)[0]; evals += 1
            if fc < vals[3]:
                simplex[3], vals[3] = xc, fc
            else:
                for i in range(1, 4):
                    simplex[i] = [simplex[0][k] + 0.5 * (simplex[i][k] - simplex[0][k]) for k in range(3)]
                    vals[i] = f(simplex[i])[0]; evals += 1
    best = min(cache.items(), key=lambda kv: kv[1][0])
    x, (err, m) = best
    scene.view_settings.exposure = x[0]
    tint = [round(x[1], 4), round(g_tint, 4), round(x[2], 4)]
    for g in groups:
        g.inputs['Tint'].default_value = (*tint, 1.0); g.inputs['Tint Campur'].default_value = 1.0
    tmp.unlink(missing_ok=True)
    print('OPTIMASI', evals, 'evaluasi, selisih sRGB', round(err ** 0.5, 4), 'exposure', round(x[0], 2), 'tint', tint)
    return round(float(x[0]), 2), tint, '#%02x%02x%02x' % tuple(int(round(max(0.0, min(1.0, v)) * 255)) for v in m)


def ukur_warna_akhir(scene, produk_dir, produk, qc):
    """Rata-rata warna kayu utama pada render FRONT (hex sRGB) dan hex swatch finish default."""
    default = produk.get('finish', {}).get('default') or (produk.get('finish_kayu') or [{}])[0].get('id')
    stats_path = produk_dir / 'sumber' / 'finish' / (str(default).upper() + '_statistik.json')
    ns.select_shot(scene, 'FRONT'); scene.ns_studio.shot = 'FRONT'
    tmp = qc / '_warna_probe.png'
    m = render_mean(scene, tmp)
    tmp.unlink(missing_ok=True)
    to_hex = lambda c: '#%02x%02x%02x' % tuple(int(round(max(0.0, min(1.0, v)) * 255)) for v in c)
    sw = json.loads(stats_path.read_text(encoding='utf-8')).get('swatch_hex') if stats_path.is_file() else None
    return to_hex(m), sw


def simpan_kalibrasi(blend, exposure, tint):
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    for o in bpy.data.objects:
        if o.get('ns_product_root'):
            o['ns_view_transform'], o['ns_look'] = VIEW_TRANSFORM
            if exposure is not None:
                o['ns_exposure'] = float(exposure)
            elif 'ns_exposure' in o:
                del o['ns_exposure']   # studio berstandar: exposure per produk tidak dipakai lagi
            if tint is not None:
                o['ns_tint'] = [float(v) for v in tint]
    if tint is not None:
        for m in bpy.data.materials:
            g = group_node_of(m) if m.get('ns_role') == 'WOOD_A' else None
            if g is not None:
                g.inputs['Tint'].default_value = (*tint, 1.0)
                g.inputs['Tint Campur'].default_value = 1.0
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=True)


def main():
    produk_dir = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
    blend = produk_dir / (produk_dir.name + '.blend')
    produk = json.loads((produk_dir / 'sumber' / 'produk.json').read_text(encoding='utf-8'))
    info_path = produk_dir / 'sumber' / 'ekspor' / 'dwg_info.json'
    report = {'file': blend.name, 'cek': [], 'gagal': []}

    def check(name, ok, detail=''):
        (report['cek'] if ok else report['gagal']).append({'nama': name, 'detail': detail} if detail else name)

    bpy.ops.wm.open_mainfile(filepath=str(blend))
    s = bpy.context.scene
    roots = [o for o in bpy.data.objects if o.get('ns_product_root')]
    check('Satu root produk', len(roots) == 1)
    check('Tanpa lampu dan kamera', all(o.type not in {'LIGHT', 'CAMERA'} for o in bpy.data.objects))
    check('Tekstur ter-pack', all(i.packed_file for i in bpy.data.images if i.users))
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    check('Semua slot material punya peran', all(
        slot.material and slot.material.get('ns_role') for o in meshes for slot in o.material_slots))
    finish_ids = [str(v) for v in (roots[0].get('ns_finishes', []) if roots else [])]
    embedded = {str(m.get('ns_finish_id')) for m in bpy.data.materials if m.get('ns_finish_id') and m.get('ns_role') == 'WOOD_A'}
    check('Setiap finish di produk.json tertanam sebagai material', bool(finish_ids) and set(finish_ids) <= embedded,
          f'produk.json={finish_ids} tertanam={sorted(embedded)}')
    check('Finish default terpasang di kayu utama', any(
        slot.material and str(slot.material.get('ns_finish_id')) == str(roots[0].get('ns_default_finish')) for o in meshes for slot in o.material_slots) if roots else False)
    check('Setiap mesh punya UV meter', all('UV meter' in o.data.uv_layers for o in meshes))
    pts = [o.matrix_world @ v.co for o in meshes if not o.parent or o.parent.type == 'EMPTY' for v in o.data.vertices]
    lo = Vector([min(p[a] for p in pts) for a in range(3)]); hi = Vector([max(p[a] for p in pts) for a in range(3)])
    size = hi - lo
    check('Dasar di Z=0 dan terpusat', abs(lo.z) < 0.0005 and abs(lo.x + hi.x) < 0.001 and abs(lo.y + hi.y) < 0.001,
          f'lo={[round(v, 4) for v in lo]} hi={[round(v, 4) for v in hi]}')
    if info_path.exists() and produk.get('cek_extents', True):
        info = json.loads(info_path.read_text(encoding='utf-8'))
        unit_label = produk.get('unit', 'auto')
        if unit_label == 'auto':
            unit_label = INSUNITS.get(info.get('insunits'), 'mm')
        unit = UNIT[unit_label]
        if info.get('extmin') and info.get('extmax'):
            ext = (Vector(info['extmax']) - Vector(info['extmin'])) * unit
            # EXTMIN/EXTMAX mengikuti WCS sedangkan STLOUT mengikuti UCS gambar, jadi
            # urutan sumbu bisa berbeda; bandingkan tiga ukuran yang sudah diurutkan.
            got, expect = sorted(size), sorted(abs(v) for v in ext)
            diff = max(abs(a - b) for a, b in zip(got, expect))
            check('Ukuran luar sama dengan extents DWG (toleransi 1 mm)', diff <= 0.001,
                  f'produk cm={[round(v * 100, 2) for v in size]} dwg cm={[round(v * 100, 2) for v in ext]}')
    for d in [o for o in bpy.data.objects if o.get('ns_drawer')]:
        d['Open (m)'] = 0.1; d.update_tag(); bpy.context.view_layer.update()
        check('Driver laci ' + d.name, abs(d.location.y + 0.1) < 0.00001)
        d['Open (m)'] = 0.0; d.update_tag(); bpy.context.view_layer.update()
    report['dimensions_cm'] = [round(v * 100, 2) for v in size]
    report['lulus'] = not report['gagal']
    if '--tanpa-render' in sys.argv:
        (produk_dir / 'PEMERIKSAAN.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print('PERIKSA_SELESAI', 'LULUS' if report['lulus'] else 'GAGAL', report['dimensions_cm'], report['gagal'])
        return

    # --- Render QC di studio ------------------------------------------------------
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / '01_STUDIO' / 'Studio_Nakas.blend'))
    ns.register()
    s = bpy.context.scene
    assert bpy.ops.ns.import_product(filepath=str(blend)) == {'FINISHED'}
    pakai_view_transform(s)
    qc = ROOT / '04_HASIL_RENDER' / produk_dir.name / 'qc'
    qc.mkdir(parents=True, exist_ok=True)
    # --- Exposure mengikuti referensi: terangnya front hasil render disamakan dengan swatch -----
    # Exposure dan tint saling memengaruhi lewat AgX (tint hangat menaikkan terang tampak),
    # jadi keduanya dipaskan bergantian beberapa putaran, lalu warna akhir diukur.
    if s.get('ns_std_exposure') is not None:
        # Studio berstandar (pasang_latar_studio.py): exposure sama untuk semua produk supaya
        # latar dan lampu konsisten; hanya albedo kayu (tint) yang disamakan dengan swatch.
        ns.select_shot(s, 'FRONT'); s.ns_studio.shot = 'FRONT'
        exposure = None
        tint = kalibrasi_warna(s, produk_dir, produk, qc, iterasi=4, normalisasi=False)
        report['exposure_studio'] = float(s['ns_std_exposure'])
    else:
        exposure = kalibrasi_exposure(s, produk_dir, produk, qc)
        tint = None
        for _ in range(3):
            tint = kalibrasi_warna(s, produk_dir, produk, qc, tint_awal=tint, iterasi=1)
            exposure = kalibrasi_exposure(s, produk_dir, produk, qc)
        exposure, tint, _ = kalibrasi_optimasi(s, produk_dir, produk, qc, exposure, tint)
    report['exposure'] = exposure
    report['tint'] = tint
    report['warna_front_render'], report['warna_swatch'] = ukur_warna_akhir(s, produk_dir, produk, qc)
    print('KALIBRASI front render', report['warna_front_render'], 'swatch', report['warna_swatch'], 'exposure', exposure, 'tint', tint)
    cepat = '--qc-cepat' in sys.argv
    s.render.resolution_x = s.render.resolution_y = 700
    s.render.resolution_percentage = 100
    s.cycles.samples = 48; s.cycles.adaptive_threshold = 0.05
    for shot in (('HERO', 'FRONT') if cepat else ('HERO', 'FRONT', 'SIDE')):
        ns.select_shot(s, shot); s.ns_studio.shot = shot
        s.render.filepath = str(qc / (shot.lower() + '.png'))
        bpy.ops.render.render(write_still=True)
    if cepat:
        report['render_qc'] = str(qc)
        simpan_kalibrasi(blend, exposure, tint)
        (produk_dir / 'PEMERIKSAAN.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print('PERIKSA_SELESAI', 'LULUS' if report['lulus'] else 'GAGAL', report['dimensions_cm'], report['gagal'], 'exposure', exposure, 'tint', tint)
        return
    # Satu render HERO per finish yang dibawa produk, lalu kembali ke finish default.
    default_finish = ns.current_finish(s, 'WOOD_A')
    ns.select_shot(s, 'HERO'); s.ns_studio.shot = 'HERO'
    for fid, nama, _ in ns.product_finish_materials(s, 'WOOD_A'):
        ns.apply_finish(s, 'WOOD_A', fid)
        s.render.filepath = str(qc / f'finish_{fid}.png')
        bpy.ops.render.render(write_still=True)
    if default_finish:
        ns.apply_finish(s, 'WOOD_A', default_finish)
    # Laci terbuka sebagian untuk memperlihatkan kotak laci.
    for d in [o for o in s.ns_studio.product.all_objects if o.get('ns_drawer')]:
        d['Open (m)'] = min(0.12, d.id_properties_ui('Open (m)').as_dict().get('max', 0.12)); d.update_tag()
    bpy.context.view_layer.update()
    ns.select_shot(s, 'HERO'); s.ns_studio.shot = 'HERO'
    s.render.filepath = str(qc / 'hero_laci_terbuka.png')
    bpy.ops.render.render(write_still=True)
    for d in [o for o in s.ns_studio.product.all_objects if o.get('ns_drawer')]:
        d['Open (m)'] = 0.0; d.update_tag()
    bpy.context.view_layer.update()

    # Ortografis berlabel.
    lo, hi = ns.product_bounds(s)
    size = hi - lo; center = (lo + hi) / 2
    black = bpy.data.materials.new('QC | label'); black.use_nodes = True
    black.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.02, 0.02, 0.02, 1)
    black.node_tree.nodes['Principled BSDF'].inputs['Emission Color'].default_value = (0.02, 0.02, 0.02, 1)
    guides = []

    def label(text, loc, rot, size_m):
        curve = bpy.data.curves.new('QC text', type='FONT'); curve.body = text; curve.size = size_m
        curve.align_x = 'CENTER'; curve.align_y = 'CENTER'
        o = bpy.data.objects.new('QC | ' + text, curve); s.collection.objects.link(o)
        o.location = loc; o.rotation_euler = rot; o.data.materials.append(black); guides.append(o)

    def line(p0, p1, thick=0.003):
        p0, p1 = Vector(p0), Vector(p1)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(p0 + p1) / 2)
        o = bpy.context.object; d = p1 - p0
        o.dimensions = (max(abs(d.x), thick), max(abs(d.y), thick), max(abs(d.z), thick))
        o.data.materials.append(black); o.name = 'QC | garis'; guides.append(o)

    text_h = max(size) * 0.06
    views = {
        'front_ortho': {'cam_dir': Vector((0, -1, 0)), 'rot': (math.pi / 2, 0, 0), 'shot': 'FRONT', 'extent': max(size.x, size.z),
                        'lines': [((lo.x, lo.y - 0.02, -0.04), (hi.x, lo.y - 0.02, -0.04)), ((hi.x + 0.04, lo.y - 0.02, 0), (hi.x + 0.04, lo.y - 0.02, hi.z))],
                        'labels': [(f'L {size.x * 100:.1f} cm', (center.x, lo.y - 0.02, -0.04 - text_h), (math.pi / 2, 0, 0)),
                                   (f'T {size.z * 100:.1f} cm', (hi.x + 0.04 + text_h, lo.y - 0.02, center.z), (math.pi / 2, 0, math.pi / 2))]},
        'side_ortho': {'cam_dir': Vector((1, 0, 0)), 'rot': (math.pi / 2, 0, math.pi / 2), 'shot': 'SIDE', 'extent': max(size.y, size.z),
                       'lines': [((hi.x + 0.02, lo.y, -0.04), (hi.x + 0.02, hi.y, -0.04)), ((hi.x + 0.02, hi.y + 0.04, 0), (hi.x + 0.02, hi.y + 0.04, hi.z))],
                       'labels': [(f'D {size.y * 100:.1f} cm', (hi.x + 0.02, center.y, -0.04 - text_h), (math.pi / 2, 0, math.pi / 2)),
                                  (f'T {size.z * 100:.1f} cm', (hi.x + 0.02, hi.y + 0.04 + text_h, center.z), (math.pi / 2, 0, math.pi))]},
    }
    for name, v in views.items():
        cam_data = bpy.data.cameras.new('QC cam'); cam_data.type = 'ORTHO'; cam_data.ortho_scale = v['extent'] * 1.45
        cam = bpy.data.objects.new('QC | kamera ' + name, cam_data); s.collection.objects.link(cam)
        cam.location = center + v['cam_dir'] * 3.0; cam.location.z = center.z - 0.02
        cam.rotation_euler = v['rot']
        ns.select_shot(s, v['shot']); s.camera = cam
        for p0, p1 in v['lines']:
            line(p0, p1)
        for text, loc, rot in v['labels']:
            label(text, loc, rot, text_h)
        s.render.filepath = str(qc / (name + '.png'))
        bpy.ops.render.render(write_still=True)
        for o in guides:
            bpy.data.objects.remove(o, do_unlink=True)
        guides.clear()
        bpy.data.objects.remove(cam, do_unlink=True)
    report['render_qc'] = str(qc)
    if exposure is not None or tint is not None:
        simpan_kalibrasi(blend, exposure, tint)
        info_path = produk_dir / 'INFORMASI.json'
        if info_path.is_file():
            info = json.loads(info_path.read_text(encoding='utf-8'))
            info['studio_exposure'] = exposure if exposure is not None else report.get('exposure_studio')
            info['finish_tint'] = tint
            info.pop('studio_tint', None)
            info['studio_view'] = list(VIEW_TRANSFORM)
            info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding='utf-8')
    (produk_dir / 'PEMERIKSAAN.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('PERIKSA_SELESAI', 'LULUS' if report['lulus'] else 'GAGAL', report['dimensions_cm'], report['gagal'], 'exposure', exposure, 'tint', tint)


main()
