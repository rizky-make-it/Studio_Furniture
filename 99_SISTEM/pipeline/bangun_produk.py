"""Bangun file produk .blend dari hasil ekspor DWG (dwg_ke_stl.py) + produk.json.

Jalankan:  blender -b --factory-startup --python bangun_produk.py -- <folder_produk>/sumber/produk.json [--finish-ulang]
Keluaran:  <folder_produk>/<NamaFolder>.blend  (produk polos sesuai STANDAR_FILE_PRODUK v2,
           semua finish kayu dari produk.json ditanam; --finish-ulang memaksa kalibrasi tekstur ulang)
           <folder_produk>/INFORMASI.json
           <folder_produk>/sumber/ekspor/part_saran.json (ukuran tiap part + tebakan peran, bantuan saat mengisi produk.json)

produk.json (kunci utama):
  nama, kategori, dwg, unit ('mm'|'cm'|'m'|'inch'|'auto'), sumbu {"atas": "+Y", "depan": "+Z"},
  bevel_m, part {<handle DWG>: {nama, peran, laci, serat}}, default_part {peran},
  laci {"1": {travel_m, kotak}}, finish {default, handle, izin[]}, referensi[], catatan
"""
import bpy, bmesh, json, math, sys
from pathlib import Path
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parents[2]
FINISH = ROOT / '02_PRODUK' / '_FINISH'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import finish_kayu as fk
UNIT = {'mm': 0.001, 'cm': 0.01, 'm': 1.0, 'inch': 0.0254, 'ft': 0.3048}
INSUNITS = {1: 'inch', 2: 'ft', 4: 'mm', 5: 'cm', 6: 'm'}
ROLE_COLORS = {'WOOD_B': (0.74, 0.62, 0.47, 1), 'METAL': (0.42, 0.44, 0.46, 1), 'FELT': (0.06, 0.05, 0.04, 1), 'KACA': (0.93, 0.97, 0.95, 1)}


def axis_vector(label):
    sign = -1 if label.strip().startswith('-') else 1
    v = Vector((0, 0, 0))
    v['XYZ'.index(label.strip()[-1].upper())] = sign
    return v


def cad_to_studio_matrix(sumbu):
    z = axis_vector(sumbu.get('atas', '+Z'))
    y = -axis_vector(sumbu.get('depan', '-Y'))
    x = y.cross(z)
    return Matrix((x, y, z))


def clean_mesh(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.000001)
    bmesh.ops.dissolve_limit(bm, angle_limit=0.001, verts=bm.verts, edges=bm.edges, delimit={'NORMAL'})
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def bounds_of(objects):
    pts = [o.matrix_world @ v.co for o in objects for v in o.data.vertices]
    lo = Vector([min(p[a] for p in pts) for a in range(3)])
    hi = Vector([max(p[a] for p in pts) for a in range(3)])
    return lo, hi


def grain_axis_for(obj, cfg):
    """Sumbu serat part: eksplisit ('X'/'Y'/'Z'), 'denah' (melingkar mendatar mengikuti
    garis denah), bingkai (dict), atau sumbu terpanjang part (seperti kayu sungguhan:
    serat memanjang mengikuti panjang balok/papan)."""
    if cfg.get('serat') in ('X', 'Y', 'Z', 'denah'):
        return cfg['serat']
    if isinstance(cfg.get('serat'), dict):
        if not ({'bingkai', 'sapu'} & set(cfg['serat'])):
            raise SystemExit('serat (dict) harus berisi "sapu" atau "bingkai": ' + json.dumps(cfg['serat']))
        return cfg['serat']  # sapu / bingkai: lihat uv_meter
    lo, hi = bounds_of([obj])
    size = hi - lo
    return 'XYZ'[max(range(3), key=lambda a: size[a])]


def _hull2d(pts):
    """Convex hull 2D (monotone chain), berlawanan arah jarum jam."""
    pts = sorted(set((round(a, 6), round(b, 6)) for a, b in pts))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class KelilingHull:
    """Parameter panjang busur di keliling convex hull suatu penampang (meter).

    Setiap titik diproyeksikan ke titik TERDEKAT pada keliling (bukan ray-cast dari pusat,
    yang rusak untuk penampang tipis memanjang). Untuk titik di permukaan part (di keliling
    atau beberapa mm di dalamnya: bullnose, radius tepi) hasilnya kontinu di seluruh
    keliling, termasuk sudut membulat. Mode tertutup: satu sambungan di arah `seam` dari
    pusat (taruh di sisi tersembunyi). Mode terbuka (`buang`): sisi-sisi keliling yang
    normal luarnya searah `buang` dibuang, jadi jalurnya hanya sisi luar (dipakai mode
    'sapu': list/panel yang membelok di sudut, sisi belakang tidak dihitung).
    proyeksi(P) -> (s, d): s = panjang busur, d = jarak titik ke jalur."""

    def __init__(self, pts, seam=(0.0, -1.0), buang=None):
        import numpy as np
        h = _hull2d(pts)
        if len(h) < 3:
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            h = [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]
        n = len(h)
        area = cx = cy = 0.0
        for i in range(n):
            x0, y0 = h[i]; x1, y1 = h[(i + 1) % n]
            c = x0 * y1 - x1 * y0
            area += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c
        if abs(area) < 1e-12:
            cx = sum(p[0] for p in h) / n; cy = sum(p[1] for p in h) / n
        else:
            area *= 0.5; cx /= (6 * area); cy /= (6 * area)
        self.c = (cx, cy)
        edges = [(h[i], h[(i + 1) % n]) for i in range(n)]
        if buang is not None:
            bx, by = buang
            keep = []
            for a, b in edges:
                dx, dy = b[0] - a[0], b[1] - a[1]
                L = math.hypot(dx, dy) or 1.0
                nx, ny = dy / L, -dx / L          # normal luar (poligon berlawanan jarum jam)
                keep.append((nx * bx + ny * by) <= 0.9)
            if all(keep) or not any(keep):
                raise ValueError('mode sapu: sisi belakang tidak ditemukan atau semua sisi terbuang')
            # Jalur = sisi yang dipertahankan, berurutan mulai tepat sesudah deret sisi terbuang.
            k = next(i for i in range(n) if keep[i] and not keep[i - 1])
            path = []
            i = k
            while keep[i % n] and len(path) < n:
                path.append(edges[i % n]); i += 1
        else:
            # Titik sambungan: verteks hull yang paling jauh searah `seam` dari pusat. Jatuh di
            # sudut penampang (tepi mesh yang ada), tidak di tengah muka, jadi tidak ada muka
            # yang terbelah sambungan.
            sx, sy = seam
            k = max(range(n), key=lambda i: round((h[i][0] - cx) * sx + (h[i][1] - cy) * sy, 9))
            path = [edges[(k + j) % n] for j in range(n)]
        A = np.array([p[0] for p in path], dtype=np.float64)
        B = np.array([p[1] for p in path], dtype=np.float64)
        L = np.linalg.norm(B - A, axis=1)
        self.A, self.E, self.L = A, B - A, np.maximum(L, 1e-12)
        self.cum = np.concatenate([[0.0], np.cumsum(L)[:-1]])
        self.total = float(L.sum())
        self.tertutup = buang is None

    def _ray(self, a, b, d):
        e = (b[0] - a[0], b[1] - a[1])
        den = e[0] * d[1] - e[1] * d[0]
        if abs(den) < 1e-15:
            return None
        ca = (self.c[0] - a[0], self.c[1] - a[1])
        u = (ca[0] * d[1] - ca[1] * d[0]) / den
        t = (ca[0] * e[1] - ca[1] * e[0]) / den
        if 0.0 <= u <= 1.0 and t >= 0.0:
            return (a[0] + u * e[0], a[1] + u * e[1])
        return None

    def proyeksi(self, P):
        import numpy as np
        P = np.asarray(P, dtype=np.float64).reshape(-1, 2)
        out_s = np.empty(len(P)); out_d = np.empty(len(P))
        for i0 in range(0, len(P), 4096):
            Q = P[i0:i0 + 4096]
            rel = Q[:, None, :] - self.A[None, :, :]
            t = np.clip((rel * self.E[None]).sum(-1) / (self.L ** 2)[None], 0.0, 1.0)
            foot = self.A[None] + t[..., None] * self.E[None]
            dist = np.linalg.norm(Q[:, None, :] - foot, axis=-1)
            j = dist.argmin(1)
            r = np.arange(len(Q))
            out_s[i0:i0 + 4096] = self.cum[j] + t[r, j] * self.L[j]
            out_d[i0:i0 + 4096] = dist[r, j]
        if self.tertutup:
            # Verteks di titik sambungan: selalu s = 0 (bukan = keliling) agar sambungan UV
            # tepat di tepi sudut itu, apa pun pembulatan float-nya.
            out_s[out_s > self.total - 1e-6] = 0.0
        return out_s, out_d

    def __call__(self, x, y):
        s, _ = self.proyeksi([(x, y)])
        return float(s[0])


