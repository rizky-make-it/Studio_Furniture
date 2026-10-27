import bpy,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'99_SISTEM'))
import nakas_studio_tools as ns
ns.register()
s=bpy.context.scene
product=s.ns_studio.product
lo,hi=ns.product_bounds(s)
product_scene=bpy.data.scenes.new('PRODUK | Nakas Oak dua laci')
product_scene.collection.children.link(product)
product_scene.unit_settings.system='METRIC'
product_scene.unit_settings.scale_length=1
product_scene.unit_settings.length_unit='CENTIMETERS'
product_scene['category']='NAKAS'
product_scene['dimensions_cm']=[round(float(v)*100,2) for v in hi-lo]
product_scene['front']='-Y; ground Z=0'
product.name='PROD | Nakas Oak 2 Laci'
product['category']='NAKAS'
product['asset_id']='nakas_oak_2laci_001'
bpy.ops.file.pack_all()
bpy.data.libraries.write(str(ROOT/'02_PRODUK/Nakas/Nakas_Oak_2Laci.blend'),{product_scene},path_remap='RELATIVE',compress=True)
bpy.data.scenes.remove(product_scene)
objects=list(product.all_objects)
s.ns_studio.product=None
for obj in objects:bpy.data.objects.remove(obj,do_unlink=True)
group=bpy.data.collections['PRODUCTS']
for coll in list(group.children):bpy.data.collections.remove(coll)
s.name='STUDIO | Nakas kosong'
s['ns_package_layout']='Studio Furniture / 1.0'
s.ns_studio.output='//../04_HASIL_RENDER/'
s.render.filepath='//../04_HASIL_RENDER/preview.png'
s.camera=bpy.data.objects['CAM | STUDIO OVERVIEW']
for obj in s.objects:
    if obj.get('ns_equipment'):obj.visible_camera=True;obj.visible_shadow=True
s.ns_studio.preview_mode='FAST';ns.apply_preview(s)
for text in list(bpy.data.texts):bpy.data.texts.remove(text)
addon=bpy.data.texts.load(str(ROOT/'99_SISTEM/nakas_studio_tools.py'));addon.use_fake_user=True
readme=bpy.data.texts.new('MULAI DI SINI');readme.use_fake_user=True
readme.write('Buka MULAI_STUDIO.cmd dari folder utama.\nPanel Nakas Studio > Pilih file produk atau Muat contoh nakas.\nProduk sumber berada di 02_PRODUK; sesi kerja di 03_PROYEK; render di 04_HASIL_RENDER.\n')
bpy.data.orphans_purge(do_local_ids=True,do_linked_ids=True,do_recursive=True)
assert not list(group.objects) and not list(group.children)
assert not any(o.get('ns_product_root') or o.get('ns_drawer') for o in s.objects)
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'01_STUDIO/Studio_Nakas.blend'))
(ROOT/'02_PRODUK/Nakas/INFORMASI.json').write_text(json.dumps({'id':'nakas_oak_2laci_001','category':'NAKAS','name':'Nakas Oak Natural Dua Laci','dimensions_cm':[50,40,55],'unit':'meter','front':'-Y','ground':'Z=0','textures':'packed','import':'append through studio panel'},indent=2))
print('ASSETS_SEPARATED_OK')
