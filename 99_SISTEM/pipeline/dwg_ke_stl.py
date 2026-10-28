"""Ekspor setiap 3DSOLID dari DWG ke STL dengan AutoCAD Core Console.

Jalankan (Python mana pun):  python dwg_ke_stl.py <file.dwg> <folder_keluaran> [--tanda=1,1,-1]
Keluaran di folder tersebut:
  solid_<i>.stl   satu file per solid (biner, FACETRES 10)
  parts.json      daftar solid: index, handle DWG, layer, warna, file STL
  dwg_info.json   INSUNITS, EXTMIN/EXTMAX, jumlah solid
  *.log           log AutoCAD
Butuh AutoCAD 2021 (accoreconsole.exe). Lokasi lain bisa diatur lewat
variabel lingkungan ACCORECONSOLE.
"""
import json, os, re, subprocess, sys, time
from pathlib import Path

ACC = Path(os.environ.get('ACCORECONSOLE', r'C:\Program Files\Autodesk\AutoCAD 2021\accoreconsole.exe'))


def run_script(dwg, script, log):
    if not ACC.is_file():
        raise SystemExit(f'accoreconsole.exe tidak ditemukan: {ACC}')
    with open(log, 'wb') as out:
        proc = subprocess.run([str(ACC), '/i', str(dwg), '/s', str(script), '/l', 'en-US'],
                              stdout=out, stderr=subprocess.STDOUT, timeout=900)
    return proc.returncode


def lisp_path(p):
    return str(p).replace('\\', '/')


def read_log(path):
    data = Path(path).read_bytes()
    for enc in ('utf-16', 'utf-8', 'latin-1'):
        try:
            return data.decode(enc).replace('\x00', '')
        except UnicodeDecodeError:
            continue
    return ''


def read_stl(path):
    """Segitiga STL biner sebagai list of (v0, v1, v2) tuple float."""
    import struct
    data = Path(path).read_bytes()
    count = struct.unpack('<I', data[80:84])[0]
    tris = []
    for i in range(count):
        off = 84 + i * 50 + 12
        tris.append(tuple(struct.unpack('<fff', data[off + k * 12:off + k * 12 + 12]) for k in range(3)))
    return data, tris


def write_stl_shifted(path, data, offset):
    import struct
    out = bytearray(data)
    count = struct.unpack('<I', data[80:84])[0]
    for i in range(count):
        for k in range(3):
            off = 84 + i * 50 + 12 + k * 12
            x, y, z = struct.unpack('<fff', data[off:off + 12])
            out[off:off + 12] = struct.pack('<fff', x + offset[0], y + offset[1], z + offset[2])
    Path(path).write_bytes(bytes(out))


