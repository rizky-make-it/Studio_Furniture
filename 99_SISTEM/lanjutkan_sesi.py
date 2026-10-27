import bpy,sys,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
old=sys.modules.get('nakas_studio_tools')
if old and hasattr(bpy.types.Scene,'ns_studio'):old.unregister()
spec=importlib.util.spec_from_file_location('nakas_studio_tools',ROOT/'99_SISTEM/nakas_studio_tools.py')
ns=importlib.util.module_from_spec(spec);sys.modules[spec.name]=ns;spec.loader.exec_module(ns);ns.register()
bpy.context.scene.ns_studio.preview_mode='FAST'
ns.apply_preview(bpy.context.scene)
def panel():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.show_region_ui=True
                for region in area.regions:
                    if region.type=='UI':
                        try:region.active_panel_category='Nakas Studio'
                        except (RuntimeError,TypeError,ValueError):pass
    return None
bpy.app.timers.register(panel,first_interval=1)
