"""Gear on a Humanoid character in Unity: a shared clip library, and a pack and weapon mounted as a prefab."""
import json
import shutil
import subprocess
import uuid
from pathlib import Path

from .unity_material import unity_cli

LIBRARY_FOLDER = "Assets/Art/Animation/UniversalAnimationLibrary"


def _run(root, name, body, log):
    """One temporary Editor script, removed afterwards whatever happens."""
    class_name = f"{name}_{uuid.uuid4().hex}"
    script = root / "Assets/Editor" / f"{class_name}.cs"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("using System; using System.Linq; using UnityEditor; using UnityEngine; using UnityEngine.Playables; "
                      "using UnityEngine.Animations;\npublic static class " + class_name + " {\n" + body + "\n}\n")
    try:
        subprocess.run([unity_cli(root), "run", str(root), "--timeout", "900", "--", "-executeMethod", f"{class_name}.Run",
                        "-logFile", str(log)], check=True)
    finally:
        script.unlink(missing_ok=True)
        script.with_suffix(".cs.meta").unlink(missing_ok=True)


def open_skin_script(prefab, material):
    """The Editor script. A generated body with its hidden faces gone is one open skin. Unity's default shadows on it printed jagged
    black marks on a back that had none with shadows off, so both sides shade and cast."""
    return f"""public static void Run() {{
    var material = AssetDatabase.LoadAssetAtPath<Material>({json.dumps(material)});
    if (material == null) throw new Exception("No material at " + {json.dumps(material)});
    material.SetFloat("_Cull", 0f);
    EditorUtility.SetDirty(material);
    var root = PrefabUtility.LoadPrefabContents({json.dumps(prefab)});
    foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
        renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.TwoSided;
    PrefabUtility.SaveAsPrefabAsset(root, {json.dumps(prefab)});
    PrefabUtility.UnloadPrefabContents(root);
    AssetDatabase.SaveAssets();
    Debug.Log("SavePrefabAsset done");
}}"""


def open_skin(root, prefab, material):
    root = Path(root).resolve()
    _run(root, "OpenSkin", open_skin_script(prefab, material), root / "Logs/SlopForgeOpenSkin.log")


def library_script(library):
    return f"""public static void Run() {{
    var importer = (ModelImporter)AssetImporter.GetAtPath({json.dumps(library)});
    importer.bakeAxisConversion = true;
    importer.animationType = ModelImporterAnimationType.Human;
    importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
    importer.SaveAndReimport();
    importer = (ModelImporter)AssetImporter.GetAtPath({json.dumps(library)});
    var clips = importer.defaultClipAnimations;
    foreach (var clip in clips) {{
        clip.loopTime = clip.name.EndsWith("_Loop");
        clip.lockRootHeightY = clip.lockRootRotation = clip.lockRootPositionXZ = true;
        clip.keepOriginalPositionY = clip.keepOriginalOrientation = clip.keepOriginalPositionXZ = true;
    }}
    importer.clipAnimations = clips;
    importer.SaveAndReimport();
    var avatar = AssetDatabase.LoadAllAssetsAtPath({json.dumps(library)}).OfType<Avatar>().FirstOrDefault();
    if (avatar == null || !avatar.isValid || !avatar.isHuman) throw new Exception("The clip library has no valid Humanoid Avatar");
}}"""


def import_clip_library(root, fbx, licence):
    """The library's FBX in the project as Humanoid clips, with _Loop clips looping and the root staying put, so one set
    of clips plays on every character through Unity's retargeting. Does nothing if it's already there."""
    root = Path(root).resolve()
    folder = root / LIBRARY_FOLDER
    target = folder / Path(fbx).name
    if target.exists():
        return target
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(fbx, target)
    shutil.copy(licence, folder)
    _run(root, "ClipLibrary", library_script(target.relative_to(root).as_posix()), root / "Logs/SlopForgeClipLibrary.log")
    return target


def leg_swing_script(fbx, library, idle_clip, thigh, knee, arm_drop=1.0, level_head=False):
    """The Editor script. It clears the Avatar's limits, reads her stance from the idle clip, then scales the range of each
    leg's swing round that stance and sets the centre that keeps it, so she stands as before and steps smaller. `arm_drop`
    scales how far the arms can lower on every clip. Scaling the range works where offsetting the centre did nothing.
    `level_head` retunes the neck's and head's nod so the idle faces straight ahead: Unity straightens a neck by how its bones
    lean at rest, so one clip faced one figure 14 degrees down, in shadow, and another 20 up."""
    level = """
        if (name == "Neck" || name == "Head") {
            int bone = Array.IndexOf(HumanTrait.BoneName, name);
            var limit = Narrow(name, 1f, stance);
            for (int axis = 0; axis < 3; axis++) {
                int muscle = HumanTrait.MuscleFromBone(bone, axis);
                if (muscle < 0 || !HumanTrait.MuscleName[muscle].Contains("Nod Down-Up") || Mathf.Abs(stance[muscle]) < 0.02f) continue;
                // The neck takes most of the lift, so the head keeps some nod of its own in other clips.
                bool high = stance[muscle] >= 0;
                float range = high ? limit.max[axis] : -limit.min[axis];
                float lift = -pitch * (name == "Neck" ? 0.7f : 0.3f);
                float tuned = Mathf.Clamp(range + lift / stance[muscle], range * 0.25f, range * 2.5f);
                if (high) { var top = limit.max; top[axis] = tuned; limit.max = top; }
                else { var low = limit.min; low[axis] = -tuned; limit.min = low; }
            }
            bones[i].limit = limit;
        }""" if level_head else ""
    return f"""static HumanLimit Narrow(string bone, float scale, float[] stance) {{
    int index = Array.IndexOf(HumanTrait.BoneName, bone);
    Vector3 low = Vector3.zero, high = Vector3.zero, centre = Vector3.zero;
    for (int axis = 0; axis < 3; axis++) {{
        int muscle = HumanTrait.MuscleFromBone(index, axis);
        if (muscle < 0) continue;
        float min = HumanTrait.GetMuscleDefaultMin(muscle), max = HumanTrait.GetMuscleDefaultMax(muscle);
        string name = HumanTrait.MuscleName[muscle];
        float k = name.Contains("Front-Back") || name.Contains("Stretch") || name.Contains("Up-Down") ? scale : 1f;
        low[axis] = min * k;
        high[axis] = max * k;
        centre[axis] = (1f - k) * stance[muscle] * (stance[muscle] >= 0 ? max : min);
    }}
    return new HumanLimit {{ useDefaultValues = false, min = low, max = high, center = centre }};
}}
public static void Run() {{
    var importer = (ModelImporter)AssetImporter.GetAtPath({json.dumps(fbx)});
    var description = importer.humanDescription;
    var bones = description.human;
    for (int i = 0; i < bones.Length; i++) bones[i].limit = new HumanLimit {{ useDefaultValues = true }};
    description.human = bones;
    importer.humanDescription = description;
    importer.SaveAndReimport();
    importer = (ModelImporter)AssetImporter.GetAtPath({json.dumps(fbx)});
    description = importer.humanDescription;
    var body = (GameObject)UnityEngine.Object.Instantiate(AssetDatabase.LoadAssetAtPath<GameObject>({json.dumps(fbx)}));
    var animator = body.GetComponent<Animator>();
    animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;  // off screen it writes no transforms, and the pose read back is the rest pose
    var head = animator.GetBoneTransform(HumanBodyBones.Head);
    var headRest = head.rotation;
    var idle = AssetDatabase.LoadAllAssetsAtPath({json.dumps(library)}).OfType<AnimationClip>().First(c => c.name.EndsWith("|{idle_clip}"));
    var graph = PlayableGraph.Create();
    graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
    var clip = AnimationClipPlayable.Create(graph, idle);
    clip.SetApplyFootIK(false);
    AnimationPlayableOutput.Create(graph, "pose", animator).SetSourcePlayable(clip);
    graph.Play();
    graph.Evaluate(.01f);
    var handler = new HumanPoseHandler(animator.avatar, body.transform);
    var pose = new HumanPose();
    float[] stance = null;
    float pitch = 0f;
    for (int step = 0; step < 8; step++) {{
        clip.SetTime(idle.length * step / 8f);
        graph.Evaluate(0f);
        handler.GetHumanPose(ref pose);
        pitch += Mathf.Asin(Mathf.Clamp((head.rotation * Quaternion.Inverse(headRest) * body.transform.forward).y, -1f, 1f)) * Mathf.Rad2Deg / 8f;
        stance ??= new float[pose.muscles.Length];
        for (int muscle = 0; muscle < stance.Length; muscle++) stance[muscle] += pose.muscles[muscle] / 8f;
    }}
    handler.Dispose();
    graph.Destroy();
    UnityEngine.Object.DestroyImmediate(body);
    bones = description.human;
    for (int i = 0; i < bones.Length; i++) {{
        string name = bones[i].humanName;
        float scale = name.EndsWith("UpperLeg") || name.EndsWith("Foot") ? {thigh}f : name.EndsWith("LowerLeg") ? {knee}f : 1f;
        if (scale < 1f) bones[i].limit = Narrow(HumanTrait.BoneName.First(b => b.Replace(" ", "") == name), scale, stance);
        if ({arm_drop}f != 1f && name.EndsWith("UpperArm")) {{
            var bone = Array.IndexOf(HumanTrait.BoneName, HumanTrait.BoneName.First(b => b.Replace(" ", "") == name));
            var limit = Narrow(HumanTrait.BoneName[bone], 1f, stance);
            for (int axis = 0; axis < 3; axis++) {{
                int muscle = HumanTrait.MuscleFromBone(bone, axis);
                if (muscle >= 0 && HumanTrait.MuscleName[muscle].Contains("Down-Up")) {{
                    var low = limit.min;
                    low[axis] *= {arm_drop}f;
                    limit.min = low;
                }}
            }}
            bones[i].limit = limit;
        }}{level}
    }}
    Debug.Log("HEAD facing " + pitch.ToString("F1") + " degrees up in the idle before tuning");
    description.human = bones;
    importer.humanDescription = description;
    importer.SaveAndReimport();
    var avatar = AssetDatabase.LoadAllAssetsAtPath({json.dumps(fbx)}).OfType<Avatar>().FirstOrDefault();
    if (avatar == null || !avatar.isValid || !avatar.isHuman) throw new Exception("Narrowing the legs broke the Humanoid Avatar");
}}"""


def narrow_leg_swing(root, fbx, library, thigh, knee, idle_clip="Idle_Loop", arm_drop=1.0, level_head=False):
    """Smaller steps for a long skirt or a heavy body, on every clip at once, through the character's Avatar. Clips made for
    trousers stride about a metre, far past a skirt that moves as a tube, and a boot then floats free of the hem. `thigh`
    scales the hip and ankle, `knee` the knee. `arm_drop` keeps a wide body's arms clear of it: the clips drop them straight
    down, through the torso. An Animator state must keep Foot IK off, its default, or the clip's foot goals undo this."""
    root = Path(root).resolve()
    _run(root, "LegSwing", leg_swing_script(fbx, library, idle_clip, thigh, knee, arm_drop, level_head), root / "Logs/SlopForgeLegSwing.log")