def _pulau(mesh):
    """Indeks pulau (komponen terhubung) per verteks."""
    import numpy as np
    parent = list(range(len(mesh.vertices)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for e in mesh.edges:
        a, b = find(e.vertices[0]), find(e.vertices[1])
        if a != b:
            parent[a] = b
    roots = [find(i) for i in range(len(parent))]
    lab = {r: k for k, r in enumerate(sorted(set(roots)))}
    return np.array([lab[r] for r in roots])


def _seam_for(q_ax, c_p=0.0):
    # Sambungan keliling di sudut tersembunyi: bawah bila sumbu kedua penampang = Z, selain
    # itu belakang (+Y, arah headboard/dinding), condong ke sisi DALAM produk (menuju pusat,
    # dari posisi pulau c_p pada sumbu pertama penampang) -> sudut dalam-bawah / dalam-belakang.
    dalam = 0.0 if abs(c_p) < 0.05 else (-1.0 if c_p > 0 else 1.0)
    return (dalam, -1.0) if q_ax == 2 else (dalam, 1.0)


def _bungkus_keliling(Ul, Tl, loop_poly):
    """Muka yang melintasi sambungan keliling tertutup (U melompat ~keliling) dibuka supaya
    teksturnya tidak terjepit. Sisi muka yang lebih dekat ke titik sambungan yang digeser satu
    keliling, jadi garis sambungan jatuh di tepi muka yang paling dekat titik sambungan
    (sudut yang dipilih), bukan di tepi seberangnya."""
    import numpy as np
    npoly = int(loop_poly.max()) + 1 if len(loop_poly) else 0
    mx = np.full(npoly, -np.inf); mn = np.full(npoly, np.inf); tp = np.zeros(npoly)
    np.maximum.at(mx, loop_poly, Ul); np.minimum.at(mn, loop_poly, Ul); np.maximum.at(tp, loop_poly, Tl)
    lompat = (mx - mn) > 0.5 * np.maximum(tp, 1e-12)
    kecil = Ul < 0.5 * Tl
    b = np.full(npoly, np.inf); a = np.full(npoly, np.inf)
    np.minimum.at(b, loop_poly[kecil], Ul[kecil])
    np.minimum.at(a, loop_poly[~kecil], (Tl - Ul)[~kecil])
    lp = lompat[loop_poly]
    geser_besar = (a < b)[loop_poly]
    U = Ul.copy()
    U[lp & kecil & ~geser_besar] += Tl[lp & kecil & ~geser_besar]
    U[lp & ~kecil & geser_besar] -= Tl[lp & ~kecil & geser_besar]
    return U


def uv_meter(obj, grain, seed=0, hull=False, ujung_ambang=None):
    """UV 'keliling' (1 satuan = 1 m), V searah serat.

    grain 'X'|'Y'|'Z': U = panjang busur keliling penampang di sekitar sumbu serat, V =
      koordinat sumbu serat. hull=True (produk "uv_keliling": "hull"): keliling diukur di
      convex hull penampang SETIAP PULAU part (proyeksi titik terdekat) sehingga tepi dan
      sudut membulat tersambung tanpa sambungan; sambungan di bawah/belakang. Tanpa hull:
      keliling kotak pembatas (perilaku lama). Muka ujung (serat potong) memakai proyeksi
      datar: default bila sumbu normal dominan = sumbu serat; `ujung_ambang` (mis. 0.95)
      membatasinya ke muka yang |normal[serat]| > ambang, sehingga serat mengalir terus
      di atas lengkung (mis. ujung atas tiang R60).
    grain 'denah': serat mendatar melingkari garis denah (muka atas/bawah: sepanjang sumbu
      denah terpanjang).
    grain {'sapu': {'belakang': '+Y'}}: untuk part memanjang yang ujungnya membelok di sudut
      (list kaki R35, panel kaki ujung seperempat lingkaran, plinth): V = panjang busur di
      sepanjang garis denah LUAR (sisi belakang dibuang), U = z + d (di atas setengah tinggi)
      atau z - d (di bawah), d = jarak ke garis luar. Serat sambung tanpa putus mengelilingi
      sudut, di atas bullnose dan ke muka atas/bawah.
    grain {'bingkai': ...}: lihat bawah."""
    import numpy as np
    for old in list(obj.data.uv_layers):
        obj.data.uv_layers.remove(old)
    uv = obj.data.uv_layers.new(name='UV meter')
    uv.active = uv.active_render = True
    offset = np.array(((seed * 0.37) % 1.0, (seed * 0.61) % 1.0))
    me = obj.data
    nv = len(me.vertices)
    co = np.empty(nv * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
    nl = len(me.loops)
    lv = np.empty(nl, dtype=np.int64); me.loops.foreach_get('vertex_index', lv)
    npoly = len(me.polygons)
    pn = np.empty(npoly * 3); me.polygons.foreach_get('normal', pn); pn = pn.reshape(-1, 3)
    ls = np.empty(npoly, dtype=np.int64); me.polygons.foreach_get('loop_start', ls)
    lt = np.empty(npoly, dtype=np.int64); me.polygons.foreach_get('loop_total', lt)
    loop_poly = np.repeat(np.arange(npoly), lt)
    out = np.zeros((nl, 2))

    if isinstance(grain, dict) and 'sapu' in grain:
        b = grain['sapu']
        bk = axis_vector(b.get('belakang', '+Y'))
        kel = KelilingHull([(x, y) for x, y in co[:, :2]], buang=(bk.x, bk.y))
        s, d = kel.proyeksi(co[:, :2])
        zmid = (co[:, 2].min() + co[:, 2].max()) / 2
        U = np.where(co[:, 2] >= zmid, co[:, 2] + d, co[:, 2] - d)
        out[:, 0] = U[lv]; out[:, 1] = s[lv]
        uv.data.foreach_set('uv', (out + offset).ravel())
        return
    if grain == 'denah':
        kel = KelilingHull([(x, y) for x, y in co[:, :2]], seam=(0.0, 1.0))
        s, _ = kel.proyeksi(co[:, :2])
        ex = np.ptp(co[:, 0]); ey = np.ptp(co[:, 1])
        top = np.abs(pn[loop_poly, 2]) > float(ujung_ambang or 0.7)
        v = co[lv]
        side_uv = np.stack([v[:, 2], _bungkus_keliling(s[lv], np.full(nl, kel.total), loop_poly)], 1)
        top_uv = np.stack([v[:, 1], v[:, 0]], 1) if ex >= ey else np.stack([v[:, 0], v[:, 1]], 1)
        out = np.where(top[:, None], top_uv, side_uv)
        uv.data.foreach_set('uv', (out + offset).ravel())
        return
    if isinstance(grain, dict):
        # Mode bingkai lama (zona tinggi), dipertahankan untuk kompatibilitas.
        if 'bingkai' not in grain:
            raise SystemExit('uv_meter: mode serat dict tidak dikenal ' + json.dumps(grain))
        b = grain['bingkai']
        t_ax, r_ax = 'XYZ'.index(b.get('tiang', 'Z')), 'XYZ'.index(b.get('rel', 'X'))
        lo_t = co[:, t_ax].min()
        z1, z2 = b.get('zona_tiang_m', [0.0, 1e9])
        for poly in me.polygons:
            n = max(range(3), key=lambda a: abs(poly.normal[a]))
            c = poly.center[t_ax] - lo_t
            gg = t_ax if (z1 <= c <= z2) else r_ax
            if gg == n:
                gg = r_ax if gg == t_ax else t_ax
            u_axis = next(a for a in (0, 1, 2) if a not in (n, gg))
            for ix in poly.loop_indices:
                vv = me.vertices[me.loops[ix].vertex_index].co
                uv.data[ix].uv = (vv[u_axis] + offset[0], vv[gg] + offset[1])
        return

    g = 'XYZ'.index(grain) if grain in 'XYZ' else 2
    p_ax, q_ax = [a for a in (0, 1, 2) if a != g]
    if ujung_ambang is not None:
        is_end = np.abs(pn[loop_poly, g]) > float(ujung_ambang)
    else:
        is_end = np.abs(pn[loop_poly]).argmax(1) == g
    v = co[lv]
    end_uv = np.stack([v[:, p_ax], v[:, q_ax]], 1)
    if hull:
        lab = _pulau(me)
        U = np.zeros(nv); T = np.zeros(nv)
        for k in np.unique(lab):
            idx = np.where(lab == k)[0]
            pts = co[idx][:, [p_ax, q_ax]]
            kel = KelilingHull([tuple(p) for p in pts], seam=_seam_for(q_ax, float(pts[:, 0].mean())))
            U[idx], _ = kel.proyeksi(pts)
            T[idx] = kel.total
        side_uv = np.stack([_bungkus_keliling(U[lv], T[lv], loop_poly), v[:, g]], 1)
    else:
        lo = co.min(0); hi = co.max(0)
        w, h = max(hi[p_ax] - lo[p_ax], 1e-6), max(hi[q_ax] - lo[q_ax], 1e-6)
        a = v[:, p_ax] - lo[p_ax]; bq = v[:, q_ax] - lo[q_ax]
        dd = np.stack([bq, w - a, h - bq, a], 1)
        side = dd.argmin(1)
        kel_b = np.choose(side, [a, w + bq, w + h + (w - a), 2 * w + h + (h - bq)])
        side_uv = np.stack([kel_b, v[:, g]], 1)
    out = np.where(is_end[:, None], end_uv, side_uv)
    uv.data.foreach_set('uv', (out + offset).ravel())


def bevel(obj, width):
    mod = obj.modifiers.new('Bevel tepi', 'BEVEL')
    mod.width = width; mod.segments = 3; mod.limit_method = 'ANGLE'
    mod.angle_limit = math.radians(42); mod.harden_normals = True
    wn = obj.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
    wn.keep_sharp = True; wn.weight = 40
    for p in obj.data.polygons:
        p.use_smooth = True


def link_only(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


def cube(name, size, loc, coll, parent, role):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    link_only(o, coll)
    o.parent = parent
    o['ns_role_part'] = role
    return o


def swatch_color(spec, role, produk_dir):
    """Warna peran dari produk.json: 'peran_warna': {'KAIN': 'referensi/x.png' | [r,g,b] (sRGB 0..1)}."""
    src = spec.get('peran_warna', {}).get(role)
    if src is None:
        return None
    if isinstance(src, (list, tuple)):
        rgb = [float(v) for v in src[:3]]
    else:
        img = fk.load_rgb(produk_dir / 'sumber' / src)
        rgb = [float(v) for v in fk.center_crop(img).reshape(-1, 3).mean(0)]
    return [c ** 2.2 for c in rgb]  # sRGB -> linear untuk Base Color


def role_material(role, spec=None, produk_dir=None):
    name = 'ROLE | ' + role
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get('Principled BSDF')
    custom = swatch_color(spec, role, produk_dir) if spec else None
    color = (*custom, 1) if custom else ROLE_COLORS.get(role, {'KAIN': (0.62, 0.56, 0.47, 1), 'KASUR': (0.9, 0.89, 0.86, 1)}.get(role, (0.6, 0.6, 0.6, 1)))
    b.inputs['Base Color'].default_value = color
    b.inputs['Roughness'].default_value = {'WOOD_B': 0.62, 'METAL': 0.35, 'FELT': 0.95, 'KAIN': 0.88, 'KASUR': 0.93}.get(role, 0.5)
    b.inputs['Metallic'].default_value = 0.8 if role == 'METAL' else 0.0
    if role == 'KACA':
        # Kaca bertekstur (hammered/water glass): transmisi penuh, sedikit kehijauan, permukaan
        # bergelombang dari Voronoi halus (sel ~8 mm) sebagai bump. Parameter dari produk.json 'kaca'.
        kc = (spec or {}).get('kaca', {})
        b.inputs['Base Color'].default_value = (*kc.get('warna', [0.93, 0.97, 0.95]), 1)
        b.inputs['Transmission Weight'].default_value = 1.0
        b.inputs['IOR'].default_value = float(kc.get('ior', 1.52))
        b.inputs['Roughness'].default_value = float(kc.get('roughness', 0.06))
        n, l = nt.nodes, nt.links
        coord = n.new('ShaderNodeTexCoord'); coord.location = (-900, -200)
        vor = n.new('ShaderNodeTexVoronoi'); vor.location = (-650, -200); vor.feature = 'SMOOTH_F1'
        vor.inputs['Scale'].default_value = 1.0 / float(kc.get('sel_m', 0.008))
        vor.inputs['Smoothness'].default_value = 0.8; vor.inputs['Randomness'].default_value = 0.9
        l.new(coord.outputs['Object'], vor.inputs['Vector'])
        bump = n.new('ShaderNodeBump'); bump.location = (-350, -200)
        bump.inputs['Strength'].default_value = float(kc.get('bump', 0.5)); bump.inputs['Distance'].default_value = float(kc.get('bump_jarak_m', 0.0012))
        l.new(vor.outputs['Distance'], bump.inputs['Height']); l.new(bump.outputs['Normal'], b.inputs['Normal'])
        try:
            m.surface_render_method = 'BLENDED'  # EEVEE/viewport: kaca tembus pandang
        except (AttributeError, TypeError):
            pass
        m.diffuse_color = (0.85, 0.9, 0.88, 0.3)
        m['ns_role'] = role
        return m
    if role in ('KAIN', 'KASUR'):
        # Kain: sheen + bump tenunan halus dari noise (koordinat objek, tanpa UV).
        b.inputs['Sheen Weight'].default_value = 0.6 if role == 'KAIN' else 0.4
        n, l = nt.nodes, nt.links
        coord = n.new('ShaderNodeTexCoord'); coord.location = (-900, -200)
        noise = n.new('ShaderNodeTexNoise'); noise.location = (-650, -200)
        noise.inputs['Scale'].default_value = 900 if role == 'KAIN' else 500
        noise.inputs['Detail'].default_value = 6; noise.inputs['Roughness'].default_value = 0.7
        l.new(coord.outputs['Object'], noise.inputs['Vector'])
        bump = n.new('ShaderNodeBump'); bump.location = (-350, -200)
        bump.inputs['Strength'].default_value = 0.35 if role == 'KAIN' else 0.2
        bump.inputs['Distance'].default_value = 0.0004
        l.new(noise.outputs['Fac'], bump.inputs['Height'])
        jahitan = float((spec or {}).get('kain_jahitan_m', 0) or 0)
        if role == 'KAIN' and jahitan > 0:
            # Jahitan kanal vertikal (channel tufting): alur sempit tiap `kain_jahitan_m` sepanjang X.
            wave = n.new('ShaderNodeTexWave'); wave.location = (-650, -500)
            wave.wave_type = 'BANDS'; wave.bands_direction = 'X'; wave.wave_profile = 'SIN'
            wave.inputs['Scale'].default_value = 1.0 / jahitan
            l.new(coord.outputs['Object'], wave.inputs['Vector'])
            ramp = n.new('ShaderNodeValToRGB'); ramp.location = (-450, -500); ramp.label = 'Alur jahitan'
            ramp.color_ramp.elements[0].position = 0.0; ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
            ramp.color_ramp.elements[1].position = 0.08; ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
            l.new(wave.outputs['Fac'], ramp.inputs['Fac'])
            seam = n.new('ShaderNodeBump'); seam.location = (-150, -500)
            seam.inputs['Strength'].default_value = 0.8; seam.inputs['Distance'].default_value = 0.006
            l.new(ramp.outputs['Color'], seam.inputs['Height'])
            l.new(bump.outputs['Normal'], seam.inputs['Normal'])
            l.new(seam.outputs['Normal'], b.inputs['Normal'])
        else:
            l.new(bump.outputs['Normal'], b.inputs['Normal'])
    m.diffuse_color = color
    m['ns_role'] = role
    return m


def _srgb_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _hex_rgb(h):
    h = h.lstrip('#')
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def _persegi_bulat(a0, a1, b0, b1, radius, n_busur=16, tetap=None):
    """Keliling persegi panjang berlawanan jarum jam di bidang (a, b), mulai sudut kiri-bawah.
    radius = [kiri_bawah, kanan_bawah, kanan_atas, kiri_atas] dalam meter (0 = sudut siku).
    tetap = jari-jari asal: sudut yang aslinya membulat tetap memakai n_busur+1 verteks walau
    jari-jarinya sudah 0 (verteks berimpit), supaya semua cincin sama jumlah verteksnya."""
    import numpy as np
    sudut = [((a0, b0), (1, 1), 180.0), ((a1, b0), (-1, 1), 270.0), ((a1, b1), (-1, -1), 0.0), ((a0, b1), (1, -1), 90.0)]
    pts = []
    tetap = radius if tetap is None else tetap
    for ((pa, pb), (sa, sb), start), r, r_asal in zip(sudut, radius, tetap):
        if r_asal <= 0:
            pts.append((pa, pb))
            continue
        ca, cb = pa + sa * r, pb + sb * r
        for k in range(n_busur + 1):
            t = math.radians(start + 90.0 * k / n_busur)
            pts.append((ca + r * math.cos(t), cb + r * math.sin(t)))
    return np.array(pts, dtype=np.float64)


def _ofset_dalam(P, d):
    """Offset poligon tertutup berlawanan jarum jam ke dalam sejauh d (miter per verteks)."""
    import numpy as np
    e_out = np.roll(P, -1, 0) - P
    e_in = P - np.roll(P, 1, 0)

    def normal_luar(e):
        t = e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-15)
        return np.stack([t[:, 1], -t[:, 0]], 1)
    na, nb = normal_luar(e_in), normal_luar(e_out)
    k = (na + nb) / np.maximum(1.0 + (na * nb).sum(1, keepdims=True), 1e-9)
    return P - k * d


def _mesh_cincin(o, rings):
    """Ganti mesh objek dengan permukaan dari deretan cincin (verteks sama banyak), tutup di
    cincin pertama dan terakhir. Verteks berimpit (sudut yang menyusut ke titik) digabung."""
    bm = bmesh.new()
    vr = [[bm.verts.new(tuple(float(c) for c in p)) for p in ring] for ring in rings]
    n = len(rings[0])
    for r0, r1 in zip(vr[:-1], vr[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new([r0[i], r0[j], r1[j], r1[i]])
    bm.faces.new(vr[0][::-1])
    bm.faces.new(vr[-1])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-9, edges=bm.edges)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()


def bentuk_lunak(o, b):
    """Bentuk ulang part lunak (kain/kasur) mengikuti referensi, amplop dari solid DWG.

    Hanya untuk peran KAIN/KASUR (bukan kayu). Kotak pembatas, tapak dan posisi diambil dari
    mesh DWG part itu sendiri; yang berubah hanya profil tepi (dan tinggi atas kasur).
    b = produk.json part.<handle>.bentuk:
      {"jenis": "kasur", "atas_z_m": 0.525, "radius_tepi_atas_m": 0.045,
       "radius_sudut_kaki_m": 0.05, "segmen": 12}
          tapak denah = kotak DWG (sudut kaki -Y membulat, sudut kepala siku), dasar rata di Z DWG.
      {"jenis": "bantal", "arah_depan": "-Y", "radius_gulung_m": 0.01019,
       "radius_sudut_atas_m": 0.01019, "segmen": 10}
          garis tampak depan = kotak DWG dengan sudut atas membulat, tebal = tebal DWG, muka
          depan datar persegi (siap untuk tufting), gulungan depan berjari-jari seragam.
          radius_gulung_m <= radius_sudut_atas_m agar sudut atas mulus tanpa lipatan miter.
    Tanpa 'bentuk' (atau "jenis": "dwg") solid DWG dipakai apa adanya."""
    import numpy as np
    co = np.array([v.co[:] for v in o.data.vertices])
    lo, hi = co.min(0), co.max(0)
    jenis = b.get('jenis')
    if jenis in (None, 'dwg'):
        return None
    seg = int(b.get('segmen', 12))
    info = {'jenis': jenis, 'kotak_dwg_m': [lo.round(5).tolist(), hi.round(5).tolist()]}
    if jenis == 'kasur':
        z0 = float(lo[2]); z1 = float(b.get('atas_z_m', hi[2]))
        r = float(b.get('radius_tepi_atas_m', 0.05)); rk = float(b.get('radius_sudut_kaki_m', 0.05))
        # r > rk boleh: cincin yang offset-nya melewati jari-jari sudut denah menyusut ke titik
        # sudut (verteks berimpit digabung), seperti blend sudut pada solid DWG aslinya.
        rad = [rk, rk, 0.0, 0.0]
        garis = _persegi_bulat(lo[0], hi[0], lo[1], hi[1], rad, 16)
        rings = [np.c_[garis, np.full(len(garis), z0)], np.c_[garis, np.full(len(garis), z1 - r)]]
        for k in range(1, seg + 1):
            t = math.radians(90.0 * k / seg)
            dd = r * (1 - math.cos(t))
            P = _persegi_bulat(lo[0] + dd, hi[0] - dd, lo[1] + dd, hi[1] - dd, [max(q - dd, 0.0) if q > 0 else 0.0 for q in rad], 16, tetap=rad)
            rings.append(np.c_[P, np.full(len(P), z1 - r + r * math.sin(t))])
        _mesh_cincin(o, rings)
        info.update({'atas_z_m': z1, 'radius_tepi_atas_m': r, 'radius_sudut_kaki_m': rk,
                     'tapak_m': [round(float(lo[0]), 5), round(float(hi[0]), 5), round(float(lo[1]), 5), round(float(hi[1]), 5)]})
    elif jenis == 'bantal':
        if b.get('arah_depan', '-Y') != '-Y':
            raise SystemExit('bentuk bantal: baru mendukung arah_depan -Y')
        yf, yb = float(lo[1]), float(hi[1])
        r = float(b.get('radius_gulung_m', 0.01)); rc = float(b.get('radius_sudut_atas_m', r))
        if r > rc + 1e-9:
            raise SystemExit('bentuk bantal: radius_gulung_m harus <= radius_sudut_atas_m (hindari lipatan miter)')
        rad = [0.0, 0.0, rc, rc]
        garis = _persegi_bulat(lo[0], hi[0], lo[2], hi[2], rad, 16)

        def ring(P2, y):
            return np.stack([P2[:, 0], np.full(len(P2), y), P2[:, 1]], 1)
        rings = [ring(garis, yb), ring(garis, yf + r)]
        for k in range(1, seg + 1):
            t = math.radians(90.0 * k / seg)
            dd = r * (1 - math.cos(t)) if k < seg else r
            P = _persegi_bulat(lo[0] + dd, hi[0] - dd, lo[2] + dd, hi[2] - dd, [max(q - dd, 0.0) for q in rad], 16, tetap=rad)
            rings.append(ring(P, yf + r - r * math.sin(t)))
        _mesh_cincin(o, rings)
        info.update({'radius_gulung_m': r, 'radius_sudut_atas_m': rc, 'muka_depan_y_m': round(yf, 5),
                     'muka_depan_m': [round(float(lo[0]) + r, 5), round(float(hi[0]) - r, 5), round(float(lo[2]) + r, 5), round(float(hi[2]) - r, 5)]})
    else:
        raise SystemExit('bentuk: jenis tidak dikenal ' + str(jenis))
    o['ns_bentuk'] = json.dumps(info)
    o['geometry_source'] = 'DWG 3DSOLID (amplop/tapak) + profil tepi lunak mengikuti referensi: ' + jenis
    return info


def halus_lunak(o, sudut_derajat=35):
    """Shading halus untuk part lunak: halus per sudut + normal berbobot luas muka."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    ang = math.radians(sudut_derajat)
    for fc in bm.faces:
        fc.smooth = True
    for e in bm.edges:
        e.smooth = not (len(e.link_faces) == 2 and e.calc_face_angle(0.0) > ang)
    bm.to_mesh(o.data)
    bm.free()
    wn = o.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
    wn.keep_sharp = True; wn.weight = 50; wn.mode = 'FACE_AREA'


def uv_planar(o):
    """UV 'UV meter' proyeksi datar per sumbu normal dominan (part non-kayu)."""
    import numpy as np
    me = o.data
    for old in list(me.uv_layers):
        me.uv_layers.remove(old)
    uv = me.uv_layers.new(name='UV meter'); uv.active = uv.active_render = True
    nv = len(me.vertices); nl = len(me.loops); npoly = len(me.polygons)
    co = np.empty(nv * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
    lv = np.empty(nl, dtype=np.int64); me.loops.foreach_get('vertex_index', lv)
    pn = np.empty(npoly * 3); me.polygons.foreach_get('normal', pn); pn = pn.reshape(-1, 3)
    lt = np.empty(npoly, dtype=np.int64); me.polygons.foreach_get('loop_total', lt)
    ax = np.abs(pn).argmax(1)[np.repeat(np.arange(npoly), lt)]
    v = co[lv]
    pick = np.array([[1, 2], [0, 2], [0, 1]])[ax]
    r = np.arange(nl)
    out = np.stack([v[r, pick[:, 0]], v[r, pick[:, 1]]], 1)
    uv.data.foreach_set('uv', out.ravel())


def tufting(o, t):
    """Tufting buta (tanpa kancing) di muka depan DATAR part kain.

    Hanya muka depan datar yang diganti grid rapat (grid_m); permukaan lain tidak disentuh,
    tepi muka depan hanya mendapat verteks segaris. Grid hanya digeser KE DALAM (searah
    -arah_depan) dan pergeseran memudar ke nol menuju batas muka depan.

    t (produk.json part.<handle>.tufting), meter, ruang produk:
      arah_depan "-Y"; grid_m 0.0025; acuan_x "pusat_muka" (x titik relatif pusat muka depan)
      titik      [[x, z], ...]                       titik tarik (dimple)
      tarik      [A1, s1, A2, s2]  d = A1*exp(-(r/s1)^2) + A2*exp(-(r/s2)^2)
      kanal      [{"z", "x0", "x1", "A1", "s1", "A2", "s2", "taper"}]   jahitan mendatar menerus
      lipatan    {"z": [..], "dx": [-0.025, 0.035], "A": 0.004, "s": 0.005,
                  "kipas": {"sudut": [-35, 0, 35], "panjang": 0.05, "A": 0.0015, "s": 0.003}}
      pudar      [0.015, 0.045]   d = 0 sampai 15 mm dari batas muka depan, penuh mulai 45 mm
      sudut_halus_derajat 35"""
    import numpy as np
    f_lbl = t.get('arah_depan', '-Y')
    f = axis_vector(f_lbl)
    a_ax = 'XYZ'.index(f_lbl.strip()[-1].upper())
    h_ax = 0 if a_ax != 0 else 1
    grid = float(t.get('grid_m', 0.0025))
    tol = 1e-6
    bm = bmesh.new()
    bm.from_mesh(o.data)
    # Layer dibuat sebelum mengambil referensi verteks (menambah layer membuat referensi lama invalid).
    bm.verts.layers.float.new('ns_tuft_d')   # kedalaman tarikan (m), dipakai shader kain
    bm.normal_update()
    level = max(v.co.dot(f) for v in bm.verts)
    fronts = [fc for fc in bm.faces if fc.normal.dot(f) > 0.9999 and abs(fc.calc_center_median().dot(f) - level) < tol]
    if not fronts:
        raise SystemExit('tufting: muka depan datar tidak ditemukan untuk arah ' + f_lbl)
    fset = set(fronts)
    border = [e for fc in fronts for e in fc.edges if sum(1 for lf in e.link_faces if lf in fset) == 1]
    vs = {v for fc in fronts for v in fc.verts}
    x0 = min(v.co[h_ax] for v in vs); x1 = max(v.co[h_ax] for v in vs)
    z0 = min(v.co.z for v in vs); z1 = max(v.co.z for v in vs)
    depth_level = sum(v.co[a_ax] for v in vs) / len(vs)
    if len(border) != 4:
        raise SystemExit(f'tufting: batas muka depan harus 4 sisi lurus, ditemukan {len(border)}')
    bmesh.ops.delete(bm, geom=fronts, context='FACES')
    nx = max(2, int(round((x1 - x0) / grid)))
    nz = max(2, int(round((z1 - z0) / grid)))
    for e in border:
        a, b = e.verts
        c = (nx if abs(a.co.z - b.co.z) < tol else nz) - 1
        if c > 0:
            bmesh.ops.subdivide_edges(bm, edges=[e], cuts=c, use_grid_fill=False)

    def on_face(v):
        return abs(v.co[a_ax] - depth_level) < tol and x0 - tol <= v.co[h_ax] <= x1 + tol and z0 - tol <= v.co.z <= z1 + tol
    ring = [e for e in bm.edges if e.is_boundary and all(on_face(v) for v in e.verts)]
    top = [e for e in ring if all(abs(v.co.z - z1) < tol for v in e.verts)]
    bot = [e for e in ring if all(abs(v.co.z - z0) < tol for v in e.verts)]
    if len(top) != nx or len(bot) != nx:
        raise SystemExit(f'tufting: rel atas/bawah {len(top)}/{len(bot)} sisi, harus {nx}')
    res = bmesh.ops.grid_fill(bm, edges=top + bot, use_interp_simple=True)
    new_faces = res['faces']
    if not new_faces:
        raise SystemExit('tufting: grid_fill gagal')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    inner = list({v for fc in new_faces for v in fc.verts})
    P = np.array([(v.co[h_ax], v.co.z) for v in inner])
    xc = (x0 + x1) / 2 if t.get('acuan_x') == 'pusat_muka' else 0.0
    pts = np.array(t.get('titik', []), dtype=np.float64).reshape(-1, 2)
    if len(pts):
        pts[:, 0] += xc
    A1, s1, A2, s2 = t.get('tarik', [0.008, 0.012, 0.006, 0.055])
    d = np.zeros(len(P))
    if len(pts):
        for i0 in range(0, len(P), 20000):
            Q = P[i0:i0 + 20000]
            r2 = ((Q[:, None, :] - pts[None]) ** 2).sum(-1)
            d[i0:i0 + 20000] = (A1 * np.exp(-r2 / s1 ** 2) + A2 * np.exp(-r2 / s2 ** 2)).max(1)
    for k in t.get('kanal', []):
        dz = P[:, 1] - k['z']
        tp = float(k.get('taper', 0.025))
        xx = P[:, 0] - xc
        w = np.clip(np.minimum(xx - k['x0'], k['x1'] - xx) / tp + 1.0, 0.0, 1.0)
        w = w * w * (3 - 2 * w)
        prof = k.get('A1', 0.005) * np.exp(-(dz / k.get('s1', 0.006)) ** 2) + k.get('A2', 0.003) * np.exp(-(dz / k.get('s2', 0.03)) ** 2)
        asim = k.get('asim')
        if asim:
            # Lipatan tak simetris: bantal di atas jahitan melandai lebar masuk ke jahitan
            # (s_atas), di bawahnya dinding curam (s_bawah) - seperti channel tufting asli.
            sg = np.where(dz > 0, float(asim.get('s_atas', 0.03)), float(asim.get('s_bawah', 0.006)))
            prof = np.maximum(prof, float(asim.get('A', 0.008)) * np.exp(-(dz / sg) ** 2))
        d = np.maximum(d, w * prof)

    def seg_term(Aa, Bb, amp, sig, taper=False, sig_bawah=None):
        e = Bb - Aa; L2 = max(float(e @ e), 1e-12)
        u = np.clip(((P - Aa) @ e) / L2, 0, 1)
        dv = P - (Aa + u[:, None] * e)
        dist2 = (dv ** 2).sum(-1)
        fall = (1.0 - u) if taper else 1.0
        sg = sig if sig_bawah is None else np.where(dv[:, 1] > 0, sig, sig_bawah)
        return amp * fall * np.exp(-dist2 / sg ** 2)
    lp = t.get('lipatan')
    if lp:
        for z in lp.get('z', []):
            for x, zz in pts:
                if abs(zz - z) > 1e-6:
                    continue
                dx0, dx1 = lp.get('dx', [-0.025, 0.035])
                if 's_atas' in lp:
                    d = np.maximum(d, seg_term(np.array([x + dx0, z]), np.array([x + dx1, z]), lp.get('A', 0.004),
                                               float(lp['s_atas']), sig_bawah=float(lp.get('s_bawah', lp.get('s', 0.005)))))
                else:
                    d = np.maximum(d, seg_term(np.array([x + dx0, z]), np.array([x + dx1, z]), lp.get('A', 0.004), lp.get('s', 0.005)))
                kp = lp.get('kipas')
                if kp:
                    for ang in kp.get('sudut', [-35, 0, 35]):
                        th = math.radians(ang)
                        tip = np.array([x + math.sin(th) * kp.get('panjang', 0.05), z + math.cos(th) * kp.get('panjang', 0.05)])
                        d = np.maximum(d, seg_term(np.array([x, z]), tip, kp.get('A', 0.0015), kp.get('s', 0.003), taper=True))
    p0, p1 = t.get('pudar', [0.015, 0.045])
    bd = np.minimum.reduce([P[:, 0] - x0, x1 - P[:, 0], P[:, 1] - z0, z1 - P[:, 1]])
    fw = np.clip((bd - p0) / max(p1 - p0, 1e-9), 0, 1); fw = fw * fw * (3 - 2 * fw)
    d = d * fw
    fv = Vector(f)
    lay = bm.verts.layers.float.get('ns_tuft_d')
    for v, dd in zip(inner, d):
        v[lay] = float(dd)
        if dd > 0:
            v.co -= fv * float(dd)
    bm.normal_update()
    ang = math.radians(float(t.get('sudut_halus_derajat', 35)))
    for fc in bm.faces:
        fc.smooth = True
    for e in bm.edges:
        e.smooth = not (len(e.link_faces) == 2 and e.calc_face_angle(0.0) > ang)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    me = o.data
    for old in list(me.uv_layers):
        me.uv_layers.remove(old)
    uvl = me.uv_layers.new(name='UV meter'); uvl.active = uvl.active_render = True
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
    lv = np.empty(len(me.loops), dtype=np.int64); me.loops.foreach_get('vertex_index', lv)
    uvl.data.foreach_set('uv', co[lv][:, [h_ax, 2]].ravel())
    o['ns_tufting'] = json.dumps({'titik': pts.round(4).tolist(), 'tarik': [A1, s1, A2, s2], 'kanal': t.get('kanal', []),
                                  'grid_m': grid, 'maks_mm': round(float(d.max()) * 1000, 2), 'verteks_grid': len(inner),
                                  'muka_depan_m': [round(x0, 5), round(x1, 5), round(z0, 5), round(z1, 5)],
                                  'muka_depan_y_m': round(depth_level, 5)})
    return len(pts), float(d.max())


def _nodes_xyz(n, l, coord):
    sep = n.new('ShaderNodeSeparateXYZ'); l.new(coord.outputs['Object'], sep.inputs[0])
    return sep


def _math(n, l, op, a=None, b=None, va=None, vb=None, clamp=False):
    m = n.new('ShaderNodeMath'); m.operation = op; m.use_clamp = clamp
    if a is not None:
        l.new(a, m.inputs[0])
    elif va is not None:
        m.inputs[0].default_value = va
    if b is not None:
        l.new(b, m.inputs[1])
    elif vb is not None:
        m.inputs[1].default_value = vb
    return m.outputs[0]


def _alur(n, l, nilai, pusat, lebar):
    """Profil alur segitiga 0..1: 1 tepat di `pusat`, 0 sejauh `lebar` (setengah lebar)."""
    dist = _math(n, l, 'ABSOLUTE', _math(n, l, 'SUBTRACT', nilai, vb=pusat))
    return _math(n, l, 'SUBTRACT', va=1.0, b=_math(n, l, 'DIVIDE', dist, vb=lebar), clamp=True)


def _bump(n, l, height, strength, distance, normal_in=None, invert=False):
    bp = n.new('ShaderNodeBump'); bp.invert = invert
    bp.inputs['Strength'].default_value = strength; bp.inputs['Distance'].default_value = distance
    l.new(height, bp.inputs['Height'])
    if normal_in is not None:
        l.new(normal_in, bp.inputs['Normal'])
    return bp.outputs['Normal']


def _kali_warna(n, l, col, faktor):
    mix = n.new('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'; mix.inputs[0].default_value = 1.0
    l.new(col, mix.inputs[6])
    if isinstance(faktor, (int, float)):
        mix.inputs[7].default_value = (faktor, faktor, faktor, 1)
    else:
        l.new(faktor, mix.inputs[7])
    return mix.outputs[2]


def fabric_material(name, role, rgb_srgb, kain):
    """Kain jok heather prosedural (koordinat objek = ruang produk, meter), dari produk.json 'kain':
      warna            hex albedo
      heather          {"skala_m": 0.0105, "variasi": 0.11}     bercak warna halus
      slub             {"ukuran_m": [0.003, 0.003, 0.02], "kontras": 0.05, "bump": 0.15}
                       gores benang tegak (sumbu Z)
      herringbone      {"pitch_m": 0.0075, "kolom_m": 0.020, "kontras": 0.03, "bump": 0.10}
                       rusuk diagonal +-45 derajat (jarak tegak lurus pitch_m) dalam kolom tegak
      benang           {"skala_m": 0.001, "bump": 0.25}         tekstur benang mikro (bump)
      welt             dihitung builder dari amplop part: {"x": [xl, xr], "z_atas": zt,
                       "y_maks": ym, "lebar_m": 0.0008, "bump": 0.6}  alur jahitan tepi
      roughness 0.9, sheen 0.45, sheen_roughness 0.5"""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; n, l = nt.nodes, nt.links
    b = n.get('Principled BSDF')
    base = [_srgb_lin(c) for c in rgb_srgb]
    coord = n.new('ShaderNodeTexCoord')

    def noise(scale_xyz, detail):
        mp = n.new('ShaderNodeMapping'); mp.inputs['Scale'].default_value = scale_xyz
        l.new(coord.outputs['Object'], mp.inputs['Vector'])
        nz = n.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 1.0
        nz.inputs['Detail'].default_value = detail; nz.inputs['Roughness'].default_value = 0.55
        l.new(mp.outputs['Vector'], nz.inputs['Vector'])
        return nz.outputs['Fac']
    he = kain.get('heather', {})
    s = float(he.get('skala_m', 0.0105)); var = float(he.get('variasi', 0.11))
    ramp = n.new('ShaderNodeValToRGB'); ramp.label = 'Heather'
    ramp.color_ramp.elements[0].position = 0.35; ramp.color_ramp.elements[0].color = (*[c * (1 - var) for c in base], 1)
    ramp.color_ramp.elements[1].position = 0.65; ramp.color_ramp.elements[1].color = (*[min(1.0, c * (1 + var)) for c in base], 1)
    l.new(noise((1 / s, 1 / s, 1 / s), 3.0), ramp.inputs['Fac'])
    col = ramp.outputs['Color']
    sl = kain.get('slub', {})
    ux, uy, uz = sl.get('ukuran_m', [0.003, 0.003, 0.02])
    f_sl = noise((1 / ux, 1 / uy, 1 / uz), 2.0)
    sk = float(sl.get('kontras', 0.05))
    sr = n.new('ShaderNodeMapRange'); sr.inputs['To Min'].default_value = 1 - sk; sr.inputs['To Max'].default_value = 1 + sk
    l.new(f_sl, sr.inputs['Value'])
    col = _kali_warna(n, l, col, sr.outputs['Result'])
    sep = _nodes_xyz(n, l, coord)
    normal = None
    hb = kain.get('herringbone')
    if hb:
        pitch = float(hb.get('pitch_m', 0.0075)); colw = float(hb.get('kolom_m', 0.020))
        kcol = _math(n, l, 'FLOOR', _math(n, l, 'DIVIDE', sep.outputs['X'], vb=colw))
        par = _math(n, l, 'COSINE', _math(n, l, 'MULTIPLY', kcol, vb=math.pi))       # +-1 bergantian per kolom
        uarg = _math(n, l, 'ADD', sep.outputs['Z'], _math(n, l, 'MULTIPLY', sep.outputs['X'], par))
        rib = _math(n, l, 'SINE', _math(n, l, 'MULTIPLY', uarg, vb=2 * math.pi / (pitch * math.sqrt(2))))
        madd = n.new('ShaderNodeMath'); madd.operation = 'MULTIPLY_ADD'
        l.new(rib, madd.inputs[0]); madd.inputs[1].default_value = 0.5; madd.inputs[2].default_value = 0.5
        rib01 = madd.outputs[0]
        kk = float(hb.get('kontras', 0.03))
        hr = n.new('ShaderNodeMapRange'); hr.inputs['To Min'].default_value = 1 - kk; hr.inputs['To Max'].default_value = 1 + kk
        l.new(rib01, hr.inputs['Value'])
        col = _kali_warna(n, l, col, hr.outputs['Result'])
        normal = _bump(n, l, rib01, float(hb.get('bump', 0.10)), 0.0005)
    gt_ = kain.get('gelap_tuft')
    if gt_:
        # Kain yang tertarik ke dalam (tufting) sedikit lebih gelap: serat memadat + bayangan diri.
        # gelap = 1 - faktor * min(d / kedalaman, 1) ^ pangkat  (pangkat > 1: gelap terpusat di lipatan)
        at = n.new('ShaderNodeAttribute'); at.attribute_type = 'GEOMETRY'; at.attribute_name = 'ns_tuft_d'
        rel = _math(n, l, 'MINIMUM', _math(n, l, 'DIVIDE', at.outputs['Fac'], vb=float(gt_.get('kedalaman_m', 0.012))), vb=1.0)
        pw = _math(n, l, 'POWER', rel, vb=float(gt_.get('pangkat', 1.0)))
        fac = _math(n, l, 'SUBTRACT', va=1.0, b=_math(n, l, 'MULTIPLY', pw, vb=float(gt_.get('faktor', 0.12))))
        col = _kali_warna(n, l, col, fac)
    l.new(col, b.inputs['Base Color'])
    bn = kain.get('benang', {})
    sb = float(bn.get('skala_m', 0.001))
    normal = _bump(n, l, noise((1 / sb, 1 / sb, 1 / sb), 2.0), float(bn.get('bump', 0.25)), 0.0003, normal)
    normal = _bump(n, l, f_sl, float(sl.get('bump', 0.15)), 0.0006, normal)
    wl = kain.get('welt')
    if wl and 'x' in wl:
        lw = float(wl.get('lebar_m', 0.0008))
        xl, xr = wl['x']; zt = float(wl['z_atas']); ym = float(wl['y_maks'])
        depan = _math(n, l, 'LESS_THAN', sep.outputs['Y'], vb=ym)
        bawah_atas = _math(n, l, 'LESS_THAN', sep.outputs['Z'], vb=zt)
        dalam_x = _math(n, l, 'MULTIPLY', _math(n, l, 'GREATER_THAN', sep.outputs['X'], vb=xl), _math(n, l, 'LESS_THAN', sep.outputs['X'], vb=xr))
        gl = _math(n, l, 'MULTIPLY', _alur(n, l, sep.outputs['X'], xl, lw), bawah_atas)
        gr = _math(n, l, 'MULTIPLY', _alur(n, l, sep.outputs['X'], xr, lw), bawah_atas)
        gt = _math(n, l, 'MULTIPLY', _alur(n, l, sep.outputs['Z'], zt, lw), dalam_x)
        g = _math(n, l, 'MULTIPLY', _math(n, l, 'MAXIMUM', _math(n, l, 'MAXIMUM', gl, gr), gt), depan)
        normal = _bump(n, l, g, float(wl.get('bump', 0.6)), 0.0008, normal, invert=True)
    l.new(normal, b.inputs['Normal'])
    b.inputs['Roughness'].default_value = float(kain.get('roughness', 0.9))
    b.inputs['Sheen Weight'].default_value = float(kain.get('sheen', 0.45))
    b.inputs['Sheen Roughness'].default_value = float(kain.get('sheen_roughness', 0.5))
    b.inputs['Coat Weight'].default_value = 0.0
    m.diffuse_color = (*base, 1)
    m['ns_role'] = role
    m['ns_kain'] = json.dumps({'warna_srgb': [round(c, 4) for c in rgb_srgb], 'konfigurasi': kain}, ensure_ascii=False)
    return m


def kasur_material(name, kasur):
    """Sprei kasur: pique diamond halus, sheen lembut, gelap tipis dekat bibir rangka,
    lipatan bawah, dan jahitan sudut sprei (garis dihitung builder dari tapak kasur).
    produk.json 'kasur': {warna, roughness, sheen, pique: {periode_m, bump},
      gelap_bawah: {z0, z1, faktor}, lipat_bawah: {z, s, bump},
      jahitan_sudut: {sudut_derajat, z: [z0, z1], lebar_m, bump, radius_mask_m}}
      (builder menambah jahitan_sudut.garis = [{"p": [x, y], "n": [nx, ny]}, ...])"""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; n, l = nt.nodes, nt.links
    b = n.get('Principled BSDF')
    rgb = _hex_rgb(kasur.get('warna', '#E9E9EB'))
    base = [_srgb_lin(c) for c in rgb]
    coord = n.new('ShaderNodeTexCoord')
    sep = _nodes_xyz(n, l, coord)
    rgbn = n.new('ShaderNodeRGB'); rgbn.outputs[0].default_value = (*base, 1)
    col = rgbn.outputs[0]
    gb = kasur.get('gelap_bawah')
    if gb:
        mr = n.new('ShaderNodeMapRange'); mr.interpolation_type = 'SMOOTHSTEP'
        mr.inputs['From Min'].default_value = gb['z0']; mr.inputs['From Max'].default_value = gb['z1']
        mr.inputs['To Min'].default_value = gb.get('faktor', 0.75); mr.inputs['To Max'].default_value = 1.0
        l.new(sep.outputs['Z'], mr.inputs['Value'])
        col = _kali_warna(n, l, col, mr.outputs['Result'])
    pq = kasur.get('pique', {})
    per = float(pq.get('periode_m', 0.002))
    bands = []
    for d in ((1.0, 1.0, 1.0), (1.0, -1.0, 0.0)):
        L = math.sqrt(sum(c * c for c in d))
        dot = n.new('ShaderNodeVectorMath'); dot.operation = 'DOT_PRODUCT'
        l.new(coord.outputs['Object'], dot.inputs[0]); dot.inputs[1].default_value = tuple(c / L for c in d)
        sn = _math(n, l, 'SINE', _math(n, l, 'MULTIPLY', dot.outputs['Value'], vb=2 * math.pi / per))
        bands.append(_math(n, l, 'ABSOLUTE', sn))
    normal = _bump(n, l, _math(n, l, 'MULTIPLY', bands[0], bands[1]), float(pq.get('bump', 0.12)), 0.0003)
    js = kasur.get('jahitan_sudut')
    if js and js.get('garis'):
        lw = float(js.get('lebar_m', 0.0008)); z0, z1 = js.get('z', [0.32, 0.5]); rm = float(js.get('radius_mask_m', 0.02))
        acc = None
        for g in js['garis']:
            (px, py), (nx_, ny_) = g['p'], g['n']
            dx = _math(n, l, 'SUBTRACT', sep.outputs['X'], vb=px); dy = _math(n, l, 'SUBTRACT', sep.outputs['Y'], vb=py)
            dd = _math(n, l, 'ADD', _math(n, l, 'MULTIPLY', dx, vb=nx_), _math(n, l, 'MULTIPLY', dy, vb=ny_))
            alur = _math(n, l, 'SUBTRACT', va=1.0, b=_math(n, l, 'DIVIDE', _math(n, l, 'ABSOLUTE', dd), vb=lw), clamp=True)
            r2 = _math(n, l, 'ADD', _math(n, l, 'MULTIPLY', dx, dx), _math(n, l, 'MULTIPLY', dy, dy))
            alur = _math(n, l, 'MULTIPLY', alur, _math(n, l, 'LESS_THAN', r2, vb=rm * rm))
            acc = alur if acc is None else _math(n, l, 'MAXIMUM', acc, alur)
        zin = _math(n, l, 'MULTIPLY', _math(n, l, 'GREATER_THAN', sep.outputs['Z'], vb=z0), _math(n, l, 'LESS_THAN', sep.outputs['Z'], vb=z1))
        alur_z = _math(n, l, 'MULTIPLY', acc, zin)
        normal = _bump(n, l, alur_z, float(js.get('bump', 0.5)), 0.0006, normal, invert=True)
        if js.get('gelap'):
            col = _kali_warna(n, l, col, _math(n, l, 'SUBTRACT', va=1.0, b=_math(n, l, 'MULTIPLY', alur_z, vb=float(js['gelap']))))
    lb = kasur.get('lipat_bawah')
    if lb:
        dz = _math(n, l, 'DIVIDE', _math(n, l, 'SUBTRACT', sep.outputs['Z'], vb=float(lb['z'])), vb=float(lb.get('s', 0.0015)))
        g = _math(n, l, 'EXPONENT', _math(n, l, 'MULTIPLY', _math(n, l, 'MULTIPLY', dz, dz), vb=-1.0))
        normal = _bump(n, l, g, float(lb.get('bump', 0.3)), 0.0008, normal, invert=True)
    l.new(col, b.inputs['Base Color'])
    l.new(normal, b.inputs['Normal'])
    b.inputs['Roughness'].default_value = float(kasur.get('roughness', 0.88))
    b.inputs['Sheen Weight'].default_value = float(kasur.get('sheen', 0.3))
    b.inputs['Sheen Roughness'].default_value = 0.5
    b.inputs['Coat Weight'].default_value = 0.0
    m.diffuse_color = (*base, 1)
    m['ns_role'] = 'KASUR'
    m['ns_kasur'] = json.dumps(kasur, ensure_ascii=False)
    return m


def welt_dari_amplop(o, wl):
    """Posisi alur welt kain dari amplop part: inset dari siluet tampak depan (-Y)."""
    import numpy as np
    co = np.array([v.co[:] for v in o.data.vertices])
    lo, hi = co.min(0), co.max(0)
    ins = float(wl.get('inset_m', 0.0055))
    info = json.loads(o.get('ns_bentuk', '{}'))
    zona = float(wl.get('zona_depan_m', info.get('radius_gulung_m', 0.01) + 0.002))
    return {'x': [round(float(lo[0]) + ins, 6), round(float(hi[0]) - ins, 6)], 'z_atas': round(float(hi[2]) - ins, 6),
            'y_maks': round(float(lo[1]) + zona, 6)}


def jahitan_sudut_kasur(o, js):
    """Garis jahitan sudut sprei pada busur sudut kaki kasur (tapak dari kotak objek)."""
    import numpy as np
    info = json.loads(o.get('ns_bentuk', '{}'))
    co = np.array([v.co[:] for v in o.data.vertices])
    x0, y0 = co[:, 0].min(), co[:, 1].min(); x1 = co[:, 0].max()
    R = float(info.get('radius_sudut_kaki_m', js.get('radius_sudut_kaki_m', 0.05)))
    a = math.radians(float(js.get('sudut_derajat', 56)))
    garis = []
    # kiri-kaki: pusat (x0+R, y0+R), titik = pusat + R(-cos a, -sin a); kanan-kaki dicerminkan.
    for sx, cx in ((-1, x0 + R), (1, x1 - R)):
        ux, uy = sx * math.cos(a), -math.sin(a)
        garis.append({'p': [round(cx + R * ux, 6), round(y0 + R + R * uy, 6)], 'n': [round(uy, 6), round(-ux, 6)]})
    return dict(js, garis=garis)


def main():
    spec_path = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    produk_dir = spec_path.parents[1]
    ekspor = spec_path.parent / spec.get('ekspor_dir', 'ekspor')
    parts = json.loads((ekspor / 'parts.json').read_text(encoding='utf-8'))
    info = json.loads((ekspor / 'dwg_info.json').read_text(encoding='utf-8'))
    force_finish = '--finish-ulang' in sys.argv
    if not spec.get('finish_kayu'):
        raise SystemExit('produk.json harus punya "finish_kayu" (minimal satu finish dari data produk).')
    qc_dir = ROOT / '04_HASIL_RENDER' / produk_dir.name / 'qc'
    prepared = fk.siapkan_finish_produk(spec, produk_dir, qc_dir, force=force_finish)
    unit_label = spec.get('unit', 'auto')
    if unit_label == 'auto':
        unit_label = INSUNITS.get(info.get('insunits'), 'mm')
    unit = UNIT[unit_label]
    M = cad_to_studio_matrix(spec.get('sumbu', {}))
    nama = spec['nama']
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.name = 'PRODUK | ' + nama
    s.unit_settings.system = 'METRIC'; s.unit_settings.scale_length = 1; s.unit_settings.length_unit = 'CENTIMETERS'
    coll = bpy.data.collections.new('PROD | ' + nama)
    s.collection.children.link(coll)
    coll['ns_product'] = True; coll['category'] = spec.get('kategori', 'NAKAS')
    root = bpy.data.objects.new('PRODUCT_ROOT | ' + nama, None)
    root.empty_display_type = 'PLAIN_AXES'; root.empty_display_size = 0.12
    coll.objects.link(root)
    root['ns_product_root'] = True
    bpy.context.view_layer.objects.active = root

    # --- Part dari DWG ---------------------------------------------------------
    part_cfg = spec.get('part', {})
    default_role = spec.get('default_part', {}).get('peran', 'WOOD_A')
    meshes = []
    for part in parts:
        bpy.ops.wm.stl_import(filepath=str(ekspor / part['stl']))
        o = bpy.context.object
        cfg = part_cfg.get(part['handle']) or part_cfg.get(str(part['index'])) or {}
        role = cfg.get('peran', default_role)
        o.name = f"{cfg.get('nama', 'Part ' + part['handle'])} | {part['handle']}"
        if cfg.get('skala'):
            # Skala part terhadap pusatnya (koordinat CAD), mis. memanjangkan handle: [1.33, 1, 1].
            lo_cad = [min(v.co[a] for v in o.data.vertices) for a in range(3)]
            hi_cad = [max(v.co[a] for v in o.data.vertices) for a in range(3)]
            c = Vector([(lo_cad[a] + hi_cad[a]) / 2 for a in range(3)])
            sk = Vector([float(s) for s in cfg['skala']])
            for v in o.data.vertices:
                v.co = Vector([c[a] + (v.co[a] - c[a]) * sk[a] for a in range(3)])
        if cfg.get('min_cad') is not None:
            # STLOUT per solid kadang kehilangan posisi; 'min_cad' = sudut minimum part
            # dalam koordinat CAD (satuan DWG). None pada sumbu = biarkan apa adanya.
            lo_cad = [min(v.co[a] for v in o.data.vertices) for a in range(3)]
            shift = Vector([(float(t) - lo_cad[a]) if t is not None else 0.0 for a, t in enumerate(cfg['min_cad'])])
            for v in o.data.vertices:
                v.co += shift
        for v in o.data.vertices:
            v.co = M @ (v.co * unit)
        clean_mesh(o)
        link_only(o, coll)
        o.parent = root
        o['cad_handle'] = part['handle']; o['cad_index'] = part['index']; o['cad_layer'] = part['layer']
        o['ns_role_part'] = role
        o['geometry_source'] = 'DWG 3DSOLID via STLOUT FACETRES=10'
        meshes.append((o, cfg))
    # Part tambahan yang tidak ada di DWG (mis. kasur): kotak dalam koordinat CAD.
    for extra in spec.get('tambahan', []):
        size_cad = Vector([float(v) for v in extra['ukuran_cad']])
        min_cad = Vector([float(v) for v in extra['min_cad']])
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
        o = bpy.context.object
        o.name = extra.get('nama', 'Tambahan')
        for v in o.data.vertices:
            cad = Vector([min_cad[a] + (v.co[a] + 0.5) * size_cad[a] for a in range(3)])
            v.co = M @ (cad * unit)
        link_only(o, coll)
        o.parent = root
        o['ns_role_part'] = extra.get('peran', 'WOOD_B')
        o['geometry_source'] = 'tambahan produk.json (bukan dari DWG)'
        if extra.get('radius_m'):
            mod = o.modifiers.new('Bulat', 'BEVEL'); mod.width = float(extra['radius_m']); mod.segments = 6
        meshes.append((o, {'peran': extra.get('peran', 'WOOD_B'), 'serat': extra.get('serat')}))
    lo, hi = bounds_of([o for o, _ in meshes])
    offset = Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))
    for o, _ in meshes:
        for v in o.data.vertices:
            v.co += offset
    lo, hi = bounds_of([o for o, _ in meshes])
    size = hi - lo

    # Saran peran untuk produk.json (ditulis setiap kali, tidak mengubah produk.json).
    saran = []
    for o, cfg in meshes:
        plo, phi = bounds_of([o]); psz = phi - plo
        vol = psz.x * psz.y * psz.z
        guess = 'WOOD_A'
        if vol < 0.0004 and psz.z < 0.06:
            guess = 'HANDLE?'
        elif min(psz) < 0.03 and abs(plo.y - lo.y) < 0.03 and psz.x > 0.15:
            guess = 'WOOD_A (front laci?)'
        saran.append({'handle': o.get('cad_handle', 'tambahan'), 'index': o.get('cad_index', -1), 'nama': o.name,
                      'ukuran_cm': [round(v * 100, 2) for v in psz], 'min_cm': [round(v * 100, 2) for v in plo],
                      'max_cm': [round(v * 100, 2) for v in phi], 'tebakan_peran': guess,
                      'peran_dipakai': cfg.get('peran', default_role)})
    (ekspor / 'part_saran.json').write_text(json.dumps(saran, indent=1, ensure_ascii=False), encoding='utf-8')

    # --- Laci -------------------------------------------------------------------
    drawers = {}
    for key, lc in spec.get('laci', {}).items():
        n = int(key)
        travel = float(lc.get('travel_m', 0.2))
        d = bpy.data.objects.new(f'DRAWER_{n} | {nama}', None)
        d.empty_display_type = 'ARROWS'; d.empty_display_size = 0.08
        coll.objects.link(d); d.parent = root
        d['ns_drawer'] = n; d['Open (m)'] = 0.0
        d.id_properties_ui('Open (m)').update(min=0, max=travel, soft_min=0, soft_max=travel)
        drv = d.driver_add('location', 1).driver
        drv.type = 'SCRIPTED'
        var = drv.variables.new(); var.name = 'opening'; var.type = 'SINGLE_PROP'
        var.targets[0].id = d; var.targets[0].data_path = '["Open (m)"]'
        drv.expression = '-opening'
        members = [(o, cfg) for o, cfg in meshes if cfg.get('laci') == n]
        for o, _ in members:
            o.parent = d
        drawers[n] = (d, members, lc)
    for n, (d, members, lc) in drawers.items():
        fronts = [o for o, cfg in members if cfg.get('peran', default_role).startswith('WOOD')]
        if not lc.get('kotak', True) or not fronts:
            continue
        front = max(fronts, key=lambda o: bounds_of([o])[1].x - bounds_of([o])[0].x)
        flo, fhi = bounds_of([front])
        # Celah bayangan antar front (CAD biasanya menggambar front saling menempel).
        reveal = float(lc.get('celah_front_m', spec.get('celah_front_m', 0.0015)))
        if reveal > 0 and (fhi.z - flo.z) > 4 * reveal:
            zc = (flo.z + fhi.z) / 2
            k = ((fhi.z - flo.z) - 2 * reveal) / (fhi.z - flo.z)
            for v in front.data.vertices:
                v.co.z = zc + (v.co.z - zc) * k
            flo, fhi = bounds_of([front])
        clear = float(lc.get('celah_m', 0.012))
        depth = max(0.1, (hi.y - 0.012) - fhi.y - 0.02)
        w = (fhi.x - flo.x) - 2 * clear
        h = max(0.04, (fhi.z - flo.z) - 0.03)
        zb = flo.z + 0.012
        y0 = fhi.y
        cx = (flo.x + fhi.x) / 2
        box = [
            (f'Laci {n} / dasar 7 mm', (w, depth, 0.007), (cx, y0 + depth / 2, zb + 0.0035)),
            (f'Laci {n} / sisi kiri 12 mm', (0.012, depth, h), (cx - w / 2 + 0.006, y0 + depth / 2, zb + h / 2)),
            (f'Laci {n} / sisi kanan 12 mm', (0.012, depth, h), (cx + w / 2 - 0.006, y0 + depth / 2, zb + h / 2)),
            (f'Laci {n} / belakang 12 mm', (w, 0.012, h), (cx, y0 + depth - 0.006, zb + h / 2)),
        ]
        for name, sz, loc in box:
            o = cube(name, sz, loc, coll, d, 'WOOD_B')
            meshes.append((o, {'peran': 'WOOD_B'}))

    # --- UV, bevel, material ------------------------------------------------------
    # Finish kayu mengikuti data produk: semua finish di produk.json ditanam ke file
    # (use_fake_user) supaya bisa dipilih di studio; satu dipakai sebagai default.
    finish_cfg = spec.get('finish', {})
    wood_ids = [p['item']['id'] for p in prepared]
    default_wood = finish_cfg.get('default') or wood_ids[0]
    if default_wood not in wood_ids:
        raise SystemExit(f'finish.default "{default_wood}" tidak ada di finish_kayu {wood_ids}')
    group = fk.build_group()
    wood_materials = {p['item']['id']: fk.wood_material(p, group) for p in prepared}
    hardware = fk.hardware_entries()
    default_hw = finish_cfg.get('handle') or next((h['id'] for h in hardware if h.get('default')), hardware[0]['id'])
    hw_entry = next((h for h in hardware if h['id'] == default_hw), None)
    if hw_entry is None:
        raise SystemExit(f'Hardware "{default_hw}" tidak ada di {FINISH / "finishes.json"}')
    materials = {'WOOD_A': wood_materials[default_wood], 'HANDLE': fk.hardware_material(hw_entry)}
    bevel_w = float(spec.get('bevel_m', 0.0006))
    hull = spec.get('uv_keliling') == 'hull'
    kain_cfg = spec.get('kain')
    kasur_cfg = spec.get('kasur')
    # "bevel_peran": peran yang diberi bevel + UV keliling kayu (default: semua peran, perilaku
    # lama). Peran lain (mis. KAIN/KASUR) memakai UV datar + shading halus tanpa bevel.
    bevel_peran = spec.get('bevel_peran')
    for i, (o, cfg) in enumerate(meshes):
        role = cfg.get('peran', default_role)
        kayu = bevel_peran is None or role in bevel_peran
        if cfg.get('bentuk'):
            if role not in ('KAIN', 'KASUR'):
                raise SystemExit(f'"bentuk" hanya untuk part lunak (KAIN/KASUR), bukan {role}: {o.name}')
            print('BENTUK', o.name, json.dumps(bentuk_lunak(o, cfg['bentuk'])))
        if cfg.get('tufting'):
            n_tuft = tufting(o, cfg['tufting'])
            print('TUFTING', o.name, n_tuft, 'titik', len(o.data.vertices), 'verteks')
            wn = o.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
            wn.keep_sharp = True; wn.weight = 50; wn.mode = 'FACE_AREA'
        elif not kayu:
            uv_planar(o)
            halus_lunak(o, float(cfg.get('sudut_halus_derajat', 35)))
        else:
            uv_meter(o, grain_axis_for(o, cfg), seed=i, hull=hull, ujung_ambang=cfg.get('ujung_ambang'))
            bevel(o, float(cfg.get('bevel_m', 0.00035 if role == 'HANDLE' else bevel_w)))
        if role == 'KASUR' and kasur_cfg:
            if 'KASUR' not in materials:
                kc = dict(kasur_cfg)
                if kc.get('jahitan_sudut'):
                    kc['jahitan_sudut'] = jahitan_sudut_kasur(o, kc['jahitan_sudut'])
                materials['KASUR'] = kasur_material('KASUR | ' + kc.get('nama', 'Sprei'), kc)
            mat = materials['KASUR']
        elif role == 'KAIN' and kain_cfg:
            if 'KAIN' not in materials:
                src = kain_cfg.get('warna') or spec.get('peran_warna', {}).get('KAIN')
                if isinstance(src, str) and src.startswith('#'):
                    rgb = _hex_rgb(src)
                elif isinstance(src, (list, tuple)):
                    rgb = [float(c) for c in src[:3]]
                else:
                    img = fk.load_rgb(produk_dir / 'sumber' / src)
                    rgb = [float(c) for c in fk.center_crop(img).reshape(-1, 3).mean(0)]
                kc = dict(kain_cfg)
                if isinstance(kc.get('welt'), dict) and 'inset_m' in kc['welt']:
                    kc['welt'] = dict(kc['welt'], **welt_dari_amplop(o, kc['welt']))
                materials['KAIN'] = fabric_material('KAIN | ' + kc.get('nama', 'Kain'), 'KAIN', rgb, kc)
            mat = materials['KAIN']
        else:
            mat = materials.get(role) or role_material(role, spec, produk_dir)
        o.data.materials.clear()
        o.data.materials.append(mat)
    bpy.context.view_layer.update()

    # --- Metadata ---------------------------------------------------------------
    dims_cm = [round(float(v) * 100, 3) for v in size]
    root['dimensions_cm'] = dims_cm
    root['ns_finishes'] = wood_ids
    root['ns_default_finish'] = default_wood
    root['ns_finish_wood_a'] = default_wood
    root['ns_finish_handle'] = default_hw
    root['ns_spec'] = str(spec_path)
    root['source'] = spec.get('dwg', '')
    root['unit_assumption'] = f"angka DWG dibaca sebagai {unit_label}; INSUNITS={info.get('insunits')}"
    s['asset_id'] = spec.get('id', produk_dir.name.lower())
    s['category'] = spec.get('kategori', 'NAKAS')
    for area in bpy.context.screen.areas if bpy.context.screen else []:
        if area.type == 'VIEW_3D':
            area.spaces.active.shading.type = 'MATERIAL'
    bpy.ops.file.pack_all()
    unpacked = [i.name for i in bpy.data.images if i.users and not i.packed_file]
    assert not unpacked, 'Tekstur belum ter-pack: ' + ', '.join(unpacked)
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    out = produk_dir / (produk_dir.name + '.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(out), compress=True)
    meta = {
        'id': s['asset_id'], 'category': s['category'], 'name': nama,
        'dimensions_cm': dims_cm, 'front': '-Y', 'ground': 'Z=0', 'unit': 'meter', 'textures': 'packed',
        'source_geometry': spec.get('dwg', ''), 'unit_assumption': root['unit_assumption'],
        'cad_parts': len(parts), 'drawers': {k: v.get('travel_m') for k, v in spec.get('laci', {}).items()},
        'finishes': [{'id': p['item']['id'], 'name': p['item']['nama'], 'base_texture': p['item']['tekstur_dasar'],
                      'swatch_hex': p['statistik'].get('swatch_hex')} for p in prepared],
        'default_finish': default_wood, 'default_handle': default_hw,
        'detail_level': spec.get('detail_level', 'eksterior + kotak laci sederhana (tanpa rel/sekrup)'),
        'parts': [{'nama': o.name, 'handle': o.get('cad_handle', ''), 'peran': o.get('ns_role_part', ''),
                   'sumber_geometri': o.get('geometry_source', '')} for o, _ in meshes],
        'references': spec.get('referensi', []), 'notes': spec.get('catatan', ''),
        'import': 'append through studio panel', 'built_by': 'pipeline/bangun_produk.py',
    }
    (produk_dir / 'INFORMASI.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
    print('BANGUN_OK', out.name, 'L x D x T cm =', dims_cm, 'part', len(meshes), 'laci', list(drawers), 'finish', wood_ids)


main()
