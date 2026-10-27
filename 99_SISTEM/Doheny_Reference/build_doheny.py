import bpy,bmesh,math,sys,json
from pathlib import Path
from mathutils import Vector
REF=Path(__file__).resolve().parent;ROOT=REF.parents[1]
ASSET=ROOT/'02_PRODUK/Nakas/Doheny_B_Tan_Mindi';OUT=ROOT/'04_HASIL_RENDER/Doheny_B_Tan_Mindi'
OUT.mkdir(exist_ok=True,parents=True)
sys.path.insert(0,str(ROOT/'99_SISTEM'))
import nakas_studio_tools as ns
ns.register()
s=bpy.context.scene
for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
for coll in list(bpy.data.collections):bpy.data.collections.remove(coll)
s.name='PRODUK | Doheny · B Tan Mindi'
s.unit_settings.system='METRIC';s.unit_settings.scale_length=1;s.unit_settings.length_unit='CENTIMETERS'
coll=bpy.data.collections.new('PROD | Doheny B Tan Mindi');s.collection.children.link(coll);coll['ns_product']=True;coll['category']='NAKAS'
root=bpy.data.objects.new('PRODUCT_ROOT | Doheny',None);coll.objects.link(root);root['ns_product_root']=True
root['source']='doheny side table 1.dwg';root['unit_assumption']='CAD numerical dimensions interpreted as millimetres; DWG INSUNITS says inches'
s.ns_studio.product=coll
def mat(name,color,rough=.5,metal=0):
    m=bpy.data.materials.new(name);m.use_nodes=True;m.diffuse_color=(*color,1)
    b=m.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(*color,1);b.inputs['Roughness'].default_value=rough;b.inputs['Metallic'].default_value=metal
    return m
wood=mat('B TAN MINDI | Asli PDF halaman 2',(.43,.30,.19),.46)
n,l=wood.node_tree.nodes,wood.node_tree.links;b=n.get('Principled BSDF')
tex=n.new('ShaderNodeTexImage');tex.image=bpy.data.images.load(str(ASSET/'Tekstur/B_Tan_Mindi_Asli.png'));tex.interpolation='Linear';tex.extension='EXTEND';tex.label='ZUMA GROUP / B TAN-MINDY / original embedded image 753 x 1130'
l.new(tex.outputs['Color'],b.inputs['Base Color'])
b.inputs['IOR'].default_value=1.47;b.inputs['Coat Weight'].default_value=.10;b.inputs['Coat Roughness'].default_value=.40
bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.00013
l.new(tex.outputs['Color'],bump.inputs['Height']);l.new(bump.outputs['Normal'],b.inputs['Normal'])
r=n.new('ShaderNodeMapRange');r.inputs['To Min'].default_value=.40;r.inputs['To Max'].default_value=.51;l.new(tex.outputs['Color'],r.inputs['Value']);l.new(r.outputs['Result'],b.inputs['Roughness'])
bronze=mat('Handle | Aged satin bronze',(.25,.18,.095),.33,.85)
n,l=bronze.node_tree.nodes,bronze.node_tree.links;b=n.get('Principled BSDF');noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=90
rough=n.new('ShaderNodeMapRange');rough.inputs['To Min'].default_value=.27;rough.inputs['To Max'].default_value=.43;l.new(noise.outputs['Fac'],rough.inputs['Value']);l.new(rough.outputs['Result'],b.inputs['Roughness'])
steel=mat('Hardware | Zinc coated steel',(.42,.44,.46),.30,.82)
dark=mat('Hardware | Dark slide channel',(.035,.04,.045),.42,.7)
felt=mat('Underside | Felt glides',(.055,.045,.032),.94)
def bevel(o,width=.0005):
    mod=o.modifiers.new('Small edge rounding / real highlights','BEVEL');mod.width=width;mod.segments=3;mod.limit_method='ANGLE';mod.angle_limit=math.radians(42);mod.harden_normals=True
    mod=o.modifiers.new('Weighted normals','WEIGHTED_NORMAL');mod.keep_sharp=True;mod.weight=40
    for p in o.data.polygons:p.use_smooth=True
