bl_info = {
    'name': 'Nakas Studio', 'author': 'Nakas Studio', 'version': (2, 5, 0),
    'blender': (4, 5, 0), 'location': 'View 3D > Sidebar > Nakas Studio',
    'description': 'Studio nakas, pergantian produk dan finish, kamera, dan batch render',
    'category': '3D View',
}

import bpy
import importlib.util
import json
import math
import os
import subprocess
from datetime import datetime
from pathlib import Path
from mathutils import Vector
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       PointerProperty, StringProperty)
from bpy_extras.io_utils import ImportHelper

SHOTS = [
    ('HERO', '01 · Hero 3/4 kanan', 'Tampilan utama produk'),
    ('FRONT', '02 · Depan', 'Tampak depan'),
    ('LEFT', '03 · 3/4 kiri', 'Sisi kiri dan depan'),
    ('SIDE', '04 · Samping kanan', 'Profil dan kedalaman'),
    ('DETAIL', '05 · Detail', 'Detail laci dan tekstur; atur target bila perlu'),
]
SHOT_IDS = [item[0] for item in SHOTS]

# Factory values, never captured from the user's edited lights.
# Profiles keep the original studio and the realistic studio independent.
LIGHTING_DEFAULTS = {
    'NAKAS': {
        'V1': {
            'HERO': (140, 38, 100, 45, 14), 'FRONT': (125, 48, 85, 40, 16),
            'LEFT': (135, 43, 95, 45, 14), 'SIDE': (130, 55, 110, 40, 12),
            'DETAIL': (115, 28, 120, 32, 12),
        },
        'V2': {
            'HERO': (238, 64.6, 170, 76.5, 24), 'FRONT': (212.5, 81.6, 144.5, 68, 28),
            'LEFT': (229.5, 73.1, 161.5, 76.5, 24), 'SIDE': (221, 93.5, 187, 68, 20),
            'DETAIL': (195.5, 47.6, 204, 54.4, 20),
        },
        # V3 (28 Okt 2026): satu profil untuk semua angle supaya terang dan kontras antar-angle sama.
        'V3': {shot: (238, 64.6, 170, 76.5, 24) for shot in ('HERO', 'FRONT', 'LEFT', 'SIDE', 'DETAIL')},
    },
}
# Latar konsisten (pasang_latar_studio.py): cyclorama = shadow catcher, film transparan, latar warna
# tetap ditempel di compositor 'NS | Latar'. Exposure dan view transform mengikuti standar studio
# (scene['ns_std_exposure'], scene['ns_std_view']), bukan nilai per produk.
LATAR_GROUP = 'NS | Latar'
# Key, Fill, Rim, Top = mode awal. Tengah = softbox rendah tepat di depan produk,
# diarahkan ke rongga rak/laci agar area tengah tidak gelap (dipasang tambah_lampu_tengah.py).
LIGHT_ROLES = ('Key', 'Fill', 'Rim', 'Top', 'Tengah')

# Finish: material produk diberi peran (ns_role), bukan nama finish. Library
# 02_PRODUK/_FINISH menyediakan material FIN | ... (kayu) dan HW | ... (handle).
FINISH_LIBRARY = Path('02_PRODUK') / '_FINISH' / 'Finish_Library.blend'
FINISH_MANIFEST = Path('02_PRODUK') / '_FINISH' / 'finishes.json'
FINISH_ROLES = (('WOOD_A', 'finish_wood', 'Kayu utama'), ('HANDLE', 'finish_handle', 'Handle'))
_finish_catalog = {'mtime': None, 'items': {}}


def finish_catalog():
    """Daftar finish per peran dari finishes.json: {peran: [(id, nama, nama_material)]}."""
    root = package_root()
    path = root / FINISH_MANIFEST if root else None
    if not path or not path.is_file():
        _finish_catalog['items'] = {}
        return {}
    mtime = path.stat().st_mtime
    if _finish_catalog['mtime'] != mtime:
        data = json.loads(path.read_text(encoding='utf-8'))
        items = {}
        for item in data.get('finish', []):
            items.setdefault(item.get('peran', 'WOOD_A'), []).append((item['id'], item['nama'], 'FIN | ' + item['nama']))
        for item in data.get('hardware', []):
            items.setdefault(item.get('peran', 'HANDLE'), []).append((item['id'], item['nama'], 'HW | ' + item['nama']))
        _finish_catalog.update(mtime=mtime, items=items,
                               bases=sorted(data.get('tekstur_dasar', {})),
                               base_of={f['id']: f.get('tekstur_dasar', '?') for f in data.get('finish', [])})
    return _finish_catalog['items']


