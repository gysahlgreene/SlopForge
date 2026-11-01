"""B1: a raw creature rig checked against its limb declaration, on a four-legged box fixture (no Blender)."""
import copy
import math
from pathlib import Path

import numpy as np
import pytest

from slopforge.creature_rig import bone_names, check_rig, deformation_poses, fit_bones, structure
from slopforge.failures import candidate_quality_rejection

LIMBS = {"ground_contact": 4}
LIMITS = {"max_rig_limbs_missing": 0, "max_rig_asymmetry": 0.05, "max_rig_bones_outside": 0, "max_rig_head_turn": 0.05}

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


def creature(bones=BONES, legs=None, extra=4000, body="bone_1"):
    """Boxes for body, head, tail and four legs, each skinned to one bone; a leg's floor corners follow its paw.
    `extra` vertices inside the body follow the spine, as a dense fur body outweighs thin legs (#139)."""
    legs = legs or default_legs()
    parts = [((-0.15, -0.55, 0.4), (0.15, 0.55, 0.7), body, body),
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
        leads.append(body)
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


NAMES = {"bone_0": "Hips", "bone_1": "Spine1", "bone_2": "Spine2", "bone_3": "Chest", "bone_4": "Neck1",
         "bone_5": "Head", "bone_6": "HeadEnd", "bone_7": "Tail1", "bone_8": "Tail2",
         **{f"hind{s}{k}": name + "." + s for s in "LR" for k, name in enumerate(("Thigh", "Shin", "HindPaw", "HindToes"))},
         **{f"front{s}{k}": name + "." + s for s in "LR"
            for k, name in enumerate(("Scapula", "UpperArm", "Forearm", "FrontPaw", "FrontToes"))}}


def named(bones=BONES, legs=None):
    rig = creature(bones, legs)
    return bone_names(structure(rig, LIMBS, LIMITS), rig)


def test_a_passing_quadruped_gets_video2rigs_generic_names():
    names = named()
    assert names == NAMES
    assert not any(name.startswith(("Left", "Right")) for name in names.values())   # no humanoid vocabulary


def test_bones_past_a_chains_names_are_unfitted_ends():
    bones = dict(BONES)
    bones["hindLx"] = ((0.1, 0.37, 0.02), "hindL3")      # a fifth hind bone on each side, the floor on the last two
    bones["hindRx"] = ((-0.1, 0.37, 0.02), "hindR3")
    bones["bone_9"] = ((0, -0.78, 0.9), "bone_5")        # a second branch off the head (an ear)
    legs = default_legs()
    legs.update({f"hind{s}": ((x, 0.4), f"hind{s}3", f"hind{s}0") for s, x in (("L", 0.1), ("R", -0.1))})
    names = named(bones, legs)
    assert names["hindLx"] == "HindToesEnd.L" and names["hindRx"] == "HindToesEnd.R"
    assert {names["bone_6"], names["bone_9"]} == {"HeadEnd", "HeadEnd1"}
    rig = creature(bones, legs)
    shares = structure(rig, LIMBS, LIMITS)["skin_share"]           # these ends lead no skin
    assert not {"HindToesEnd.L", "HeadEnd", "HeadEnd1"} & set(fit_bones(names, shares))


def pelvis_rig():
    """The rabbit's seed 3 (2026-10-31): the root a little behind the hind legs, the tail off a bone of that pelvis, the
    hind legs one bone further along the spine, and single leaf bones off the hind legs' and front legs' hubs."""
    bones = {"pelvis0": ((0, 0.46, 0.55), None), "pelvis1": ((0, 0.44, 0.55), "pelvis0"), **BONES}
    bones["bone_0"] = (BONES["bone_0"][0], "pelvis1")
    bones["bone_7"] = (BONES["bone_7"][0], "pelvis1")
    bones["belly"] = ((0, 0.3, 0.42), "bone_0")
    bones["breast"] = ((0, -0.3, 0.42), "bone_3")
    return bones


def test_a_root_behind_the_hind_legs_is_the_hips_and_leaf_bones_on_the_body_are_ends():
    names = named(pelvis_rig())
    assert names["pelvis0"] == "Hips" and names["bone_3"] == "Chest"
    assert [names[bone] for bone in ("pelvis1", "bone_0", "bone_1", "bone_2")] == ["Spine1", "Spine2", "Spine3", "Spine4"]
    assert names["bone_7"] == "Tail1" and names["bone_8"] == "Tail2" and names["hindL0"] == "Thigh.L"
    assert names["belly"] == "Spine2End" and names["breast"] == "ChestEnd"


def test_only_the_spine_between_the_hind_legs_and_the_chest_counts_as_bending():
    report = check_rig(creature(pelvis_rig()), LIMBS, {**LIMITS, "min_rig_spine_bones": 2})
    assert report["status"] == "passed" and report["measured"]["rig_spine_bones"] == 2    # not the pelvis's two


def test_a_rig_read_backwards_is_still_refused():
    """A root behind the hind legs is accepted only on the line to the front legs: read from the wrong end, the
    "hind" hub is not on it."""
    bones = dict(BONES)
    bones["bone_3"] = (BONES["bone_3"][0], "bone_2")
    rig = creature(bones)
    report = structure(rig, LIMBS, LIMITS)
    report["limbs"] = [{**limb, "end": "hind" if limb["end"] == "front" else "front"} for limb in report["limbs"]]
    with pytest.raises(ValueError, match="hind legs leave the body at bone_3, not on the line from the root bone_0"):
        bone_names(report, rig)


def test_two_chains_off_the_hips_cannot_be_named():
    bones = {**BONES, "second0": ((0, 0.5, 0.5), "bone_0"), "second1": ((0, 0.5, 0.45), "second0")}
    rig = creature(bones)
    with pytest.raises(ValueError, match="2 chains leave the hips"):
        bone_names(structure(rig, LIMBS, LIMITS), rig)


def test_an_undeclared_chain_off_the_chest_cannot_be_named():
    bones = {**BONES, "wing": ((0, -0.3, 0.68), "bone_3"), "wing1": ((0, -0.25, 0.6), "wing")}
    rig = creature(bones)
    with pytest.raises(ValueError, match="2 chains leave the chest besides the front legs"):
        bone_names(structure(rig, LIMBS, LIMITS), rig)


def test_a_chain_off_the_spine_cannot_be_named():
    bones = {**BONES, "wing": ((0, 0.1, 0.68), "bone_1"), "wing1": ((0, 0.1, 0.6), "wing")}
    rig = creature(bones)
    with pytest.raises(ValueError, match="wing branches off the Spine1"):
        bone_names(structure(rig, LIMBS, LIMITS), rig)


def test_fit_bones_declare_thin_paws_the_auto_rule_would_drop():
    """#139: video2rig's auto rule fits only bones leading over 0.4 % of the skin; the declared list keeps every limb
    bone, the spine, neck, head and tail, symmetric left and right, without end bones."""
    rig = creature()
    report = structure(rig, LIMBS, LIMITS)
    paws = [raw for raw in rig["bones"] if NAMES[raw].startswith(("FrontPaw", "HindPaw", "FrontToes", "HindToes"))]
    assert paws and all(report["skin_share"][raw] < 0.004 for raw in paws)
    fit = fit_bones(bone_names(report, rig), report["skin_share"])
    assert set(fit) == set(NAMES.values()) - {"HeadEnd"}
    assert {name[:-2] for name in fit if name.endswith(".L")} == {name[:-2] for name in fit if name.endswith(".R")}


def test_the_review_poses_use_only_bones_the_rig_has():
    poses = deformation_poses(set(NAMES.values()))
    assert [pose["label"] for pose in poses] == ["rest", "left fore lifted", "right hind lifted",
                                                 "head up and turned", "tail up and aside", "spine bent"]
    assert poses[0]["rotations"] == {}
    used = {bone for pose in poses for bone in pose["rotations"]}
    assert used <= set(NAMES.values())
    assert {"Spine1", "Spine2", "Tail1", "Tail2", "Neck1", "Head"} <= used


def test_the_creature_type_declares_four_legs_and_its_rig_limits(tmp_path):
    import shutil
    import yaml
    from slopforge.creature_rig import rig_settings
    from slopforge.taxonomy import load_taxonomy
    template = Path(__file__).resolve().parents[1] / "templates/asset_types/creature.yaml"
    (tmp_path / "ai/asset_types").mkdir(parents=True)
    shutil.copy(template, tmp_path / "ai/asset_types/creature.yaml")
    creature_type = load_taxonomy(tmp_path)["creature"]
    assert creature_type["pipeline"] == "model"
    # owner ruling 2026-10-30 (#154): the skin is weighted again by bone heat on a voxel proxy
    assert rig_settings(creature_type) == {"limbs": LIMBS, "limits": {**LIMITS, "min_rig_spine_bones": 2}, "seeds": 4,
                                           "skin_weights": "proxy_heat",
                                           "straighten_head": True}
    with pytest.raises(ValueError, match="max_rig_head_turn"):
        rig_settings({**creature_type, "max_rig_head_turn": -1})
    # the finish straightens a turned head (owner's choice, 2026-10-31); undeclared, it does not
    assert rig_settings(creature_type)["straighten_head"] is True
    assert rig_settings({**creature_type, "straighten_head": None})["straighten_head"] is False
    with pytest.raises(ValueError, match="straighten_head"):
        rig_settings({**creature_type, "straighten_head": "yes"})
    # the concept keeps the head in line with the body: a three-quarter view otherwise turns it to the camera
    import yaml
    rules = " ".join(yaml.safe_load(template.read_text())["requirements"])
    assert "in line with the body" in rules and "not turned toward the viewer" in rules
    assert rig_settings({**creature_type, "skin_weights": None})["skin_weights"] == "skintokens"   # undeclared
    with pytest.raises(ValueError, match="skin_weights"):
        rig_settings({**creature_type, "skin_weights": "heat"})
    for bad in ({"ground_contact": 6}, {"ground_contact": 4, "wings": 2}, None):
        with pytest.raises(ValueError, match="quadrupeds only"):
            rig_settings({**creature_type, "limbs": bad})
    with pytest.raises(ValueError, match="max_rig_asymmetry"):
        rig_settings({**creature_type, "max_rig_asymmetry": 2})
    assert yaml.safe_load(template.read_text())["limbs"] == LIMBS


def test_a_checked_rig_carries_its_names_and_fit_bones_or_why_it_has_none():
    report = check_rig(creature(), LIMBS, LIMITS)
    assert report["status"] == "passed" and report["names"] == NAMES
    assert report["fit_bones"] == fit_bones(report["names"], report["skin_share"])
    assert set(report["fit_bones"]) == set(NAMES.values()) - {"HeadEnd"}
    bones = {**BONES, "wing": ((0, -0.3, 0.68), "bone_3"), "wing1": ((0, -0.25, 0.6), "wing")}
    report = check_rig(creature(bones), LIMBS, LIMITS)
    assert report["status"] == "failed" and report["failure_codes"] == ["rig_structure"]
    assert report["errors"] == ["the rig cannot be named: 2 chains leave the chest besides the front legs; "
                                "a quadruped has one neck"]
    assert "names" not in report and not candidate_quality_rejection(report)


def test_a_skull_that_branches_is_the_head_even_when_its_jaw_leads_the_skin():
    # the neck line ends at the skull, whose jaw and ears are its children; the jaw leads the head's skin
    bones = {**BONES, "jaw": ((0, -0.7, 0.72), "bone_5"), "ear": ((0, -0.6, 0.9), "bone_5")}
    bones.pop("bone_6")
    rig = creature(bones)
    head = [index for index, corner in enumerate(rig["vertices"])
            if corner[1] <= -0.5 and corner[2] >= 0.6 and abs(corner[0]) <= 0.1]   # the head box, every corner
    rig["weights"][head] = 0.0
    rig["weights"][head, rig["bones"].index("jaw")] = 1.0
    names = check_rig(rig, LIMBS, LIMITS)["names"]
    assert (names["bone_4"], names["bone_5"]) == ("Neck1", "Head")
    assert {names["jaw"], names["ear"]} == {"HeadEnd", "HeadEnd1"}


def test_a_creature_facing_plus_y_is_named_from_its_own_head_end():
    turned = {name: ((-x, -y, z), parent) for name, ((x, y, z), parent) in BONES.items()}   # turned half a circle
    rig = creature(turned)
    rig["vertices"] = rig["vertices"] * (-1, -1, 1)
    report = check_rig(rig, LIMBS, LIMITS)
    assert report["status"] == "passed" and report["facing"] == "+Y"
    assert report["names"] == NAMES       # still left is left: up x forward


def test_a_tail_standing_above_the_head_is_refused_not_mislabelled():
    bones = {**BONES, "bone_8": ((0, 0.72, 1.1), "bone_7")}
    rig = creature(bones)
    tail = rig["bones"].index("bone_8")
    corners, tris = box((-0.03, 0.5, 0.55), (0.03, 0.85, 1.2))   # the tail raised past the ears
    rig["vertices"][8 * 2:8 * 3] = corners
    report = check_rig(rig, LIMBS, LIMITS)
    assert report["status"] == "failed" and report["failure_codes"] == ["rig_structure"]
    assert "highest skin" in report["errors"][0] and "+Y" in report["errors"][0]
    assert rig["vertices"][:, 2].argmax() // 8 == 2 and tail     # the highest skin is the tail's


def test_an_end_bone_that_leads_skin_is_fitted():
    """Owner ruling (2026-10-27): fit_bones includes every bone that leads skin, end bones included. A five-bone hind
    leg's last bone is HindToesEnd and carries the floor skin, as on the B1 wolf (0.40 % of its skin)."""
    bones = {**BONES, "hindLx": ((0.1, 0.37, 0.02), "hindL3"), "hindRx": ((-0.1, 0.37, 0.02), "hindR3")}
    legs = default_legs()
    legs.update({f"hind{s}": ((x, 0.4), f"hind{s}x", f"hind{s}0") for s, x in (("L", 0.1), ("R", -0.1))})
    report = check_rig(creature(bones, legs), LIMBS, LIMITS)
    assert report["status"] == "passed"
    assert {"HindToesEnd.L", "HindToesEnd.R"} <= set(report["fit_bones"])
    assert "HeadEnd" not in report["fit_bones"]          # an end that leads no skin stays out


def turned_head(dx=0.15):
    """The fixture with its head's skin and joints moved `dx` to its left: a head turned off the body's line."""
    rig = creature()
    head = [rig["bones"].index(name) for name in ("bone_5", "bone_6")]
    rig["vertices"][rig["weights"][:, head].sum(1) > 0.5, 0] += dx
    rig["heads"][head, 0] += dx
    return rig


def test_a_turned_head_is_measured_and_its_yaw_is_signed():
    """2026-10-30, owner: "from the front view the face is always angled". The B1 wolf's muzzle stood 0.063-0.072 of
    its height off the line through its hips and chest (its concept turned the head to the camera); concepts asked to
    keep it in line turned it the other way. The check measures the turn; the finish straightens it (owner's choice)."""
    from slopforge.creature_rig import head_yaw
    straight = check_rig(creature(), LIMBS, LIMITS)
    assert straight["status"] == "passed" and straight["measured"]["rig_head_turn"] == pytest.approx(0, abs=1e-6)
    assert head_yaw(creature(), straight["names"]) == pytest.approx(0, abs=1e-6)
    turned = turned_head()
    report = check_rig(turned, LIMBS, LIMITS)
    height = np.ptp(turned["vertices"][:, 2])
    assert report["status"] == "passed"                         # the finish straightens it; no seed would
    assert report["measured"]["rig_head_turn"] == pytest.approx(0.15 / height, rel=0.02)
    # the muzzle (the head skin's forward-most fifth: x 0.15, y -0.8) seen from the neck's base (0, -0.52), against
    # the body's line from the hips to the chest (-y): turned toward the creature's left (+x), positive
    assert head_yaw(turned, report["names"]) == pytest.approx(math.degrees(math.atan2(0.15, 0.28)), abs=0.01)
    assert head_yaw(turned_head(-0.15), report["names"]) == pytest.approx(-math.degrees(math.atan2(0.15, 0.28)), abs=0.01)


def test_a_rig_whose_body_has_too_few_spine_bones_is_refused():
    """The rabbit (2026-10-31): SkinTokens' seed 1 joined the hips straight to the chest, 61 cm away, so the body could
    not bend, and every check passed it. The fixture's body has two spine bones."""
    bones = {name: bone for name, bone in BONES.items() if name not in ("bone_1", "bone_2")}
    bones["bone_3"] = (BONES["bone_3"][0], "bone_0")
    limits = {**LIMITS, "min_rig_spine_bones": 2}
    rig = creature(bones, body="bone_0")
    report = check_rig(rig, LIMBS, limits)
    assert report["status"] == "failed" and report["failure_codes"] == ["rig_spine"]
    assert report["measured"]["rig_spine_bones"] == 0 and "2" in report["errors"][0] and "spine" in report["errors"][0]
    assert candidate_quality_rejection(report)                 # the next seed is tried
    passing = check_rig(creature(), LIMBS, limits)
    assert passing["status"] == "passed" and passing["measured"]["rig_spine_bones"] == 2
    # a project's older copy of the type declares no limit: measured, not refused
    assert check_rig(rig, LIMBS, LIMITS)["status"] == "passed"


def test_a_too_short_spine_is_a_rig_candidates_quality_failure():
    from slopforge.failures import _KIND_CODES
    assert _KIND_CODES["rig"]["rig_spine"] == ("rig_spine_bones", "min_rig_spine_bones")


def test_the_creature_type_asks_for_a_spine_that_bends(tmp_path):
    import yaml
    from slopforge.creature_rig import rig_settings
    template = Path(__file__).resolve().parents[1] / "templates/asset_types/creature.yaml"
    declared = yaml.safe_load(template.read_text())
    assert rig_settings(declared)["limits"]["min_rig_spine_bones"] == 2
    with pytest.raises(ValueError, match="min_rig_spine_bones"):
        rig_settings({**declared, "min_rig_spine_bones": 1.5})