def uvmap(o,grain='V',seed=0):
    uv=o.data.uv_layers.new(name='Mindi board grain')
    coords=[v.co for v in o.data.vertices]
    mn=Vector([min(v[i] for v in coords) for i in range(3)]);mx=Vector([max(v[i] for v in coords) for i in range(3)]);center=(mn+mx)/2
    offsetu=.50+(.06 if seed%2 else -.06);offsetv=.50+(seed%3-1)*.04
    for p in o.data.polygons:
        norm=p.normal
        for ix in p.loop_indices:
            v=o.data.vertices[o.data.loops[ix].vertex_index].co-center
            if abs(norm.z)>.65: a,c=(v.y,v.x) if grain=='H' else (v.x,v.y)
            elif abs(norm.y)>.65:a,c=(v.z,v.x) if grain=='H' else (v.x,v.z)
            else:a,c=(v.z,v.y) if grain=='H' else (v.y,v.z)
            uv.data[ix].uv=(a/.58+offsetu,c/.76+offsetv)
def cube(name,size,loc,material=wood,parent=root,radius=.0006,grain='H',seed=0):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    for c in list(o.users_collection):c.objects.unlink(o)
    coll.objects.link(o);o.parent=parent;o.data.materials.append(material);uvmap(o,grain,seed);bevel(o,radius);return o
names={0:'Drawer / front from CAD',1:'Carcass / recessed curved base from CAD',2:'Handle / curved bronze pull from CAD',3:'Carcass / rounded top from CAD',4:'Carcass / open shelf from CAD',5:'Carcass / right rounded front stile from CAD',6:'Carcass / rear panel from CAD',7:'Carcass / right side from CAD',8:'Carcass / left side from CAD',9:'Carcass / left rounded front stile from CAD'}
drawer=bpy.data.objects.new('DRAWER_1 | Doheny',None);coll.objects.link(drawer);drawer.parent=root;drawer['ns_drawer']=1;drawer['Open (m)']=0.0;drawer.id_properties_ui('Open (m)').update(min=0,max=.24,soft_min=0,soft_max=.24)
d=drawer.driver_add('location',1).driver;d.type='SCRIPTED';v=d.variables.new();v.name='opening';v.type='SINGLE_PROP';v.targets[0].id=drawer;v.targets[0].data_path='["Open (m)"]';d.expression='-opening'
for i in range(10):
    bpy.ops.wm.stl_import(filepath=str(REF/f'solid_{i}.stl'));o=bpy.context.object;o.name=names[i]
    # AutoCAD STL uses Y as vertical and +Z as front. Convert to studio Z-up, front -Y.
    for v in o.data.vertices:
        x,y,z=v.co;v.co=((x-234.1198403)/1000,-(z-310.852665)/1000,(y-307.0164185)/1000)
    bm=bmesh.new();bm.from_mesh(o.data);bmesh.ops.remove_doubles(bm,verts=bm.verts,dist=.000001)
    bmesh.ops.dissolve_limit(bm,angle_limit=.001,verts=bm.verts,edges=bm.edges,delimit={'NORMAL'})
    bmesh.ops.recalc_face_normals(bm,faces=bm.faces)
    bm.to_mesh(o.data);bm.free();o.data.update()
    for c in list(o.users_collection):c.objects.unlink(o)
    coll.objects.link(o);o.parent=drawer if i in [0,2] else root
    o['cad_part']=i;o['geometry_source']='DWG solid, tessellated by AutoCAD FACETRES=10'
    if i==0:
        # A 2 mm reveal on each side keeps the moving front clear of the stiles.
        for v in o.data.vertices:v.co.x*=346/350
    o.data.materials.clear();o.data.materials.append(bronze if i==2 else wood)
    uvmap(o,'H' if i in [0,1,3,4] else 'V',i);bevel(o,.00035 if i==2 else .0005)
