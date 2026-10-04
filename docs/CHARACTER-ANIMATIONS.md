# Character animation libraries

Project-local reusable clip collections live in `ai/animation_libraries/<name>.yaml`. Each clip records an ID, one of `idle`, `walk`, `run`, `jump`, `attack`, `hurt`, `death`, or `interact`, a project-relative FBX/GLB, loop and root-motion settings, and an optional source-to-target bone-name map. Mapping targets must be unique. This metadata stays independent of any character-generation or animation provider.

Validate a library with:

```sh
slopforge --project /path/to/unity-project animation validate base
```

Validation checks file presence, containment, format, clip names, and mapping shape. It does not perform skeletal retargeting, measure deformation, modify Unity `ModelImporter` settings, or create an `AnimatorController`/prefab. Those operations need a verified rig/animation toolchain and Unity Editor integration; the current provider audit leaves that integration unresolved. A metadata mapping alone is not evidence that two skeletons are compatible.
