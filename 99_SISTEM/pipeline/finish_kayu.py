"""Finish kayu per produk: swatch dari data produk + tekstur dasar -> material ter-embed.

Modul ini dipakai bangun_produk.py (dan addon). Harus dijalankan di Blender.
Definisi finish ada di produk.json milik produk:
  "finish_kayu": [
    {"id": "zuma_b_tan_mindi", "nama": "ZUMA B Tan Mindi", "kayu": "Mindi",
     "sumber": {"pdf": "...pdf", "halaman": 2, "obj": 52},   # gambar tertanam di PDF, ATAU
     "swatch": "referensi/b_tan.jpg",                         # file gambar relatif ke sumber/
     "tekstur_dasar": "silver_oak_veneer_01",                 # id di _FINISH/finishes.json
     "kilap": {"roughness_min": 0.40, "roughness_max": 0.54, "coat": 0.08},
     "kalibrasi": {"gain_kontras": 1.15}}
  ],
  "finish": {"default": "zuma_b_tan_mindi", "handle": "hw_bronze_satin"}
Hasil per finish di <produk>/sumber/finish/: <ID>_swatch.*, <ID>_albedo.jpg,
<ID>_swatch_seamless.png, dan statistik di <ID>_statistik.json.
"""
import bpy, json, math, shutil, sys, tempfile
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINISH = ROOT / '02_PRODUK' / '_FINISH'
sys.path.insert(0, str(Path(__file__).resolve().parent))


# --- gambar ----------------------------------------------------------------------
def load_rgb(path):
    """(H, W, 3) float32 sRGB 0..1, baris atas dulu. Image.pixels 8-bit = byte/255 (sudah sRGB)."""
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return np.ascontiguousarray(buf.reshape(h, w, 4)[::-1, :, :3])


def save_rgb(path, rgb_srgb, quality=93):
    h, w = rgb_srgb.shape[:2]
    img = bpy.data.images.new(path.stem, w, h, alpha=False)
    img.colorspace_settings.name = 'sRGB'
    buf = np.ones((h, w, 4), dtype=np.float32)
    buf[:, :, :3] = np.clip(rgb_srgb[::-1], 0, 1)
    img.pixels.foreach_set(buf.ravel())
    img.filepath_raw = str(path)
    img.file_format = 'JPEG' if path.suffix.lower() in {'.jpg', '.jpeg'} else 'PNG'
    img.save(quality=quality)
    bpy.data.images.remove(img)


def center_crop(a, fraction=0.8):
    h, w = a.shape[:2]
    dy, dx = int(h * (1 - fraction) / 2), int(w * (1 - fraction) / 2)
    return a[dy:h - dy, dx:w - dx]


def resize_nn(a, h, w):
    ys = (np.arange(h) * a.shape[0] / h).astype(int)
    xs = (np.arange(w) * a.shape[1] / w).astype(int)
    return a[ys][:, xs]


