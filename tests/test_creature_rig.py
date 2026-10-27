"""B1: a raw creature rig checked against its limb declaration, on a four-legged box fixture (no Blender)."""
import copy

import numpy as np
import pytest

from slopforge.creature_rig import structure
from slopforge.failures import candidate_quality_rejection

LIMBS = {"ground_contact": 4}
LIMITS = {"max_rig_limbs_missing": 0, "max_rig_asymmetry": 0.05, "max_rig_bones_outside": 0}

# Raw SkinTokens-style names, heads in metres, the creature facing -Y with its left on +X (the model pipeline's frame).
BONES = {
    "bone_0": ((0, 0.4, 0.55), None),          # hips: the root and the hind legs' hub
    "bone_1": ((0, 0.1, 0.55), "bone_0"),
    "bone_2": ((0, -0.2, 0.55), "bone_1"),
    "bone_3": ((0, -0.4, 0.6), "bone_2"),       # chest: the front legs' hub
    "bone_4": ((0, -0.52, 0.66), "bone_3"),
    "bone_5": ((0, -0.62, 0.8), "bone_4"),      # head
    "bone_6": ((0, -0.75, 0.85), "bone_5"),
    "bone_7": ((0, 0.56, 0.58), "bone_0"),      # tail
    "bone_8": ((0, 0.72, 0.58), "bone_7"),
}
for side, x in (("L", 0.1), ("R", -0.1)):
    hind = [f"hind{side}{k}" for k in range(4)]
    for name, z, parent in zip(hind, (0.45, 0.28, 0.1), ("bone_0", *hind)):
        BONES[name] = ((x, 0.4, z), parent)
    BONES[hind[3]] = ((x, 0.38, 0.03), hind[2])
    front = [f"front{side}{k}" for k in range(5)]
    for name, z, parent in zip(front, (0.55, 0.4, 0.25, 0.1), ("bone_3", *front)):
        BONES[name] = ((x, -0.4, z), parent)
    BONES[front[4]] = ((x, -0.42, 0.03), front[3])


def box(lo, hi):
    """An axis-aligned box: 8 corners (index 4x + 2y + z) and 12 outward triangles."""
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
    quads = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    return corners, [tri for a, b, c, d in quads for tri in ((a, b, c), (a, c, d))]


def default_legs():
    """Each leg box: its centre, the bone its floor corners follow (the paw) and the one its top follows."""
    return {f"{end}{side}": ((x, y), f"{end}{side}{paw}", f"{end}{side}{top}")
            for end, y, paw, top in (("hind", 0.4, 2, 0), ("front", -0.4, 3, 1)) for side, x in (("L", 0.1), ("R", -0.1))}


def creature(bones=BONES, legs=None, extra=4000):
    """Boxes for body, head, tail and four legs, each skinned to one bone; a leg's floor corners follow its paw.
    `extra` vertices inside the body follow the spine, as a dense fur body outweighs thin legs (#139)."""
    legs = legs or default_legs()
    parts = [((-0.15, -0.55, 0.4), (0.15, 0.55, 0.7), "bone_1", "bone_1"),
             ((-0.1, -0.8, 0.6), (0.1, -0.5, 0.95), "bone_5", "bone_5"),
             ((-0.03, 0.5, 0.55), (0.03, 0.85, 0.62), "bone_8", "bone_8")]
    parts += [((x - 0.04, y - 0.04, 0.0), (x + 0.04, y + 0.04, 0.42), low, high)
              for (x, y), low, high in legs.values()]
    names = list(bones)
    vertices, triangles, leads = [], [], []
    for lo, hi, low, high in parts:
        corners, tris = box(lo, hi)
        triangles += [[i + len(vertices) for i in tri] for tri in tris]
        vertices += corners.tolist()
        leads += [low if corner[2] == lo[2] else high for corner in corners]
    rng = np.random.default_rng(0)
    for point in rng.uniform((-0.12, -0.5, 0.45), (0.12, 0.5, 0.65), (extra, 3)):
        vertices.append(point.tolist())
        leads.append("bone_1")
    weights = np.zeros((len(vertices), len(names)))
    for index, name in enumerate(leads):
        weights[index, names.index(name)] = 1.0
    return {"vertices": np.array(vertices), "triangles": np.array(triangles), "weights": weights,
            "bones": names, "parents": [bones[name][1] for name in names],
            "heads": np.array([bones[name][0] for name in names], float), "armature_count": 1}


def test_a_four_legged_rig_with_a_chain_per_foot_passes():
    report = structure(creature(), LIMBS, LIMITS)
    assert report["status"] == "passed", report["errors"]
    assert report["artifact_kind"] == "rig" and report["errors"] == [] == report["failure_codes"]
    assert report["measured"] == {**report["measured"], "rig_limbs_missing": 0, "rig_bones_outside": 0}
    assert report["measured"]["rig_asymmetry"] == pytest.approx(0.0, abs=1e-9)
    assert report["facing"] == "-Y"
    chains = {(limb["end"], limb["side"]): limb["chain"] for limb in report["limbs"]}
    assert chains == {("hind", "L"): [f"hindL{k}" for k in range(4)], ("hind", "R"): [f"hindR{k}" for k in range(4)],
                      ("front", "L"): [f"frontL{k}" for k in range(5)],
                      ("front", "R"): [f"frontR{k}" for k in range(5)]}
    assert {limb["hub"] for limb in report["limbs"]} == {"bone_0", "bone_3"}


