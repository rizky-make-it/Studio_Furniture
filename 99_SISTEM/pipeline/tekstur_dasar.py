"""Pendaftaran set tekstur PBR (Poly Haven dsb.) ke 02_PRODUK/_FINISH/tekstur_dasar.

Dipakai oleh addon (tombol "Tambah tekstur dasar") dan oleh daftar_tekstur_dasar.py.
Harus dijalankan di dalam Blender (butuh bpy untuk mengubah EXR ke JPG).

daftarkan(sumber, nama=None) menerima:
  * zip unduhan Poly Haven  (<id>_4k.blend.zip: .blend + textures/*)
  * folder hasil ekstrak zip tersebut, atau folder berisi gambar langsung
  * file .blend / gambar di dalam folder tersebut (folder induknya yang dipakai)
Hasil: tekstur_dasar/<id>/<id>_diff_4k.jpg, _rough_4k.jpg, _nor_gl_4k.jpg (EXR
diubah ke JPG 8-bit agar library dan file produk tetap kecil), lalu entri
'tekstur_dasar.<id>' di finishes.json (folder relatif, ukuran_m default 1 x 1).
"""
import bpy, json, re, shutil, tempfile, zipfile
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINISH = ROOT / '02_PRODUK' / '_FINISH'
BASE = FINISH / 'tekstur_dasar'
MANIFEST = FINISH / 'finishes.json'
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.exr', '.tif', '.tiff'}
PATTERNS = {
    'albedo': re.compile(r'(_diff|diffuse|_color|_col\b|albedo|basecolor)', re.I),
    'roughness': re.compile(r'(_rough|roughness)', re.I),
    'normal': re.compile(r'(_nor_gl|normal_gl|_nor\b|_normal)', re.I),
}
SKIP = re.compile(r'(_disp|displacement|_ao\b|_arm\b|_dx\b|_spec)', re.I)


def manifest_load():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def manifest_save(data):
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def resolve(path_str):
    p = Path(path_str)
    return p if p.is_absolute() else FINISH / p


def asset_id(name):
    stem = Path(name).name
    for suffix in ('.zip', '.blend'):
        if stem.lower().endswith(suffix):
            stem = stem[:-len(suffix)]
    stem = re.sub(r'[_-](1|2|4|8|16)k$', '', stem, flags=re.I)
    return re.sub(r'[^a-z0-9_]+', '_', stem.lower()).strip('_')


def pick_maps(files):
    picked = {}
    for key, pattern in PATTERNS.items():
        cands = [p for p in files if pattern.search(p.stem) and not SKIP.search(p.stem)]
        if key == 'albedo':
            cands = [p for p in cands if not PATTERNS['roughness'].search(p.stem)]
        if cands:
            picked[key] = max(cands, key=lambda p: p.stat().st_size)
    return picked


def to_jpg(src, dst, quality=95):
    """Salin gambar sebagai JPG 8-bit tanpa konversi warna (nilai mentah dipertahankan)."""
    img = bpy.data.images.load(str(src), check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    out = bpy.data.images.new(dst.stem, w, h, alpha=False)
    buf[3::4] = 1.0
    out.pixels.foreach_set(np.clip(buf, 0, 1))
    out.filepath_raw = str(dst)
    out.file_format = 'JPEG'
    out.save(quality=quality)
    bpy.data.images.remove(out)


def arah_serat(path):
    """'V' bila serat memanjang vertikal di gambar, 'H' bila horizontal.
    Profil rata-rata baris vs kolom: serat horizontal membuat rata-rata tiap baris
    berbeda-beda (sebaran besar), sedangkan rata-rata tiap kolom hampir sama."""
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    luma = buf.reshape(h, w, 4)[:, :, :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    step = max(1, min(w, h) // 1024)
    luma = luma[::step, ::step]
    rows, cols = luma.mean(axis=1), luma.mean(axis=0)
    return 'H' if rows.std() > cols.std() * 1.15 else 'V'


def daftarkan(sumber, nama=None, ukuran_m=(1.0, 1.0)):
    sumber = Path(sumber)
    if sumber.is_file() and sumber.suffix.lower() in IMAGE_EXT | {'.blend'}:
        sumber = sumber.parent
    tmp = None
    if sumber.is_file() and sumber.suffix.lower() == '.zip':
        tmp = Path(tempfile.mkdtemp(prefix='tekstur_'))
        with zipfile.ZipFile(sumber) as z:
            z.extractall(tmp)
        folder = tmp
        ident = nama or asset_id(sumber.name)
    elif sumber.is_dir():
        folder = sumber
        ident = nama or asset_id(sumber.name)
    else:
        raise ValueError('Sumber harus zip Poly Haven, folder, atau file di dalamnya: ' + str(sumber))
    files = [p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXT]
    picked = pick_maps(files)
    if 'albedo' not in picked:
        raise ValueError('Tidak ada peta diffuse/color di ' + str(sumber))
    dest = BASE / ident
    dest.mkdir(parents=True, exist_ok=True)
    names = {}
    for key, src in picked.items():
        if src.suffix.lower() in {'.jpg', '.jpeg'}:
            target = dest / src.name
            if src.resolve() != target.resolve():
                shutil.copyfile(src, target)
        else:
            target = dest / (src.stem + '.jpg')
            to_jpg(src, target)
        names[key] = target.name
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    data = manifest_load()
    bases = data.setdefault('tekstur_dasar', {})
    entry = bases.get(ident, {})
    entry.update({'folder': 'tekstur_dasar/' + ident, 'albedo': names['albedo'],
                  'normal': names.get('normal'), 'roughness': names.get('roughness'),
                  'ukuran_m': list(entry.get('ukuran_m', ukuran_m)), 'lisensi': entry.get('lisensi', 'CC0 (Poly Haven)'),
                  'serat_gambar': arah_serat(dest / names['albedo']),
                  'sumber': str(sumber)})
    bases[ident] = entry
    manifest_save(data)
    return ident, names


def pakai_untuk_finish(finish_id, base_id):
    data = manifest_load()
    if base_id not in data.get('tekstur_dasar', {}):
        raise ValueError('Tekstur dasar tidak terdaftar: ' + base_id)
    item = next((f for f in data['finish'] if f['id'] == finish_id), None)
    if item is None:
        raise ValueError('Finish tidak ada: ' + finish_id)
    item['tekstur_dasar'] = base_id
    manifest_save(data)
    return item['nama']
