# Third-party notices

SlopForge is licensed under MIT; see `LICENSE`. No ComfyUI implementation source, custom node code, or model weights are bundled. Included examples and public benchmark evidence are limited to the assets documented in this repository.

The image workflow is a local ComfyUI API-format graph using ComfyUI core node names. Its source-machine provenance and the model references are documented in `LICENSE-PROVENANCE.md` and `docs/COMFYUI.md`. The Hunyuan3D API graph is assembled by SlopForge from node names exposed by the local ComfyUI installation.

Python dependencies are installed from their upstream packages and remain under their respective licenses. Model weights and ComfyUI custom nodes installed separately are not covered by SlopForge's license; review their publishers' terms before use or redistribution.

The optional `slopforge character rig` command invokes Blender's bundled Rigify add-on through the installed Blender executable. The provider records GPL-2.0-or-later provenance and Blender version in the character manifest. Blender/Rigify is not bundled by SlopForge; consult the installed Blender distribution's license notices. No UniRig/SkinTokens code or weights are bundled or installed.

The local Cesium Man rigging benchmark fixture comes from the Khronos [glTF Sample Assets](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/CesiumMan). The model and its metadata are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode); Cesium logos and trademarks have separate restrictions listed in the upstream [legal marks notice](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/main/LICENSES/LicenseRef-LegalMark-Cesium.txt). SlopForge’s MIT license does not replace those terms.
