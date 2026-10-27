"""Ekstrak gambar tertanam dari PDF tanpa dependensi luar (hanya stdlib).

Dipakai: python ekstrak_gambar_pdf.py <file.pdf> <folder_keluaran>
Menulis JPEG (DCTDecode) apa adanya, JPEG2000 (JPXDecode) sebagai .jp2,
dan gambar FlateDecode RGB/Gray 8-bit sebagai PNG. Mencetak daftar
gambar beserta nomor halaman tempat gambar dipakai.
"""
import re, sys, zlib, struct, json
from pathlib import Path


def png_bytes(width, height, channels, raw):
    color_type = {1: 0, 3: 2, 4: 6}[channels]
    stride = width * channels
    rows = b''.join(b'\x00' + raw[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, color_type, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b''))


def colorspace_of(d, objects):
    m = re.search(rb'/ColorSpace\s*(?:/(\w+)|(\d+)\s+0\s+R|\[\s*/ICCBased\s+(\d+)\s+0\s+R)', d)
    if not m:
        return '?'
    if m.group(1):
        return m.group(1).decode()
    ref = int(m.group(2) or m.group(3))
    target = objects.get(ref, (b'', None))[0]
    if m.group(2):
        inner = re.search(rb'/ICCBased\s+(\d+)\s+0\s+R', target)
        if inner:
            target = objects.get(int(inner.group(1)), (b'', None))[0]
        elif re.search(rb'/Device(RGB|Gray|CMYK)', target):
            return 'Device' + re.search(rb'/Device(RGB|Gray|CMYK)', target).group(1).decode()
    n = re.search(rb'/N\s+(\d+)', target)
    return {b'1': 'DeviceGray', b'3': 'DeviceRGB', b'4': 'DeviceCMYK'}.get(n.group(1), '?') if n else '?'


