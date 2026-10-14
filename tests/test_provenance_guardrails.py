"""Provenance mutation table: invalid shapes must reject, valid baseline must pass."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from slopforge.pipelines.reuse import stage_reuse_decision

# ---------------------------------------------------------------------------
# Shared fixture: produces a real temp file + valid stage dict
# ---------------------------------------------------------------------------

def _make_valid_stage(root: Path) -> dict:
    """Create one real output file and a compliant concept_generation stage."""
    data = b"concept image bytes"
    file = root / "concept_image.png"
    file.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    return {
        "name": "concept_generation",
        "attempt": 1,
        "status": "succeeded",
        "inputs": [],
        "settings": {},
        "outputs": [
            {
                "id": "image.concept:1",
                "type": "image.concept",
                "path": "concept_image.png",
                "sha256": sha,
                "stage": "concept_generation",
                "attempt": 1,
                "derived_from": [],
            }
        ],
    }

# Five planned invalid-mutation cases: (label, mutation_fn)

MUTATIONS = (
    (
        "malformed sibling",
        lambda s: s["outputs"].append(None),
    ),
    (
        "incomplete output",
        lambda s: s["outputs"][0].pop("sha256"),
    ),
    (
        "duplicate output ID",
        lambda s: s["outputs"].append(dict(s["outputs"][0])),
    ),
    (
        "contradictory lineage",
        lambda s: s["outputs"][0]["derived_from"].append(
            {"artifact_id": "foreign", "sha256": "f" * 64}
        ),
    ),
    (
        "malformed output collection",
        lambda s: s.__setitem__("outputs", None),
    ),
)


class ProvenanceGuardrailTests(unittest.TestCase):
    def test_valid_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stage = _make_valid_stage(root)
            result = stage_reuse_decision(root, stage, inputs=[], settings={})
            self.assertTrue(result["reusable"], msg=str(result.get("reasons", [])))

    def test_invalid_mutations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for label, mutation_fn in MUTATIONS:
                # Fresh copy of the valid baseline for every subTest.
                stage = _make_valid_stage(root)
                stage = copy.deepcopy(stage)
                mutation_fn(stage)
                with self.subTest(label=label):
                    result = stage_reuse_decision(root, stage, inputs=[], settings={})
                    self.assertFalse(result["reusable"])


if __name__ == "__main__":
    unittest.main()
