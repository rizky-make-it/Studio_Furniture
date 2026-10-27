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
ROLE_COLORS = {'WOOD_B': (0.74, 0.62, 0.47, 1), 'METAL': (0.42, 0.44, 0.46, 1), 'FELT': (0.06, 0.05, 0.04, 1)}


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
    if cfg.get('serat') in ('X', 'Y', 'Z'):
        return cfg['serat']
    lo, hi = bounds_of([obj])
    size = hi - lo
    thinnest = min(range(3), key=lambda a: size[a])
    return 'X' if thinnest == 2 else 'Z'


def uv_meter(obj, grain, seed=0):
    """UV tri-planar, 1 satuan = 1 m; V searah serat 'grain' (X/Y/Z)."""
    for old in list(obj.data.uv_layers):
        obj.data.uv_layers.remove(old)
    uv = obj.data.uv_layers.new(name='UV meter')
    uv.active = uv.active_render = True
    g = 'XYZ'.index(grain)
    offset = ((seed * 0.37) % 1.0, (seed * 0.61) % 1.0)
    for p in obj.data.polygons:
        n = max(range(3), key=lambda a: abs(p.normal[a]))
        gg = g if g != n else (2 if n != 2 else 0)
        u_axis = next(a for a in (0, 1, 2) if a not in (n, gg))
        for ix in p.loop_indices:
            v = obj.data.vertices[obj.data.loops[ix].vertex_index].co
            uv.data[ix].uv = (v[u_axis] + offset[0], v[gg] + offset[1])


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
        l.new(bump.outputs['Normal'], b.inputs['Normal'])
    m.diffuse_color = color
    m['ns_role'] = role
    return m


def main():
    spec_path = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    produk_dir = spec_path.parents[1]
    ekspor = spec_path.parent / 'ekspor'
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
    for i, (o, cfg) in enumerate(meshes):
        role = cfg.get('peran', default_role)
        uv_meter(o, grain_axis_for(o, cfg), seed=i)
        bevel(o, 0.00035 if role == 'HANDLE' else bevel_w)
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
        'detail_level': 'eksterior + kotak laci sederhana (tanpa rel/sekrup)',
        'references': spec.get('referensi', []), 'notes': spec.get('catatan', ''),
        'import': 'append through studio panel', 'built_by': 'pipeline/bangun_produk.py',
    }
    (produk_dir / 'INFORMASI.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
    print('BANGUN_OK', out.name, 'L x D x T cm =', dims_cm, 'part', len(meshes), 'laci', list(drawers), 'finish', wood_ids)


main()