def equip_script(character, pack, weapon, library, hold_clip, pack_scale, pack_height):
    """The Editor script. The pack's flat rear goes against the coat, measured in the bind pose. The weapon's grip, its
    lowest fifth, goes in the palm in the hold clip's pose, with the barrel along the forearm and its top up. Both are
    children of a bone, so every clip carries them. The gear is rigid: colliders and bodies are stripped from it."""
    folder = str(Path(character).parent.as_posix())
    name = Path(character).stem
    return f"""static GameObject Gear(string path, string name) {{
    var asset = AssetDatabase.LoadAssetAtPath<GameObject>(path);
    if (asset == null) throw new Exception("Missing gear: " + path);
    var gear = (GameObject)PrefabUtility.InstantiatePrefab(asset);
    PrefabUtility.UnpackPrefabInstance(gear, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
    gear.name = name;
    foreach (var item in gear.GetComponentsInChildren<Rigidbody>()) UnityEngine.Object.DestroyImmediate(item);
    foreach (var item in gear.GetComponentsInChildren<Collider>()) UnityEngine.Object.DestroyImmediate(item);
    foreach (var item in gear.GetComponentsInChildren<Animator>()) UnityEngine.Object.DestroyImmediate(item);
    return gear;
}}
public static void Run() {{
    UnityEditor.SceneManagement.EditorSceneManager.NewScene(UnityEditor.SceneManagement.NewSceneSetup.DefaultGameObjects, UnityEditor.SceneManagement.NewSceneMode.Single);
    var body = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>({json.dumps(character)}));
    PrefabUtility.UnpackPrefabInstance(body, PrefabUnpackMode.OutermostRoot, InteractionMode.AutomatedAction);
    body.name = {json.dumps(name + "_equipped")};
    var animator = body.GetComponent<Animator>();
    animator.applyRootMotion = false;
    var skin = body.GetComponentInChildren<SkinnedMeshRenderer>();
    float top = skin.bounds.max.y;
    float back = float.MaxValue;
    foreach (var vertex in skin.sharedMesh.vertices) {{
        var point = skin.transform.TransformPoint(vertex);
        if (Mathf.Abs(point.x) < .07f * top && point.y > .6f * top && point.y < .77f * top && point.z < back) back = point.z;
    }}
    var pack = Gear({json.dumps(pack)}, "Pack");
    pack.transform.localScale *= {pack_scale}f;
    pack.transform.rotation = Quaternion.Euler(0, 180, 0) * pack.transform.rotation;
    var bounds = pack.GetComponentsInChildren<Renderer>().Select(r => r.bounds).Aggregate((a, b) => {{ a.Encapsulate(b); return a; }});
    pack.transform.position += new Vector3(-bounds.center.x, {pack_height}f * top - bounds.center.y, back + .015f - bounds.max.z);
    pack.transform.SetParent(animator.GetBoneTransform(HumanBodyBones.Chest), true);

    var hand = animator.GetBoneTransform(HumanBodyBones.RightHand);
    var forearm = animator.GetBoneTransform(HumanBodyBones.RightLowerArm);
    var hold = AssetDatabase.LoadAllAssetsAtPath({json.dumps(library)}).OfType<AnimationClip>().First(c => c.name.EndsWith("|{hold_clip}"));
    var graph = PlayableGraph.Create();
    graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
    AnimationPlayableOutput.Create(graph, "pose", animator).SetSourcePlayable(AnimationClipPlayable.Create(graph, hold));
    graph.Play();
    graph.Evaluate(0f);
    var weapon = Gear({json.dumps(weapon)}, "Weapon");
    weapon.transform.position = Vector3.zero;
    var points = weapon.GetComponentsInChildren<MeshFilter>().SelectMany(f => f.sharedMesh.vertices.Select(v => f.transform.TransformPoint(v))).ToArray();
    var box = new Bounds(points[0], Vector3.zero);
    foreach (var point in points) box.Encapsulate(point);
    var low = points.Where(p => p.y < box.min.y + box.size.y * .22f).ToArray();
    var grip = new Vector3(low.Average(p => p.x), low.Average(p => p.y), low.Average(p => p.z));
    bool alongX = box.size.x > box.size.z;
    var muzzle = (alongX ? Vector3.right : Vector3.forward) * Mathf.Sign(alongX ? box.center.x - grip.x : box.center.z - grip.z);
    var gripLocal = weapon.transform.InverseTransformPoint(grip + Vector3.up * box.size.y * .13f);
    var along = (hand.position - forearm.position).normalized;
    var up = Vector3.ProjectOnPlane(Vector3.up, along).normalized;
    weapon.transform.rotation = Quaternion.LookRotation(along, up) * Quaternion.Inverse(Quaternion.LookRotation(muzzle, Vector3.up)) * weapon.transform.rotation;
    weapon.transform.position += hand.position + along * .055f - up * .015f - weapon.transform.TransformPoint(gripLocal);
    weapon.transform.SetParent(hand, true);
    graph.Destroy();
    if (PrefabUtility.SaveAsPrefabAsset(body, {json.dumps(folder + "/" + name + "_equipped.prefab")}) == null) throw new Exception("Could not save the equipped prefab");
}}"""


ARM_SOLVER = """// The middle of the closed fist in the hand's own space, from the vertices the hand mostly moves. The wrist is about 10 cm short of it.
// The torso's front and back as seen from straight ahead, in a frame that follows the chest, so an arm can be tested against it. Cells are 3 cm.
class Torso {
    public const float Cell = 0.03f;
    public readonly System.Collections.Generic.Dictionary<(int, int), Vector2> Span = new();
    public static (int, int) Key(Vector3 point) => (Mathf.FloorToInt(point.x / Cell), Mathf.FloorToInt(point.y / Cell));
    public void Add(Vector3 point) {
        var key = Key(point);
        Span[key] = Span.TryGetValue(key, out var old) ? new Vector2(Mathf.Min(old.x, point.z), Mathf.Max(old.y, point.z)) : new Vector2(point.z, point.z);
    }
    public float Inside(Vector3 point) => Span.TryGetValue(Key(point), out var span) && point.z > span.x ? Mathf.Max(0f, span.y - point.z) : 0f;
    public float FrontAt(Vector3 point, float around) {
        float front = float.NegativeInfinity;
        int reach = Mathf.CeilToInt(around / Cell);
        var key = Key(point);
        for (int x = -reach; x <= reach; x++)
            for (int y = -reach; y <= reach; y++)
                if (Span.TryGetValue((key.Item1 + x, key.Item2 + y), out var span)) front = Mathf.Max(front, span.y);
        return front;
    }
}
static Torso BuildTorso(SkinnedMeshRenderer skin, System.Collections.Generic.HashSet<Transform> arms, Mesh baked, Vector3 origin, Quaternion frame) {
    skin.BakeMesh(baked, true);
    var torso = new Torso();
    var vertices = baked.vertices;
    var weights = skin.sharedMesh.boneWeights;
    var bones = skin.bones;
    var back = Quaternion.Inverse(frame);
    for (int i = 0; i < vertices.Length; i++)
        if (!arms.Contains(bones[weights[i].boneIndex0]))
            torso.Add(back * (skin.transform.TransformPoint(vertices[i]) - origin));
    return torso;
}
static Vector3 FistCentre(SkinnedMeshRenderer skin, Transform hand) {
    int bone = Array.IndexOf(skin.bones, hand);
    var mesh = skin.sharedMesh;
    var vertices = mesh.vertices;
    var weights = mesh.boneWeights;
    Vector3 total = Vector3.zero;
    int count = 0;
    for (int i = 0; i < vertices.Length; i++) {
        if (weights[i].boneIndex0 != bone || weights[i].weight0 < 0.5f) continue;
        total += hand.InverseTransformPoint(skin.transform.TransformPoint(vertices[i]));
        count++;
    }
    if (count == 0) throw new Exception("No vertices follow " + hand.name);
    return total / count;
}
static void Solve(Transform upper, Transform lower, Transform hand, Vector3 fist, Vector3 grip, Vector3 pole, Vector3 thumb, Vector3 line, Quaternion bindHand, Vector3 bindForearm) {
    // The fist's offset depends on the arm's angle and the arm's on the offset. Taking each answer whole, one arm jumped between two
    // wrists 7 cm apart and stayed 9 cm off its grip, because near a straight arm a small move swings the forearm. Half steps settle it.
    Vector3 wrist = grip - hand.rotation * Vector3.Scale(fist, hand.lossyScale);
    for (int pass = 0; pass < 12; pass++) {
        Reach(upper, lower, hand, wrist, pole, thumb, line, bindHand, bindForearm);
        wrist = Vector3.Lerp(wrist, grip - hand.rotation * Vector3.Scale(fist, hand.lossyScale), 0.5f);
    }
}
// For a weapon that swings: the fist's roll round the haft comes in from outside, once a frame, and its wrist is placed in one step, so the wrist has one answer.
static Quaternion Gripped(Vector3 roll, Vector3 thumb, Vector3 line, Quaternion bindHand, Vector3 bindForearm) {
    Quaternion from = Quaternion.LookRotation(Vector3.ProjectOnPlane(bindForearm, thumb).normalized, thumb);
    return Quaternion.LookRotation(Vector3.ProjectOnPlane(roll, line).normalized, line) * Quaternion.Inverse(from) * bindHand;
}
static void SolveSwung(Transform upper, Transform lower, Transform hand, Vector3 fist, Vector3 grip, Vector3 pole, Quaternion held) {
    Bend(upper, lower, hand, grip - held * Vector3.Scale(fist, hand.lossyScale), pole);
    hand.rotation = held;
}
static void Reach(Transform upper, Transform lower, Transform hand, Vector3 target, Vector3 pole, Vector3 thumb, Vector3 line, Quaternion bindHand, Vector3 bindForearm) {
    Bend(upper, lower, hand, target, pole);
    Vector3 forearm = (hand.position - lower.position).normalized;
    Quaternion from = Quaternion.LookRotation(Vector3.ProjectOnPlane(bindForearm, thumb).normalized, thumb);
    Quaternion into = Quaternion.LookRotation(Vector3.ProjectOnPlane(forearm, line).normalized, line);
    hand.rotation = into * Quaternion.Inverse(from) * bindHand;
}
static void Bend(Transform upper, Transform lower, Transform hand, Vector3 target, Vector3 pole) {
    Vector3 shoulder = upper.position;
    float a = (lower.position - shoulder).magnitude, b = (hand.position - lower.position).magnitude;
    Vector3 to = target - shoulder;
    float reach = Mathf.Clamp(to.magnitude, 0.01f, (a + b) * 0.999f);
    Vector3 way = to.normalized;
    float along = (a * a - b * b + reach * reach) / (2f * reach);
    Vector3 elbow = shoulder + way * along + Vector3.ProjectOnPlane(pole, way).normalized * Mathf.Sqrt(Mathf.Max(0f, a * a - along * along));
    upper.rotation = Quaternion.FromToRotation(lower.position - shoulder, elbow - shoulder) * upper.rotation;
    lower.rotation = Quaternion.FromToRotation(hand.position - lower.position, shoulder + way * reach - lower.position) * lower.rotation;
}
"""