def pipeline_module(name):
    """Muat modul dari 99_SISTEM/pipeline milik paket (tanpa cache import)."""
    root = package_root()
    if not root:
        raise ValueError('Buka file dari dalam paket Studio_Furniture terlebih dahulu.')
    path = root / '99_SISTEM' / 'pipeline' / (name + '.py')
    spec = importlib.util.spec_from_file_location('ns_pipeline_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def product_finish_materials(scene, role):
    """Material finish yang tertanam di produk aktif (dibawa dari file produk), per peran."""
    root = root_for(scene)
    if root is None:
        return []
    allowed = set(str(v) for v in root.get('ns_finishes', []))
    found = []
    for mat in bpy.data.materials:
        fid = mat.get('ns_finish_id')
        if not fid or mat.library or str(fid).endswith('.lama') or mat.get('ns_role') != role:
            continue
        if role == 'WOOD_A' and allowed and str(fid) not in allowed:
            continue
        found.append((str(fid), str(mat.get('ns_finish_nama', mat.name)), mat.name))
    return found


def available_finishes(scene, role):
    """Finish yang bisa dipilih: tertanam di produk dulu, lalu library global (hardware)."""
    items = product_finish_materials(scene, role)
    seen = {fid for fid, _, _ in items}
    for fid, nama, mat in finish_catalog().get(role, []):
        if fid not in seen:
            items.append((fid, nama, mat))
    return items


def lib_finish_items(settings, context):
    scene = context.scene if context else bpy.context.scene
    items = []
    for fid, nama, mat_name in product_finish_materials(scene, 'WOOD_A'):
        mat = bpy.data.materials.get(mat_name)
        base = str(mat.get('ns_finish_dasar', '?')) if mat else '?'
        items.append((fid, f'{nama} · {base}', mat_name))
    return items or [('', '— produk belum punya finish —', '')]


def lib_tekstur_items(settings, context):
    finish_catalog()
    return [(b, b, '') for b in _finish_catalog.get('bases', [])] or [('', '— tidak ada —', '')]


def material_role(mat):
    """Peran material: prop ns_role, nama 'ROLE | X', atau tebakan dari metallic."""
    if mat is None:
        return None
    role = mat.get('ns_role')
    if role:
        return str(role)
    if mat.name.startswith('ROLE | '):
        return mat.name.split('|', 1)[1].strip().split('.')[0]
    return 'HANDLE' if mat.metallic >= 0.5 else 'WOOD_A'


def product_slots(scene):
    """{peran: [(obj, index_slot)]} untuk produk aktif."""
    slots = {}
    coll = scene.ns_studio.product
    if not coll:
        return slots
    for obj in coll.all_objects:
        if obj.type != 'MESH':
            continue
        for index, slot in enumerate(obj.material_slots):
            role = material_role(slot.material)
            if role:
                slots.setdefault(role, []).append((obj, index))
    return slots


def current_finish(scene, role):
    for obj, index in product_slots(scene).get(role, []):
        mat = obj.material_slots[index].material
        if mat and mat.get('ns_finish_id'):
            return str(mat['ns_finish_id'])
    return ''


def finish_material(finish_id, material_name, refresh=False):
    """Material finish yang sudah ada di file, atau append dari library (tanpa link).
    refresh=True memaksa append ulang (setelah library dibangun ulang); salinan lama ditandai '(lama)'."""
    for mat in bpy.data.materials:
        if mat.get('ns_finish_id') == finish_id and not mat.library:
            if not refresh:
                return mat
            mat['ns_finish_id'] = finish_id + '.lama'
            mat.name = mat.name + ' (lama)'
    root = package_root()
    path = root / FINISH_LIBRARY if root else None
    if not path or not path.is_file():
        raise ValueError('Finish_Library.blend tidak ditemukan di 02_PRODUK/_FINISH.')
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        if material_name not in src.materials:
            raise ValueError(f'Material {material_name} tidak ada di library.')
        dst.materials = [material_name]
    mat = dst.materials[0]
    mat['ns_finish_id'] = finish_id
    return mat


def apply_finish(scene, role, finish_id, refresh=False):
    """Pasang finish ke semua slot peran tersebut pada produk aktif; kembalikan jumlah slot."""
    entry = next((e for e in available_finishes(scene, role) if e[0] == finish_id), None)
    if entry is None:
        raise ValueError(f'Finish {finish_id} tidak ada di produk maupun library untuk peran {role}.')
    targets = product_slots(scene).get(role, [])
    if not targets:
        raise ValueError('Produk aktif tidak punya material dengan peran ' + role + '.')
    mat = finish_material(finish_id, entry[2], refresh)
    mat['ns_role'] = role
    for obj, index in targets:
        obj.material_slots[index].material = mat
    root = root_for(scene)
    if root is not None:
        root['ns_finish_' + role.lower()] = finish_id
    return len(targets)


def finish_items(role, prop_name):
    def items(settings, context):
        scene = context.scene if context else bpy.context.scene
        allowed = None
        root = root_for(scene) if scene and scene.get('ns_ready') else None
        if root is not None and root.get('ns_finishes'):
            allowed = set(str(v) for v in root['ns_finishes'])
        result = [(fid, nama, mat) for fid, nama, mat in available_finishes(scene, role)
                  if allowed is None or fid in allowed or role != 'WOOD_A']
        return result or [('', '— tidak ada —', 'Produk belum membawa finish')]
    return items


def finish_updated(role, prop_name):
    def update(settings, context):
        scene = context.scene
        if not scene.get('ns_ready') or settings.get('_finish_guard'):
            return
        value = getattr(settings, prop_name)
        if not value or value == current_finish(scene, role):
            return
        try:
            count = apply_finish(scene, role, value)
            settings['_finish_pesan'] = f'{count} bagian diganti ke {value}.'
        except ValueError as exc:
            settings['_finish_pesan'] = 'Gagal: ' + str(exc)
        for area in context.screen.areas if context.screen else []:
            area.tag_redraw()
    return update


def lib_tekstur_updated(settings, context):
    """Memilih tekstur dasar langsung memasang varian finish produk yang memakai tekstur itu (bila ada)."""
    scene = context.scene
    if not scene.get('ns_ready') or not settings.lib_tekstur:
        return
    for fid, nama, mat_name in product_finish_materials(scene, 'WOOD_A'):
        mat = bpy.data.materials.get(mat_name)
        if mat and str(mat.get('ns_finish_dasar', '')) == settings.lib_tekstur and fid != current_finish(scene, 'WOOD_A'):
            try:
                apply_finish(scene, 'WOOD_A', fid)
                sync_finish_props(scene)
                settings['_finish_pesan'] = f'Varian {nama} dipasang.'
            except ValueError as exc:
                settings['_finish_pesan'] = 'Gagal: ' + str(exc)
            break


def sync_finish_props(scene):
    """Samakan dropdown dengan finish yang sedang terpasang (tanpa memicu apply)."""
    settings = scene.ns_studio
    settings['_finish_guard'] = True
    try:
        for role, prop_name, _ in FINISH_ROLES:
            current = current_finish(scene, role)
            if current and current != getattr(settings, prop_name):
                try:
                    setattr(settings, prop_name, current)
                except TypeError:
                    pass
    finally:
        settings['_finish_guard'] = False


class NS_OT_ApplyFinish(bpy.types.Operator):
    bl_idname = 'ns.apply_finish'
    bl_label = 'Pasang finish'
    bl_description = 'Pasang finish dari library ke semua bagian produk dengan peran ini; file produk sumber tidak berubah'
    bl_options = {'REGISTER', 'UNDO'}
    role: StringProperty(default='WOOD_A')
    finish_id: StringProperty(default='')

    def execute(self, context):
        scene = context.scene
        prop_name = next((p for r, p, _ in FINISH_ROLES if r == self.role), None)
        finish_id = self.finish_id or (getattr(scene.ns_studio, prop_name) if prop_name else '')
        try:
            count = apply_finish(scene, self.role, finish_id)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        sync_finish_props(scene)
        self.report({'INFO'}, f'{count} bagian memakai finish {finish_id}.')
        return {'FINISHED'}


class NS_OT_AddBaseTexture(bpy.types.Operator, ImportHelper):
    bl_idname = 'ns.tambah_tekstur_dasar'
    bl_label = 'Tambah tekstur dasar'
    bl_description = 'Daftarkan unduhan Poly Haven (zip, folder hasil ekstrak, atau file di dalamnya) ke 02_PRODUK/_FINISH/tekstur_dasar; EXR diubah ke JPG'
    filter_glob: StringProperty(default='*.zip;*.blend;*.jpg;*.jpeg;*.png;*.exr', options={'HIDDEN'})
    nama: StringProperty(name='Nama set (kosong = dari nama file)', default='')

    def execute(self, context):
        try:
            td = pipeline_module('tekstur_dasar')
            ident, names = td.daftarkan(self.filepath, self.nama or None)
        except Exception as exc:
            self.report({'ERROR'}, 'Gagal mendaftarkan tekstur: ' + str(exc))
            return {'CANCELLED'}
        _finish_catalog['mtime'] = None
        try:
            context.scene.ns_studio.lib_tekstur = ident
        except TypeError:
            pass
        self.report({'INFO'}, f'Tekstur dasar "{ident}" terdaftar ({", ".join(sorted(names))}). Pilih finish, klik "Pakai untuk finish", lalu bangun ulang library.')
        return {'FINISHED'}


def product_spec_path(scene):
    root = root_for(scene)
    path = Path(str(root.get('ns_spec', ''))) if root is not None else None
    if path and path.is_file():
        return path
    raise ValueError('Produk aktif tidak punya produk.json (bukan hasil bangun_produk.py).')


class NS_OT_SetFinishTexture(bpy.types.Operator):
    bl_idname = 'ns.pakai_tekstur_finish'
    bl_label = 'Pakai tekstur ini untuk finish'
    bl_description = 'Catat di produk.json produk aktif bahwa finish terpilih memakai set tekstur dasar terpilih; berlaku setelah produk dibangun ulang'

    def execute(self, context):
        s = context.scene.ns_studio
        if not s.lib_finish or not s.lib_tekstur:
            self.report({'ERROR'}, 'Pilih finish dan tekstur dasar dulu.'); return {'CANCELLED'}
        try:
            spec = product_spec_path(context.scene)
            nama = pipeline_module('finish_kayu').pakai_tekstur_untuk_finish(spec, s.lib_finish, s.lib_tekstur)
        except Exception as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self.report({'INFO'}, f'{nama} akan memakai {s.lib_tekstur} (dicatat di {spec.name}). Klik "Bangun ulang produk aktif".')
        return {'FINISHED'}


class NS_OT_RebuildFinishLibrary(bpy.types.Operator):
    bl_idname = 'ns.bangun_ulang_produk'
    bl_label = 'Bangun ulang produk aktif'
    bl_description = 'Jalankan Blender di latar: bangun ulang file produk dari produk.json (finish ikut dikalibrasi ulang) lalu periksa. Beberapa menit; setelah selesai impor ulang produk'
    render_qc: BoolProperty(name='Render QC (hero/front/side/ortho, lebih lama)', default=False)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        root = package_root()
        if not root:
            self.report({'ERROR'}, 'Buka file dari dalam paket Studio_Furniture dulu.'); return {'CANCELLED'}
        try:
            spec = product_spec_path(context.scene)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        pipeline = root / '99_SISTEM' / 'pipeline'
        blender = bpy.app.binary_path
        produk_dir = spec.parents[1]
        periksa = [blender, '-b', '--python', str(pipeline / 'periksa_produk.py'), '--', str(produk_dir)]
        if not self.render_qc:
            periksa.append('--tanpa-render')
        self._steps = [('Bangun produk', [blender, '-b', '--factory-startup', '--python', str(pipeline / 'bangun_produk.py'), '--', str(spec), '--finish-ulang']),
                       ('Periksa produk', periksa)]
        logdir = root / '99_SISTEM' / '_kerja'
        logdir.mkdir(exist_ok=True)
        self._logpath = logdir / 'bangun_produk.log'
        self._log = open(self._logpath, 'w', encoding='utf-8')
        self._index = -1
        self._next()
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0, window=context.window)
        wm.modal_handler_add(self)
        self.report({'INFO'}, 'Membangun ulang produk di latar belakang; log: ' + str(self._logpath))
        return {'RUNNING_MODAL'}

    def _next(self):
        self._index += 1
        if self._index >= len(self._steps):
            return False
        label, cmd = self._steps[self._index]
        self._log.write(f'\n===== {label} =====\n'); self._log.flush()
        self._proc = subprocess.Popen(cmd, stdout=self._log, stderr=subprocess.STDOUT,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return True

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        code = self._proc.poll()
        if code is None:
            return {'PASS_THROUGH'}
        if code != 0:
            return self._finish(context, f'Langkah "{self._steps[self._index][0]}" gagal (kode {code}); lihat {self._logpath}.')
        if self._next():
            return {'PASS_THROUGH'}
        return self._finish(context)

    def _finish(self, context, error=None):
        context.window_manager.event_timer_remove(self._timer)
        self._log.close()
        _finish_catalog['mtime'] = None
        if error:
            self.report({'ERROR'}, error); return {'CANCELLED'}
        self.report({'INFO'}, 'File produk selesai dibangun ulang. Impor ulang lewat "Pilih file produk" untuk memakai finish barunya.')
        return {'FINISHED'}


def lighting_profile(scene):
    category = scene.get('ns_lighting_category', 'NAKAS')
    profile = scene.get('ns_lighting_profile')
    if not profile:
        version = str(scene.get('studio_version', ''))
        profile = 'V2' if version.startswith('2.') else 'V1' if version.startswith('1.') else ''
    defaults = LIGHTING_DEFAULTS.get(category, {}).get(profile)
    return category, defaults


class NS_OT_ResetLighting(bpy.types.Operator):
    bl_idname = 'ns.reset_lighting'
    bl_label = 'Reset watt lighting'
    bl_description = 'Kembalikan watt ke standar kategori; kamera, posisi lampu, warna, ukuran, dan Exposure tetap'
    bl_options = {'REGISTER', 'UNDO'}

    scope: EnumProperty(items=[('ANGLE', 'Angle aktif', ''),
                               ('CATEGORY', 'Semua angle kategori', '')], default='ANGLE')

    @classmethod
    def poll(cls, context):
        return bool(context.scene and context.scene.get('ns_ready'))

    def execute(self, context):
        scene = context.scene
        category, defaults = lighting_profile(scene)
        if defaults is None:
            self.report({'ERROR'}, 'Standar watt belum tersedia untuk kategori/versi studio ini.')
            return {'CANCELLED'}
        pending = {}
        for rig in scene.collection.children_recursive:
            shot = rig.get('ns_light_shot')
            if shot not in defaults or rig.get('ns_lighting_category', category) != category:
                continue
            if self.scope == 'ANGLE' and shot != scene.ns_studio.shot:
                continue
            rig_scale = float(scene.get('ns_rig_scale', 1.0)) ** 2
            for obj in rig.all_objects:
                role = str(obj.get('ns_role', '')).split(' ')[0]
                if obj.type == 'LIGHT' and role in LIGHT_ROLES and LIGHT_ROLES.index(role) < len(defaults[shot]):
                    pending[obj] = defaults[shot][LIGHT_ROLES.index(role)] * rig_scale
        if not pending:
            self.report({'WARNING'}, 'Lampu preset untuk kategori ini tidak ditemukan.')
            return {'CANCELLED'}
        for obj, watts in pending.items():
            # A linked duplicate must not change another angle's light data.
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            obj.data.energy = watts
        self.report({'INFO'}, f'{len(pending)} lampu {category}: watt standar dipulihkan.')
        return {'FINISHED'}


def rig_lights():
    """[(objek lampu, angle, peran)] untuk semua rig angle."""
    out = []
    for rig in bpy.data.collections:
        shot = rig.get('ns_light_shot')
        if not shot:
            continue
        for obj in rig.all_objects:
            if obj.type == 'LIGHT':
                role = str(obj.get('ns_role', '')).split(' ')[0]
                if role:
                    out.append((obj, shot, role))
    return out


_watt_cache = {}
_msgbus_owner = object()
# Properti lampu yang ikut disamakan antar angle: watt, warna, ukuran softbox, sebaran.
LIGHT_PROPS = ('energy', 'color', 'size', 'size_y', 'spread')


def light_state(data):
    state = {}
    for prop in LIGHT_PROPS:
        if hasattr(data, prop):
            value = getattr(data, prop)
            state[prop] = tuple(value) if prop == 'color' else float(value)
    return state


def snapshot_watts():
    _watt_cache.clear()
    try:
        lights = rig_lights()
    except AttributeError:
        return  # bpy.data belum boleh diakses (saat addon diaktifkan Blender); diisi lagi di load_post
    for obj, _, _ in lights:
        _watt_cache[obj.name] = light_state(obj.data)


def _differs(a, b):
    if isinstance(a, tuple):
        return any(abs(x - y) > 1e-6 for x, y in zip(a, b))
    return abs(a - b) > 1e-6


def copy_watts(source_shot, roles=None, props=None):
    """Salin properti lampu (default: semua LIGHT_PROPS) dari angle sumber ke angle lain per peran.
    Kembalikan jumlah lampu yang diubah."""
    lights = rig_lights()
    props = tuple(props) if props else LIGHT_PROPS
    source = {role: light_state(obj.data) for obj, shot, role in lights
              if shot == source_shot and (roles is None or role in roles)}
    changed = 0
    for obj, shot, role in lights:
        if shot == source_shot or role not in source:
            continue
        state = light_state(obj.data)
        todo = [p for p in props if p in source[role] and p in state and _differs(source[role][p], state[p])]
        if not todo:
            continue
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        for p in todo:
            setattr(obj.data, p, source[role][p])
        changed += 1
    snapshot_watts()
    return changed


def propagate_watts(scene):
    """Bila 'Ubah semua angle sekaligus' aktif: properti lampu yang baru berubah disalin ke peran sama di angle lain."""
    if not scene.get('ns_ready') or not hasattr(scene, 'ns_studio'):
        return 0
    if not scene.ns_studio.lighting_all_angles:
        snapshot_watts()
        return 0
    changed = []
    for obj, shot, role in rig_lights():
        before = _watt_cache.get(obj.name)
        if before is None:
            continue
        now = light_state(obj.data)
        props = [p for p in now if p in before and _differs(before[p], now[p])]
        if props:
            changed.append((shot, role, props))
    total = 0
    for shot, role, props in changed:
        total += copy_watts(shot, roles={role}, props=props)
    if not changed:
        snapshot_watts()
    return total


def _on_light_energy(*args):
    scene = getattr(bpy.context, 'scene', None)
    if scene is not None:
        try:
            propagate_watts(scene)
        except (AttributeError, ReferenceError):
            pass


def subscribe_light_energy():
    bpy.msgbus.clear_by_owner(_msgbus_owner)
    # 'energy'/'size' didefinisikan di tiap jenis lampu, 'color' di Light dasar.
    keys = [(bpy.types.Light, 'color')]
    for light_type in (bpy.types.AreaLight, bpy.types.PointLight, bpy.types.SpotLight, bpy.types.SunLight):
        keys.append((light_type, 'energy'))
    keys += [(bpy.types.AreaLight, 'size'), (bpy.types.AreaLight, 'size_y'), (bpy.types.AreaLight, 'spread')]
    for key in keys:
        bpy.msgbus.subscribe_rna(key=key, owner=_msgbus_owner, args=(), notify=_on_light_energy, options={'PERSISTENT'})
    snapshot_watts()


def _load_post(*args):
    subscribe_light_energy()


RIG_REF_SIZE = 0.55      # rig lampu dirancang untuk nakas ~55 cm
RIG_REF_CENTER = Vector((0.0, 0.0, 0.25))


def rig_scale_factor(scene):
    """Faktor pembesaran rig lampu dari ukuran produk aktif (1.0 = nakas, maks 3.0)."""
    try:
        lo, hi = product_bounds(scene)
    except ValueError:
        return 1.0
    return max(1.0, min(3.0, max(hi - lo) / RIG_REF_SIZE))


def apply_rig_scale(scene, factor):
    """Geser lampu menjauh dari pusat produk sebesar faktor dan naikkan watt kuadratnya,
    supaya pencahayaan produk besar setara dengan nakas. Posisi/watt dasar disimpan di
    lampu agar bisa dihitung ulang untuk produk berikutnya."""
    prev = float(scene.get('ns_rig_scale', 1.0))
    if abs(prev - factor) < 1e-3:
        return 0
    changed = 0
    try:
        lo, hi = product_bounds(scene)
        aim_at = Vector((0.0, 0.0, (lo.z + hi.z) / 2))
    except ValueError:
        aim_at = RIG_REF_CENTER
    # Lampu juga harus di depan dinding cyclorama: Rim yang terdorong ke belakangnya (produk besar)
    # tidak lagi menyinari produk, dan cahaya bocornya meninggalkan bintik noise di latar.
    y_max = 4.6
    cyc = next((o for o in scene.objects if o.type == 'MESH' and o.name.startswith('Cyclorama')), None)
    if cyc is not None:
        y_max = min(y_max, max((cyc.matrix_world @ Vector(v)).y for v in cyc.bound_box) - 0.35)
    for obj, shot, role in rig_lights():
        if 'ns_base_location' not in obj:
            obj['ns_base_location'] = [float(v) for v in ((obj.location - RIG_REF_CENTER) / prev + RIG_REF_CENTER)]
        base = Vector(obj['ns_base_location'])
        target = RIG_REF_CENTER + (base - RIG_REF_CENTER) * factor
        # Tetap di dalam ruang studio (dinding ±4.9 m, balok plafon 4.1 m); kalau tidak,
        # lampu menyinari dinding/plafon dari luar dan muncul hotspot di frame.
        target.x = max(-4.6, min(4.6, target.x)); target.y = max(-4.6, min(y_max, target.y)); target.z = min(3.9, target.z)
        obj.location = target
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        # Watt mengikuti kuadrat jarak nyata ke pusat produk (bukan faktor nominal).
        base_dist = max((base - RIG_REF_CENTER).length, 0.3)
        prev_dist = max(((base - RIG_REF_CENTER) * prev).length, 0.3) if 'ns_prev_dist' not in obj else float(obj['ns_prev_dist'])
        new_dist = max((target - RIG_REF_CENTER).length, 0.3)
        obj.data.energy = obj.data.energy / (prev_dist ** 2) * (new_dist ** 2)
        obj['ns_prev_dist'] = new_dist
        if role != 'Tengah':
            aim(obj, aim_at)
        ratio = new_dist / prev_dist
        if hasattr(obj.data, 'size'):
            obj.data.size = obj.data.size * ratio
        if hasattr(obj.data, 'size_y'):
            obj.data.size_y = obj.data.size_y * ratio
        changed += 1
    # Cyclorama tidak diskalakan (bagian yang jauh dari lampu jadi gelap). Sebagai gantinya
    # lensa kamera dipanjangkan sebanding ukuran produk: kamera mundur, sudut pandang
    # menyempit, sehingga latar yang terlihat di belakang produk tetap muat di cyclorama.
    for obj in scene.objects:
        if obj.type == 'MESH' and obj.name.startswith('Cyclorama') and 'ns_base_scale' in obj:
            obj.scale = Vector(obj['ns_base_scale'])
    for shot in SHOT_IDS:
        cam = camera_for(scene, shot)
        if cam is None:
            continue
        if 'ns_base_lens' not in cam:
            cam['ns_base_lens'] = float(cam.data.lens) / prev
        cam.data.lens = min(250.0, float(cam['ns_base_lens']) * factor)
    scene['ns_rig_scale'] = factor
    try:
        fit_cameras(scene)
    except ValueError:
        pass
    snapshot_watts()
    return changed


class NS_OT_SyncLighting(bpy.types.Operator):
    bl_idname = 'ns.sync_lighting'
    bl_label = 'Samakan semua angle dengan angle ini'
    bl_description = 'Salin watt, warna, ukuran, dan sebaran tiap lampu (Key, Fill, Rim, Top, Tengah) dari angle aktif ke semua angle lain'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        changed = copy_watts(context.scene.ns_studio.shot)
        self.report({'INFO'}, f'{changed} lampu di angle lain disamakan dengan angle {context.scene.ns_studio.shot}.')
        return {'FINISHED'}


def camera_for(scene, shot):
    return next((o for o in scene.objects if o.type == 'CAMERA'
                 and o.get('ns_shot') == shot), None)


def product_objects(scene):
    coll = scene.ns_studio.product
    return [o for o in coll.all_objects
            if o.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}
            and not o.hide_render] if coll else []