def seamless(a, feather=0.45):
    h, w = a.shape[:2]
    rolled = np.roll(np.roll(a, h // 2, axis=0), w // 2, axis=1)
    yy = np.abs(np.linspace(-1, 1, h))[:, None]
    xx = np.abs(np.linspace(-1, 1, w))[None, :]
    t = np.clip((np.maximum(yy, xx) - feather) / (1 - feather), 0, 1)
    weight = 1 - (t * t * (3 - 2 * t))
    return (a * weight[..., None] + rolled * (1 - weight[..., None])).astype(np.float32)


def calibrate(base, swatch, gain=1.0):
    """Serat dari luminans tekstur dasar, warna dari swatch (rata-rata + sebaran per kanal)."""
    sw = center_crop(swatch)
    ms, ss = sw.reshape(-1, 3).mean(0), sw.reshape(-1, 3).std(0)
    luma = base @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    z = (luma - float(luma.mean())) / max(float(luma.std()), 1e-4)
    out = ms + z[..., None] * ss * gain
    return np.clip(out, 0, 1).astype(np.float32), {
        'swatch_mean_srgb': [round(float(v), 4) for v in ms], 'swatch_std_srgb': [round(float(v), 4) for v in ss],
        'gain_kontras': gain, 'swatch_hex': '#%02x%02x%02x' % tuple(int(round(v * 255)) for v in ms)}


# --- sumber swatch ------------------------------------------------------------------
def siapkan_swatch(item, sumber_dir, finish_dir):
    """Pastikan file swatch ada di finish_dir; ambil dari PDF (gambar tertanam) atau salin file."""
    existing = list(finish_dir.glob(item['id'].upper() + '_swatch.*'))
    if existing:
        return existing[0]
    src = item.get('sumber', {})
    if item.get('swatch'):
        found = sumber_dir / item['swatch']
        if not found.is_file():
            raise FileNotFoundError('Swatch tidak ada: ' + str(found))
    elif src.get('pdf') and src.get('obj'):
        import ekstrak_gambar_pdf
        tmp = Path(tempfile.mkdtemp(prefix='swatch_'))
        ekstrak_gambar_pdf.main(src['pdf'], str(tmp))
        entries = json.loads((tmp / 'daftar_gambar.json').read_text())
        hit = next((e for e in entries if e['obj'] == src['obj'] and e['file']), None)
        if hit is None:
            raise ValueError(f"Objek gambar {src['obj']} tidak ada di {src['pdf']}")
        found = tmp / hit['file']
    else:
        raise ValueError('Finish ' + item['id'] + ' butuh "swatch" (file) atau "sumber" {pdf, obj}.')
    target = finish_dir / (item['id'].upper() + '_swatch' + found.suffix.lower())
    shutil.copyfile(found, target)
    return target


def base_entry(base_id):
    manifest = json.loads((FINISH / 'finishes.json').read_text(encoding='utf-8'))
    entry = manifest.get('tekstur_dasar', {}).get(base_id)
    if entry is None:
        raise ValueError(f'Tekstur dasar "{base_id}" belum terdaftar di {FINISH / "finishes.json"}')
    folder = Path(entry['folder'])
    entry = dict(entry, folder=folder if folder.is_absolute() else FINISH / folder)
    return entry


def siapkan_finish_produk(spec, produk_dir, qc_dir=None, force=False):
    """Buat (bila belum ada) tekstur tiap finish di produk.json; kembalikan daftar siap-material."""
    sumber_dir = produk_dir / 'sumber'
    finish_dir = sumber_dir / 'finish'
    finish_dir.mkdir(parents=True, exist_ok=True)
    result = []
    for item in spec.get('finish_kayu', []):
        tag = item['id'].upper()
        base = base_entry(item['tekstur_dasar'])
        swatch_path = siapkan_swatch(item, sumber_dir, finish_dir)
        albedo_path = finish_dir / f'{tag}_albedo.jpg'
        seam_path = finish_dir / f'{tag}_swatch_seamless.png'
        stats_path = finish_dir / f'{tag}_statistik.json'
        stale = force or not (albedo_path.is_file() and seam_path.is_file() and stats_path.is_file())
        if not stale:
            stats = json.loads(stats_path.read_text(encoding='utf-8'))
            stale = stats.get('tekstur_dasar') != item['tekstur_dasar'] or stats.get('gain_kontras') != item.get('kalibrasi', {}).get('gain_kontras', 1.0)
        if stale:
            swatch = load_rgb(swatch_path)
            albedo, stats = calibrate(load_rgb(base['folder'] / base['albedo']), swatch, item.get('kalibrasi', {}).get('gain_kontras', 1.0))
            stats['tekstur_dasar'] = item['tekstur_dasar']
            save_rgb(albedo_path, albedo)
            save_rgb(seam_path, seamless(swatch))
            stats_path.write_text(json.dumps(stats, indent=1), encoding='utf-8')
            if qc_dir:
                qc_dir.mkdir(parents=True, exist_ok=True)
                side = 600
                view = np.concatenate([resize_nn(center_crop(swatch, 0.9), side, side), np.ones((side, 24, 3), dtype=np.float32),
                                       resize_nn(albedo[:albedo.shape[0] // 2, :albedo.shape[1] // 2], side, side)], axis=1)
                save_rgb(qc_dir / f'finish_{item["id"]}_tekstur_vs_swatch.png', view)
        result.append({'item': item, 'base': base, 'albedo': albedo_path, 'swatch_seamless': seam_path, 'statistik': stats})
    return result


# --- material -----------------------------------------------------------------------
def socket(group, name, kind, in_out='INPUT', default=None, lo=None, hi=None):
    s = group.interface.new_socket(name=name, in_out=in_out, socket_type=kind)
    if default is not None:
        s.default_value = default
    if lo is not None:
        s.min_value = lo
    if hi is not None:
        s.max_value = hi
    return s


def build_group():
    g = bpy.data.node_groups.get('TALA Kayu')
    if g:
        return g
    g = bpy.data.node_groups.new('TALA Kayu', 'ShaderNodeTree')
    socket(g, 'Albedo', 'NodeSocketColor', default=(0.5, 0.4, 0.3, 1))
    socket(g, 'Normal Peta', 'NodeSocketColor', default=(0.5, 0.5, 1, 1))
    socket(g, 'Kekasaran Peta', 'NodeSocketFloat', default=0.5, lo=0, hi=1)
    socket(g, 'Tint', 'NodeSocketColor', default=(1, 1, 1, 1))
    socket(g, 'Tint Campur', 'NodeSocketFloat', default=0.0, lo=0, hi=1)
    socket(g, 'Kekasaran Min', 'NodeSocketFloat', default=0.40, lo=0, hi=1)
    socket(g, 'Kekasaran Max', 'NodeSocketFloat', default=0.55, lo=0, hi=1)
    socket(g, 'Coat', 'NodeSocketFloat', default=0.08, lo=0, hi=1)
    socket(g, 'Coat Kekasaran', 'NodeSocketFloat', default=0.35, lo=0, hi=1)
    socket(g, 'Normal Kekuatan', 'NodeSocketFloat', default=0.6, lo=0, hi=2)
    socket(g, 'BSDF', 'NodeSocketShader', in_out='OUTPUT')
    n, l = g.nodes, g.links
    gi = n.new('NodeGroupInput'); gi.location = (-700, 0)
    go = n.new('NodeGroupOutput'); go.location = (500, 0)
    tint = n.new('ShaderNodeMix'); tint.data_type = 'RGBA'; tint.blend_type = 'MULTIPLY'; tint.location = (-350, 150)
    l.new(gi.outputs['Tint Campur'], tint.inputs[0]); l.new(gi.outputs['Albedo'], tint.inputs[6]); l.new(gi.outputs['Tint'], tint.inputs[7])
    rough = n.new('ShaderNodeMapRange'); rough.location = (-350, -150)
    rough.inputs['From Min'].default_value = 0; rough.inputs['From Max'].default_value = 1
    l.new(gi.outputs['Kekasaran Peta'], rough.inputs['Value'])
    l.new(gi.outputs['Kekasaran Min'], rough.inputs['To Min']); l.new(gi.outputs['Kekasaran Max'], rough.inputs['To Max'])
    nm = n.new('ShaderNodeNormalMap'); nm.location = (-350, -400); nm.space = 'TANGENT'
    l.new(gi.outputs['Normal Peta'], nm.inputs['Color']); l.new(gi.outputs['Normal Kekuatan'], nm.inputs['Strength'])
    b = n.new('ShaderNodeBsdfPrincipled'); b.location = (50, 0)
    b.inputs['IOR'].default_value = 1.47; b.inputs['Specular IOR Level'].default_value = 0.45
    l.new(tint.outputs[2], b.inputs['Base Color']); l.new(rough.outputs['Result'], b.inputs['Roughness'])
    l.new(nm.outputs['Normal'], b.inputs['Normal'])
    l.new(gi.outputs['Coat'], b.inputs['Coat Weight']); l.new(gi.outputs['Coat Kekasaran'], b.inputs['Coat Roughness'])
    l.new(b.outputs['BSDF'], go.inputs['BSDF'])
    g.use_fake_user = True
    return g


def image(path, colorspace):
    img = bpy.data.images.load(str(path), check_existing=True)
    img.colorspace_settings.name = colorspace
    return img


def wood_material(prepared, group=None):
    """Material 'FIN | <nama>' dari hasil siapkan_finish_produk (satu entri)."""
    item, base = prepared['item'], prepared['base']
    group = group or build_group()
    m = bpy.data.materials.new('FIN | ' + item['nama'])
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    n, l = nt.nodes, nt.links
    coord = n.new('ShaderNodeTexCoord'); coord.location = (-1100, 0)
    mapping = n.new('ShaderNodeMapping'); mapping.location = (-900, 0); mapping.label = 'UV dalam meter'
    ux, uy = base.get('ukuran_m', [1, 1])
    mapping.inputs['Scale'].default_value = (1 / ux, 1 / uy, 1)
    if base.get('serat_gambar', 'V') == 'H':
        mapping.inputs['Rotation'].default_value = (0, 0, math.radians(90))
        mapping.label = 'UV dalam meter · serat gambar horizontal, diputar 90°'
    l.new(coord.outputs['UV'], mapping.inputs['Vector'])
    albedo = n.new('ShaderNodeTexImage'); albedo.location = (-650, 300); albedo.label = 'Albedo terkalibrasi'
    albedo.image = image(prepared['albedo'], 'sRGB')
    swatch = n.new('ShaderNodeTexImage'); swatch.location = (-650, 0); swatch.label = 'Swatch asli (seamless)'
    swatch.image = image(prepared['swatch_seamless'], 'sRGB')
    normal = rough = None
    if base.get('normal'):
        normal = n.new('ShaderNodeTexImage'); normal.location = (-650, -300); normal.label = 'Normal'
        normal.image = image(base['folder'] / base['normal'], 'Non-Color')
    if base.get('roughness'):
        rough = n.new('ShaderNodeTexImage'); rough.location = (-650, -600); rough.label = 'Kekasaran'
        rough.image = image(base['folder'] / base['roughness'], 'Non-Color')
    for node in (albedo, swatch, normal, rough):
        if node is not None:
            l.new(mapping.outputs['Vector'], node.inputs['Vector'])
    pilih = n.new('ShaderNodeMix'); pilih.data_type = 'RGBA'; pilih.blend_type = 'MIX'; pilih.location = (-350, 200)
    pilih.label = 'Pakai swatch asli (0 = PBR, 1 = foto klien)'; pilih.inputs[0].default_value = 0.0
    l.new(albedo.outputs['Color'], pilih.inputs[6]); l.new(swatch.outputs['Color'], pilih.inputs[7])
    grp = n.new('ShaderNodeGroup'); grp.node_tree = group; grp.location = (-100, 0); grp.label = 'TALA Kayu'
    kil = item.get('kilap', {})
    grp.inputs['Kekasaran Min'].default_value = kil.get('roughness_min', 0.4)
    grp.inputs['Kekasaran Max'].default_value = kil.get('roughness_max', 0.55)
    grp.inputs['Coat'].default_value = kil.get('coat', 0.08)
    l.new(pilih.outputs[2], grp.inputs['Albedo'])
    if normal is not None:
        l.new(normal.outputs['Color'], grp.inputs['Normal Peta'])
    else:
        grp.inputs['Normal Kekuatan'].default_value = 0.0
    if rough is not None:
        l.new(rough.outputs['Color'], grp.inputs['Kekasaran Peta'])
    out = n.new('ShaderNodeOutputMaterial'); out.location = (200, 0)
    l.new(grp.outputs['BSDF'], out.inputs['Surface'])
    mean = prepared['statistik'].get('swatch_mean_srgb', [0.5, 0.4, 0.3])
    m.diffuse_color = (*[c ** 2.2 for c in mean], 1)
    m['ns_role'] = 'WOOD_A'
    m['ns_finish_id'] = item['id']
    m['ns_finish_nama'] = item['nama']
    m['ns_finish_dasar'] = item['tekstur_dasar']
    m['ns_finish_sumber'] = json.dumps(item.get('sumber', item.get('swatch', '')), ensure_ascii=False)
    m.use_fake_user = True
    return m


def hardware_material(item):
    m = bpy.data.materials.new('HW | ' + item['nama'])
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get('Principled BSDF')
    color = (*item['warna'], 1)
    b.inputs['Base Color'].default_value = color
    b.inputs['Metallic'].default_value = item['metallic']
    n, l = nt.nodes, nt.links
    noise = n.new('ShaderNodeTexNoise'); noise.location = (-600, -200); noise.inputs['Scale'].default_value = 90
    rough = n.new('ShaderNodeMapRange'); rough.location = (-300, -200); rough.label = 'Variasi kekasaran'
    rough.inputs['To Min'].default_value = max(0, item['roughness'] - 0.06)
    rough.inputs['To Max'].default_value = min(1, item['roughness'] + 0.08)
    l.new(noise.outputs['Fac'], rough.inputs['Value']); l.new(rough.outputs['Result'], b.inputs['Roughness'])
    m.diffuse_color = color; m.metallic = item['metallic']; m.roughness = item['roughness']
    m['ns_role'] = item.get('peran', 'HANDLE')
    m['ns_finish_id'] = item['id']
    m['ns_finish_nama'] = item['nama']
    m.use_fake_user = True
    return m


def hardware_entries():
    manifest = json.loads((FINISH / 'finishes.json').read_text(encoding='utf-8'))
    return manifest.get('hardware', [])


def pakai_tekstur_untuk_finish(produk_json, finish_id, base_id):
    """Ubah tekstur_dasar sebuah finish di produk.json; kembalikan nama finish."""
    produk_json = Path(produk_json)
    spec = json.loads(produk_json.read_text(encoding='utf-8'))
    base_entry(base_id)
    item = next((f for f in spec.get('finish_kayu', []) if f['id'] == finish_id), None)
    if item is None:
        raise ValueError('Finish tidak ada di produk.json: ' + finish_id)
    item['tekstur_dasar'] = base_id
    produk_json.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding='utf-8')
    return item['nama']