HAFT_LINE = "(-right * 0.85f + up * 0.35f + forward * 0.25f).normalized;  // steeper carried the head across his face"
HAFT_SEARCH = """    // The grips sit a fist clear of the body's front, from the waist upwards, at the lowest height both arms can reach with the elbows bent:
    // a grip set from shoulder width and pulled in for reach ended inside a big man's belly, and his forearm went through it.
    float clear = Mathf.Max(Vector3.Scale(fistR, handR.lossyScale).magnitude, 0.06f) + 0.03f;
    bool reached = false;
    float lowest = float.PositiveInfinity;
    // The right hand may go out beside a big belly, which is how a heavy man carries one low.
    foreach (float across in new[] { 0.3f, 0.45f, 0.6f })
        for (float below = wide * 1.1f; below >= wide * 0.2f; below -= 0.02f) {
            Vector3 tryR = middle + right * wide * across - up * below;
            Vector3 tryL = tryR + line * wide * 0.72f;
            float front = Mathf.Max(rest.FrontAt(tryR, 0.06f), rest.FrontAt(tryL, 0.06f));
            if (float.IsInfinity(front)) continue;
            tryR.z = front + clear;
            tryL.z = tryR.z + (line * wide * 0.72f).z;
            if ((tryR - upperR.position).magnitude <= 0.9f * reachR && (tryL - upperL.position).magnitude <= 0.9f * reachL) {
                if (tryR.y < lowest) { lowest = tryR.y; gripR = tryR; gripL = tryL; reached = true; }
                break;
            }
        }
    if (!reached) throw new Exception("No height lets both arms reach a grip clear of this figure's body. Its arms are too short for this hold.");
"""
HAFT_PLACE = """    float Across(float from, float to) {
        var part = vertices.Where(v => v[axis] >= from && v[axis] <= to).ToArray();
        if (part.Length == 0) return 0f;
        var pl = part.Aggregate(Vector3.Min); var ph = part.Aggregate(Vector3.Max);
        return (ph - pl).sqrMagnitude - (ph[axis] - pl[axis]) * (ph[axis] - pl[axis]);
    }
    bool headHigh = Across(high[axis] - size * 0.25f, high[axis]) >= Across(low[axis], low[axis] + size * 0.25f);
    Vector3 longAxis = Vector3.zero; longAxis[axis] = headHigh ? 1f : -1f;
    // The haft's own middle, from the end away from the head: a lopsided head moves the whole object's middle off the haft.
    float buttEnd = headHigh ? low[axis] : high[axis];
    var haft = vertices.Where(v => Mathf.Abs(v[axis] - buttEnd) < size * 0.4f).ToArray();
    Vector3 butt = haft.Aggregate(Vector3.zero, (sum, v) => sum + v) / haft.Length; butt[axis] = buttEnd;
    Quaternion turn = Quaternion.FromToRotation(longAxis, line);
    held.transform.rotation = turn * held.transform.rotation;
    // Turning moved the weapon round its own origin, which on a weapon with its pivot at the grip is nowhere near the world's.
    Vector3 pivot = held.transform.position;
    held.transform.position += gripR - (pivot + turn * (butt - pivot) + line * size * 0.16f);
"""
HAFT_SOLVE = """            Solve(upperR, lowerR, handR, fistR, targetR, side * 0.5f - Vector3.up, Vector3.forward, lineNow, bindR, forearmR);
            Solve(upperL, lowerL, handL, fistL, targetL, -side * 0.5f - Vector3.up, Vector3.forward, lineNow, bindL, forearmL);
"""
# A weapon carried ahead rather than across the chest: the shape names its muzzle end, and each hand goes on the middle of a slice of the mesh, at its own distance along from the origin.
CARRY_PLACE = """    Vector3 restChest = chest.position;
    Vector3 origin = held.transform.position;
    Vector3 toMuzzle = Vector3.zero; toMuzzle[axis] = MUZZLEf;
    Vector3 Slice(float along) {
        var part = vertices.Where(v => Mathf.Abs(Vector3.Dot(v - origin, toMuzzle) - along) < 0.02f).ToArray();
        if (part.Length == 0) throw new Exception("Nothing of the weapon " + along + " m along from its origin.");
        return (part.Aggregate(Vector3.Min) + part.Aggregate(Vector3.Max)) / 2f;
    }
    Vector3 wristAt = Slice(WRIST), foreAt = Slice(FORESTOCK);
    int tall = Enumerable.Range(0, 3).Where(k => k != axis).OrderByDescending(k => high[k] - low[k]).First();
    Vector3 topAxis = Vector3.zero; topAxis[tall] = TOP;
    Quaternion turn = Quaternion.LookRotation(line, Vector3.ProjectOnPlane(up, line)) * Quaternion.Inverse(Quaternion.LookRotation(toMuzzle, topAxis));
    held.transform.rotation = turn * held.transform.rotation;
    held.transform.position += gripR - (origin + turn * (wristAt - origin));
    // A hand cradles the forestock from under it: through its middle, a fist would be inside a part twice its depth.
    Vector3 restWeaponP = held.transform.position; Quaternion restWeaponQ = held.transform.rotation;
    var muzzle = new GameObject("Muzzle").transform;
    muzzle.SetParent(held.transform, true);
    muzzle.position = held.transform.position + turn * (Slice(Mathf.Max(Vector3.Dot(high - origin, toMuzzle), Vector3.Dot(low - origin, toMuzzle)) - 0.02f) - origin);
    muzzle.rotation = Quaternion.LookRotation(line, Vector3.ProjectOnPlane(up, line));
    gripL = held.transform.position + turn * (foreAt - origin) - turn * topAxis * UNDER;
    localL = chest.InverseTransformPoint(gripL);
    foreach (var (arm, grip, most) in new[] { ("right", gripR, reachR)LEFT_REACH }) {
        float needed = (grip - (arm == "right" ? upperR : upperL).position).magnitude;
        Debug.Log("CARRY " + arm + " arm needs " + needed.ToString("F3") + " of " + most.ToString("F3"));
        if (needed > 0.97f * most) throw new Exception("The " + arm + " grip is " + needed.ToString("F2") + " m from the shoulder and the arm reaches " + most.ToString("F2") + " m. Bring the hand in or the muzzle across.");
    }
    float sunk = held.GetComponentsInChildren<MeshFilter>(true).SelectMany(f => f.sharedMesh.vertices.Select(v => rest.Inside(f.transform.TransformPoint(v)))).Max();
    Debug.Log("CARRY gripR " + gripR.ToString("F3") + " gripL " + gripL.ToString("F3") + " shoulders " + upperR.position.ToString("F3") + " " + upperL.position.ToString("F3") + " reach " + reachR.ToString("F3") + " " + reachL.ToString("F3") + " in body " + sunk.ToString("F3"));
    if (sunk > 0.03f) throw new Exception("The weapon goes into the body by " + sunk.ToString("F2") + " m. Move the hand out or point the muzzle further across, so the weapon passes beside the body.");
"""
CARRY_SOLVE = """            // The rifle keeps most of its line while the body moves round it: a jog leans the chest 30 degrees and turns it 15 each way, which carried on the chest swept the muzzle 60 cm and pointed it at the floor.
            Quaternion carried = chest.rotation * Quaternion.Inverse(chestRest);
            Quaternion steadied = Quaternion.Slerp(Quaternion.identity, carried, STEADY);
            held.transform.SetPositionAndRotation(chest.position + steadied * (restWeaponP - restChest), steadied * restWeaponQ);
            targetR = chest.position + steadied * (gripR - restChest);
            targetL = chest.position + steadied * (gripL - restChest);
            // A fist stays still on a rifle: the forearm runs close to the barrel's line, where a roll taken from it has no answer.
            SolveSwung(upperR, lowerR, handR, fistR, targetR, ELBOW_R, Gripped(steadied * LONG_R, Vector3.forward, steadied * THUMB_R, bindR, forearmR));
LEFT_HAND"""
CARRY_LEFT = """            SolveSwung(upperL, lowerL, handL, fistL, targetL, -side * 0.5f - Vector3.up, Gripped(steadied * LONG_L, Vector3.forward, steadied * THUMB_L, bindL, forearmL));
"""
# One hand on the weapon: the other arm keeps what the clip gives it, and there's no grip to measure it against.
CARRY_NO_LEFT = """            targetL = handL.TransformPoint(fistL);
"""
CARRY_CURVES = """        var heldCurves = new AnimationCurve[7];
        for (int r = 0; r < 7; r++) heldCurves[r] = new AnimationCurve();
        Quaternion heldLast = Quaternion.identity;
"""
CARRY_KEYS = """            Vector3 heldAt = held.transform.localPosition; Quaternion heldTurn = held.transform.localRotation;
            if (Quaternion.Dot(heldTurn, heldLast) < 0f) heldTurn = new Quaternion(-heldTurn.x, -heldTurn.y, -heldTurn.z, -heldTurn.w);
            heldLast = heldTurn;
            heldCurves[0].AddKey(time, heldAt.x); heldCurves[1].AddKey(time, heldAt.y); heldCurves[2].AddKey(time, heldAt.z);
            heldCurves[3].AddKey(time, heldTurn.x); heldCurves[4].AddKey(time, heldTurn.y); heldCurves[5].AddKey(time, heldTurn.z); heldCurves[6].AddKey(time, heldTurn.w);
"""
CARRY_WRITE = """        string heldPath = AnimationUtility.CalculateTransformPath(held.transform, body.transform);
        string[] heldNames = { "m_LocalPosition.x", "m_LocalPosition.y", "m_LocalPosition.z", "m_LocalRotation.x", "m_LocalRotation.y", "m_LocalRotation.z", "m_LocalRotation.w" };
        for (int r = 0; r < 7; r++) AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(heldPath, typeof(Transform), heldNames[r]), heldCurves[r]);
"""
CARRY_RESTORE = """    held.transform.SetPositionAndRotation(restWeaponP, restWeaponQ);
"""
# The right elbow's way is in the figure's axes and doesn't turn with the chest: leaning with a jog, it sent the forearm 10 cm into the coat. Metres along from the weapon's origin towards its muzzle; `line` in the body's right, up and forward; the right hand in shoulder widths across, below and ahead of the shoulders' middle; each hand by the way its wrist-to-knuckles and little-finger-to-thumb lines point in the body's axes.
RIFLE_CARRY = {"to_muzzle": 1, "line": [-0.75, -0.18, 0.63], "wrist": -0.11, "forestock": 0.33, "top": 1, "under_forestock": 0.07, "right_hand": [0.85, 0.45, 0.32], "steady": 0.3, "elbow_right": [0.5, -1, 0],
                  "hands": {"right": {"long": [0, -0.5, 1], "thumb": [0, 1, 0.5]}, "left": {"long": [1, 0, 0.6], "thumb": [-0.6, 0, 1]}}}
WRENCH_CARRY = {**RIFLE_CARRY, "one_hand": True, "line": [0.15, 0.35, 0.92], "wrist": -0.22, "forestock": 0.08, "under_forestock": 0, "right_hand": [1.2, 1.3, 0.8],
                 "hands": {"right": {"long": [0, -1, 0.3], "thumb": [0.15, 0.35, 0.92]}, "left": {"long": [1, 0, 0], "thumb": [0, 0, 1]}}}
LAUNCHER_CARRY = {**RIFLE_CARRY, "to_muzzle": -1, "line": [-0.65, -0.15, 0.72], "wrist": -0.25, "forestock": 0.15, "under_forestock": 0.03, "right_hand": [1.1, 1.3, 0.7], "elbow_right": [0.7, -1, -0.25]}


def _vector(values):
    x, y, z = values
    return f"new Vector3({x}f, {y}f, {z}f)"