def product_bounds(scene):
    objects = product_objects(scene)
    if not objects:
        raise ValueError('Produk aktif belum berisi geometri.')
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        points.extend(evaluated.matrix_world @ Vector(v) for v in evaluated.bound_box)
    lo = Vector([min(p[a] for p in points) for a in range(3)])
    hi = Vector([max(p[a] for p in points) for a in range(3)])
    return lo, hi


def root_for(scene):
    coll = scene.ns_studio.product
    if coll:
        return next((o for o in coll.all_objects if o.get('ns_product_root')), None)


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def select_shot(scene, shot):
    for obj in scene.objects:
        if obj.type == 'MESH' and obj.name.startswith(('Room', 'Ceiling')):
            # Dinding/balok ruang hanya konteks; cyclorama yang jadi latar. Produk besar
            # membuat kamera dan lampu dekat balok plafon sehingga balok muncul sebagai hotspot.
            obj.visible_camera = False
        if obj.get('ns_equipment') or obj.get('ns_guide'):
            # Perlengkapan dan panah penunjuk arah lampu tidak boleh terender
            # (produk besar membuat kamera mundur sehingga keduanya masuk frame).
            obj.visible_camera = False
            obj.visible_shadow = False
            # Shadow catcher latar menghitung objek yang terkena sinar diffuse sebagai penghalang
            # cahaya world: kaki stand di lantai muncul sebagai bintik gelap di latar.
            if obj.get('ns_guide') or obj.get('ns_equipment'):
                obj.visible_diffuse = False
                obj.visible_glossy = False
                obj.visible_transmission = False
    cam = camera_for(scene, shot)
    if cam is None:
        raise ValueError('Kamera preset tidak ditemukan. Buka file Nakas_Studio.blend.')
    scene.camera = cam
    for coll in bpy.data.collections:
        if coll.get('ns_light_shot'):
            visible = coll['ns_light_shot'] == shot
            coll.hide_render = not visible
            coll.hide_viewport = not visible
    if not bpy.app.background:
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.spaces.active.region_3d.view_perspective = 'CAMERA'
    if hasattr(scene.ns_studio, 'preview_mode'):
        apply_preview(scene)