# Drawer interior / mechanical construction not provided by the CAD solids.
z0=.32296
cube('Drawer / inset bottom 7 mm',(.302,.358,.007),(0,-.012,z0+.006),parent=drawer,radius=.0004,seed=1)
for sign in [-1,1]:
    cube('Drawer / solid side 12 mm',(.012,.37,.080),(sign*.157,-.012,z0+.047),parent=drawer,grain='H',seed=3 if sign<0 else 4)
    cube('Slide / cabinet spacer',(.029,.350,.06),(sign*.185,-.005,z0+.043),seed=2)
    cube('Slide / fixed channel',(.0025,.338,.027),(sign*.1705,-.014,z0+.045),steel,radius=.0003)
    cube('Slide / telescoping rail',(.0025,.330,.022),(sign*.166,-.017,z0+.045),steel,parent=drawer,radius=.0003)
    for dz in [-.010,.010]:cube('Slide / folded edge',(.002,.33,.0025),(sign*.164,-.017,z0+.045+dz),dark,parent=drawer,radius=.0003)
    for yy in [-.14,.0,.13]:
        bpy.ops.mesh.primitive_cylinder_add(vertices=24,radius=.0026,depth=.0015,location=(sign*.1635,yy,z0+.045),rotation=(0,math.pi/2,0))
        o=bpy.context.object;o.name='Slide / screw head'
        for c in list(o.users_collection):c.objects.unlink(o)
        coll.objects.link(o);o.parent=drawer;o.data.materials.append(steel);bevel(o,.0002)
    for yy in [-.192,.169]:
        for k in range(4):cube('Joinery / end-grain key',(.0005,.007,.009),(sign*.1632,yy,z0+.019+k*.017),wood,parent=drawer,radius=.00015,grain='V',seed=k)
cube('Drawer / inner front',(.302,.012,.08),(0,-.191,z0+.047),parent=drawer,seed=2)
cube('Drawer / rear',(.302,.012,.08),(0,.167,z0+.047),parent=drawer,seed=4)
for x in [-.17,.17]:
    for y in [-.16,.16]:
        # Pads contained within the CAD base envelope to preserve CAD overall height.
        cube('Base / inset felt pad',(.022,.022,.001),(x,y,.001),felt,radius=.001)
for x in [-.13,.13]:
    for z in [.10,.36]:
        bpy.ops.mesh.primitive_cylinder_add(vertices=24,radius=.0025,depth=.001,location=(x,.2255,z),rotation=(math.pi/2,0,0))
        o=bpy.context.object;o.name='Back / recessed fixing'
        for c in list(o.users_collection):c.objects.unlink(o)
        coll.objects.link(o);o.parent=root;o.data.materials.append(dark)
bpy.context.view_layer.update()
lo,hi=ns.product_bounds(s)
root['dimensions_cm']=[round(float(x)*100,3) for x in hi-lo]
s['asset_id']='doheny_side_table_b_tan_mindi';s['category']='NAKAS';s['unit_note']=root['unit_assumption']
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            space=area.spaces.active;space.shading.type='MATERIAL';space.shading.use_scene_lights=False;space.shading.use_scene_world=False;space.region_3d.view_location=(0,0,.23);space.region_3d.view_distance=1.2
            space.region_3d.view_rotation=Vector((1,-1.5,.8)).to_track_quat('Z','Y')
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(ASSET/'Doheny_B_Tan_Mindi.blend'))
metadata={'name':'Doheny Side Table — B Tan Mindi','category':'NAKAS','source_geometry':'doheny side table 1.dwg','source_finish':'ZUMA GROUP.pdf, page 2, B TAN-MINDY','texture_native_pixels':[753,1130],'dimensions_cm':list(root['dimensions_cm']),'unit_assumption':root['unit_assumption'],'cad_parts':10,'added_details':'Drawer box, sliders, fasteners, small edge rounding, inset felt pads','drawer_travel_m':.24,'front':'-Y','textures':'packed'}
(ASSET/'INFORMASI.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
# Use the existing studio, retaining the product as a separate library file.
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'01_STUDIO/Studio_Nakas.blend'))
s=bpy.context.scene
assert bpy.ops.ns.import_product(filepath=str(ASSET/'Doheny_B_Tan_Mindi.blend'))=={'FINISHED'}
s.ns_studio.output='//../04_HASIL_RENDER/Doheny_B_Tan_Mindi/'
ns.select_shot(s,'HERO');s.ns_studio.shot='HERO'
s.render.filepath=s.ns_studio.output+'hero.png'
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'03_PROYEK/Doheny_B_Tan_Mindi_Studio.blend'))
s.render.resolution_x=s.render.resolution_y=700;s.cycles.samples=32;s.cycles.adaptive_threshold=.04
s.render.filepath=str(OUT/'hero_draft.png');bpy.ops.render.render(write_still=True)
ns.select_shot(s,'FRONT');s.render.filepath=str(OUT/'front_draft.png');bpy.ops.render.render(write_still=True)
print('DOHENY_BUILT',metadata)
