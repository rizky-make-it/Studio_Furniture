import bpy, json
from mathutils import Vector
s = bpy.context.scene
out = {'scene_props': {k: str(s.get(k)) for k in ('studio_version', 'ns_lighting_profile', 'ns_lighting_category', 'ns_ready')}}
rigs = []
for c in bpy.data.collections:
    if c.get('ns_light_shot'):
        lights = []
        for o in c.all_objects:
            if o.type == 'LIGHT':
                d = o.data
                lights.append({'name': o.name, 'role': o.get('ns_role'), 'type': d.type, 'energy': d.energy,
                               'size': [round(getattr(d, 'size', 0), 3), round(getattr(d, 'size_y', 0), 3)], 'shape': getattr(d, 'shape', None),
                               'color': [round(v, 3) for v in d.color], 'loc': [round(v, 3) for v in o.location],
                               'rot': [round(v, 3) for v in o.rotation_euler], 'props': {k: str(o[k]) for k in o.keys()},
                               'parent': o.parent.name if o.parent else None, 'data_users': d.users, 'spread': round(getattr(d, 'spread', 0), 3)})
            else:
                lights.append({'name': o.name, 'type': o.type, 'props': {k: str(o[k]) for k in o.keys()}})
        rigs.append({'coll': c.name, 'shot': c['ns_light_shot'], 'props': {k: str(c[k]) for k in c.keys()}, 'parent_coll': next((p.name for p in bpy.data.collections if c.name in p.children), None), 'objects': lights})
out['rigs'] = rigs
out['cameras'] = [{'name': o.name, 'shot': o.get('ns_shot'), 'loc': [round(v, 3) for v in o.location], 'rot': [round(v, 3) for v in o.rotation_euler], 'lens': o.data.lens} for o in s.objects if o.type == 'CAMERA']
out['equipment'] = [o.name for o in s.objects if o.get('ns_equipment')]
out['exposure'] = s.view_settings.exposure
import pathlib; pathlib.Path(__file__).with_name('inspeksi_lampu.json').write_text(json.dumps(out, indent=1)); print('INSPEKSI_OK')