def apply_preview(scene):
    mode = scene.ns_studio.preview_mode
    overview = scene.camera and scene.camera.name == 'CAM | STUDIO OVERVIEW'
    # Material Preview uses EEVEE, which does not use Cycles ray visibility.
    # Hide only physical equipment in the viewport; render visibility stays intact.
    for obj in scene.objects:
        if not (obj.get('ns_equipment') or obj.get('ns_guide')):
            continue
        hide = mode == 'FAST' and not overview
        if hide:
            if 'ns_preview_hidden_before' not in obj:
                obj['ns_preview_hidden_before'] = obj.hide_get()
            obj.hide_set(True)
        elif 'ns_preview_hidden_before' in obj:
            obj.hide_set(bool(obj['ns_preview_hidden_before']))
            del obj['ns_preview_hidden_before']
    scene.cycles.preview_samples = 8
    scene.cycles.use_preview_denoising = True
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = area.spaces.active
            space.lock_camera = False
            space.shading.type = 'SOLID' if mode == 'PAUSE' or (mode == 'FAST' and overview) else 'MATERIAL' if mode == 'FAST' else 'RENDERED'
            if space.shading.type == 'SOLID':
                # Mode Jeda tetap memperlihatkan tekstur finish (tanpa lampu), supaya ganti finish terlihat.
                space.shading.color_type = 'TEXTURE'
                space.shading.light = 'STUDIO'
            space.shading.use_scene_lights = True
            space.shading.use_scene_world = True
            if bpy.data.node_groups.get(LATAR_GROUP):
                # Latar ditempel di compositor; tanpa ini pratinjau memperlihatkan film transparan.
                space.shading.use_compositor = 'CAMERA'
            space.overlay.show_overlays = False
            area.tag_redraw()


