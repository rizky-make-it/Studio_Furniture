import bpy,json
from pathlib import Path
from mathutils import Vector
BASE=Path(__file__).resolve().parent
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
bpy.ops.wm.stl_import(filepath=str(BASE/'all_parts.stl'))
obj=bpy.context.object
bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.mesh.separate(type='LOOSE');bpy.ops.object.mode_set(mode='OBJECT')
parts=[]
for i,o in enumerate(list(bpy.context.selected_objects)):
    o.name=f'CAD Part {i:02}'
    pts=[o.matrix_world@v.co for v in o.data.vertices]
    lo=[min(v[a] for v in pts) for a in range(3)];hi=[max(v[a] for v in pts) for a in range(3)]
    parts.append({'name':o.name,'lo':lo,'hi':hi,'size':[hi[a]-lo[a] for a in range(3)],'triangles':len(o.data.polygons)})
(BASE/'parts_bounds.json').write_text(json.dumps(parts,indent=2))
print(json.dumps(parts))
bpy.ops.wm.save_as_mainfile(filepath=str(BASE/'CAD_import.blend'))
