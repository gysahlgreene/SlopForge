"""Create Unity animation import settings, controller, and character prefab."""
import json
import subprocess
import uuid
from pathlib import Path

from .animation import _contained_file
from .character_rigging import _character_asset
from .manifest import register_artifact
from .unity_material import unity_cli


_REQUIRED_HUMAN_BONES = {
    "Hips", "Spine", "Head",
    "LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "RightUpperLeg", "RightLowerLeg", "RightFoot",
}


def build_character_animator(project_root, config, manifest, character_selector, *, rig_type="generic"):
    if rig_type not in {"generic", "humanoid"}:
        raise ValueError("Unity rig type must be generic or humanoid")
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    humanoid_mapping = None
    if rig_type == "humanoid":
        humanoid_mapping = character.get("rigging", {}).get("unity_humanoid_mapping")
        if not isinstance(humanoid_mapping, dict):
            raise ValueError("Unity Humanoid bone mapping is required from the selected rigging provider")
        missing = sorted(_REQUIRED_HUMAN_BONES - humanoid_mapping.keys())
        if missing:
            raise ValueError("Unity Humanoid bone mapping is missing: " + ", ".join(missing))
        if (any(not isinstance(name, str) or not name.strip() or not isinstance(bone, str) or not bone.strip()
                for name, bone in humanoid_mapping.items())
                or len(set(humanoid_mapping.values())) != len(humanoid_mapping)):
            raise ValueError("Unity Humanoid bone mapping must use unique, non-empty rig bones")
    artifacts = character.get("artifacts", {})
    rig = artifacts.get("rig")
    if not rig or rig.get("status") != "ready" or rig.get("approval", {}).get("status") != "approved":
        raise ValueError("Unity setup requires a ready, approved character rig")
    rig_path = _contained_file(root, rig.get("path"), "Character rig", {".fbx"})
    clips = []
    for artifact_id, artifact in artifacts.items():
        if not artifact_id.startswith("animation."):
            continue
        if artifact.get("status") != "ready" or artifact.get("approval", {}).get("status") != "approved":
            continue
        clips.append({"id": artifact_id, "path": _contained_file(root, artifact.get("path"),
                      f"Animation {artifact_id}", {".fbx"}).relative_to(root).as_posix(),
                      "loop": bool(artifact.get("provenance", {}).get("loop", False)),
                      "root_motion": bool(artifact.get("provenance", {}).get("root_motion", False))})
    if not clips:
        raise ValueError("Unity setup requires at least one ready, approved retargeted animation")

    output_dir = (root / config["asset_pipeline"]["output_root"] / "Characters" /
                  character["name"] / "Unity").resolve()
    if not output_dir.is_relative_to(root):
        raise ValueError("Unity output directory must stay inside the project")
    controller = output_dir / f"{character['name']}.controller"
    prefab = output_dir / f"{character['name']}.prefab"
    if controller.exists() or prefab.exists():
        raise FileExistsError(f"Unity character outputs already exist: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    class_name = "SlopForgeCharacterAnimator_" + uuid.uuid4().hex
    script = root / "Assets/Editor" / f"{class_name}.cs"
    script.parent.mkdir(parents=True, exist_ok=True)
    rig_asset = rig_path.relative_to(root).as_posix()
    controller_asset = controller.relative_to(root).as_posix()
    prefab_asset = prefab.relative_to(root).as_posix()
    animation_paths = ", ".join(json.dumps(clip["path"]) for clip in clips)
    loop_flags = ", ".join(str(clip["loop"]).lower() for clip in clips)
    root_motion = any(clip["root_motion"] for clip in clips)
    humanoid_description = ""
    humanoid_clip_hierarchy = ""
    if humanoid_mapping is not None:
        human_bones = ",\n            ".join(
            "new HumanBone {{ humanName = {human}, boneName = {bone}, limit = new HumanLimit {{ useDefaultValues = true }} }}".format(
                human=json.dumps(human_name), bone=json.dumps(bone_name))
            for human_name, bone_name in sorted(humanoid_mapping.items()))
        humanoid_description = f"""rigImporter.animationType = ModelImporterAnimationType.Human;
        rigImporter.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
        rigImporter.SaveAndReimport();
        rigImporter = AssetImporter.GetAtPath(rigPath) as ModelImporter;
        if (rigImporter == null) throw new Exception("Character FBX importer not found after skeleton import: " + rigPath);
        var humanDescription = rigImporter.humanDescription;
        humanDescription.human = new HumanBone[] {{
            {human_bones}
        }};
        rigImporter.humanDescription = humanDescription;
        """
        humanoid_clip_hierarchy = "importer.preserveHierarchy = true;"
    script.write_text(f'''using System;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public static class {class_name}
{{
    public static void Build()
    {{
        const string rigPath = {json.dumps(rig_asset)};
        const string controllerPath = {json.dumps(controller_asset)};
        const string prefabPath = {json.dumps(prefab_asset)};
        string[] clipPaths = new string[] {{{animation_paths}}};
        bool[] loopFlags = new bool[] {{{loop_flags}}};
        AssetDatabase.Refresh();
        var rigImporter = AssetImporter.GetAtPath(rigPath) as ModelImporter;
        if (rigImporter == null) throw new Exception("Character FBX importer not found: " + rigPath);
        {humanoid_description}
        rigImporter.animationType = {"ModelImporterAnimationType.Human" if rig_type == "humanoid" else "ModelImporterAnimationType.Generic"};
        rigImporter.avatarSetup = {"ModelImporterAvatarSetup.CreateFromThisModel" if rig_type == "humanoid" else "ModelImporterAvatarSetup.NoAvatar"};
        rigImporter.SaveAndReimport();
        Avatar avatar = null;
        if ({str(rig_type == "humanoid").lower()})
        {{
            avatar = AssetDatabase.LoadAllAssetsAtPath(rigPath).OfType<Avatar>().FirstOrDefault();
            if (avatar == null || !avatar.isValid || !avatar.isHuman)
                throw new Exception("Unity could not create a valid Humanoid Avatar from " + rigPath + ". Review bone mapping or use Generic.");
        }}
        for (int i = 0; i < clipPaths.Length; i++)
        {{
            var importer = AssetImporter.GetAtPath(clipPaths[i]) as ModelImporter;
            if (importer == null) throw new Exception("Animation FBX importer not found: " + clipPaths[i]);
            importer.animationType = {"ModelImporterAnimationType.Human" if rig_type == "humanoid" else "ModelImporterAnimationType.Generic"};
            importer.avatarSetup = {"ModelImporterAvatarSetup.CopyFromOther" if rig_type == "humanoid" else "ModelImporterAvatarSetup.NoAvatar"};
            if ({str(rig_type == "humanoid").lower()}) importer.sourceAvatar = avatar;
            {humanoid_clip_hierarchy}
            var clipSettings = importer.clipAnimations;
            if (clipSettings.Length == 0) clipSettings = importer.defaultClipAnimations;
            for (int j = 0; j < clipSettings.Length; j++) clipSettings[j].loopTime = loopFlags[i];
            importer.clipAnimations = clipSettings;
            importer.SaveAndReimport();
        }}
        var controller = AnimatorController.CreateAnimatorControllerAtPath(controllerPath);
        var machine = controller.layers[0].stateMachine;
        foreach (string clipPath in clipPaths)
        {{
            var motion = AssetDatabase.LoadAllAssetsAtPath(clipPath).OfType<AnimationClip>()
                .FirstOrDefault(clip => !clip.name.StartsWith("__preview__"));
            if (motion == null) throw new Exception("No imported animation clip in " + clipPath);
            machine.AddState(motion.name).motion = motion;
        }}
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(rigPath);
        if (model == null) throw new Exception("Character FBX did not import as a model: " + rigPath);
        var instance = PrefabUtility.InstantiatePrefab(model) as GameObject;
        if (instance == null) throw new Exception("Could not instantiate character model " + rigPath);
        instance.name = model.name;
        var animator = instance.GetComponent<Animator>();
        if (animator == null) animator = instance.AddComponent<Animator>();
        animator.avatar = avatar;
        animator.runtimeAnimatorController = controller;
        animator.applyRootMotion = {str(root_motion).lower()};
        var savedPrefab = PrefabUtility.SaveAsPrefabAsset(instance, prefabPath);
        var savedAnimator = savedPrefab == null ? null : savedPrefab.GetComponent<Animator>();
        if (savedAnimator == null || savedAnimator.runtimeAnimatorController != controller)
            throw new Exception("Unity character prefab is missing its Animator or controller");
        if ({str(rig_type == "humanoid").lower()} &&
            (savedAnimator.avatar == null || !savedAnimator.avatar.isValid || !savedAnimator.avatar.isHuman))
            throw new Exception("Unity character prefab did not retain a valid Humanoid Avatar");
        UnityEngine.Object.DestroyImmediate(instance);
        AssetDatabase.SaveAssets();
        Debug.Log("SLOPFORGE_CHARACTER_ANIMATOR_CREATED " + controllerPath + " " + prefabPath);
    }}
}}
''')
    log_path = root / "Logs" / "SlopForgeAnimation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        try:
            subprocess.run([unity_cli(root), "run", str(root), "--timeout", "600", "--", "-executeMethod",
                            f"{class_name}.Build", "-logFile", str(log_path)], check=True)
        except subprocess.CalledProcessError as exc:
            detail = log_path.read_text(errors="replace")[-5000:] if log_path.is_file() else ""
            raise RuntimeError("Unity character setup failed" + (f":\n{detail}" if detail else "")) from exc
        if not controller.is_file() or not prefab.is_file():
            raise RuntimeError("Unity completed without creating the controller and character prefab")
    except Exception:
        controller.unlink(missing_ok=True)
        prefab.unlink(missing_ok=True)
        raise
    finally:
        script.unlink(missing_ok=True)
        script.with_suffix(".cs.meta").unlink(missing_ok=True)

    provenance = {"provider": "Unity ModelImporter and AnimatorController", "rig_type": rig_type,
                  "source_rig": rig["path"], "animations": [clip["id"] for clip in clips]}
    derived_from = ([{"asset_id": character["id"], "output_id": "rig"}] +
                    [{"asset_id": character["id"], "output_id": clip["id"]} for clip in clips])
    controller_artifact = register_artifact(manifest, character["id"], "unity.animator_controller",
        "unity.animator_controller", controller.relative_to(root).as_posix(), status="candidate",
        derived_from=derived_from, provenance=provenance, approval_status="pending")
    prefab_artifact = register_artifact(manifest, character["id"], "unity.character_prefab", "unity.prefab",
        prefab.relative_to(root).as_posix(), status="candidate", derived_from=derived_from,
        provenance=provenance, approval_status="pending")
    if rig_type == "humanoid":
        character.setdefault("pipeline_status", {})["unity_avatar_status"] = "valid"
    return {"status": "review_required", "controller": controller_artifact, "prefab": prefab_artifact}