def preview_updated(settings, context):
    if context.scene.get('ns_ready'):
        apply_preview(context.scene)


class NS_OT_PreviewMode(bpy.types.Operator):
    bl_idname = 'ns.preview_mode'
    bl_label = 'Pilih pratinjau'
    mode: StringProperty(default='FAST')

    def execute(self, context):
        context.scene.ns_studio.preview_mode = self.mode
        apply_preview(context.scene)
        return {'FINISHED'}


class NS_OT_QuickAngle(bpy.types.Operator):
    bl_idname = 'ns.quick_angle'
    bl_label = 'Lihat angle produk'
    shot: StringProperty(default='HERO')

    def execute(self, context):
        context.scene.ns_studio.shot = self.shot
        select_shot(context.scene, self.shot)
        return {'FINISHED'}


class NS_OT_Navigate(bpy.types.Operator):
    bl_idname = 'ns.navigate'
    bl_label = 'Atur tampilan'
    bl_description = 'Mengubah tampilan layar; kamera render dan produk tetap'
    action: StringProperty(default='HOME')

    def execute(self, context):
        area = context.area if context.area and context.area.type == 'VIEW_3D' else next((a for a in context.screen.areas if a.type=='VIEW_3D'), None)
        if area is None:
            return {'CANCELLED'}
        space=area.spaces.active
        space.lock_camera=False
        view=space.region_3d
        if self.action=='HOME':
            select_shot(context.scene,context.scene.ns_studio.shot)
            view.view_camera_zoom=0
            view.view_camera_offset=(0,0)
        else:
            region=next(r for r in area.regions if r.type=='WINDOW')
            with context.temp_override(area=area,region=region):
                if self.action in {'IN','OUT'}:
                    bpy.ops.view3d.zoom(delta=1 if self.action=='IN' else -1)
                else:
                    if view.view_perspective=='CAMERA':
                        if product_objects(context.scene):
                            lo,hi=product_bounds(context.scene)
                            view.view_location=(lo+hi)/2
                            view.view_distance=max(1.2,max(hi-lo)*3)
                        else:
                            view.view_location=(0,0,1)
                            view.view_distance=6
                        view.view_perspective='PERSP'
                    bpy.ops.view3d.view_orbit(type='ORBIT'+self.action,angle=math.radians(15))
        return {'FINISHED'}


def shot_updated(settings, context):
    if context.scene.get('ns_ready'):
        try:
            select_shot(context.scene, settings.shot)
        except ValueError:
            pass


def quality_updated(settings, context):
    scene = context.scene
    if settings.quality == 'PREVIEW':
        scene.render.resolution_x = scene.render.resolution_y = 800
        scene.cycles.samples = 48
        scene.cycles.adaptive_threshold = 0.08
    else:
        scene.render.resolution_x = scene.render.resolution_y = 1600
        scene.cycles.samples = 192
        scene.cycles.adaptive_threshold = 0.015
    scene.render.resolution_percentage = 100


class NS_Settings(bpy.types.PropertyGroup):
    preview_mode: EnumProperty(name='Pratinjau', default='FAST', update=preview_updated,
                              items=[('FAST','Cepat','Lighting perkiraan dengan EEVEE'),
                                     ('DETAIL','Cek detail','Cycles 8 samples; tunggu sampai stabil'),
                                     ('PAUSE','Jeda','Tampilan bentuk tanpa perhitungan lighting')])
    product: PointerProperty(type=bpy.types.Collection, name='Produk aktif')
    shot: EnumProperty(name='Kamera', items=SHOTS, update=shot_updated)
    output: StringProperty(name='Folder render', subtype='DIR_PATH', default='//renders/',
                           options={'PATH_SUPPORTS_BLEND_RELATIVE'})
    quality: EnumProperty(name='Kualitas', default='FINAL', update=quality_updated,
                         items=[('PREVIEW', 'Preview · 800 px', ''),
                                ('FINAL', 'Final · 1600 px', '')])
    frame_margin: FloatProperty(name='Ruang tepi', default=1.18, min=1.02, max=2.0)
    actual_width: FloatProperty(name='Lebar nyata (cm)', default=50.0, min=1, max=500)
    import_scale: EnumProperty(name='Faktor setelah impor', default='1', items=[
        ('1', '1 × · pertahankan ukuran', 'Importer FBX/GLTF biasanya sudah membaca unit'),
        ('0.01', '0.01 × · angka mentah cm ke m', ''),
        ('0.001', '0.001 × · angka mentah mm ke m', ''),
    ])
    include_hero: BoolProperty(name='Hero 3/4 kanan', default=True)
    include_front: BoolProperty(name='Depan', default=True)
    include_left: BoolProperty(name='3/4 kiri', default=True)
    include_side: BoolProperty(name='Samping', default=True)
    include_detail: BoolProperty(name='Detail', default=True)
    finish_wood: EnumProperty(name='Finish kayu', items=finish_items('WOOD_A', 'finish_wood'),
                              update=finish_updated('WOOD_A', 'finish_wood'))
    finish_handle: EnumProperty(name='Finish handle', items=finish_items('HANDLE', 'finish_handle'),
                                update=finish_updated('HANDLE', 'finish_handle'))
    lib_finish: EnumProperty(name='Finish', items=lib_finish_items)
    lib_tekstur: EnumProperty(name='Tekstur dasar', items=lib_tekstur_items, update=lib_tekstur_updated)
    lighting_all_angles: BoolProperty(name='Ubah semua angle sekaligus', default=False,
                                      description='Saat watt, warna, ukuran, atau sebaran satu lampu diubah, lampu dengan peran sama di semua angle ikut berubah',
                                      update=lambda self, context: snapshot_watts())


def fit_cameras(scene):
    lo, hi = product_bounds(scene)
    center, size = (lo + hi) / 2, hi - lo
    corners = [Vector((x, y, z)) for x in (lo.x, hi.x)
               for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    for shot in SHOT_IDS:
        cam = camera_for(scene, shot)
        if cam is None:
            continue
        fraction = Vector(cam.get('ns_target_fraction', (0, 0, 0.5)))
        target = Vector((center.x + size.x * fraction.x,
                         center.y + size.y * fraction.y,
                         lo.z + size.z * fraction.z))
        direction = Vector(cam['ns_direction']).normalized()
        cam.location = target + direction
        aim(cam, target)
        if shot == 'DETAIL':
            distance = max(size) * 1.45
        else:
            # Solve the pinhole frustum for every world-space bound corner.
            # Vertical FOV follows render aspect, pixel aspect, and sensor fit.
            aspect = (scene.render.resolution_x * scene.render.pixel_aspect_x /
                      (scene.render.resolution_y * scene.render.pixel_aspect_y))
            tan_x = cam.data.sensor_width / (2 * cam.data.lens)
            tan_y = tan_x / aspect
            inverse = cam.rotation_euler.to_matrix().transposed()
            distance = 0.01
            for point in corners:
                local = inverse @ (point - target)
                distance = max(distance, local.z + abs(local.x) / tan_x * scene.ns_studio.frame_margin,
                               local.z + abs(local.y) / tan_y * scene.ns_studio.frame_margin)
        cam.location = target + direction * distance
        aim(cam, target)
        cam.data.dof.focus_distance = distance
    return size


def center_product(scene):
    root = root_for(scene)
    if root is None:
        raise ValueError('Root produk tidak ditemukan. Gunakan Ambil Objek Terpilih.')
    lo, hi = product_bounds(scene)
    root.location += Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))
    bpy.context.view_layer.update()


def activate_product(scene, coll):
    group = bpy.data.collections.get('PRODUCTS')
    if group:
        for other in group.children:
            other.hide_render = other.hide_viewport = other != coll
    coll.hide_render = coll.hide_viewport = False
    scene.ns_studio.product = coll


