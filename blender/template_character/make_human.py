import bpy, sys, json, importlib
args = json.loads(sys.argv[sys.argv.index("--") + 1])
mod = next(m for m in bpy.context.preferences.addons.keys() if m.endswith("mpfb"))
HumanService = importlib.import_module(mod + ".services.humanservice").HumanService
TargetService = importlib.import_module(mod + ".services.targetservice").TargetService
user = args["userdata"]
bpy.ops.wm.read_factory_settings(use_empty=True)
macro = TargetService.get_default_macro_info_dict()
macro.update(args["macro"])
basemesh = HumanService.create_human(scale=0.1, macro_detail_dict=macro, feet_on_ground=True)
import os
targets_root = os.path.join(os.path.dirname(importlib.import_module(mod).__file__), "data", "targets")
for name, weight in args.get("targets", {}).items():
    TargetService.load_target(basemesh, f"{targets_root}/{name}.target.gz", weight=weight)
# The rig must exist before assets are added, or MPFB gives them no bone weights.
HumanService.add_builtin_rig(basemesh, "game_engine")
for kind, path in args["assets"]:
    HumanService.add_mhclo_asset(f"{user}/{path}", basemesh, asset_type=kind, subdiv_levels=0)
HumanService.set_character_skin(f"{user}/{args['skin']}", basemesh, skin_type="GAMEENGINE")
print("HUMAN", basemesh.name, len(basemesh.data.vertices), [o.name for o in bpy.data.objects])
bpy.ops.wm.save_as_mainfile(filepath=args["output"])
