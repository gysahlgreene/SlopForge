"""The rights in a delivered artifact are the weakest over its complete lineage. Mutation tests per the provenance
skill: one valid baseline, then each malformed or contradictory shape must reject with a reason, never raise."""
import copy

import pytest

from slopforge.failures import StageFailure
from slopforge.providers import artifact_rights, lineage_rights, require_shippable

CLEARED = {"status": "cleared", "terms": "Apache-2.0", "terms_version": "LICENSE", "read_on": "2026-10-27"}
DINO = {"status": "attribution_required", "terms": "DINOv3 License", "terms_version": "2025-08-19",
        "read_on": "2026-10-27", "notice": "Built with DINOv3."}
BLENDER = {"status": "cleared", "terms": "GPL-2.0-or-later covers Blender, not what it makes",
           "terms_version": "FAQ", "read_on": "2026-10-27"}


def ref(name, sha="a", derived=()):
    return {"id": name, "type": "x", "path": f"{name}.bin", "sha256": sha * 64, "stage": name, "attempt": 1,
            "derived_from": [{"artifact_id": item["id"], "sha256": item["sha256"]} for item in derived]}


def stage(name, inputs, outputs, rights, status="succeeded"):
    provenance = {} if rights is None else {"output_rights": rights}
    return {"id": f"stage-{name}", "name": name, "attempt": 1, "status": status, "inputs": inputs,
            "outputs": outputs, "settings": {}, "provenance": provenance}


def baseline():
    concept = ref("concept", "c")
    mesh = ref("mesh", "m", [concept])
    material = ref("material", "t", [mesh])
    asset = {"executions": [
        {"id": "e1", "stages": [stage("concept_generation", [], [concept], [{"source": "z_image", **CLEARED}])]},
        {"id": "e2", "stages": [
            stage("mesh_workflow_execution", [concept], [mesh],
                  [{"source": "trellis_2", **CLEARED}, {"source": "dino_v3", **DINO}]),
            stage("material_assembly_export", [mesh], [material], [{"source": "blender", **BLENDER}])]}]}
    return asset, [material]


def test_the_weakest_status_over_the_lineage_with_its_notices():
    asset, refs = baseline()
    rights = lineage_rights(asset, refs)
    assert rights["status"] == "attribution_required"
    assert rights["notices"] == ["Built with DINOv3."]
    assert {item["source"] for item in rights["sources"]} == {"z_image", "trellis_2", "dino_v3", "blender"}


def _stages(asset):
    return [item for execution in asset["executions"] for item in execution["stages"]]


def _mutate(change):
    asset, refs = baseline()
    change(asset, refs)
    return lineage_rights(asset, refs)


@pytest.mark.parametrize("change, reason", [
    (lambda a, r: _stages(a)[0]["provenance"].clear(), "concept_generation attempt 1 recorded no output rights"),
    (lambda a, r: _stages(a)[0]["provenance"].update(output_rights=[{"source": "z_image", "status": "unknown",
                                                                       "reason": "terms unread"}]), "terms unread"),
    (lambda a, r: a["executions"].pop(0), "no stage records producing concept"),
    (lambda a, r: a["executions"].append({"id": "copy", "stages": [stage("concept_generation", [], [ref("concept", "c")],
                                                                         [{"source": "other", **CLEARED}])]}),
     "disagree"),
    (lambda a, r: a["executions"].append({"id": "broken", "stages": "not a list"}), "malformed"),
    (lambda a, r: a["executions"].append("not an execution"), "malformed"),
    (lambda a, r: _stages(a)[1]["provenance"].update(output_rights={"source": "x"}), "malformed"),
    (lambda a, r: _stages(a)[1]["provenance"].update(output_rights=[{"source": "x", "status": "cleared"}]),
     "invalid output rights"),
    (lambda a, r: _stages(a)[2].update(status="failed"), "did not succeed"),
    (lambda a, r: r[0].pop("sha256"), "malformed"),
    (lambda a, r: r.clear(), "no lineage recorded"),
    (lambda a, r: a.pop("executions"), "malformed"),
])
def test_each_malformed_or_contradictory_lineage_is_unknown_with_a_reason(change, reason):
    rights = _mutate(change)
    assert rights["status"] == "unknown"
    assert any(reason in item for item in rights["reasons"]), rights["reasons"]


def test_an_adopted_copy_that_agrees_keeps_the_baseline_and_a_cycle_ends():
    asset, refs = baseline()
    asset["executions"].append(copy.deepcopy(asset["executions"][1]))  # a resumed run adopted both stages
    assert lineage_rights(asset, refs)["status"] == "attribution_required"
    _stages(asset)[0]["inputs"] = [copy.deepcopy(refs[0])]  # the concept claims the material as input
    assert lineage_rights(asset, refs)["status"] == "attribution_required"