def adopt_objects(scene, objects, label):
    objects = [o for o in objects if o.type not in {'CAMERA', 'LIGHT'}]
    if not any(o.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'} for o in objects):
        raise ValueError('Tidak ada mesh atau geometri produk yang dapat dipakai.')
    group = bpy.data.collections.get('PRODUCTS')
    if group is None:
        group = bpy.data.collections.new('PRODUCTS')
        scene.collection.children.link(group)
    coll = bpy.data.collections.new('PROD | ' + label)
    group.children.link(coll)
    coll['ns_product'] = True
    object_set = set(objects)
    root = bpy.data.objects.new('PRODUCT_ROOT | ' + label, None)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = 0.12
    root['ns_product_root'] = True
    coll.objects.link(root)
    for obj in objects:
        if obj.get('ns_product_root'):
            # Bawa metadata produk (ns_finishes, ns_exposure, ns_spec, dimensions_cm, ...) ke root baru.
            for key in obj.keys():
                if key not in {'ns_product_root', '_RNA_UI'}:
                    try:
                        root[key] = obj[key]
                    except (TypeError, ValueError):
                        pass
            obj['ns_product_root'] = False
        world = obj.matrix_world.copy()
        for previous in list(obj.users_collection):
            previous.objects.unlink(obj)
        coll.objects.link(obj)
        if obj.parent not in object_set:
            obj.parent = root
            obj.matrix_world = world
    activate_product(scene, coll)
    bpy.context.view_layer.update()
    return root


class NS_OT_Center(bpy.types.Operator):
    bl_idname = 'ns.center_product'
    bl_label = 'Letakkan di lantai & tengah'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            center_product(context.scene)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        return {'FINISHED'}


class NS_OT_Fit(bpy.types.Operator):
    bl_idname = 'ns.fit_cameras'
    bl_label = 'Atur framing semua kamera'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            fit_cameras(context.scene)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self.report({'INFO'}, 'Framing diperbarui. Periksa dan rapikan kamera detail secara manual.')
        return {'FINISHED'}


class NS_OT_Scale(bpy.types.Operator):
    bl_idname = 'ns.scale_product'
    bl_label = 'Terapkan lebar nyata'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        try:
            lo, hi = product_bounds(scene)
            root = root_for(scene)
            if not root or hi.x - lo.x < 0.000001:
                raise ValueError('Lebar produk tidak valid.')
            root.scale *= (scene.ns_studio.actual_width / 100) / (hi.x - lo.x)
            context.view_layer.update()
            center_product(scene)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        return {'FINISHED'}


class NS_OT_Rotate(bpy.types.Operator):
    bl_idname = 'ns.rotate_product'
    bl_label = 'Putar produk 90°'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        root = root_for(context.scene)
        if not root:
            return {'CANCELLED'}
        root.rotation_euler.z += math.pi / 2
        context.view_layer.update()
        center_product(context.scene)
        return {'FINISHED'}


class NS_OT_Adopt(bpy.types.Operator):
    bl_idname = 'ns.adopt_selected'
    bl_label = 'Ambil objek terpilih sebagai produk'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = list(context.selected_objects)
        if not selected:
            self.report({'ERROR'}, 'Pilih seluruh bagian model produk terlebih dahulu.')
            return {'CANCELLED'}
        if any(o.get('ns_studio_asset') or o.get('ns_product_root') for o in selected):
            self.report({'ERROR'}, 'Pilihan berisi rig studio atau root produk. Pilih hanya model pengganti.')
            return {'CANCELLED'}
        try:
            adopt_objects(context.scene, selected, context.active_object.name if context.active_object else 'Produk baru')
            center_product(context.scene)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self.report({'INFO'}, 'Produk aktif diganti. Periksa dimensi lalu klik Atur framing.')
        return {'FINISHED'}


class NS_OT_Import(bpy.types.Operator, ImportHelper):
    bl_idname = 'ns.import_product'
    bl_label = 'Impor produk pengganti'
    bl_options = {'REGISTER', 'UNDO'}
    filter_glob: StringProperty(default='*.blend;*.fbx;*.obj;*.glb;*.gltf', options={'HIDDEN'})

    def invoke(self, context, event):
        root = package_root()
        if root and not self.filepath:
            self.filepath = str(root / '02_PRODUK') + os.sep
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        before = set(bpy.data.objects)
        before_collections = set(bpy.data.collections)
        previous_product = context.scene.ns_studio.product
        filepath = self.filepath
        try:
            ext = Path(filepath).suffix.lower()
            if ext == '.blend':
                with bpy.data.libraries.load(filepath, link=False) as (src, dst):
                    dst.objects = list(src.objects)
                    # Finish kayu yang ditanam di produk (FIN | ...) ikut dibawa walau belum dipakai objek.
                    dst.materials = [m for m in src.materials if m.startswith('FIN | ') or m.startswith('HW | ')]
                imported = [o for o in dst.objects if o is not None]
                for obj in imported:
                    if not obj.users_collection:
                        context.scene.collection.objects.link(obj)
                for mat in dst.materials:
                    if mat is not None and mat.get('ns_finish_id'):
                        mat.use_fake_user = True
            elif ext == '.fbx':
                bpy.ops.import_scene.fbx(filepath=filepath)
            elif ext == '.obj':
                bpy.ops.wm.obj_import(filepath=filepath)
            elif ext in {'.glb', '.gltf'}:
                bpy.ops.import_scene.gltf(filepath=filepath)
            else:
                raise ValueError('Format yang didukung: BLEND, FBX, OBJ, GLB, GLTF.')
            created = set(bpy.data.objects) - before
            product = [o for o in created if o.type not in {'CAMERA', 'LIGHT'}]
            root = adopt_objects(context.scene, product, Path(filepath).stem)
            root.scale *= float(context.scene.ns_studio.import_scale)
            for obj in created - set(product):
                bpy.data.objects.remove(obj, do_unlink=True)
            for coll in set(bpy.data.collections) - before_collections:
                if not coll.objects and not coll.children and not coll.get('ns_product'):
                    bpy.data.collections.remove(coll)
            context.view_layer.update()
            center_product(context.scene)
            fit_cameras(context.scene)
            apply_rig_scale(context.scene, rig_scale_factor(context.scene))
            if context.scene.get('ns_std_exposure') is not None:
                # Studio berstandar: semua produk memakai exposure dan view yang sama, sehingga
                # terang latar dan lampu konsisten. Warna kayu dikoreksi di material produk.
                apply_studio_standard(context.scene)
            elif root.get('ns_exposure') is not None:
                # Exposure hasil kalibrasi periksa_produk.py: terang front disamakan dengan swatch referensi.
                context.scene.view_settings.exposure = float(root['ns_exposure'])
            if root.get('ns_view_transform'):
                # View transform tempat kalibrasi warna produk dilakukan (Khronos PBR Neutral untuk
                # produk baru; AgX menekan saturasi kayu). Produk lama tanpa properti ini tetap AgX.
                try:
                    context.scene.view_settings.view_transform = str(root['ns_view_transform'])
                    context.scene.view_settings.look = str(root.get('ns_look') or 'None')
                except TypeError as exc:
                    self.report({'WARNING'}, f"View transform {root['ns_view_transform']} tidak tersedia: {exc}")
            select_shot(context.scene, context.scene.ns_studio.shot)
            sync_finish_props(context.scene)
            self.report({'INFO'}, 'Produk dimuat, diposisikan, dan kamera disesuaikan. Periksa ukuran dan angle detail.')
            return {'FINISHED'}
        except Exception as exc:
            for obj in set(bpy.data.objects) - before:
                bpy.data.objects.remove(obj, do_unlink=True)
            for coll in set(bpy.data.collections) - before_collections:
                bpy.data.collections.remove(coll)
            if previous_product:
                activate_product(context.scene, previous_product)
            self.report({'ERROR'}, 'Impor gagal: ' + str(exc))
            return {'CANCELLED'}


def apply_studio_standard(scene):
    scene.view_settings.exposure = float(scene['ns_std_exposure'])
    view = list(scene.get('ns_std_view') or ())
    if view:
        try:
            scene.view_settings.view_transform = str(view[0])
            scene.view_settings.look = str(view[1]) if len(view) > 1 else 'None'
        except TypeError as exc:
            print('Nakas Studio: view transform standar tidak tersedia:', exc)


class NS_OT_Activate(bpy.types.Operator):
    bl_idname = 'ns.activate_product'
    bl_label = 'Gunakan produk'
    bl_options = {'REGISTER', 'UNDO'}
    collection_name: StringProperty()

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if not coll or not coll.get('ns_product'):
            return {'CANCELLED'}
        activate_product(context.scene, coll)
        sync_finish_props(context.scene)
        return {'FINISHED'}


def render_directory(scene):
    label = bpy.path.clean_name(scene.ns_studio.product.name if scene.ns_studio.product else 'produk')
    folder = Path(bpy.path.abspath(scene.ns_studio.output)) / label / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def chosen_shots(settings):
    return [shot for shot in SHOT_IDS if getattr(settings, 'include_' + shot.lower())]


class NS_OT_RenderBatch(bpy.types.Operator):
    bl_idname = 'ns.render_batch'
    bl_label = 'Render semua angle terpilih'
    bl_description = 'Simpan PNG per kamera ke folder baru; Esc untuk membatalkan'

    def execute(self, context):
        self._shots = chosen_shots(context.scene.ns_studio)
        if not self._shots:
            self.report({'ERROR'}, 'Pilih minimal satu angle.'); return {'CANCELLED'}
        try:
            product_bounds(context.scene)
            self._folder = render_directory(context.scene)
        except (ValueError, OSError) as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self._scene = context.scene
        self._original = (self._scene.ns_studio.shot, self._scene.render.filepath)
        self._index = 0
        self._running = self._done = self._cancelled = False
        if bpy.app.background:
            try:
                for shot in self._shots:
                    self._scene.ns_studio.shot = shot
                    select_shot(self._scene, shot)
                    self._scene.render.filepath = str(self._folder / (shot.lower() + '.png'))
                    bpy.ops.render.render(write_still=True)
            finally:
                self._restore()
            return {'FINISHED'}
        self._complete_handler = self._on_complete
        self._cancel_handler = self._on_cancel
        bpy.app.handlers.render_complete.append(self._complete_handler)
        bpy.app.handlers.render_cancel.append(self._cancel_handler)
        self._timer = context.window_manager.event_timer_add(0.4, window=context.window)
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, 'Batch render dimulai: ' + str(self._folder))
        return {'RUNNING_MODAL'}

    def _on_complete(self, scene, *args):
        if scene == self._scene:
            self._done = True

    def _on_cancel(self, scene, *args):
        if scene == self._scene:
            self._cancelled = True
            self._done = True

    def _restore(self):
        shot, filepath = self._original
        self._scene.ns_studio.shot = shot
        select_shot(self._scene, shot)
        self._scene.render.filepath = filepath

    def _finish(self, context, cancelled=False):
        context.window_manager.event_timer_remove(self._timer)
        for handlers, fn in ((bpy.app.handlers.render_complete, self._complete_handler),
                             (bpy.app.handlers.render_cancel, self._cancel_handler)):
            if fn in handlers:
                handlers.remove(fn)
        self._restore()
        self.report({'WARNING'} if cancelled else {'INFO'},
                    ('Batch dibatalkan. Hasil selesai tetap tersimpan: ' if cancelled else 'Render selesai: ') + str(self._folder))
        return {'CANCELLED'} if cancelled else {'FINISHED'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self._cancelled = True
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        busy = bpy.app.is_job_running('RENDER')
        if self._cancelled and not busy:
            return self._finish(context, True)
        if self._running:
            if not self._done or busy:
                return {'PASS_THROUGH'}
            self._index += 1
            self._running = False
        if self._index >= len(self._shots):
            return self._finish(context)
        shot = self._shots[self._index]
        self._scene.ns_studio.shot = shot
        select_shot(self._scene, shot)
        self._scene.render.filepath = str(self._folder / (shot.lower() + '.png'))
        self._done = False
        self._running = True
        try:
            result = bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)
            if result == {'CANCELLED'}:
                return self._finish(context, True)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return self._finish(context, True)
        return {'PASS_THROUGH'}