def two_hand_script(character, weapon, library, clips, carry=None):
    """The Editor script. It mounts the weapon on the chest, with its grip low by the right hip and its head up past the left shoulder,
    and bakes each clip with both arms solved onto the haft, frame by frame, as an ordinary Humanoid clip, so any Animator plays it and
    the game needs no code. The library has no two-handed clips, and a weapon parented to one swinging hand drags the other arm across
    the body. A closed fist's thumb-to-little-finger line runs front to back in the bind pose, which is the line the haft takes through it.
    With `carry`, the weapon points ahead instead, each hand on a part measured from its origin, with its fist held still on it."""
    folder = str(Path(character).parent.as_posix())
    name = Path(character).stem
    names = ", ".join(json.dumps(clip) for clip in clips)
    line, gap, search, place, solve = HAFT_LINE, "wide * 0.72f", HAFT_SEARCH, HAFT_PLACE, HAFT_SOLVE
    curves = keys = write = restore = ""
    if carry:
        along = carry["line"]
        line = f"(right * {along[0]}f + up * {along[1]}f + forward * {along[2]}f).normalized;"
        gap = f"{carry['forestock'] - carry['wrist']}f"
        place = CARRY_PLACE.replace("WRIST", f"{carry['wrist']}f").replace("FORESTOCK", f"{carry['forestock']}f").replace("TOP", f"{carry['top']}f").replace("UNDER", f"{carry['under_forestock']}f").replace("MUZZLE", str(carry["to_muzzle"])).replace("LEFT_REACH", "" if carry.get("one_hand") else ', ("left", gripL, reachL)')
        search = "    gripR = middle + right * wide * ACROSSf - up * wide * BELOWf + forward * wide * AHEADf;\n"
        for token, value in zip(("ACROSS", "BELOW", "AHEAD"), carry["right_hand"]):
            search = search.replace(token, str(value))
        solve = CARRY_SOLVE.replace("LEFT_HAND", CARRY_NO_LEFT if carry.get("one_hand") else CARRY_LEFT).replace("STEADY", f"{carry['steady']}f").replace("ELBOW_R", _vector(carry["elbow_right"]))
        curves, keys, write, restore = CARRY_CURVES, CARRY_KEYS, CARRY_WRITE, CARRY_RESTORE
        for hand, tag in (("right", "R"), ("left", "L")):
            for way in ("long", "thumb"):
                solve = solve.replace(f"{way.upper()}_{tag}", _vector(carry["hands"][hand][way]))
    return f"""const float Fps = 30f;
{ARM_SOLVER}public static void Run() {{
    UnityEditor.SceneManagement.EditorSceneManager.NewScene(UnityEditor.SceneManagement.NewSceneSetup.DefaultGameObjects, UnityEditor.SceneManagement.NewSceneMode.Single);
    var body = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>({json.dumps(character)}));
    PrefabUtility.UnpackPrefabInstance(body, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
    body.transform.position = Vector3.zero;
    var animator = body.GetComponent<Animator>();
    animator.applyRootMotion = false;
    animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
    Transform B(HumanBodyBones bone) => animator.GetBoneTransform(bone);
    Transform chest = B(HumanBodyBones.Chest) != null ? B(HumanBodyBones.Chest) : B(HumanBodyBones.Spine);
    Transform hips = B(HumanBodyBones.Hips), footL = B(HumanBodyBones.LeftFoot), footR = B(HumanBodyBones.RightFoot);
    float groundFoot = Mathf.Min(footL.position.y, footR.position.y);
    int twist = Array.IndexOf(HumanTrait.MuscleName, "Chest Twist Left-Right");
    Transform upperR = B(HumanBodyBones.RightUpperArm), lowerR = B(HumanBodyBones.RightLowerArm), handR = B(HumanBodyBones.RightHand);
    Transform upperL = B(HumanBodyBones.LeftUpperArm), lowerL = B(HumanBodyBones.LeftLowerArm), handL = B(HumanBodyBones.LeftHand);
    float wide = (upperR.position - upperL.position).magnitude;
    Vector3 right = Vector3.right, up = Vector3.up, forward = Vector3.forward;
    Vector3 middle = (upperR.position + upperL.position) / 2f;
    Vector3 gripR = middle + right * wide * 0.32f - up * wide * 0.95f + forward * wide * 0.8f;
    Vector3 line = {line}
    Vector3 gripL = gripR + line * {gap};
    Quaternion bindR = handR.rotation, bindL = handL.rotation;
    Vector3 forearmR = (handR.position - lowerR.position).normalized, forearmL = (handL.position - lowerL.position).normalized;
    var skin = body.GetComponentInChildren<SkinnedMeshRenderer>();
    Vector3 fistR = FistCentre(skin, handR), fistL = FistCentre(skin, handL);
    // A big man's arms are short for his width: a grip set from his shoulders alone sat 10 cm past his straight arm. Both grips come in
    // together, towards the chest, until each is within reach with the elbow still bent.
    float Reach2(Transform u, Transform l, Transform h, Vector3 fist) => (l.position - u.position).magnitude + (h.position - l.position).magnitude + Vector3.Scale(fist, h.lossyScale).magnitude;
    float reachR = Reach2(upperR, lowerR, handR, fistR), reachL = Reach2(upperL, lowerL, handL, fistL);
    var arms = new System.Collections.Generic.HashSet<Transform> {{ upperR, lowerR, handR, upperL, lowerL, handL }};
    foreach (var bone in skin.bones)
        if (arms.Contains(bone.parent)) arms.Add(bone);
    var baked = new Mesh {{ indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 }};
    Quaternion chestRest = chest.rotation;
    var rest = BuildTorso(skin, arms, baked, Vector3.zero, Quaternion.identity);
{search}    Vector3 localR = chest.InverseTransformPoint(gripR), localL = chest.InverseTransformPoint(gripL), localLine = chest.InverseTransformDirection(line);
    foreach (var (markerName, parent, local) in new[] {{ ("FistR", handR, fistR), ("FistL", handL, fistL) }}) {{
        var marker = new GameObject(markerName).transform;
        marker.SetParent(parent, false);
        marker.localPosition = local;
    }}

    var held = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>({json.dumps(weapon)}));
    PrefabUtility.UnpackPrefabInstance(held, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
    held.name = "Weapon";
    foreach (var collider in held.GetComponentsInChildren<Collider>(true)) UnityEngine.Object.DestroyImmediate(collider);
    foreach (var rigid in held.GetComponentsInChildren<Rigidbody>(true)) UnityEngine.Object.DestroyImmediate(rigid);
    var vertices = held.GetComponentsInChildren<MeshFilter>(true).SelectMany(f => f.sharedMesh.vertices.Select(v => f.transform.TransformPoint(v))).ToArray();
    var low = vertices.Aggregate(Vector3.Min); var high = vertices.Aggregate(Vector3.Max);
    int axis = Enumerable.Range(0, 3).OrderByDescending(k => high[k] - low[k]).First();
    float size = high[axis] - low[axis];
{place}    held.transform.SetParent(chest, true);
    var placed = held.GetComponentsInChildren<MeshFilter>(true).SelectMany(f => f.sharedMesh.vertices.Select(v => f.transform.TransformPoint(v))).ToArray();
    foreach (var grip in new[] {{ gripR, gripL }}) {{
        float nearest = placed.Min(v => (v - grip).magnitude);
        if (nearest > 0.08f) throw new Exception("A grip isn't on the weapon: " + nearest.ToString("F2") + " m from its nearest point. Fists on a grip would close on nothing.");
    }}
    foreach (var (markerName, at) in new[] {{ ("GripR", gripR), ("GripL", gripL) }}) {{
        var marker = new GameObject(markerName).transform;
        marker.SetParent(held.transform, true);
        marker.position = at;
    }}

    UnityEditor.SceneManagement.EditorSceneManager.GetActiveScene();
    var camera = Camera.main;
    camera.enabled = false;
    var handler = new HumanPoseHandler(animator.avatar, body.transform);
    var pose = new HumanPose();
    var library = AssetDatabase.LoadAllAssetsAtPath({json.dumps(library)}).OfType<AnimationClip>().ToArray();
    System.IO.Directory.CreateDirectory({json.dumps(folder)} + "/TwoHand");
    var overrides = new System.Collections.Generic.List<string>();
    foreach (var clipName in new[] {{ {names} }}) {{
        var source = library.First(c => c.name.EndsWith("|" + clipName));
        var graph = PlayableGraph.Create();
        graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
        var output = AnimationPlayableOutput.Create(graph, "a", animator);
        var playable = AnimationClipPlayable.Create(graph, source);
        playable.SetApplyFootIK(false);
        output.SetSourcePlayable(playable);
        graph.Play();
        graph.Evaluate(0.01f); camera.Render(); graph.Evaluate(0.01f);
        int frames = Mathf.CeilToInt(source.length * Fps) + 1;
        var muscles = new AnimationCurve[HumanTrait.MuscleCount];
        for (int m = 0; m < muscles.Length; m++) muscles[m] = new AnimationCurve();
        var root = new AnimationCurve[7];
        for (int r = 0; r < 7; r++) root[r] = new AnimationCurve();
        float worst = 0f, deepest = 0f;
{curves}        for (int f = 0; f < frames; f++) {{
            float time = source.length * f / (frames - 1);
            playable.SetTime(time);
            graph.Evaluate(0f);
            // A jog twists the torso to swing free arms, which waved a chest-mounted hammer from side to side.
            Quaternion hipsInClip = hips.rotation;
            handler.GetHumanPose(ref pose);
            for (int m = 0; m < muscles.Length; m++) {{
                string muscle = HumanTrait.MuscleName[m];
                if ((muscle.StartsWith("Spine") || muscle.StartsWith("Chest") || muscle.StartsWith("UpperChest")) && !muscle.Contains("Front-Back"))
                    pose.muscles[m] *= 0.25f;
                else if (muscle.StartsWith("Spine") || muscle.StartsWith("Chest") || muscle.StartsWith("UpperChest"))
                    pose.muscles[m] *= 0.6f;  // a jog's forward rock, with hands fixed to the chest, read as a hunch
                else if (muscle.Contains("Shoulder"))
                    pose.muscles[m] = 0f;  // the shoulder pump belongs to free swinging arms
                else if ((muscle.StartsWith("Neck") || muscle.StartsWith("Head")) && !muscle.Contains("Nod"))
                    pose.muscles[m] *= 0.25f;  // a clip's head turns to offset the torso's twist: with that damped, the head swung on its own
            }}
            handler.SetHumanPose(ref pose);
            // Changing muscles under a held body rotation makes Unity turn the hips to keep its body direction: 27 degrees on a jog, so he ran
            // twisted to one side. Put them back where the clip has them.
            pose.bodyRotation = hipsInClip * Quaternion.Inverse(hips.rotation) * pose.bodyRotation;
            handler.SetHumanPose(ref pose);
            // The chest turns against the hips, as a runner's does, or a hammer mounted on it swings with each stride: 38 cm on a jog.
            float Facing() {{ var ahead = chest.rotation * Quaternion.Inverse(chestRest) * Vector3.forward; return Mathf.Atan2(ahead.x, ahead.z) * Mathf.Rad2Deg; }}
            float turned = Facing();
            pose.muscles[twist] += 0.1f;
            handler.SetHumanPose(ref pose);
            float gain = (Facing() - turned) / 0.1f;
            if (Mathf.Abs(gain) > 1f) pose.muscles[twist] += (0.25f * turned - Facing()) / gain;
            handler.SetHumanPose(ref pose);
            pose.bodyRotation = hipsInClip * Quaternion.Inverse(hips.rotation) * pose.bodyRotation;
            handler.SetHumanPose(ref pose);
            // Narrowed legs on a bouncy clip floated this man's lower foot 22 cm off the floor. Most of that comes out.
            float lowestFoot = Mathf.Min(footL.position.y, footR.position.y);
            pose.bodyPosition -= Vector3.up * 0.8f * (lowestFoot - groundFoot) / animator.humanScale;
            handler.SetHumanPose(ref pose);
            Vector3 lineNow = chest.TransformDirection(localLine);
            Vector3 targetR = chest.TransformPoint(localR), targetL = chest.TransformPoint(localL);
            Vector3 side = chest.TransformDirection(chest.InverseTransformDirection(right));
{solve}            worst = Mathf.Max(worst, (handR.TransformPoint(fistR) - targetR).magnitude, (handL.TransformPoint(fistL) - targetL).magnitude);
            if (f % 3 == 0) {{
                Quaternion frame = chest.rotation * Quaternion.Inverse(chestRest);
                var torso = BuildTorso(skin, arms, baked, chest.position, frame);
                foreach (var (from, to) in new[] {{ (lowerR, handR), (lowerL, handL) }})
                    for (float along = 0.1f; along <= 1f; along += 0.1f)
                        deepest = Mathf.Max(deepest, torso.Inside(Quaternion.Inverse(frame) * (Vector3.Lerp(from.position, to.position, along) - chest.position)));
            }}
            handler.GetHumanPose(ref pose);
            for (int m = 0; m < muscles.Length; m++) muscles[m].AddKey(time, pose.muscles[m]);
            root[0].AddKey(time, pose.bodyPosition.x); root[1].AddKey(time, pose.bodyPosition.y); root[2].AddKey(time, pose.bodyPosition.z);
            root[3].AddKey(time, pose.bodyRotation.x); root[4].AddKey(time, pose.bodyRotation.y); root[5].AddKey(time, pose.bodyRotation.z); root[6].AddKey(time, pose.bodyRotation.w);
{keys}        }}
        var clip = new AnimationClip {{ name = {json.dumps(name)} + "_TwoHand_" + clipName, frameRate = Fps }};
        for (int m = 0; m < muscles.Length; m++)
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), HumanTrait.MuscleName[m]), muscles[m]);
        string[] rootNames = {{ "RootT.x", "RootT.y", "RootT.z", "RootQ.x", "RootQ.y", "RootQ.z", "RootQ.w" }};
        for (int r = 0; r < 7; r++)
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), rootNames[r]), root[r]);
{write}        var settings = AnimationUtility.GetAnimationClipSettings(clip);
        settings.loopTime = true;
        settings.keepOriginalPositionY = true; settings.keepOriginalPositionXZ = true; settings.keepOriginalOrientation = true;
        // Baked into the pose, as the library's are: otherwise the hips' rise and fall leave as root motion and, with that off, are lost.
        settings.loopBlendPositionY = true; settings.loopBlendPositionXZ = true; settings.loopBlendOrientation = true;
        AnimationUtility.SetAnimationClipSettings(clip, settings);
        graph.Destroy();
        Debug.Log("TWOHAND baked " + clip.name + " frames " + frames + " worst fist " + worst.ToString("F3") + " arm in body " + deepest.ToString("F3"));
        if (deepest > 0.05f) throw new Exception(clip.name + ": an arm goes " + deepest.ToString("F2") + " m into the body. Check the grips against this figure's shape.");
        if (worst > 0.05f) throw new Exception(clip.name + ": a fist ends " + worst.ToString("F2") + " m off its grip. Check the grips are within reach of this figure's arms.");
        AssetDatabase.CreateAsset(clip, {json.dumps(folder)} + "/TwoHand/" + clip.name + ".anim");
    }}
    handler.Dispose();
    camera.enabled = true;
    animator.Rebind();
{restore}    PrefabUtility.SaveAsPrefabAsset(body, {json.dumps(folder + "/" + name + "_twohand.prefab")});
    UnityEngine.Object.DestroyImmediate(body);
    AssetDatabase.SaveAssets();
    Debug.Log("TWOHAND saved");
}}"""


def two_hand(root, character, weapon, library, clips=("Idle_Loop", "Walk_Loop", "Jog_Fwd_Loop"), carry=None):
    """`<character>_twohand.prefab` and `TwoHand/<character>_TwoHand_<clip>.anim` beside the character's prefab. Paths are project-relative."""
    root = Path(root).resolve()
    _run(root, "TwoHand", two_hand_script(character, weapon, library, clips, carry), root / "Logs/SlopForgeTwoHand.log")


