import bpy,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];ASSET=ROOT/'02_PRODUK/Nakas/Doheny_B_Tan_Mindi';OUT=ROOT/'04_HASIL_RENDER/Doheny_B_Tan_Mindi'
sys.path.insert(0,str(ROOT/'99_SISTEM'))
import nakas_studio_tools as ns
ns.register()
s=bpy.context.scene
wood=bpy.data.materials['B TAN MINDI | Asli PDF halaman 2'];n,l=wood.node_tree.nodes,wood.node_tree.links
bsdf=n.get('Principled BSDF');tex=next(node for node in n if node.type=='TEX_IMAGE')
finish=n.new('ShaderNodeMixRGB');finish.name='B Tan | Satin stain calibration';finish.blend_type='MULTIPLY';finish.inputs[0].default_value=1;finish.inputs[2].default_value=(.65,.62,.58,1)
l.new(tex.outputs['Color'],finish.inputs[1]);l.new(finish.outputs[0],bsdf.inputs['Base Color'])
for obj in s.objects:
    if obj.name.startswith('Back / recessed fixing'):obj.location.y=.224
lo,hi=ns.product_bounds(s);ns.root_for(s)['dimensions_cm']=[round(float(v)*100,3) for v in hi-lo]
bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=str(ASSET/'Doheny_B_Tan_Mindi.blend'))
meta=json.loads((ASSET/'INFORMASI.json').read_text());meta['dimensions_cm']=list(ns.root_for(s)['dimensions_cm']);meta['finish_note']='Original PDF color image with adjustable satin stain calibration; roughness and bump are approximations, not scanned maps.';(ASSET/'INFORMASI.json').write_text(json.dumps(meta,indent=2))
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'01_STUDIO/Studio_Nakas.blend'))
s=bpy.context.scene;bpy.ops.ns.import_product(filepath=str(ASSET/'Doheny_B_Tan_Mindi.blend'))
s.ns_studio.output='//../04_HASIL_RENDER/Doheny_B_Tan_Mindi/'
ns.select_shot(s,'HERO');s.ns_studio.shot='HERO'
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'03_PROYEK/Doheny_B_Tan_Mindi_Studio.blend'))
s.render.resolution_x=s.render.resolution_y=700;s.cycles.samples=32
s.render.filepath=str(OUT/'hero_finish_check.png');bpy.ops.render.render(write_still=True)
print('FINISH_CALIBRATED')