class NS_OT_SelectCamera(bpy.types.Operator):
    bl_idname = 'ns.select_camera'
    bl_label = 'Pilih kamera untuk diedit'

    def execute(self, context):
        cam = context.scene.camera
        if not cam:
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        cam.select_set(True)
        context.view_layer.objects.active = cam
        return {'FINISHED'}


class NS_OT_Overview(bpy.types.Operator):
    bl_idname = 'ns.studio_overview'
    bl_label = 'Lihat ruang studio / kembali ke produk'

    def execute(self, context):
        scene = context.scene
        overview = bpy.data.objects.get('CAM | STUDIO OVERVIEW')
        if overview is None:
            return {'CANCELLED'}
        if scene.camera == overview:
            select_shot(scene, scene.ns_studio.shot)
        else:
            scene.camera = overview
            for obj in scene.objects:
                if obj.get('ns_equipment'):
                    obj.visible_camera = True
                    obj.visible_shadow = True
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
        apply_preview(scene)
        return {'FINISHED'}


class NS_OT_LightingView(bpy.types.Operator):
    bl_idname = 'ns.lighting_view'
    bl_label = 'Lihat lighting · Cycles'
    bl_description = 'Gunakan Rendered View untuk melihat lampu studio dan pantulan Cycles'

    def execute(self, context):
        context.scene.ns_studio.preview_mode = 'DETAIL'
        apply_preview(context.scene)
        return {'FINISHED'}


def package_root():
    if bpy.data.filepath:
        for parent in Path(bpy.data.filepath).parents:
            if (parent/'01_STUDIO').is_dir() and (parent/'02_PRODUK').is_dir():
                return parent
    return None


class NS_OT_LoadExample(bpy.types.Operator):
    bl_idname = 'ns.load_example'
    bl_label = 'Muat contoh nakas'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        root = package_root()
        path = root/'02_PRODUK/Nakas/Nakas_Oak_2Laci.blend' if root else None
        if path is None or not path.is_file():
            self.report({'ERROR'}, 'File contoh tidak ditemukan. Gunakan Pilih file produk.')
            return {'CANCELLED'}
        context.scene.ns_studio.import_scale = '1'
        return bpy.ops.ns.import_product(filepath=str(path))


