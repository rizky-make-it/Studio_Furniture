import bpy,sys,importlib.util
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
old=sys.modules.get('nakas_studio_tools')
if old and hasattr(bpy.types.Scene,'ns_studio'):old.unregister()
spec=importlib.util.spec_from_file_location('nakas_studio_tools',ROOT/'99_SISTEM/nakas_studio_tools.py')
ns=importlib.util.module_from_spec(spec);sys.modules[spec.name]=ns;spec.loader.exec_module(ns);ns.register()
s=bpy.context.scene
session='Sesi_Nakas_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')
path=ROOT/'03_PROYEK'/(session+'.blend')
output=ROOT/'04_HASIL_RENDER'/session
output.mkdir(parents=True,exist_ok=True)
s.ns_studio.output='//../04_HASIL_RENDER/'+session+'/'
s.render.filepath=s.ns_studio.output+'preview.png'
s.ns_studio.preview_mode='FAST';ns.apply_preview(s)
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.show_region_ui=True
            area.spaces.active.region_3d.view_perspective='CAMERA'
bpy.ops.wm.save_as_mainfile(filepath=str(path))
def show_panel():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type=='VIEW_3D':
                for region in area.regions:
                    if region.type=='UI':
                        try:region.active_panel_category='Nakas Studio'
                        except (RuntimeError,TypeError,ValueError):pass
    return None
bpy.app.timers.register(show_panel,first_interval=1)
print('SESSION_READY',path)