def fix_offsets(out, parts):
    """STLOUT per solid kadang menulis koordinat relatif (x/y mulai 0). Cocokkan tiap solid
    dengan potongan di semua_solid.stl (segitiga sama + translasi tetap) lalu tulis ulang
    solid_<i>.stl dengan koordinat absolut. Offset dicatat di parts.json."""
    _, all_tris = read_stl(out / 'semua_solid.stl')

    def run_matches(tris, j):
        """Offset bila segitiga tris[0:n] == all_tris[j:j+n] + translasi tetap, else None."""
        if j + len(tris) > len(all_tris):
            return None
        offset = tuple(all_tris[j][0][a] - tris[0][0][a] for a in range(3))
        for i in range(len(tris)):
            a, b = tris[i], all_tris[j + i]
            if any(abs(b[k][c] - a[k][c] - offset[c]) > 0.05 for k in range(3) for c in range(3)):
                return None
        return offset

    # STLOUT menulis solid dalam urutan seleksi yang sama, jadi potongan solid ke-i
    # menyusul potongan solid ke-(i-1). Cocokkan berurutan; bila meleset, cari ke depan.
    cursor = 0
    used = [False] * len(all_tris)
    loaded = {}
    for part in parts:
        data, tris = read_stl(out / part['stl'])
        loaded[part['handle']] = (data, tris)
        if not tris:
            continue
        found, at = None, None
        for j in [cursor] + [j for j in range(len(all_tris) - len(tris) + 1) if j != cursor and not used[j]]:
            offset = run_matches(tris, j)
            if offset is not None:
                found, at = offset, j
                break
        if found is None:
            part['offset'] = None
            continue
        for j in range(at, at + len(tris)):
            used[j] = True
        cursor = at + len(tris)
        part['offset'] = [round(v, 4) for v in found]
        part['metode_posisi'] = 'urutan'
    # Strategi 2: STLOUT multi-solid sering berupa UNION (segitiga tidak sama), tetapi
    # verteks permukaan luar tiap solid tetap ada di dalamnya. Sumbu yang "hilang" =
    # sumbu yang minimumnya 0 pada semua solid. Untuk tiap solid, cari translasi pada sumbu
    # hilang yang membuat verteks-verteksnya bertemu verteks union (cocok pada sumbu lain).
    mins = [[min(v[a] for t in tris for v in t) for a in range(3)] for _, tris in loaded.values() if tris]
    lost = [a for a in range(3) if mins and all(abs(m[a]) < 1e-3 for m in mins)]
    kept = [a for a in range(3) if a not in lost]
    pending = [p for p in parts if p.get('offset') is None and loaded.get(p['handle'], (None, []))[1]]
    if lost and pending:
        union_verts = sorted({tuple(round(c, 2) for c in v) for t in all_tris for v in t})
        from collections import defaultdict, Counter
        bucket = defaultdict(list)
        for u in union_verts:
            bucket[tuple(round(u[k], 1) for k in kept)].append(u)
        for part in pending:
            data, tris = loaded[part['handle']]
            verts = sorted({tuple(round(c, 2) for c in v) for t in tris for v in t})
            step = max(1, len(verts) // 600)
            votes = Counter()
            for v in verts[::step]:
                key = tuple(round(v[k], 1) for k in kept)
                for u in bucket.get(key, []):
                    if all(abs(u[k] - v[k]) <= 0.06 for k in kept):
                        votes[tuple(round(u[a] - v[a], 1) for a in lost)] += 1
            if not votes:
                part['offset'] = None
                print('PERINGATAN: posisi solid', part['handle'], 'tidak ditemukan di semua_solid.stl (tersembunyi di dalam union?)')
                continue
            best, count = votes.most_common(1)[0]
            sampled = len(verts[::step])
            if count < max(6, sampled * 0.25):
                part['offset'] = None
                print('PERINGATAN: posisi solid', part['handle'], f'ragu ({count}/{sampled} verteks cocok)')
                continue
            offset = [0.0, 0.0, 0.0]
            for i, a in enumerate(lost):
                offset[a] = float(best[i])
            part['offset'] = [round(v, 4) for v in offset]
            part['metode_posisi'] = f'verteks ({count}/{sampled})'
    for part in parts:
        data, tris = loaded.get(part['handle'], (None, []))
        if data is not None and part.get('offset') and any(abs(v) > 1e-4 for v in part['offset']):
            write_stl_shifted(out / part['stl'], data, part['offset'])
    for part in parts:
        print('POSISI', part['index'], part['handle'], part.get('metode_posisi', 'GAGAL'), part.get('offset'))


def massprop_all(dwg, out, parts):
    """Bounding box WCS tiap solid lewat MASSPROP (ditulis ke .mpr). Sumber posisi yang pasti."""
    for p in out.glob('massprop_*.mpr'):
        p.unlink()
    script = ['(setvar "FILEDIA" 0)', '(setvar "TILEMODE" 1)', '_.UCS', '_W',
              '(setq solidset (ssget "_X" \'((0 . "3DSOLID"))))']
    for part in parts:
        script += ['_.MASSPROP', f'(ssname solidset {part["index"]})', '', '_Y', lisp_path(out / f'massprop_{part["index"]}.mpr')]
    script += ['_.QUIT', '_N', '']
    (out / 'massprop.scr').write_text('\n'.join(script), encoding='ascii')
    run_script(dwg, out / 'massprop.scr', out / 'massprop.log')
    for part in parts:
        path = out / f'massprop_{part["index"]}.mpr'
        part['bbox_wcs'] = None
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        m = re.search(r'Bounding box:\s*X:\s*(-?[\d.]+)\s*--\s*(-?[\d.]+)\s*Y:\s*(-?[\d.]+)\s*--\s*(-?[\d.]+)\s*Z:\s*(-?[\d.]+)\s*--\s*(-?[\d.]+)', text)
        if m:
            v = [float(x) for x in m.groups()]
            part['bbox_wcs'] = {'min': [v[0], v[2], v[4]], 'max': [v[1], v[3], v[5]]}
        c = re.search(r'Centroid:\s*X:\s*(-?[\d.]+)\s*Y:\s*(-?[\d.]+)\s*Z:\s*(-?[\d.]+)', text)
        if c:
            part['centroid_wcs'] = [float(x) for x in c.groups()]


def write_stl_transformed(path, data, signs, offset):
    """v' = signs * v + offset per sumbu. Bila jumlah sumbu negatif ganjil, urutan verteks
    dibalik agar muka tetap menghadap keluar; normal dihitung ulang dari verteks."""
    import struct, math
    out = bytearray(data)
    count = struct.unpack('<I', data[80:84])[0]
    mirror = (signs[0] * signs[1] * signs[2]) < 0
    for i in range(count):
        base = 84 + i * 50
        vs = []
        for k in range(3):
            off = base + 12 + k * 12
            v = struct.unpack('<fff', data[off:off + 12])
            vs.append(tuple(signs[a] * v[a] + offset[a] for a in range(3)))
        if mirror:
            vs = [vs[0], vs[2], vs[1]]
        e1 = [vs[1][a] - vs[0][a] for a in range(3)]; e2 = [vs[2][a] - vs[0][a] for a in range(3)]
        n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        ln = math.sqrt(sum(c * c for c in n)) or 1.0
        out[base:base + 12] = struct.pack('<fff', *(c / ln for c in n))
        for k in range(3):
            out[base + 12 + k * 12:base + 24 + k * 12] = struct.pack('<fff', *vs[k])
    Path(path).write_bytes(bytes(out))


def tanda_dari_union(out, rows, perm, signs, undetermined):
    """Tentukan tanda sumbu yang tidak bisa dibaca dari posisi (translasi hilang) dengan
    mencocokkan verteks tiap solid terhadap semua_solid.stl (satu frame konsisten) untuk
    setiap kombinasi tanda. STLOUT membalik sumbu yang translasinya dibuang, sehingga
    bulatan tepi/handle bisa tercermin bila tanda salah. Kembalikan (signs, skor)."""
    import itertools
    union_path = out / 'semua_solid.stl'
    if not union_path.is_file():
        return signs, None
    _, all_tris = read_stl(union_path)
    if not all_tris:
        return signs, None
    umin = [min(v[a] for t in all_tris for v in t) for a in range(3)]
    grid = 0.5
    ukeys = {tuple(round((v[a] - umin[a]) / grid) for a in range(3)) for t in all_tris for v in t}
    samples = []
    for part, _, lo, hi, tris in rows:
        verts = sorted({v for t in tris for v in t})
        step = max(1, len(verts) // 400)
        samples.append((part, lo, hi, verts[::step]))
    best, best_score, scores = None, -1, {}
    for combo in itertools.product((1, -1), repeat=len(undetermined)):
        cand = list(signs)
        for a, sgn in zip(undetermined, combo):
            cand[a] = sgn
        mapped = []
        for part, lo, hi, _ in samples:
            w = part['bbox_wcs']
            mapped.append([w['min'][perm[a]] if cand[a] > 0 else -w['max'][perm[a]] for a in range(3)])
        gmin = [min(m[a] for m in mapped) for a in range(3)]
        score = 0
        for (part, lo, hi, verts), m in zip(samples, mapped):
            lo_t = [lo[a] if cand[a] > 0 else -hi[a] for a in range(3)]
            offset = [m[a] - gmin[a] - lo_t[a] for a in range(3)]
            for v in verts:
                key = tuple(round((cand[a] * v[a] + offset[a]) / grid) for a in range(3))
                if key in ukeys:
                    score += 1
        scores[combo] = score
        if score > best_score:
            best, best_score = cand, score
    print('TANDA union: kandidat', {''.join('+' if c > 0 else '-' for c in k): v for k, v in scores.items()}, 'dipilih', best)
    return best, best_score


def fix_positions_massprop(out, parts, info, tanda_paksa=None):
    """Samakan posisi tiap solid_<i>.stl dengan bounding box WCS dari MASSPROP.
    STLOUT memakai sumbu UCS (permutasi sumbu WCS) dan membuang translasi pada sebagian
    sumbu; sumbu yang translasinya hilang ternyata juga DIBALIK arahnya (verteks tercermin
    per solid), sehingga tandanya harus ditentukan dan verteks dicerminkan kembali.
    Pemetaan sumbu dari ukuran bbox; tanda dari urutan posisi, bila tidak terbaca dari
    pencocokan dengan semua_solid.stl (atau tanda_paksa). Tiap STL ditulis ulang:
    v' = tanda*v + offset sehingga min-nya = (min WCS terpeta - min global)."""
    import itertools
    rows = []
    for part in parts:
        if not part.get('bbox_wcs'):
            continue
        data, tris = read_stl(out / part['stl'])
        if not tris:
            continue
        lo = [min(v[a] for t in tris for v in t) for a in range(3)]
        hi = [max(v[a] for t in tris for v in t) for a in range(3)]
        rows.append((part, data, lo, hi, tris))
    if len(rows) < 1:
        return False
    best, best_score = None, -1
    for perm in itertools.permutations(range(3)):
        score = 0
        for part, _, lo, hi, _ in rows:
            w = part['bbox_wcs']
            score += sum(1 for a in range(3) if abs((hi[a] - lo[a]) - (w['max'][perm[a]] - w['min'][perm[a]])) < 0.5)
        if score > best_score:
            best, best_score = perm, score
    perm = best
    signs, undetermined = [], []
    for a in range(3):
        agree = disagree = 0
        for (p1, _, lo1, _, _), (p2, _, lo2, _, _) in itertools.combinations(rows, 2):
            ds = lo1[a] - lo2[a]
            dw = p1['bbox_wcs']['min'][perm[a]] - p2['bbox_wcs']['min'][perm[a]]
            if abs(ds) < 0.5 or abs(dw) < 0.5:
                continue
            if ds * dw > 0:
                agree += 1
            else:
                disagree += 1
        if agree == 0 and disagree == 0:
            undetermined.append(a)
        signs.append(-1 if disagree > agree else 1)
    metode = 'posisi'
    if tanda_paksa:
        signs, metode = [int(v) for v in tanda_paksa], 'paksa'
    elif undetermined:
        signs, skor_union = tanda_dari_union(out, rows, perm, signs, undetermined)
        metode = 'union' if skor_union is not None else 'default(+)'
        if skor_union is None:
            print('PERINGATAN: tanda sumbu', ['XYZ'[a] for a in undetermined], 'tidak bisa ditentukan (tanpa semua_solid.stl); dianggap +')
    mapped_min = []
    for part, _, lo, hi, _ in rows:
        w = part['bbox_wcs']
        mapped_min.append([w['min'][perm[a]] if signs[a] > 0 else -w['max'][perm[a]] for a in range(3)])
    gmin = [min(m[a] for m in mapped_min) for a in range(3)]
    for (part, data, lo, hi, _), m in zip(rows, mapped_min):
        lo_t = [lo[a] if signs[a] > 0 else -hi[a] for a in range(3)]
        target = [m[a] - gmin[a] for a in range(3)]
        offset = [target[a] - lo_t[a] for a in range(3)]
        part['offset'] = [round(v, 4) for v in offset]
        part['tanda'] = list(signs)
        part['metode_posisi'] = 'massprop'
        if any(abs(v) > 1e-4 for v in offset) or any(sg < 0 for sg in signs):
            write_stl_transformed(out / part['stl'], data, signs, offset)
    info['sumbu_stl_ke_wcs'] = {'permutasi': ['XYZ'[p] for p in perm], 'tanda': signs, 'metode_tanda': metode,
                                'sumbu_tanpa_translasi': ['XYZ'[a] for a in undetermined],
                                'min_global_wcs_terpeta': gmin, 'skor': best_score}
    print('SUMBU STL->WCS', info['sumbu_stl_ke_wcs'])
    return True


def main(dwg, out_dir, tanda_paksa=None):
    dwg = Path(dwg).resolve()
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    solids_txt = out / 'solids.txt'
    info_txt = out / 'dwg_info.txt'
    for p in (solids_txt, info_txt):
        if p.exists():
            p.unlink()
    # Tahap 1: daftar solid + info gambar.
    probe = out / 'probe.scr'
    probe.write_text('\n'.join([
        '(setvar "FILEDIA" 0)', '(setvar "TILEMODE" 1)',
        f'(setq inf (open "{lisp_path(info_txt)}" "w"))',
        '(prin1 (list (getvar "INSUNITS") (getvar "EXTMIN") (getvar "EXTMAX") (getvar "LUNITS")) inf)',
        '(close inf)',
        '(setq solidset (ssget "_X" \'((0 . "3DSOLID"))))',
        f'(setq outf (open "{lisp_path(solids_txt)}" "w"))',
        '(setq idx 0)',
        '(if solidset (repeat (sslength solidset) (prin1 (entget (ssname solidset idx)) outf) (write-line "" outf) (setq idx (1+ idx))))',
        '(close outf)',
        '_.QUIT', '_N', '']), encoding='ascii')
    run_script(dwg, probe, out / 'probe.log')
    if not solids_txt.exists():
        raise SystemExit('AutoCAD tidak menulis solids.txt; lihat ' + str(out / 'probe.log'))
    lines = [l for l in solids_txt.read_text(encoding='utf-8', errors='replace').splitlines() if l.strip()]
    parts = []
    for i, line in enumerate(lines):
        handle = re.search(r'\(5 \. "([^"]*)"\)', line)
        layer = re.search(r'\(8 \. "([^"]*)"\)', line)
        color = re.search(r'\(62 \. (-?\d+)\)', line)
        parts.append({'index': i, 'handle': handle.group(1) if handle else f'IDX{i}',
                      'layer': layer.group(1) if layer else '0', 'color': int(color.group(1)) if color else 256,
                      'stl': f'solid_{i}.stl'})
    info_raw = info_txt.read_text(encoding='utf-8', errors='replace') if info_txt.exists() else ''
    nums = [float(v) for v in re.findall(r'-?\d+\.?\d*(?:e[-+]?\d+)?', info_raw)]
    info = {'insunits': int(nums[0]) if nums else None,
            'extmin': nums[1:4] if len(nums) >= 7 else None, 'extmax': nums[4:7] if len(nums) >= 7 else None,
            'lunits': int(nums[7]) if len(nums) >= 8 else None, 'jumlah_solid': len(parts), 'dwg': str(dwg)}
    # Tahap 2: STLOUT per solid.
    for p in out.glob('solid_*.stl'):
        p.unlink()
    # STLOUT menulis koordinat dalam UCS gambar yang tersimpan (bukan WCS): sumbu bisa
    # tertukar, translasi dibuang, dan arah sumbu terbalik per solid. UCS World dulu.
    export = ['(setvar "FILEDIA" 0)', '(setvar "TILEMODE" 1)', '(setvar "FACETRES" 10)', '_.UCS', '_W',
              '(setq solidset (ssget "_X" \'((0 . "3DSOLID"))))']
    for part in parts:
        export += ['_.STLOUT', f'(ssname solidset {part["index"]})', '', '_Y', lisp_path(out / part['stl'])]
    # Semua solid dalam satu STL: posisi relatif antar part selalu benar di sini.
    export += ['_.STLOUT', '!solidset', '', '_Y', lisp_path(out / 'semua_solid.stl')]
    export += ['(princ "EXPORT_ALL_DONE")', '_.QUIT', '_N', '']
    (out / 'export.scr').write_text('\n'.join(export), encoding='ascii')
    run_script(dwg, out / 'export.scr', out / 'export.log')
    missing = [p['stl'] for p in parts if not (out / p['stl']).is_file()]
    if missing:
        raise SystemExit('STL tidak dibuat: ' + ', '.join(missing) + '; lihat ' + str(out / 'export.log'))
    # Posisi pasti dari MASSPROP (bounding box WCS per solid); pencocokan union hanya cadangan.
    massprop_all(dwg, out, parts)
    if not fix_positions_massprop(out, parts, info, tanda_paksa):
        if (out / 'semua_solid.stl').is_file():
            fix_offsets(out, parts)
    for part in parts:
        print('POSISI', part['index'], part['handle'], part.get('metode_posisi', 'GAGAL'), part.get('offset'))
    (out / 'parts.json').write_text(json.dumps(parts, indent=1), encoding='utf-8')
    (out / 'dwg_info.json').write_text(json.dumps(info, indent=1), encoding='utf-8')
    print('DWG_EKSPOR_OK', len(parts), 'solid', 'INSUNITS', info['insunits'], 'EXT', info['extmin'], info['extmax'])


if __name__ == '__main__':
    # Opsional argumen ke-3: --tanda=1,1,-1 memaksa tanda sumbu STL (X,Y,Z).
    paksa = next((a.split('=', 1)[1].split(',') for a in sys.argv[3:] if a.startswith('--tanda=')), None)
    main(sys.argv[1], sys.argv[2], paksa)
