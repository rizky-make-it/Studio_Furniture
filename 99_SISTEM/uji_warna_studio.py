"""Uji netralitas warna studio dengan kartu warna.

Jalankan:  blender -b 01_STUDIO/Studio_Nakas.blend --python 99_SISTEM/uji_warna_studio.py -- [folder_keluaran] [exposure] [view] [look] [netral] [auto]
  folder_keluaran  default 99_SISTEM/_kerja/uji_warna
  exposure         angka; 'auto' di opsi = exposure dicari agar kartu abu 18% terender tepat (#757575)
  view/look        mis. "Khronos PBR Neutral" None, atau AgX "AgX - Base Contrast"
  netral           semua lampu dibuat putih dan world abu 0.5 (hanya di memori, file tidak disimpan)
Kartu: abu 18%, putih 80%, white oak #d6c2a0, oak emas #d7a56c, walnut gelap #594f45, tan mindi #b69a81,
dipasang di posisi produk, dirender dari kamera FRONT dengan rig FRONT. Mencetak selisih hue, saturasi, value
dan jarak warna tiap patch. Studio netral yang benar: dHue ~0, saturasi tidak turun, abu 18% = #757575.
Bisa juga dijalankan pada file sesi (03_PROYEK/*.blend): mesh produk disembunyikan otomatis.
Catatan teknis: render probe dipaksa PNG 8-bit karena PNG 16-bit dimuat sebagai float linear.
"""

import bpy, sys, importlib.util, colorsys, math
import numpy as np
from pathlib import Path
ROOT = Path(r'C:/Users/Admin/Documents/Studio_Furniture')
args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
OUT = Path(args[0]) if args and not args[0].lstrip('-').replace('.', '').isdigit() else ROOT / '99_SISTEM/_kerja/uji_warna'
if args and OUT != Path(args[0]): args = ['_'] + args
OUT.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('nakas_studio_tools', ROOT / '99_SISTEM/nakas_studio_tools.py')
ns = importlib.util.module_from_spec(spec); sys.modules['nakas_studio_tools'] = ns; spec.loader.exec_module(ns); ns.register()
s = bpy.context.scene
if len(args) > 1: s.view_settings.exposure = float(args[1])
if len(args) > 2: s.view_settings.view_transform = args[2]
if len(args) > 3: s.view_settings.look = args[3]
NETRAL = 'netral' in args[4:]
AUTO = 'auto' in args[4:]
if NETRAL:
    for o in bpy.data.objects:
        if o.type == 'LIGHT': o.data.color = (1.0, 1.0, 1.0)
    w = s.world
    if w and w.use_nodes:
        bg = next(n for n in w.node_tree.nodes if n.type == 'BACKGROUND')
        bg.inputs[0].default_value = (0.5, 0.5, 0.5, 1.0)
PATCHES = [('abu 18%', (0.46, 0.46, 0.46)), ('putih 80%', (0.90, 0.90, 0.90)), ('white oak', (0xd6/255, 0xc2/255, 0xa0/255)),
           ('oak emas', (0xd7/255, 0xa5/255, 0x6c/255)), ('walnut gelap', (0x59/255, 0x4f/255, 0x45/255)), ('tan mindi', (0xb6/255, 0x9a/255, 0x81/255))]
# kartu: 6 patch mendatar, gambar 600x100 sRGB
W, H = 600, 100
img = bpy.data.images.new('kartu', W, H, alpha=False); img.colorspace_settings.name = 'sRGB'
buf = np.ones((H, W, 4), dtype=np.float32)
for i, (_, c) in enumerate(PATCHES): buf[:, i*100:(i+1)*100, :3] = c
img.pixels.foreach_set(buf.ravel()); img.filepath_raw = str(OUT / 'kartu.png'); img.file_format = 'PNG'; img.save()
bpy.data.images.remove(img); img = bpy.data.images.load(str(OUT / 'kartu.png')); img.colorspace_settings.name = 'sRGB'
# plane 0.6 x 0.1 m di posisi muka produk (depan -Y), tinggi 0.4 m, menghadap -Y
for o in bpy.data.objects:
    if o.type == 'MESH' and not any(k in o.name.lower() for k in ('cyc', 'room', 'floor', 'lantai', 'ceiling', 'wall', 'latar')):
        o.hide_render = True
bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, 0.4), rotation=(math.radians(90), 0, 0))
plane = bpy.context.active_object; plane.scale = (0.6, 0.1, 1); plane.name = 'KARTU'
m = bpy.data.materials.new('KARTU'); m.use_nodes = True; nt = m.node_tree
b = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'); b.inputs['Roughness'].default_value = 1.0; b.inputs['Specular IOR Level'].default_value = 0.0
t = nt.nodes.new('ShaderNodeTexImage'); t.image = img; nt.links.new(t.outputs['Color'], b.inputs['Base Color'])
if 'emisi' in args[4:]:
    nt.nodes.remove(b); em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Strength'].default_value = 1.0
    nt.links.new(t.outputs['Color'], em.inputs['Color']); nt.links.new(em.outputs['Emission'], next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL').inputs['Surface'])
if 'konstan' in args[4:]:
    nt.links.remove(t.outputs['Color'].links[0]); b.inputs['Base Color'].default_value = (0.18, 0.18, 0.18, 1.0)
if 'lambert' in args[4:]:
    nt.nodes.remove(b); d = nt.nodes.new('ShaderNodeBsdfDiffuse'); nt.links.new(t.outputs['Color'], d.inputs['Color'])
    nt.links.new(d.outputs['BSDF'], next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL').inputs['Surface'])
chk = np.array(img.pixels[:], dtype=np.float64).reshape(H, W, 4); print('CEK pixel patch abu tersimpan', chk[50, 50, :3].round(3), 'putih', chk[50, 150, :3].round(3))
plane.data.materials.append(m)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.uv.reset(); bpy.ops.object.mode_set(mode='OBJECT')
ns.select_shot(s, 'FRONT'); s.ns_studio.shot = 'FRONT'
cam = s.camera
# kamera ortho lurus ke kartu supaya pengukuran bersih
cam.data.type = 'ORTHO'; cam.data.ortho_scale = 0.6; cam.location = (0, -2.0, 0.4); cam.rotation_euler = (math.radians(90), 0, 0)
s.render.resolution_x, s.render.resolution_y = 600, 100; s.render.resolution_percentage = 100; s.cycles.samples = 64
def render_measure():
    # PNG 16-bit dimuat Blender sebagai float LINEAR (Image.pixels bukan sRGB); paksa 8-bit agar pixels = byte sRGB
    s.render.image_settings.file_format = 'PNG'; s.render.image_settings.color_depth = '8'; s.render.image_settings.color_mode = 'RGB'
    s.render.filepath = str(OUT / 'kartu_render.png'); bpy.ops.render.render(write_still=True)
    r = bpy.data.images.load(str(OUT / 'kartu_render.png'), check_existing=False)
    a = np.array(r.pixels[:], dtype=np.float64).reshape(100, 600, 4)[::-1, :, :3]; bpy.data.images.remove(r); return a
def lin(v): return v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4
if AUTO:
    # exposure supaya patch putih 80% terender pada nilainya (iterasi 3x, diukur linear)
    for _ in range(3):
        a = render_measure(); got = a[30:70, 20:80].reshape(-1, 3).mean(0)
        target_l = lin(0.46); got_l = sum(lin(v) for v in got) / 3
        s.view_settings.exposure += math.log2(target_l / max(got_l, 1e-4))
a = render_measure()
hexs = lambda c: '#%02x%02x%02x' % tuple(int(round(max(0, min(1, v))*255)) for v in c)
print('KARTU view', s.view_settings.view_transform, '/', s.view_settings.look, 'exposure', round(s.view_settings.exposure, 2))
for i, (name, c) in enumerate(PATCHES):
    got = a[30:70, i*100+20:i*100+80].reshape(-1, 3).mean(0)
    h0, s0, v0 = colorsys.rgb_to_hsv(*c); h1, s1, v1 = colorsys.rgb_to_hsv(*got)
    print(f'PATCH {name:12s} target {hexs(c)} render {hexs(got)}  dHue {((h1-h0)*360+180)%360-180:+5.1f}  sat {s0:.2f}->{s1:.2f}  val {v0:.2f}->{v1:.2f}  dE~{(sum((a1-b1)**2 for a1,b1 in zip(c,got))**0.5)*100:4.1f}')
