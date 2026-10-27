"""Ekspor setiap 3DSOLID dari DWG ke STL dengan AutoCAD Core Console.

Jalankan (Python mana pun):  python dwg_ke_stl.py <file.dwg> <folder_keluaran>
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
    for part in parts:
        data, tris = read_stl(out / part['stl'])
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
            print('PERINGATAN: posisi solid', part['handle'], 'tidak ditemukan di semua_solid.stl')
            continue
        for j in range(at, at + len(tris)):
            used[j] = True
        cursor = at + len(tris)
        part['offset'] = [round(v, 4) for v in found]
        if any(abs(v) > 1e-4 for v in found):
            write_stl_shifted(out / part['stl'], data, found)


def main(dwg, out_dir):
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
    export = ['(setvar "FILEDIA" 0)', '(setvar "TILEMODE" 1)', '(setvar "FACETRES" 10)',
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
    if (out / 'semua_solid.stl').is_file():
        fix_offsets(out, parts)
    (out / 'parts.json').write_text(json.dumps(parts, indent=1), encoding='utf-8')
    (out / 'dwg_info.json').write_text(json.dumps(info, indent=1), encoding='utf-8')
    print('DWG_EKSPOR_OK', len(parts), 'solid', 'INSUNITS', info['insunits'], 'EXT', info['extmin'], info['extmax'])


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