def test_a_leg_painted_on_the_body_is_a_missing_limb():
    # The right foreleg's box is skinned to the chest and its bones are gone: the leg has no chain of its own.
    bones = {name: item for name, item in BONES.items() if not name.startswith("frontR")}
    legs = default_legs()
    legs["frontR"] = ((-0.1, -0.4), "bone_3", "bone_3")
    report = structure(creature(bones, legs), LIMBS, LIMITS)
    assert report["status"] == "failed"
    assert report["failure_codes"] == ["rig_limb_missing"]
    assert report["measured"]["rig_limbs_missing"] == 1
    assert candidate_quality_rejection(report)


def test_a_leg_led_by_a_spine_bone_does_not_stand():
    legs = default_legs()
    legs["hindR"] = ((-0.1, 0.4), "bone_1", "bone_1")
    report = structure(creature(legs=legs), LIMBS, LIMITS)
    assert "rig_limb_missing" in report["failure_codes"]
    assert report["measured"]["rig_limbs_missing"] == 1


def test_twin_legs_with_different_bone_counts_are_asymmetric():
    bones = dict(BONES)
    bones["frontRx"] = ((-0.1, -0.4, 0.17), "frontR2")
    bones["frontR3"] = (BONES["frontR3"][0], "frontRx")
    report = structure(creature(bones), LIMBS, LIMITS)
    assert report["failure_codes"] == ["rig_asymmetric"]
    assert report["measured"]["rig_asymmetry"] == 1.0
    assert candidate_quality_rejection(report)


def test_twin_legs_that_do_not_mirror_are_asymmetric():
    bones = {name: (((x, y + 0.08, z) if name.startswith("frontR") else (x, y, z)), parent)
             for name, ((x, y, z), parent) in BONES.items()}
    legs = default_legs()
    legs["frontR"] = ((-0.1, -0.32), "frontR3", "frontR1")
    report = structure(creature(bones, legs), LIMBS, LIMITS)
    assert report["failure_codes"] == ["rig_asymmetric"]
    assert report["measured"]["rig_asymmetry"] == pytest.approx(0.08 / 0.95, rel=1e-6)
    assert not structure(creature(bones, legs), LIMBS, {**LIMITS, "max_rig_asymmetry": 0.1})["errors"]


def test_a_joint_outside_the_skin_fails():
    bones = dict(BONES)
    bones["bone_8"] = ((0, 0.95, 0.58), "bone_7")    # past the tail's end
    report = structure(creature(bones), LIMBS, LIMITS)
    assert report["failure_codes"] == ["rig_bone_outside"]
    assert report["measured"]["rig_bones_outside"] == 1
    assert report["joints_outside"] == ["bone_8"]
    assert candidate_quality_rejection(report)


def test_weights_and_armatures_are_checked():
    rig = creature()
    rig["weights"][0] = 0.0
    rig["weights"][1, :5] = 0.5                      # three influences summing to 2.5
    rig["armature_count"] = 2
    report = structure(rig, LIMBS, LIMITS)
    assert report["status"] == "failed"
    assert report["measured"]["unweighted_vertices"] == 1
    assert {"rig_weights", "rig_structure"} <= set(report["failure_codes"])
    assert len(report["failure_codes"]) == len(report["errors"])
    assert not candidate_quality_rejection(report)   # not a retryable quality code: fail closed


def test_each_bone_reports_its_share_of_the_skin():
    report = structure(creature(), LIMBS, LIMITS)
    shares = report["skin_share"]
    assert sum(shares.values()) == pytest.approx(1.0)
    assert shares["hindL2"] < 0.004 and shares["bone_1"] > 0.9


def test_a_chain_whose_last_bones_lead_no_skin_on_the_floor_does_not_stand():
    legs = default_legs()
    legs["hindR"] = ((-0.1, 0.4), "hindR1", "hindR2")   # the floor follows the shin, the paw only the leg's top
    report = structure(creature(legs=legs), LIMBS, LIMITS)
    assert report["failure_codes"] == ["rig_limb_missing"]
    assert "do not lead the skin on the floor" in report["errors"][0]


def test_two_feet_on_one_chain_count_as_a_missing_leg():
    legs = default_legs()
    legs["hindR"] = ((-0.1, 0.4), "hindL2", "hindL0")   # both hind feet follow the left leg's bones
    report = structure(creature(legs=legs), LIMBS, LIMITS)
    assert report["failure_codes"] == ["rig_limb_missing"]
    assert "another foot's" in report["errors"][0]
