"""The non-metal roughness floor a type can set (min_nonmetal_roughness): round 22's woods, leathers and paints
decoded at roughness 0.38-0.64, and their tops read white under the studio light (2026-11-08)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from slopforge.config import load_project
from slopforge.initializer import init_project
from slopforge.pipelines import model
from slopforge.unity_material import lift_nonmetal_roughness

WOOD, BRASS, IRON, GLASS = (75, 52, 36), (200, 150, 70), (60, 58, 55), (200, 220, 230)


def write_maps(folder, roughness=0.45):
    """Four 2x2 quadrants: wood (non-metal), brass the map marks non-metal, iron (metal), glass (alpha 64)."""
    base = np.zeros((4, 4, 4), np.uint8)
    metal = np.zeros((4, 4), np.uint8)
    for (y, x), colour, alpha, metallic in (((0, 0), WOOD, 255, 0), ((0, 2), BRASS, 255, 0),
                                             ((2, 0), IRON, 255, 255), ((2, 2), GLASS, 64, 0)):
        base[y:y + 2, x:x + 2] = (*colour, alpha)
        metal[y:y + 2, x:x + 2] = metallic
    paths = {name: Path(folder) / f"{name}.png" for name in ("basecolor", "metallic", "roughness")}
    Image.fromarray(base, "RGBA").save(paths["basecolor"])
    Image.fromarray(metal).convert("RGB").save(paths["metallic"])
    Image.new("RGB", (4, 4), (round(roughness * 255),) * 3).save(paths["roughness"])
    return paths


def quadrants(path):
    pixels = np.asarray(Image.open(path).convert("L"))
    return {name: int(pixels[y, x]) for name, (y, x) in
            {"wood": (0, 0), "brass": (0, 2), "iron": (2, 0), "glass": (2, 2)}.items()}


class LiftNonmetalRoughnessTests(unittest.TestCase):
    def test_raises_only_plain_nonmetal(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = write_maps(folder)
            share = lift_nonmetal_roughness(paths["roughness"], paths["metallic"], paths["basecolor"], 0.75)
            values = quadrants(paths["roughness"])
        self.assertEqual(values["wood"], round(0.75 * 255))
        self.assertEqual((values["brass"], values["iron"], values["glass"]), (round(0.45 * 255),) * 3)
        self.assertAlmostEqual(share, 0.25)

    def test_keeps_rougher_texels(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = write_maps(folder, roughness=0.9)
            share = lift_nonmetal_roughness(paths["roughness"], paths["metallic"], paths["basecolor"], 0.75)
            self.assertEqual(quadrants(paths["roughness"])["wood"], round(0.9 * 255))
        self.assertEqual(share, 0.0)


class PublicationFloorTests(unittest.TestCase):
    """A candidate made before its type set the floor gets it when published, so round 22's 89 objects need no
    rebuild; its packed metallic-gloss map is made again from the raised roughness."""

    def publish(self, measured):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            init_project(root)
            config = load_project(root)
            candidate = model.material_candidate_paths(root, config, "relic", 1)
            candidate["basecolor"].parent.mkdir(parents=True, exist_ok=True)
            maps = write_maps(candidate["basecolor"].parent)
            outputs = {}
            for name in ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss",
                         "emission", "preview_front", "preview_side", "preview_rear", "preview_three_quarter"):
                candidate[name].parent.mkdir(parents=True, exist_ok=True)
                if name in maps:
                    maps[name].replace(candidate[name])
                elif name == "metallic_gloss":
                    model.make_metallic_gloss(candidate["metallic"], candidate["roughness"], candidate[name])
                elif candidate[name].suffix == ".png":
                    Image.new("RGB", (4, 4), (90, 90, 255)).save(candidate[name])
                else:
                    candidate[name].write_bytes(b"x")
                outputs[name] = candidate[name].relative_to(root).as_posix()
            (root / "retained.glb").write_bytes(b"glb")
            asset = {"name": "relic", "status": "awaiting_texture_approval", "source": {"glb": "retained.glb"},
                     "generator": {"workflow": {}, "seed": {}},
                     "material_candidates": {"selected": None, "items": [
                         {"number": 1, "status": "candidate", "prompt": "wood", "outputs": outputs,
                          "validation": {"status": "passed", "measured": measured}}]}}
            manifest = {"assets": {"prop:relic": asset}}
            stubs = [patch("slopforge.pipelines.model._delivery_rights",
                           return_value={"status": "cleared", "notices": [], "reasons": [], "sources": []}),
                     patch("slopforge.pipelines.model.unity_cli", return_value="unity"),
                     patch("slopforge.pipelines.model.build_unity_material", return_value={"assets": {}}),
                     patch("slopforge.pipelines.model.build_weapon_prefab",
                           return_value={"errors": [], "motions": []}),
                     patch("slopforge.pipelines.model.verify_play_mode", return_value={"passed": [], "failed": []}),
                     patch("slopforge.pipelines.model.load_taxonomy",
                           return_value={"prop": {"min_nonmetal_roughness": 0.75}})]
            for stub in stubs:
                stub.start()
                self.addCleanup(stub.stop)
            model.approve_texture(root, config, manifest, "prop:relic", 1)
            final = model.model_paths(root, config, "relic")
            return (quadrants(final["roughness"]), np.asarray(Image.open(final["metallic_gloss"]))[0, 0, 3],
                    asset)

    def test_older_candidate_is_floored_at_publication(self):
        roughness, gloss_alpha, asset = self.publish({})
        self.assertEqual(roughness["wood"], round(0.75 * 255))
        self.assertEqual(roughness["brass"], round(0.45 * 255))
        self.assertEqual(gloss_alpha, 255 - round(0.75 * 255))  # smoothness = 1 - roughness
        self.assertEqual(asset["validation"]["measured"]["nonmetal_roughness_floor"]["applied_at"], "publication")

    def test_candidate_already_floored_is_published_as_made(self):
        roughness, _alpha, _asset = self.publish({"nonmetal_roughness_floor": {"floor": 0.75}})
        self.assertEqual(roughness["wood"], round(0.45 * 255))


if __name__ == "__main__":
    unittest.main()