# A swing from the side, from over the left shoulder, where the hold carries it, across the front and on past it to his right, falling a little as it goes, with the chest turning through it
# and the top hand sliding down the haft. Angles are round the arc from his right through the front, so 180 is his left; reaches are shares of the left arm's; `x` and `lat` lift the hands and the
# haft out of the arc's plane. Five values run the hold, the top of the swing, the blow, the end of the follow-through, the hold. Times are seconds: the blow lands at wind + strike.
HAMMER_SWING = {"wind": 0.22, "strike": 0.18, "follow": 0.18, "total": 0.88, "roll": -78, "release": 0.35,
                "lead": {"hips": 0.08, "spine": 0.045, "haft": -0.04}, "shoulder_follow": 0.45, "shoulder_most": 22, "roll_rate": 12, "roll_most": 170, "twist_most": 1.9,
                "theta": [150, 150, 88, 48, 112], "phi": [205, 205, 74, 25, 130], "r": [0.84, 0.84, 0.98, 0.85, 0.9], "x": [-0.14, -0.14, -0.14, -0.2, 0.25], "lat": [0.1, 0.1, -0.1, -0.12, 0.6],
                "grip_gap": [1, 0.8, 0.18, 0.18, 1], "elbow_left": [0, 0.9, 0, 0, 0], "elbow_right": [0, 0.4, 0.9, 0.9, 0],
                "spine_pitch": [0, -10, 24, 26, 0], "spine_yaw": [0, -50, 5, 45, 0], "spine_roll": [0, 6, -4, -8, 0],
                "hip_drop": [0, 0.02, -0.14, -0.12, 0], "hip_forward": [0, -0.05, 0.12, 0.14, 0], "hip_side": [0, -0.06, 0.05, 0.08, 0], "hip_pitch": [0, -3, 6, 7, 0], "hip_yaw": [0, -28, 8, 30, 0],
                "step": 0.42, "lift": 0.1, "step_out": 0.1, "toe_out": 22, "step_start": 0.04, "step_land": 0.36, "step_back": 0.6, "step_back_end": 0.86, "heel_lift": 0.05, "heel_turn": 25}
# A quick backhand with one hand on a long wrench, from a carry at her right side: across to her left, through the front and out to her right, nearly level.
WRENCH_SWEEP = {"one_hand": True, "wind": 0.13, "strike": 0.1, "follow": 0.1, "total": 0.5, "roll": -85, "release": 0.35,
                "lead": {"hips": 0.04, "spine": 0.02, "haft": -0.02}, "shoulder_follow": 0.45, "shoulder_most": 20, "roll_rate": 16, "roll_most": 170, "twist_most": 1.9,
                "theta": [120, 135, 85, 45, 80], "phi": [120, 190, 78, 20, 100], "r": [0.7, 0.6, 0.92, 0.78, 0.75], "x": [-0.3, -0.2, -0.3, -0.25, -0.3], "lat": [0.2, 0.25, 0, -0.05, 0.3],
                "grip_gap": [0, 0, 0, 0, 0], "elbow_left": [0, 0, 0, 0, 0], "elbow_right": [0, 0.5, 0.6, 0.9, 0], "left_out": [0, -8, -25, -30, 0], "left_back": [0, -15, 20, 30, 0],
                "spine_pitch": [0, -6, 14, 14, 0], "spine_yaw": [0, -40, 5, 35, 0], "spine_roll": [0, 4, -3, -6, 0],
                "hip_drop": [0, 0.01, -0.06, -0.05, 0], "hip_forward": [0, -0.02, 0.05, 0.06, 0], "hip_side": [0, -0.04, 0.04, 0.06, 0], "hip_pitch": [0, -2, 4, 4, 0], "hip_yaw": [0, -22, 8, 24, 0],
                "step": 0.22, "lift": 0.06, "step_out": 0.12, "toe_out": 25, "step_start": 0.02, "step_land": 0.21, "step_back": 0.33, "step_back_end": 0.48, "heel_lift": 0.03, "heel_turn": 18}


def _one_handed(script, shape):
    """The swing with only the right hand on the weapon, leaving the hold as the hold left it: its weapon curve, and the fist's roll on the handle."""
    left = ", ".join(f"{value}f" for value in shape["left_out"]), ", ".join(f"{value}f" for value in shape["left_back"])
    edits = (("        ShoulderFollows(1, clavL, upperL, weapon.TransformPoint(slide), w);\n", ""),
             ("overL = toL.magnitude - 0.98f * armL;", "overL = -1f;"),
             ("        SolveSwung(upperL, lowerL, handL, fistL, targetL, Pole(-side * (0.5f + liftL) - Vector3.up * (1f - 0.7f * liftL), targetL - upperL.position), heldL);\n",
              f"        upperL.rotation = Quaternion.AngleAxis(Track(Led(t, leadSpine), new[] {{ {left[0]} }}), Vector3.forward) * Quaternion.AngleAxis(Track(Led(t, leadSpine), new[] {{ {left[1]} }}), Vector3.right) * upperL.rotation;\n"),
             ("        rhoL = Mathf.MoveTowards(rhoL, rhoHoldL + w * Mathf.Clamp(Mathf.DeltaAngle(rhoHoldL, RollOf(handL.position - lowerL.position)), -rollMost, rollMost), rollRate);\n", ""),
             ("            SolveSwung(upperL, lowerL, handL, fistL, weapon.TransformPoint(slide), Pole(-side * (0.5f + liftL) - Vector3.up * (1f - 0.7f * liftL), weapon.TransformPoint(slide) - upperL.position), keptL);\n", ""),
             ("offL = (handL.TransformPoint(fistL) - weapon.TransformPoint(slide)).magnitude;", "offL = 0f;"),
             ("    pl.SetTime(0.0); g.Evaluate(0f);\n", "    pl.SetTime(0.0); g.Evaluate(0f);\n    holdLocalP = weapon.localPosition; holdLocalQ = weapon.localRotation;\n"),
             ("rhoR = rhoHoldR = RollOf(handR.position - lowerR.position);", "rhoR = rhoHoldR = RollOf(handR.rotation * Quaternion.Inverse(bindR) * forearmR);"))
    for old, new in edits:
        if script.count(old) != 1:
            raise ValueError(f"The swing's script no longer has this once: {old.strip()[:60]}")
        script = script.replace(old, new)
    return script