def unpredict_png(raw, w, h, channels):
    stride = w * channels
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(h):
        ft = raw[pos]; row = bytearray(raw[pos + 1:pos + 1 + stride]); pos += 1 + stride
        for i in range(stride):
            a = row[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            if ft == 1: row[i] = (row[i] + a) & 255
            elif ft == 2: row[i] = (row[i] + b) & 255
            elif ft == 3: row[i] = (row[i] + (a + b) // 2) & 255
            elif ft == 4:
                pp = a + b - c; pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += row; prev = row
    return bytes(out)


def parse_objects(data):
    """Kembalikan dict nomor objek -> (kamus_teks, stream_bytes|None)."""
    objects = {}
    for m in re.finditer(rb'(?<![0-9])(\d+)\s+(\d+)\s+obj\b', data):
        num = int(m.group(1))
        start = m.end()
        head = data[start:start + 4000]
        dict_end = head.find(b'stream')
        dictionary = head[:dict_end if dict_end >= 0 else None]
        stream = None
        if dict_end >= 0 and b'/Length' in dictionary:
            s = start + dict_end + len(b'stream')
            if data[s:s + 2] == b'\r\n':
                s += 2
            elif data[s:s + 1] == b'\n':
                s += 1
            lm = re.search(rb'/Length\s+(\d+)(\s+0\s+R)?', dictionary)
            length = None
            if lm and not lm.group(2):
                length = int(lm.group(1))
            elif lm:
                ref = re.search(rb'(?<![0-9])' + lm.group(1) + rb'\s+0\s+obj\s*(\d+)', data)
                length = int(ref.group(1)) if ref else None
            if length is None:
                e = data.find(b'endstream', s)
                length = e - s
            stream = data[s:s + length]
        objects[num] = (dictionary, stream)
    # Objek terkompresi (halaman, resources) berada di dalam /ObjStm.
    for num, (d, stream) in list(objects.items()):
        if re.search(rb'/Type\s*/ObjStm', d) and stream:
            try:
                raw = zlib.decompress(stream)
            except zlib.error:
                continue
            n = int(re.search(rb'/N\s+(\d+)', d).group(1))
            first = int(re.search(rb'/First\s+(\d+)', d).group(1))
            header = raw[:first].split()
            pairs = [(int(header[i]), int(header[i + 1])) for i in range(0, 2 * n, 2)]
            for k, (onum, off) in enumerate(pairs):
                end = first + pairs[k + 1][1] if k + 1 < len(pairs) else len(raw)
                objects.setdefault(onum, (raw[first + off:end], None))
    return objects


def page_map(data, objects):
    """Nomor halaman -> daftar nomor objek XObject yang dirujuk lewat /Resources."""
    pages = {}
    page_objs = [n for n, (d, _) in objects.items() if re.search(rb'/Type\s*/Page\b', d)]
    # Urutkan sesuai /Kids bila ada.
    kids = []
    for n, (d, _) in objects.items():
        if re.search(rb'/Type\s*/Pages\b', d) and b'/Parent' not in d:
            kids = [int(k) for k in re.findall(rb'(\d+)\s+0\s+R', re.search(rb'/Kids\s*\[(.*?)\]', d, re.S).group(1))]
    order = kids or sorted(page_objs)
    for index, pnum in enumerate(order, 1):
        d, _ = objects.get(pnum, (b'', None))
        res = d
        rm = re.search(rb'/Resources\s+(\d+)\s+0\s+R', d)
        if rm:
            res = objects.get(int(rm.group(1)), (b'', None))[0]
        xm = re.search(rb'/XObject\s*<<(.*?)>>', res, re.S)
        refs = []
        if xm:
            refs = [int(r) for r in re.findall(rb'(\d+)\s+0\s+R', xm.group(1))]
        else:
            xr = re.search(rb'/XObject\s+(\d+)\s+0\s+R', res)
            if xr:
                refs = [int(r) for r in re.findall(rb'(\d+)\s+0\s+R', objects.get(int(xr.group(1)), (b'', None))[0])]
        pages[index] = refs
    return pages


def main(pdf_path, out_dir):
    data = Path(pdf_path).read_bytes()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    objects = parse_objects(data)
    pages = page_map(data, objects)
    where = {}
    for page, refs in pages.items():
        for r in refs:
            where.setdefault(r, []).append(page)
    report = []
    for num, (d, stream) in sorted(objects.items()):
        if not re.search(rb'/Subtype\s*/Image\b', d) or stream is None:
            continue
        w = int(re.search(rb'/Width\s+(\d+)', d).group(1))
        h = int(re.search(rb'/Height\s+(\d+)', d).group(1))
        filt = re.search(rb'/Filter\s*/?\[?\s*/?(\w+)', d)
        filt = filt.group(1).decode() if filt else 'None'
        bpc = re.search(rb'/BitsPerComponent\s+(\d+)', d)
        bpc = int(bpc.group(1)) if bpc else 8
        cs = colorspace_of(d, objects)
        if b'/SMask' not in d and b'/ImageMask' in d:
            continue
        name = f'obj{num}_p{"-".join(map(str, where.get(num, [])) ) or "x"}_{w}x{h}'
        written = None
        if filt == 'DCTDecode':
            written = out / (name + '.jpg'); written.write_bytes(stream)
        elif filt == 'JPXDecode':
            written = out / (name + '.jp2'); written.write_bytes(stream)
        elif filt in ('FlateDecode', 'None') and bpc == 8:
            raw = zlib.decompress(stream) if filt == 'FlateDecode' else stream
            channels = {'DeviceRGB': 3, 'DeviceGray': 1, 'DeviceCMYK': 4}.get(cs)
            pm = re.search(rb'/Predictor\s+(\d+)', d)
            if channels and pm and int(pm.group(1)) >= 10:
                raw = unpredict_png(raw, w, h, channels)
            if channels and len(raw) >= w * h * channels and channels != 4:
                written = out / (name + '.png'); written.write_bytes(png_bytes(w, h, channels, raw[:w * h * channels]))
        report.append({'obj': num, 'pages': where.get(num, []), 'width': w, 'height': h, 'filter': filt,
                       'colorspace': cs, 'bpc': bpc, 'file': written.name if written else None})
    (out / 'daftar_gambar.json').write_text(json.dumps(report, indent=1))
    for r in report:
        print(r)
    print('TOTAL', len(report), 'halaman terdeteksi', len(pages))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