class NS_PT_Main(bpy.types.Panel):
    bl_label = 'NAKAS / STUDIO 01'
    bl_idname = 'NS_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Nakas Studio'

    def draw(self, context):
        layout, scene = self.layout, context.scene
        if not scene.get('ns_ready'):
            layout.label(text='Buka file Nakas_Studio.blend', icon='INFO')
            return
        s = scene.ns_studio
        root = package_root()
        if root:
            box=layout.box()
            box.label(text='MULAI DARI SINI',icon='FILE_FOLDER')
            box.label(text='Produk: '+s.product.name.replace('PROD | ','') if s.product else 'Studio kosong · pilih produk')
            box.operator('ns.import_product',text='Pilih file produk',icon='IMPORT')
            if not s.product:
                box.operator('ns.load_example',icon='OUTLINER_OB_MESH')
            box.operator('wm.save_as_mainfile',text='Simpan proyek sebagai...',icon='FILE_TICK')
        if s.product:
            box = layout.box()
            box.label(text='FINISH', icon='MATERIAL')
            catalog = finish_catalog()
            slots = product_slots(scene)
            if not catalog:
                box.label(text='Library finish belum ada di 02_PRODUK/_FINISH.', icon='ERROR')
            for role, prop_name, label in FINISH_ROLES:
                if role not in catalog:
                    continue
                row = box.row(align=True)
                row.enabled = role in slots
                row.prop(s, prop_name, text=label)
                op = row.operator('ns.apply_finish', text='', icon='FILE_REFRESH')
                op.role = role; op.finish_id = ''
            missing = [role for role, _, _ in FINISH_ROLES if role in catalog and role not in slots]
            if missing:
                box.label(text='Produk ini tidak punya bagian: ' + ', '.join(missing), icon='INFO')
            pesan = s.get('_finish_pesan')
            if pesan:
                box.label(text=str(pesan), icon='ERROR' if str(pesan).startswith('Gagal') else 'CHECKMARK')
            box.label(text='Ganti tekstur kayu: dropdown "Kayu utama" di atas.', icon='INFO')
        if root:
            header, body = layout.panel('ns_finish_library', default_closed=True)
            header.label(text='Tekstur finish produk (Poly Haven)')
            if body:
                body.operator('ns.tambah_tekstur_dasar', icon='IMPORT')
                col = body.column(align=True)
                col.enabled = bool(s.product)
                col.prop(s, 'lib_finish', text='Finish')
                col.prop(s, 'lib_tekstur', text='Tekstur dasar')
                col.operator('ns.pakai_tekstur_finish', icon='CHECKMARK')
                col.operator('ns.bangun_ulang_produk', icon='FILE_REFRESH')
                body.label(text='Finish mengikuti produk.json tiap produk.', icon='INFO')
                body.label(text='Unduh zip Blend 4K Poly Haven.', icon='INFO')
        box=layout.box()
        box.label(text='TAMPILAN & NAVIGASI',icon='VIEW3D')
        row=box.row(align=True)
        row.scale_y=1.4
        for mode,label in [('FAST','Cepat'),('DETAIL','Cek detail'),('PAUSE','Jeda')]:
            row.operator('ns.preview_mode',text=label,depress=s.preview_mode==mode).mode=mode
        box.label(text='Cepat: perkiraan lighting. Detail: Cycles.' if s.preview_mode=='FAST' else 'Tunggu preview stabil.' if s.preview_mode=='DETAIL' else 'Lighting dijeda; watt tetap tersimpan.')
        grid=box.grid_flow(columns=2,row_major=True,align=True)
        for shot,label in [('HERO','Hero kanan'),('FRONT','Depan'),('LEFT','Hero kiri'),('SIDE','Samping'),('DETAIL','Detail produk')]:
            grid.operator('ns.quick_angle',text=label,depress=scene.camera==camera_for(scene,shot)).shot=shot
        grid.operator('ns.studio_overview',text='Ruang studio',icon='SCENE_DATA')
        row=box.row(align=True)
        for action,label in [('IN','Perbesar +'),('OUT','Perkecil −')]:
            row.operator('ns.navigate',text=label).action=action
        box.operator('ns.navigate',text='Kembali ke kamera produk',icon='CAMERA_DATA').action='HOME'
        row=box.grid_flow(columns=2,row_major=True,align=True)
        for action,label in [('LEFT','Putar kiri'),('RIGHT','Putar kanan'),('UP','Lihat atas'),('DOWN','Lihat bawah')]:
            row.operator('ns.navigate',text=label).action=action
        header, body = layout.panel('ns_product_options', default_closed=True)
        header.label(text='Ganti produk & ukuran')
        if body:
            box = body
            box.label(text='01 / PRODUK · SKALA NYATA', icon='OUTLINER_OB_MESH')
            box.label(text=s.product.name.replace('PROD | ', '') if s.product else 'Belum ada produk')
            try:
                lo, hi = product_bounds(scene)
                size = (hi - lo) * 100
                box.label(text=f'L {size.x:.1f} × D {size.y:.1f} × T {size.z:.1f} cm')
            except ValueError:
                pass
            box.prop(s, 'import_scale')
            box.operator('ns.import_product', icon='IMPORT')
            box.operator('ns.adopt_selected', icon='ADD')
            box.operator('ns.center_product')
            box.operator('ns.rotate_product')
            if s.product:
                for obj in s.product.all_objects:
                    if obj.get('ns_drawer'):
                        box.prop(obj, '["Open (m)"]', text=f'Laci {obj["ns_drawer"]} · m', slider=True)
            row = box.row(align=True)
            row.prop(s, 'actual_width', text='Lebar cm')
            row.operator('ns.scale_product', text='Terapkan')
            group = bpy.data.collections.get('PRODUCTS')
            if group and len(group.children) > 1:
                box.label(text='Produk tersimpan:')
                for coll in group.children:
                    if coll != s.product:
                        op = box.operator('ns.activate_product', text=coll.name.replace('PROD | ', ''), icon='RESTRICT_RENDER_OFF')
                        op.collection_name = coll.name
        header, body = layout.panel('ns_camera_options', default_closed=True)
        header.label(text='Pengaturan kamera lanjutan')
        if body:
            box = body
            box.label(text='02 / KAMERA', icon='CAMERA_DATA')
            if bpy.data.objects.get('CAM | STUDIO OVERVIEW'):
                box.operator('ns.studio_overview', icon='SCENE_DATA')
            box.prop(s, 'shot', text='')
            box.prop(s, 'frame_margin')
            box.operator('ns.fit_cameras', icon='FULLSCREEN_ENTER')
            box.operator('ns.select_camera')
            if scene.camera:
                box.prop(scene.camera.data, 'lens', text='Lensa mm')
                box.prop(scene.camera.data.dof, 'use_dof', text='Depth of field')
            box.label(text='Detail: rapikan target secara manual.', icon='INFO')
        box = layout.box()
        box.label(text='03 / LIGHTING · PER ANGLE', icon='LIGHT_AREA')
        category, defaults = lighting_profile(scene)
        box.label(text=f"Kategori: {category.title()} · skala rig {float(scene.get('ns_rig_scale', 1.0)):.2f}×")
        rig = next((c for c in bpy.data.collections if c.get('ns_light_shot') == s.shot), None)
        if rig:
            for obj in rig.all_objects:
                if obj.type == 'LIGHT':
                    row = box.row(align=True)
                    row.prop(obj.data, 'energy', text=obj.get('ns_role', obj.name))
                    row.prop(obj.data, 'color', text='')
        box.prop(scene.view_settings, 'exposure', text='Exposure')
        box.prop(s, 'lighting_all_angles', icon='LINKED' if s.lighting_all_angles else 'UNLINKED')
        box.operator('ns.sync_lighting', icon='DUPLICATE')
        row = box.column(align=True)
        row.enabled = defaults is not None
        row.operator('ns.reset_lighting', text='Reset watt angle', icon='LOOP_BACK').scope = 'ANGLE'
        row.operator('ns.reset_lighting', text='Reset watt kategori').scope = 'CATEGORY'
        box.label(text='Tiap angle menyimpan watt sendiri · dapat Undo', icon='INFO')
        backdrop = bpy.data.materials.get('Studio | Warm grey seamless')
        if scene.get('ns_latar'):
            box.label(text=f"Latar dikunci: {scene['ns_latar']} · exposure standar {float(scene.get('ns_std_exposure', 0)):.2f}", icon='LOCKED')
        elif backdrop:
            node = backdrop.node_tree.nodes.get('Principled BSDF')
            box.prop(node.inputs['Base Color'], 'default_value', text='Backdrop')
        box = layout.box()
        box.label(text='04 / OUTPUT', icon='OUTPUT')
        box.prop(s, 'quality', text='')
        box.prop(s, 'output', text='')
        for shot in SHOT_IDS:
            box.prop(s, 'include_' + shot.lower())
        box.operator('render.render', text='Render angle aktif', icon='RENDER_STILL').write_still = False
        box.operator('ns.render_batch', icon='RENDER_ANIMATION')
        box.label(text='Setiap batch memakai folder baru.')


CLASSES = (NS_Settings, NS_OT_Center, NS_OT_Fit, NS_OT_Scale, NS_OT_Rotate,
           NS_OT_Adopt, NS_OT_Import, NS_OT_Activate, NS_OT_RenderBatch,
           NS_OT_SelectCamera, NS_OT_Overview, NS_OT_ResetLighting, NS_OT_LightingView,
           NS_OT_PreviewMode, NS_OT_QuickAngle, NS_OT_Navigate, NS_OT_LoadExample,
           NS_OT_ApplyFinish, NS_OT_AddBaseTexture, NS_OT_SetFinishTexture,
           NS_OT_RebuildFinishLibrary, NS_OT_SyncLighting, NS_PT_Main)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ns_studio = PointerProperty(type=NS_Settings)
    subscribe_light_energy()
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)


def unregister():
    bpy.msgbus.clear_by_owner(_msgbus_owner)
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    if hasattr(bpy.types.Scene, 'ns_studio'):
        del bpy.types.Scene.ns_studio
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    register()