def two_hand_strike_script(character, attack, shape):
    """The Editor script. A computed swing for a figure with a two-handed hold: the weapon on an arc round the middle of the shoulders, the hips and spine
    driving it, one foot stepping into the blow with both feet held by leg IK, and both fists solved onto the haft each frame. The library's clips don't do
    this: an empty hand's wrist says nothing about a haft, so a chop taken from one never came down, and its sword clips throw a heavy man's body 45 degrees
    forward. The weapon is animated in the clip, under the chest where the hold mounts it, and the clip starts and ends on the hold."""
    folder = str(Path(character).parent.as_posix())
    name = Path(character).stem
    twohand = f"{folder}/{name}_twohand.prefab"
    hold = f"{folder}/TwoHand/{name}_TwoHand_Idle_Loop.anim"
    def curve(key):
        return "new[] { " + ", ".join(f"{value}f" for value in shape[key]) + " }"
    script = f"""const float Fps = 60f;
{ARM_SOLVER}static float Smooth(float x) {{ x = Mathf.Clamp01(x); return x * x * (3f - 2f * x); }}
static void Leg(Transform upper, Transform lower, Transform foot, Vector3 ankle, Quaternion footRot, Vector3 pole) {{
    Vector3 hip = upper.position; float a = (lower.position - hip).magnitude, b = (foot.position - lower.position).magnitude;
    Vector3 to = ankle - hip; float reach = Mathf.Clamp(to.magnitude, 0.01f, (a + b) * 0.999f); Vector3 way = to.normalized;
    float along = (a * a - b * b + reach * reach) / (2f * reach);
    Vector3 knee = hip + way * along + Vector3.ProjectOnPlane(pole, way).normalized * Mathf.Sqrt(Mathf.Max(0f, a * a - along * along));
    upper.rotation = Quaternion.FromToRotation(lower.position - hip, knee - hip) * upper.rotation;
    lower.rotation = Quaternion.FromToRotation(foot.position - lower.position, hip + way * reach - lower.position) * lower.rotation;
    foot.rotation = footRot;
}}
public static void Run() {{
    UnityEditor.SceneManagement.EditorSceneManager.NewScene(UnityEditor.SceneManagement.NewSceneSetup.DefaultGameObjects, UnityEditor.SceneManagement.NewSceneMode.Single);
    var plain = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>({json.dumps(character)}));
    var pa = plain.GetComponent<Animator>();
    Transform P(HumanBodyBones b) => pa.GetBoneTransform(b);
    Quaternion bindR = P(HumanBodyBones.RightHand).rotation, bindL = P(HumanBodyBones.LeftHand).rotation;
    Vector3 forearmR = (P(HumanBodyBones.RightHand).position - P(HumanBodyBones.RightLowerArm).position).normalized, forearmL = (P(HumanBodyBones.LeftHand).position - P(HumanBodyBones.LeftLowerArm).position).normalized;
    Quaternion chestRest = (P(HumanBodyBones.Chest) != null ? P(HumanBodyBones.Chest) : P(HumanBodyBones.Spine)).rotation;
    UnityEngine.Object.DestroyImmediate(plain);
    var figure = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>({json.dumps(twohand)}));
    PrefabUtility.UnpackPrefabInstance(figure, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
    figure.transform.position = Vector3.zero;
    var animator = figure.GetComponent<Animator>();
    animator.applyRootMotion = false; animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
    Transform B(HumanBodyBones bone) => animator.GetBoneTransform(bone);
    Transform chest = B(HumanBodyBones.Chest) != null ? B(HumanBodyBones.Chest) : B(HumanBodyBones.Spine);
    Transform hips = B(HumanBodyBones.Hips), spine = B(HumanBodyBones.Spine), upperChest = B(HumanBodyBones.UpperChest), neck = B(HumanBodyBones.Neck), headBone = B(HumanBodyBones.Head);
    Transform thighL = B(HumanBodyBones.LeftUpperLeg), shinL = B(HumanBodyBones.LeftLowerLeg), footL = B(HumanBodyBones.LeftFoot), thighR = B(HumanBodyBones.RightUpperLeg), shinR = B(HumanBodyBones.RightLowerLeg), footR = B(HumanBodyBones.RightFoot);
    Transform upperR = B(HumanBodyBones.RightUpperArm), lowerR = B(HumanBodyBones.RightLowerArm), handR = B(HumanBodyBones.RightHand);
    Transform upperL = B(HumanBodyBones.LeftUpperArm), lowerL = B(HumanBodyBones.LeftLowerArm), handL = B(HumanBodyBones.LeftHand);
    Transform Find(string n) => figure.GetComponentsInChildren<Transform>(true).First(t => t.name == n);
    Transform weapon = Find("Weapon"), gripR = Find("GripR"), gripL = Find("GripL");
    Vector3 fistR = Find("FistR").localPosition, fistL = Find("FistL").localPosition;
    float reachL = (lowerL.position - upperL.position).magnitude + (handL.position - lowerL.position).magnitude + Vector3.Scale(fistL, handL.lossyScale).magnitude;
    float reachR = (lowerR.position - upperR.position).magnitude + (handR.position - lowerR.position).magnitude + Vector3.Scale(fistR, handR.lossyScale).magnitude;
    float armL = (lowerL.position - upperL.position).magnitude + (handL.position - lowerL.position).magnitude, armR = (lowerR.position - upperR.position).magnitude + (handR.position - lowerR.position).magnitude;
    Vector3 holdLocalP = weapon.localPosition; Quaternion holdLocalQ = weapon.localRotation;
    Vector3 localGripL = weapon.InverseTransformPoint(gripL.position), localGripR = weapon.InverseTransformPoint(gripR.position);
    Vector3 axisLocal = (localGripL - localGripR).normalized;
    var verts = weapon.GetComponentsInChildren<MeshFilter>(true).SelectMany(f => f.sharedMesh.vertices.Select(v => weapon.InverseTransformPoint(f.transform.TransformPoint(v)))).ToArray();
    float maxAlong = verts.Max(v => Vector3.Dot(v, axisLocal)), minAlong = verts.Min(v => Vector3.Dot(v, axisLocal));
    var headVerts = verts.Where(v => Vector3.Dot(v, axisLocal) > maxAlong - (maxAlong - minAlong) * 0.25f).ToArray();
    Vector3 headLocal = headVerts.Aggregate(Vector3.zero, (s, v) => s + v) / headVerts.Length;
    Vector3 p0 = Vector3.Cross(axisLocal, Mathf.Abs(axisLocal.y) < 0.9f ? Vector3.up : Vector3.right).normalized, faceLocal = p0; float widest = 0f;
    for (float a = 0f; a < 180f; a += 5f) {{ var d = Quaternion.AngleAxis(a, axisLocal) * p0; float s = headVerts.Max(v => Vector3.Dot(v, d)) - headVerts.Min(v => Vector3.Dot(v, d)); if (s > widest) {{ widest = s; faceLocal = d; }} }}
    Quaternion WeaponRot(Vector3 line, Vector3 face) => Quaternion.LookRotation(line, face) * Quaternion.Inverse(Quaternion.LookRotation(axisLocal, faceLocal));
    var skin = figure.GetComponentInChildren<SkinnedMeshRenderer>();
    var arms = new System.Collections.Generic.HashSet<Transform> {{ upperR, lowerR, handR, upperL, lowerL, handL }};
    foreach (var bone in skin.bones) if (arms.Contains(bone.parent)) arms.Add(bone);
    var baked = new Mesh {{ indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 }};
    var camera = Camera.main; camera.enabled = false;
    var handler = new HumanPoseHandler(animator.avatar, figure.transform);
    var pose = new HumanPose();
    var holdClip = AssetDatabase.LoadAssetAtPath<AnimationClip>({json.dumps(hold)});
    if (holdClip == null) throw new Exception("Bake the two-handed hold first: no clip at " + {json.dumps(hold)});
    var g = PlayableGraph.Create(); g.SetTimeUpdateMode(DirectorUpdateMode.Manual); var o = AnimationPlayableOutput.Create(g, "a", animator); var pl = AnimationClipPlayable.Create(g, holdClip); pl.SetApplyFootIK(false); o.SetSourcePlayable(pl); g.Play(); g.Evaluate(0.01f); camera.Render(); g.Evaluate(0.01f);
    pl.SetTime(0.0); g.Evaluate(0f);
    handler.GetHumanPose(ref pose);
    float[] holdM = (float[])pose.muscles.Clone(); Vector3 holdBP = pose.bodyPosition; Quaternion holdBR = pose.bodyRotation;
    Vector3 ankleL = footL.position, ankleR = footR.position; Quaternion footRotL = footL.rotation, footRotR = footR.rotation;
    g.Destroy();
    float tWind = {shape['wind']}f, tHit = tWind + {shape['strike']}f, tFollow = tHit + {shape['follow']}f, T = {shape['total']}f;
    // Five keys: the hold, the top of the swing, the blow, the end of the follow-through, the hold. A curve through them keeps its speed through the blow and only rests where it turns back:
    // sped up to the blow and stopped there, the hammer looked to hit an invisible wall. Each part of the body runs ahead of the next, hips first and the hammer last.
    float[] knots = {{ 0f, tWind, tHit, tFollow, T }};
    // A body part's lead fades in from nothing, so the clip leaves the hold exactly.
    float Led(float at, float lead) => at + lead * Smooth(at / 0.12f);
    float Track(float at, float[] v) {{
        at = Mathf.Clamp(at, 0f, T);
        int i = 0; while (i < 3 && at > knots[i + 1]) i++;
        float Slope(int k) {{
            if (k == 0 || k == 4) return 0f;
            float h0 = knots[k] - knots[k - 1], h1 = knots[k + 1] - knots[k], d0 = (v[k] - v[k - 1]) / h0, d1 = (v[k + 1] - v[k]) / h1;
            if (d0 * d1 <= 0f) return 0f;
            float w0 = 2f * h1 + h0, w1 = h1 + 2f * h0;
            return (w0 + w1) / (w0 / d0 + w1 / d1);
        }}
        float h = knots[i + 1] - knots[i], u = (at - knots[i]) / h;
        return (2f * u * u * u - 3f * u * u + 1f) * v[i] + (u * u * u - 2f * u * u + u) * h * Slope(i) + (-2f * u * u * u + 3f * u * u) * v[i + 1] + (u * u * u - u * u) * h * Slope(i + 1);
    }}
    float[] spinePitch = {curve('spine_pitch')}, spineYaw = {curve('spine_yaw')}, spineRoll = {curve('spine_roll')}, hipDrop = {curve('hip_drop')}, hipFwd = {curve('hip_forward')}, hipSide = {curve('hip_side')}, hipPitch = {curve('hip_pitch')}, hipYaw = {curve('hip_yaw')};
    float[] thetas = {curve('theta')}, phis = {curve('phi')}, reaches = {curve('r')}, heights = {curve('x')}, tilts = {curve('lat')}, gaps = {curve('grip_gap')}, elbowLeft = {curve('elbow_left')}, elbowRight = {curve('elbow_right')};
    float shoulderFollow = {shape['shoulder_follow']}f, shoulderMost = {shape['shoulder_most']}f;
    Transform clavL = B(HumanBodyBones.LeftShoulder), clavR = B(HumanBodyBones.RightShoulder);
    // An arm reaching takes its shoulder blade with it. With the blades still, only the arms turned, and they looked stiff.
    // It eases towards where it wants to be: taken whole, a hand passing the shoulder swung the blade 52 degrees in a frame.
    var shoulderNow = new[] {{ Quaternion.identity, Quaternion.identity }};
    void ShoulderFollows(int slot, Transform clavicle, Transform upper, Vector3 target, float amount) {{
        if (clavicle == null) return;
        Quaternion.FromToRotation(upper.position - clavicle.position, target - clavicle.position).ToAngleAxis(out float angle, out Vector3 axis);
        shoulderNow[slot] = Quaternion.RotateTowards(shoulderNow[slot], Quaternion.AngleAxis(Mathf.Min(angle * shoulderFollow, shoulderMost) * amount, axis), 5f);
        clavicle.rotation = shoulderNow[slot] * clavicle.rotation;
    }}
    float leadHips = {shape['lead']['hips']}f, leadSpine = {shape['lead']['spine']}f, leadHaft = {shape['lead']['haft']}f, release = {shape['release']}f;
    // The arc's plane, tipped over from upright by `roll` about the line straight ahead: -90 sweeps flat from his left to his right.
    float roll = {shape['roll']}f;
    Vector3 planeUp = Vector3.up * Mathf.Cos(roll * Mathf.Deg2Rad) + Vector3.right * Mathf.Sin(roll * Mathf.Deg2Rad), planeSide = Vector3.Cross(planeUp, Vector3.forward);
    float step = {shape['step']}f, lift = {shape['lift']}f, stepOut = {shape['step_out']}f, toeOut = {shape['toe_out']}f, stepStart = {shape['step_start']}f, stepLand = {shape['step_land']}f, stepBack = {shape['step_back']}f, stepBackEnd = {shape['step_back_end']}f, heelLift = {shape['heel_lift']}f, heelTurn = {shape['heel_turn']}f;
    Vector3 lastHammer = Vector3.zero; float fastest = 0f, fastestAt = 0f;
    float[] elbowLeast = {{ 180f, 180f }}, elbowMost = {{ 0f, 0f }};
    int frames = Mathf.CeilToInt(T * Fps) + 1;
    var muscles = new AnimationCurve[HumanTrait.MuscleCount]; for (int m = 0; m < muscles.Length; m++) muscles[m] = new AnimationCurve();
    var root = new AnimationCurve[7]; for (int r = 0; r < 7; r++) root[r] = new AnimationCurve();
    var wp = new AnimationCurve[7]; for (int r = 0; r < 7; r++) wp[r] = new AnimationCurve();
    string worstNote = "", deepestNote = ""; float rhoR = 0f, rhoL = 0f, rhoHoldR = 0f, rhoHoldL = 0f;
    float rollRate = {shape['roll_rate']}f, rollMost = {shape['roll_most']}f, jumpMost = 0f; string jumpNote = "";
    // A fist's roll round the haft, as an angle in the weapon's own frame, so it can be limited and brought back.
    Vector3 acrossA = Vector3.Cross(axisLocal, faceLocal).normalized;
    float RollOf(Vector3 world) {{ var local = Quaternion.Inverse(weapon.rotation) * world; return Mathf.Atan2(Vector3.Dot(local, acrossA), Vector3.Dot(local, faceLocal)) * Mathf.Rad2Deg; }}
    Vector3 RollAt(float rho) => weapon.rotation * (faceLocal * Mathf.Cos(rho * Mathf.Deg2Rad) + acrossA * Mathf.Sin(rho * Mathf.Deg2Rad));
    int twistL = Array.IndexOf(HumanTrait.MuscleName, "Left Forearm Twist In-Out"), twistR = Array.IndexOf(HumanTrait.MuscleName, "Right Forearm Twist In-Out");
    float twistMost = {shape['twist_most']}f; var twistLast = new float[2];
    float Unwrapped(float value, float last) => value + 4f * Mathf.Round((last - value) / 4f);
    var watched = new[] {{ lowerL, handL, lowerR, handR, clavL, clavR }}.Where(bone => bone != null).ToArray(); var watchedLast = new Quaternion[watched.Length];
    float worst = 0f, deepest = 0f, nearHead = 9f, topY = -9f, hitY = 9f, lowest = 9f; Quaternion lastLocal = Quaternion.identity;
    for (int f = 0; f < frames; f++) {{
        float t = T * f / (frames - 1);
        for (int m = 0; m < holdM.Length; m++) pose.muscles[m] = holdM[m];
        pose.bodyPosition = holdBP; pose.bodyRotation = holdBR;
        handler.SetHumanPose(ref pose);
        weapon.localPosition = holdLocalP; weapon.localRotation = holdLocalQ;
        // Hips first, then the spine in three equal turns, so the body leads and the head keeps its eye on the target.
        float sp = Track(Led(t, leadSpine), spinePitch), sy = Track(Led(t, leadSpine), spineYaw), sr = Track(Led(t, leadSpine), spineRoll), hp = Track(Led(t, leadHips), hipPitch), hy = Track(Led(t, leadHips), hipYaw);
        hips.position += Vector3.up * Track(Led(t, leadHips), hipDrop) + Vector3.forward * Track(Led(t, leadHips), hipFwd) + Vector3.right * Track(Led(t, leadHips), hipSide);
        hips.rotation = Quaternion.AngleAxis(hy, Vector3.up) * Quaternion.AngleAxis(hp, Vector3.right) * hips.rotation;
        foreach (var bone in new[] {{ spine, chest, upperChest }}) if (bone != null) bone.rotation = Quaternion.AngleAxis(sy / 3f, Vector3.up) * Quaternion.AngleAxis(sr / 3f, Vector3.forward) * Quaternion.AngleAxis(sp / 3f, Vector3.right) * bone.rotation;
        var look = Quaternion.AngleAxis(-0.35f * (sy + hy), Vector3.up) * Quaternion.AngleAxis(-0.35f * (sp + hp), Vector3.right) * Quaternion.AngleAxis(-0.35f * sr, Vector3.forward);
        neck.rotation = look * neck.rotation; headBone.rotation = look * headBone.rotation;
        // The front foot steps into the blow and lands just before it, turning out; the back heel lifts as the body turns over it. Both come back.
        float out_ = t < stepLand ? Smooth((t - stepStart) / (stepLand - stepStart)) : 1f - Smooth((t - stepBack) / (stepBackEnd - stepBack));
        float up = t < stepLand ? Mathf.Sin(Mathf.Clamp01((t - stepStart) / (stepLand - stepStart)) * Mathf.PI) * lift : Mathf.Sin(Mathf.Clamp01((t - stepBack) / (stepBackEnd - stepBack)) * Mathf.PI) * lift * 0.6f;
        Vector3 ankleNow = ankleR + (Vector3.forward * step + Vector3.right * stepOut) * out_ + Vector3.up * up;
        Quaternion heel = Quaternion.AngleAxis(toeOut * out_, Vector3.up) * Quaternion.AngleAxis(25f * (up / Mathf.Max(lift, 0.001f)), Vector3.right);
        float pivot = t < tFollow ? Smooth((t - stepLand) / (tFollow - stepLand)) : 1f - Smooth((t - tFollow) / (stepBackEnd - tFollow));
        Leg(thighL, shinL, footL, ankleL + (Vector3.up + Vector3.forward * 0.4f) * heelLift * pivot, Quaternion.AngleAxis(heelTurn * pivot, Vector3.up) * Quaternion.AngleAxis(25f * pivot, Vector3.right) * footRotL, Vector3.forward - Vector3.right * 0.25f);
        Leg(thighR, shinR, footR, ankleNow, heel * footRotR, Vector3.forward + Vector3.right * 0.25f);
        Vector3 hp0 = weapon.position; Quaternion hq0 = weapon.rotation;
        // The weapon's arc round the middle of the shoulders, measured round the arc's plane, leaving the hold on the way up and rejoining it on the way back.
        float w = t < tWind ? Smooth(t / tWind) : 1f - Smooth((Mathf.Clamp01((t - tFollow) / (T - tFollow)) - release) / (1f - release));
        float theta = Track(t, thetas), phi = Track(t + leadHaft, phis), r = Track(t, reaches) * reachL, x = Track(t, heights), lat = Track(t + leadHaft, tilts);
        Vector3 centre = (upperL.position + upperR.position) / 2f;
        float th = theta * Mathf.Deg2Rad, ph = phi * Mathf.Deg2Rad;
        Vector3 upperHand = centre + Vector3.forward * r * Mathf.Sin(th) - planeUp * r * Mathf.Cos(th) + planeSide * x;
        Vector3 line = (Vector3.forward * Mathf.Sin(ph) - planeUp * Mathf.Cos(ph) + planeSide * lat).normalized;
        var rot = WeaponRot(line, Vector3.Cross(planeSide, line).normalized);
        // The top hand slides down the haft for the blow, as on an axe: with the hands apart, the lower one ended inside a big man's chest.
        Vector3 slide = Vector3.LerpUnclamped(localGripR, localGripL, Track(t, gaps));
        weapon.rotation = rot; weapon.position += upperHand - weapon.TransformPoint(slide);
        Vector3 pathPos = weapon.position;
        weapon.SetPositionAndRotation(Vector3.Lerp(hp0, pathPos, w), Quaternion.Slerp(hq0, rot, w));
        ShoulderFollows(0, clavR, upperR, gripR.position, w);
        ShoulderFollows(1, clavL, upperL, weapon.TransformPoint(slide), w);
        // The hammer stops on the floor, which is the blow; the hands go where that leaves the haft.
        float bottom = headVerts.Min(v => weapon.TransformPoint(v).y);
        if (bottom < 0.02f) weapon.position += Vector3.up * (0.02f - bottom);
        Vector3 lineNow = (gripL.position - gripR.position).normalized, side = chest.right;
        // A swing laid out from one shoulder can leave the other arm short: the whole weapon comes in until both wrists reach, each wrist being where its fist on the haft puts it.
        if (f == 0) {{ rhoR = rhoHoldR = RollOf(handR.position - lowerR.position); rhoL = rhoHoldL = RollOf(handL.position - lowerL.position); }}
        Quaternion heldR = Gripped(RollAt(rhoR), Vector3.forward, lineNow, bindR, forearmR), heldL = Gripped(RollAt(rhoL), Vector3.forward, lineNow, bindL, forearmL);
        for (int pass = 0; pass < 10; pass++) {{
            Vector3 toR = upperR.position - (gripR.position - heldR * Vector3.Scale(fistR, handR.lossyScale)), toL = upperL.position - (weapon.TransformPoint(slide) - heldL * Vector3.Scale(fistL, handL.lossyScale));
            float overR = toR.magnitude - 0.98f * armR, overL = toL.magnitude - 0.98f * armL;
            if (overR <= 0f && overL <= 0f) break;
            weapon.position += (overR >= overL ? toR.normalized * overR : toL.normalized * overL) * 0.7f;
        }}
        Vector3 targetL = weapon.TransformPoint(slide);
        // An arm pointing the way its elbow is told to bend has no bend to choose, and its fist came 25 cm off the haft: the elbow goes back instead.
        Vector3 Pole(Vector3 pole, Vector3 way) {{ float off = Vector3.Cross(pole.normalized, way.normalized).magnitude; return pole - Vector3.forward * Smooth((0.6f - off) / 0.4f); }}
        // Each elbow lifts and flares on the side the hammer's load is on: the left going back, the right coming through.
        float liftL = Track(t, elbowLeft), liftR = Track(t, elbowRight);
        SolveSwung(upperR, lowerR, handR, fistR, gripR.position, Pole(side * (0.5f + liftR) - Vector3.up * (1f - 0.7f * liftR), gripR.position - upperR.position), heldR);
        SolveSwung(upperL, lowerL, handL, fistL, targetL, Pole(-side * (0.5f + liftL) - Vector3.up * (1f - 0.7f * liftL), targetL - upperL.position), heldL);
        // A round haft lets a fist turn on it unseen, so each turns towards the easiest wrist, at a limited speed and only so far from the hold, coming back to it as the clip does. Rolled at
        // once from a forearm the haft crosses, hands flipped 175 degrees in a frame; held rigid on the weapon, wrists bent to 141 degrees; free to wind round, the forearm's twist wrapped.
        rhoR = Mathf.MoveTowards(rhoR, rhoHoldR + w * Mathf.Clamp(Mathf.DeltaAngle(rhoHoldR, RollOf(handR.position - lowerR.position)), -rollMost, rollMost), rollRate);
        rhoL = Mathf.MoveTowards(rhoL, rhoHoldL + w * Mathf.Clamp(Mathf.DeltaAngle(rhoHoldL, RollOf(handL.position - lowerL.position)), -rollMost, rollMost), rollRate);
        // The forearm's twist muscle wraps at the end of its range, so a bone spun 175 degrees in a frame with the hand steady, on any path. It's unwrapped from the last frame and capped;
        // a fist turning a little on a round haft doesn't show. Capping moves the fist, so the arms reach for the haft again, and the bake below measures where the fist ends.
        for (int settle = 0; settle < 3; settle++) {{
            handler.GetHumanPose(ref pose);
            foreach (var (index, slot) in new[] {{ (twistL, 0), (twistR, 1) }}) {{
                pose.muscles[index] = Mathf.Clamp(Unwrapped(pose.muscles[index], f == 0 ? pose.muscles[index] : twistLast[slot]), -twistMost, twistMost);
                if (settle == 2) twistLast[slot] = pose.muscles[index];
            }}
            // After the Humanoid round trip, which is what a game plays.
            handler.SetHumanPose(ref pose);
            if (settle == 2) break;
            Quaternion keptR = handR.rotation, keptL = handL.rotation;
            SolveSwung(upperR, lowerR, handR, fistR, gripR.position, Pole(side * (0.5f + liftR) - Vector3.up * (1f - 0.7f * liftR), gripR.position - upperR.position), keptR);
            SolveSwung(upperL, lowerL, handL, fistL, weapon.TransformPoint(slide), Pole(-side * (0.5f + liftL) - Vector3.up * (1f - 0.7f * liftL), weapon.TransformPoint(slide) - upperL.position), keptL);
        }}
        for (int b = 0; b < watched.Length; b++) {{
            float jump = f > 0 ? Quaternion.Angle(watchedLast[b], watched[b].rotation) : 0f;
            if (jump > jumpMost) {{ jumpMost = jump; jumpNote = watched[b].name + " at " + t.ToString("F2") + " s"; }}
            watchedLast[b] = watched[b].rotation;
        }}
        float offR = (handR.TransformPoint(fistR) - gripR.position).magnitude, offL = (handL.TransformPoint(fistL) - weapon.TransformPoint(slide)).magnitude;
        if (Mathf.Max(offR, offL) > worst) {{ worst = Mathf.Max(offR, offL); worstNote = (offR > offL ? "right" : "left") + " fist at " + t.ToString("F2") + " s, forearm " + Vector3.Angle((offR > offL ? handR.position - lowerR.position : handL.position - lowerL.position), lineNow).ToString("F0") + " degrees from the haft"; }}
        Vector3 hammer = weapon.TransformPoint(headLocal);
        nearHead = Mathf.Min(nearHead, (hammer - headBone.position).magnitude); topY = Mathf.Max(topY, hammer.y); lowest = Mathf.Min(lowest, hammer.y);
        if (Mathf.Abs(t - tHit) < 0.5f / Fps) hitY = hammer.y;
        if (f > 0 && (hammer - lastHammer).magnitude * (frames - 1) / T > fastest) {{ fastest = (hammer - lastHammer).magnitude * (frames - 1) / T; fastestAt = t; }}
        lastHammer = hammer;
        foreach (var (arm, upper, lower, hand) in new[] {{ (0, upperL, lowerL, handL), (1, upperR, lowerR, handR) }}) {{
            float bend = Vector3.Angle(lower.position - upper.position, hand.position - lower.position);
            elbowLeast[arm] = Mathf.Min(elbowLeast[arm], bend); elbowMost[arm] = Mathf.Max(elbowMost[arm], bend);
        }}
        if (f % 4 == 0) {{
            Quaternion frame = chest.rotation * Quaternion.Inverse(chestRest);
            var torso = BuildTorso(skin, arms, baked, chest.position, frame);
            foreach (var (from, to) in new[] {{ (lowerR, handR), (lowerL, handL) }})
                for (float along = 0.1f; along <= 1f; along += 0.1f)
                {{ float inside = torso.Inside(Quaternion.Inverse(frame) * (Vector3.Lerp(from.position, to.position, along) - chest.position)); if (inside > deepest) {{ deepest = inside; deepestNote = from.name + " at " + t.ToString("F2") + " s"; }} }}
        }}
        handler.GetHumanPose(ref pose);
        for (int m = 0; m < muscles.Length; m++) muscles[m].AddKey(t, pose.muscles[m]);
        root[0].AddKey(t, pose.bodyPosition.x); root[1].AddKey(t, pose.bodyPosition.y); root[2].AddKey(t, pose.bodyPosition.z);
        root[3].AddKey(t, pose.bodyRotation.x); root[4].AddKey(t, pose.bodyRotation.y); root[5].AddKey(t, pose.bodyRotation.z); root[6].AddKey(t, pose.bodyRotation.w);
        Vector3 lp = chest.InverseTransformPoint(weapon.position); Quaternion lq = Quaternion.Inverse(chest.rotation) * weapon.rotation;
        if (f > 0 && Quaternion.Dot(lq, lastLocal) < 0f) lq = new Quaternion(-lq.x, -lq.y, -lq.z, -lq.w);
        lastLocal = lq;
        wp[0].AddKey(t, lp.x); wp[1].AddKey(t, lp.y); wp[2].AddKey(t, lp.z); wp[3].AddKey(t, lq.x); wp[4].AddKey(t, lq.y); wp[5].AddKey(t, lq.z); wp[6].AddKey(t, lq.w);
    }}
    var clip = new AnimationClip {{ name = {json.dumps(name)} + "_TwoHand_" + {json.dumps(attack)}, frameRate = Fps }};
    for (int m = 0; m < muscles.Length; m++) AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), HumanTrait.MuscleName[m]), muscles[m]);
    string[] rootNames = {{ "RootT.x", "RootT.y", "RootT.z", "RootQ.x", "RootQ.y", "RootQ.z", "RootQ.w" }};
    for (int r = 0; r < 7; r++) AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), rootNames[r]), root[r]);
    string path = AnimationUtility.CalculateTransformPath(weapon, figure.transform);
    string[] wpNames = {{ "m_LocalPosition.x", "m_LocalPosition.y", "m_LocalPosition.z", "m_LocalRotation.x", "m_LocalRotation.y", "m_LocalRotation.z", "m_LocalRotation.w" }};
    for (int r = 0; r < 7; r++) AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), wpNames[r]), wp[r]);
    var settings = AnimationUtility.GetAnimationClipSettings(clip);
    settings.loopTime = false; settings.keepOriginalPositionY = true; settings.keepOriginalPositionXZ = true; settings.keepOriginalOrientation = true;
    settings.loopBlendPositionY = true; settings.loopBlendPositionXZ = true; settings.loopBlendOrientation = true;
    AnimationUtility.SetAnimationClipSettings(clip, settings);
    handler.Dispose(); camera.enabled = true;
    Debug.Log("STRIKE baked " + clip.name + " length " + T.ToString("F2") + " frames " + frames + " worst fist " + worst.ToString("F3") + " arm in body " + deepest.ToString("F3") + " reach L " + reachL.ToString("F2") + " R " + reachR.ToString("F2") + " hammer top y " + topY.ToString("F2") + " blow at " + tHit.ToString("F2") + " s, y " + hitY.ToString("F2") + " lowest " + lowest.ToString("F2") + " nearest own head " + nearHead.ToString("F2") + " fastest " + fastest.ToString("F1") + " m/s at " + fastestAt.ToString("F2") + " s, elbow bend left " + elbowLeast[0].ToString("F0") + ".." + elbowMost[0].ToString("F0") + " right " + elbowLeast[1].ToString("F0") + ".." + elbowMost[1].ToString("F0") + ", largest joint jump " + jumpMost.ToString("F0") + " (" + jumpNote + ")");
    if (jumpMost > 60f) throw new Exception(clip.name + ": a joint jumps " + jumpMost.ToString("F0") + " degrees in a frame: " + jumpNote + ". Fists can stay on the haft through this, so nothing else shows it.");
    if (deepest > 0.05f) throw new Exception(clip.name + ": an arm goes " + deepest.ToString("F2") + " m into the body: " + deepestNote + ". Move the hands further from it there.");
    if (worst > 0.05f) throw new Exception(clip.name + ": a fist ends " + worst.ToString("F2") + " m off its grip: " + worstNote + ". Keep the haft away from the line of the forearm, where no fist holds still.");
    AssetDatabase.DeleteAsset({json.dumps(folder)} + "/TwoHand/" + clip.name + ".anim");
    AssetDatabase.CreateAsset(clip, {json.dumps(folder)} + "/TwoHand/" + clip.name + ".anim");
    UnityEngine.Object.DestroyImmediate(figure);
    AssetDatabase.SaveAssets();
    Debug.Log("STRIKE saved");
}}"""
    return _one_handed(script, shape) if shape.get("one_hand") else script