def test_a_regenerated_artifact_with_the_same_id_is_another_artifact():
    """Concept candidates reuse ids across generations; identity is the id with the content hash."""
    asset, refs = baseline()
    asset["executions"].append({"id": "later", "stages": [stage("concept_generation", [], [ref("concept", "d")],
                                                                None, status="failed")]})
    assert lineage_rights(asset, refs)["status"] == "attribution_required"
    _stages(asset)[0]["outputs"] = [ref("concept", "e")]  # no producer of the referenced content is left
    assert "no stage records producing concept" in " ".join(lineage_rights(asset, refs)["reasons"])


def test_restricted_anywhere_wins():
    asset, refs = baseline()
    _stages(asset)[0]["provenance"]["output_rights"] = [{"source": "flux_dev_vae", "status": "restricted",
                                                          "terms": "FLUX.1 [dev] Non-Commercial License",
                                                          "terms_version": "v1.1.1", "read_on": "2026-10-27",
                                                          "reason": "non-commercial"}]
    assert lineage_rights(asset, refs)["status"] == "restricted"


def character_manifest(published=None, rig_rights=None):
    character = {"id": "character-1", "name": "pilot", "outputs": {"model": "Assets/pilot.fbx"},
                 "artifacts": {"rig": {"id": "rig", "derived_from": [{"asset_id": "character-1", "output_id": "model"}],
                                       "provenance": {} if rig_rights is None else {"output_rights": rig_rights}}}}
    if published is not None:
        character["output_rights"] = published
    return {"assets": {"character:pilot": character}}


def test_a_registered_artifact_reads_its_parents_publication_record():
    published = {"status": "attribution_required", "notices": ["Built with DINOv3."], "reasons": [],
                 "sources": [{"source": "dino_v3", "status": "attribution_required"}]}
    manifest = character_manifest(published, [{"source": "skintokens", **CLEARED}])
    rights = artifact_rights(manifest, "character:pilot", "rig")
    assert rights["status"] == "attribution_required" and rights["notices"] == ["Built with DINOv3."]
    assert artifact_rights(character_manifest(None, [{"source": "skintokens", **CLEARED}]),
                           "character:pilot", "rig")["status"] == "unknown"  # published before rights existed
    assert artifact_rights(character_manifest(published, None), "character:pilot", "rig")["status"] == "unknown"
    broken = character_manifest({"status": "fine"}, [{"source": "skintokens", **CLEARED}])
    assert artifact_rights(broken, "character:pilot", "rig")["status"] == "unknown"
    missing = character_manifest(published, [{"source": "skintokens", **CLEARED}])
    missing["assets"]["character:pilot"]["artifacts"]["rig"]["derived_from"] = [{"asset_id": "nobody", "output_id": "x"}]
    assert "nobody" in " ".join(artifact_rights(missing, "character:pilot", "rig")["reasons"])


def test_delivery_refuses_unknown_and_restricted_and_names_the_remedy():
    require_shippable({"status": "cleared", "notices": [], "reasons": [], "sources": []}, "pilot", "approve-texture")
    with pytest.raises(StageFailure) as failure:
        require_shippable({"status": "unknown", "notices": [], "reasons": ["z_image: terms unread"], "sources": []},
                          "pilot", "approve-texture")
    assert failure.value.category == "configuration"
    assert "z_image: terms unread" in str(failure.value) and "approve-texture" in str(failure.value)
    assert "output_rights" in failure.value.remedy


def test_a_registered_artifact_that_is_a_published_output_reads_the_delivery_record():
    """A character's `model` artifact is the file approve-texture delivered: its own record (say, the concept's
    rights copied from the generator) must not hide the mesh's, which the delivery record holds."""
    published = {"status": "attribution_required", "notices": ["Built with DINOv3."], "reasons": [],
                 "sources": [{"source": "dino_v3", "status": "attribution_required"}]}
    character = {"id": "character-1", "name": "pilot", "published_artifacts": [{"path": "Assets/pilot.fbx"}],
                 "outputs": {"fbx": "Assets/pilot.fbx", "rig": "Assets/rig.fbx"}, "output_rights": published,
                 "artifacts": {
                     "model": {"id": "model", "path": "Assets/pilot.fbx", "derived_from": [],
                               "provenance": {"output_rights": [{"source": "z_image", **CLEARED}]}},
                     "rig": {"id": "rig", "derived_from": [{"asset_id": "character-1", "output_id": "model"}],
                             "provenance": {"output_rights": [{"source": "skintokens", **CLEARED}]}}}}
    manifest = {"assets": {"character:pilot": character}}
    rights = artifact_rights(manifest, "character:pilot", "rig")
    assert rights["status"] == "attribution_required" and rights["notices"] == ["Built with DINOv3."]
    del character["artifacts"]["model"]["provenance"]["output_rights"]  # the delivery record alone covers it
    assert artifact_rights(manifest, "character:pilot", "rig")["status"] == "attribution_required"
    del character["output_rights"]  # delivered before rights were recorded
    assert artifact_rights(manifest, "character:pilot", "rig")["status"] == "unknown"
