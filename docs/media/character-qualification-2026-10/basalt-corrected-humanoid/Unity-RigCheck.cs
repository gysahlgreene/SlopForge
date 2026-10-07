using UnityEngine;
using UnityEngine.Playables;
using UnityEngine.Animations;
using UnityEditor;
using System.IO;
public static class RigCheck {
 public static void Run() {
  var importer=(ModelImporter)AssetImporter.GetAtPath("Assets/Basalt.fbx");
  importer.importAnimation=true;
  importer.animationType=ModelImporterAnimationType.Human;
  importer.avatarSetup=ModelImporterAvatarSetup.CreateFromThisModel;
  importer.SaveAndReimport();
  var model=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Basalt.fbx");
  var obj=Object.Instantiate(model);
  var animator=obj.GetComponent<Animator>();
  var avatar=animator ? animator.avatar : null;
  var report="avatar_present="+(avatar!=null)+"\nvalid="+(avatar && avatar.isValid)+"\nhuman="+(avatar && avatar.isHuman)+"\n";
  if(avatar && avatar.isHuman && avatar.isValid) {
   foreach(HumanBodyBones bone in System.Enum.GetValues(typeof(HumanBodyBones))) {
    if(bone==HumanBodyBones.LastBone)continue;
    var t=animator.GetBoneTransform(bone);
    report+=bone+"="+(t?t.name:"MISSING")+"\n";
   }
  }
  var clips=System.Array.FindAll(AssetDatabase.LoadAllAssetsAtPath("Assets/Basalt.fbx"), a=>a is AnimationClip && !a.name.StartsWith("__preview"));
  report+="clips="+clips.Length+"\n";
  if(avatar && avatar.isValid && avatar.isHuman && clips.Length>0) {
   var clip=(AnimationClip)clips[0];
   var renderer=obj.GetComponentInChildren<SkinnedMeshRenderer>();
   var before=new Mesh();var after=new Mesh();
   animator.cullingMode=AnimatorCullingMode.AlwaysAnimate;
   animator.Rebind();animator.Update(0);
   var graph=PlayableGraph.Create("HumanoidValidation");
   graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
   var playable=AnimationClipPlayable.Create(graph,clip);
   var output=AnimationPlayableOutput.Create(graph,"Humanoid",animator);
   output.SetSourcePlayable(playable);graph.Play();
   playable.SetTime(0);graph.Evaluate(0);renderer.BakeMesh(before);
   graph.Evaluate(1);animator.Update(0);renderer.BakeMesh(after);
   graph.Destroy();
   float maxDelta=0;var a=before.vertices;var b=after.vertices;
   for(int i=0;i<a.Length;i++)maxDelta=Mathf.Max(maxDelta,Vector3.Distance(a[i],b[i]));
   if(maxDelta<0.001f)throw new System.Exception("Humanoid motion failed: no meaningful skin displacement");
   report+="clip_length_seconds="+clip.length+"\nmax_skinned_vertex_delta="+maxDelta+"\n";
  }
  File.WriteAllText("/tmp/basalt-unity-validation.txt",report);
  Debug.Log(report);
  EditorApplication.Exit(avatar && avatar.isValid && avatar.isHuman ? 0 : 2);
 }
}