def two_hand_strike(root, character, attack="Attack_Swing", shape=HAMMER_SWING):
    """`TwoHand/<character>_TwoHand_<attack>.anim` beside the character's prefab, after `two_hand`. Paths are project-relative."""
    root = Path(root).resolve()
    _run(root, "Strike", two_hand_strike_script(character, attack, shape), root / "Logs/SlopForgeStrike.log")


# A shot: the weapon comes straight back and its muzzle lifts, then the hold takes it up again; the body gives a moment later and for longer. Seconds, metres and degrees.
RIFLE_SHOT = {"total": 0.5, "rise": 0.03, "settle": 0.1, "back": 0.05, "lift": 4, "body": 3, "body_lag": 0.03, "elbow_right": RIFLE_CARRY["elbow_right"]}
LAUNCHER_SHOT = {"total": 0.7, "rise": 0.04, "settle": 0.14, "back": 0.06, "lift": 7, "body": 4, "body_lag": 0.04, "elbow_right": LAUNCHER_CARRY["elbow_right"]}


def two_hand_shot_script(character, attack, shape):
    """The Editor script. A firing clip for a figure with a two-handed hold: the hold's first frame, with the weapon kicked back along its line and both fists solved onto it,
    and the spine giving a little after it. The weapon is animated in the clip, and the clip starts and ends on the hold."""
    folder = str(Path(character).parent.as_posix())
    name = Path(character).stem
    return f"""const float Fps = 60f;
{ARM_SOLVER}static float Smooth(float x) {{ x = Mathf.Clamp01(x); return x * x * (3f - 2f * x); }}
static float Kick(float t, float rise, float settle, float total) {{
    if (t <= 0f) return 0f;
    if (t < rise) return Smooth(t / rise);
    return Mathf.Exp(-(t - rise) / settle) * (1f - Smooth((t - (total - 0.2f)) / 0.2f));
}}
public static void Run() {{
    UnityEditor.SceneManagement.EditorSceneManager.NewScene(UnityEditor.SceneManagement.NewSceneSetup.DefaultGameObjects, UnityEditor.SceneManagement.NewSceneMode.Single);
    var figure = (GameObject)PrefabUtility.InstantiatePrefab(AssetDatabase.LoadAssetAtPath<GameObject>({json.dumps(f"{folder}/{name}_twohand.prefab")}));
    PrefabUtility.UnpackPrefabInstance(figure, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
    figure.transform.position = Vector3.zero;
    var animator = figure.GetComponent<Animator>();
    animator.applyRootMotion = false; animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
    Transform B(HumanBodyBones bone) => animator.GetBoneTransform(bone);
    Transform chest = B(HumanBodyBones.Chest) != null ? B(HumanBodyBones.Chest) : B(HumanBodyBones.Spine), spine = B(HumanBodyBones.Spine);
    Transform upperR = B(HumanBodyBones.RightUpperArm), lowerR = B(HumanBodyBones.RightLowerArm), handR = B(HumanBodyBones.RightHand);
    Transform upperL = B(HumanBodyBones.LeftUpperArm), lowerL = B(HumanBodyBones.LeftLowerArm), handL = B(HumanBodyBones.LeftHand);
    Transform Find(string n) => figure.GetComponentsInChildren<Transform>(true).First(t => t.name == n);
    Transform weapon = Find("Weapon"), gripR = Find("GripR"), gripL = Find("GripL");
    Vector3 fistR = Find("FistR").localPosition, fistL = Find("FistL").localPosition;
    var skin = figure.GetComponentInChildren<SkinnedMeshRenderer>();
    var arms = new System.Collections.Generic.HashSet<Transform> {{ upperR, lowerR, handR, upperL, lowerL, handL }};
    foreach (var bone in skin.bones)
        if (arms.Contains(bone.parent)) arms.Add(bone);
    var baked = new Mesh {{ indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 }};
    Quaternion chestRest = chest.rotation;
    var camera = Camera.main;
    camera.enabled = false;
    var handler = new HumanPoseHandler(animator.avatar, figure.transform);
    var pose = new HumanPose();
    var hold = AssetDatabase.LoadAssetAtPath<AnimationClip>({json.dumps(f"{folder}/TwoHand/{name}_TwoHand_Idle_Loop.anim")});
    var graph = PlayableGraph.Create();
    graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
    var output = AnimationPlayableOutput.Create(graph, "a", animator);
    var playable = AnimationClipPlayable.Create(graph, hold);
    playable.SetApplyFootIK(false);
    output.SetSourcePlayable(playable);
    graph.Play();
    graph.Evaluate(0.01f); camera.Render(); graph.Evaluate(0.01f);
    float T = {shape["total"]}f;
    int frames = Mathf.RoundToInt(T * Fps) + 1;
    var muscles = new AnimationCurve[HumanTrait.MuscleCount];
    for (int m = 0; m < muscles.Length; m++) muscles[m] = new AnimationCurve();
    var root = new AnimationCurve[7];
    for (int r = 0; r < 7; r++) root[r] = new AnimationCurve();
    var wp = new AnimationCurve[7];
    for (int r = 0; r < 7; r++) wp[r] = new AnimationCurve();
    var watched = new[] {{ upperR, lowerR, handR, upperL, lowerL, handL }};
    var watchedLast = new Quaternion[watched.Length];
    float worst = 0f, deepest = 0f, jumpMost = 0f, endOff = 0f;
    Quaternion lastLocal = Quaternion.identity;
    float[] first = null;
    for (int f = 0; f < frames; f++) {{
        float t = T * f / (frames - 1);
        playable.SetTime(0.0);
        graph.Evaluate(0f);
        Vector3 across = figure.transform.right, side = across;
        Vector3 weaponAt = weapon.position, gripAt = gripR.position, line = (gripL.position - gripR.position).normalized;
        Quaternion weaponTurn = weapon.rotation;
        float kick = Kick(t, {shape["rise"]}f, {shape["settle"]}f, T), give = Kick(t - {shape["body_lag"]}f, {shape["rise"]}f, {shape["settle"]}f * 1.5f, T);
        Quaternion lift = Quaternion.AngleAxis(-{shape["lift"]}f * kick, across);
        Quaternion keptR = lift * handR.rotation, keptL = lift * handL.rotation;
        spine.rotation = Quaternion.AngleAxis(-{shape["body"]}f * give, across) * spine.rotation;
        weapon.SetPositionAndRotation(gripAt + lift * (weaponAt - gripAt) - line * {shape["back"]}f * kick, lift * weaponTurn);
        SolveSwung(upperR, lowerR, handR, fistR, gripR.position, {_vector(shape["elbow_right"])}, keptR);
        SolveSwung(upperL, lowerL, handL, fistL, gripL.position, -side * 0.5f - Vector3.up, keptL);
        worst = Mathf.Max(worst, (handR.TransformPoint(fistR) - gripR.position).magnitude, (handL.TransformPoint(fistL) - gripL.position).magnitude);
        for (int b = 0; b < watched.Length; b++) {{
            if (f > 0) jumpMost = Mathf.Max(jumpMost, Quaternion.Angle(watchedLast[b], watched[b].rotation));
            watchedLast[b] = watched[b].rotation;
        }}
        if (f % 4 == 0) {{
            Quaternion frame = chest.rotation * Quaternion.Inverse(chestRest);
            var torso = BuildTorso(skin, arms, baked, chest.position, frame);
            foreach (var (from, to) in new[] {{ (lowerR, handR), (lowerL, handL) }})
                for (float along = 0.1f; along <= 1f; along += 0.1f)
                    deepest = Mathf.Max(deepest, torso.Inside(Quaternion.Inverse(frame) * (Vector3.Lerp(from.position, to.position, along) - chest.position)));
        }}
        handler.GetHumanPose(ref pose);
        if (first == null) first = (float[])pose.muscles.Clone();
        if (f == frames - 1) for (int m = 0; m < muscles.Length; m++) endOff = Mathf.Max(endOff, Mathf.Abs(pose.muscles[m] - first[m]));
        for (int m = 0; m < muscles.Length; m++) muscles[m].AddKey(t, pose.muscles[m]);
        root[0].AddKey(t, pose.bodyPosition.x); root[1].AddKey(t, pose.bodyPosition.y); root[2].AddKey(t, pose.bodyPosition.z);
        root[3].AddKey(t, pose.bodyRotation.x); root[4].AddKey(t, pose.bodyRotation.y); root[5].AddKey(t, pose.bodyRotation.z); root[6].AddKey(t, pose.bodyRotation.w);
        Vector3 lp = weapon.localPosition; Quaternion lq = weapon.localRotation;
        if (Quaternion.Dot(lq, lastLocal) < 0f) lq = new Quaternion(-lq.x, -lq.y, -lq.z, -lq.w);
        lastLocal = lq;
        wp[0].AddKey(t, lp.x); wp[1].AddKey(t, lp.y); wp[2].AddKey(t, lp.z); wp[3].AddKey(t, lq.x); wp[4].AddKey(t, lq.y); wp[5].AddKey(t, lq.z); wp[6].AddKey(t, lq.w);
    }}
    var clip = new AnimationClip {{ name = {json.dumps(name)} + "_TwoHand_" + {json.dumps(attack)}, frameRate = Fps }};
    for (int m = 0; m < muscles.Length; m++) AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), HumanTrait.MuscleName[m]), muscles[m]);
    string[] rootNames = {{ "RootT.x", "RootT.y", "RootT.z", "RootQ.x", "RootQ.y", "RootQ.z", "RootQ.w" }};
    for (int r = 0; r < 7; r++) AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), rootNames[r]), root[r]);
    string path = AnimationUtility.CalculateTransformPath(weapon, figure.transform);
    string[] wpNames = {{ "m_LocalPosition.x", "m_LocalPosition.y", "m_LocalPosition.z", "m_LocalRotation.x", "m_LocalRotation.y", "m_LocalRotation.z", "m_LocalRotation.w" }};
    for (int r = 0; r < 7; r++) AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), wpNames[r]), wp[r]);
    var settings = AnimationUtility.GetAnimationClipSettings(clip);
    settings.loopTime = false; settings.keepOriginalPositionY = true; settings.keepOriginalPositionXZ = true; settings.keepOriginalOrientation = true;
    settings.loopBlendPositionY = true; settings.loopBlendPositionXZ = true; settings.loopBlendOrientation = true;
    AnimationUtility.SetAnimationClipSettings(clip, settings);
    graph.Destroy();
    handler.Dispose(); camera.enabled = true;
    Debug.Log("SHOT baked " + clip.name + " length " + T.ToString("F2") + " frames " + frames + " worst fist " + worst.ToString("F3") + " arm in body " + deepest.ToString("F3") + " joint jump " + jumpMost.ToString("F1") + " end off " + endOff.ToString("F3"));
    if (jumpMost > 60f) throw new Exception(clip.name + ": a joint jumps " + jumpMost.ToString("F0") + " degrees in a frame.");
    if (deepest > 0.05f) throw new Exception(clip.name + ": an arm goes " + deepest.ToString("F2") + " m into the body. Check the hold's grips against this figure's shape.");
    if (worst > 0.05f) throw new Exception(clip.name + ": a fist ends " + worst.ToString("F2") + " m off its grip. Check the kick is within reach of this figure's arms.");
    if (endOff > 0.01f) throw new Exception(clip.name + " doesn't end on the hold: a muscle is " + endOff.ToString("F3") + " off.");
    AssetDatabase.DeleteAsset({json.dumps(folder)} + "/TwoHand/" + clip.name + ".anim");
    AssetDatabase.CreateAsset(clip, {json.dumps(folder)} + "/TwoHand/" + clip.name + ".anim");
    UnityEngine.Object.DestroyImmediate(figure);
    AssetDatabase.SaveAssets();
    Debug.Log("SHOT saved");
}}"""


def two_hand_shot(root, character, attack="Attack_Shot", shape=RIFLE_SHOT):
    """`TwoHand/<character>_TwoHand_<attack>.anim` beside the character's prefab, after `two_hand`. Paths are project-relative."""
    root = Path(root).resolve()
    _run(root, "Shot", two_hand_shot_script(character, attack, shape), root / "Logs/SlopForgeShot.log")


def equip(root, character, pack, weapon, library, *, hold_clip="Pistol_Idle_Loop", pack_scale=1.0, pack_height=0.68):
    """`<character>_equipped.prefab` beside the character's prefab. Paths are project-relative assets. `pack_scale` and
    `pack_height` (the pack's centre as a share of her height) are set by eye for each character."""
    root = Path(root).resolve()
    _run(root, "Equip", equip_script(character, pack, weapon, library, hold_clip, pack_scale, pack_height),
         root / "Logs/SlopForgeEquip.log")
