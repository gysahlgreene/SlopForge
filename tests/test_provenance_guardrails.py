"""Provenance mutation table: invalid shapes must reject, valid baseline must pass."""

import copy
import hashlib
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from slopforge.pipelines.reuse import stage_reuse_decision

# ---------------------------------------------------------------------------
# Inline source fixtures for inspect_source
# ---------------------------------------------------------------------------

_LIST_COMP_FILTER_MALFORMED = textwrap.dedent('''\
def filter_malformed(records):
    return [r for r in records if isinstance(r, dict) and r['id']]
''')

_LIST_COMP_NO_UNIQUENESS_CHECK = textwrap.dedent('''\
def select_by_id(records):
    return [r['id'] for r in records]
''')

_LATER_UNIQUE_CHECK = textwrap.dedent('''\
def filter_then_check_unique(records):
    filtered = [r for r in records if r['id']]
    ids = [r['id'] for r in filtered]
    if len(set(ids)) != len(ids):
        return []
    return filtered
''')

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

_VALID_CANDIDATE_REUSE_DECISION = textwrap.dedent('''\
def candidate_reuse_decision(records, wanted):
    ids = [r['id'] for r in records]
    if len(set(ids)) != len(ids):
        return []
    return [r for r in records if r['id'] == wanted]
''')

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


class InspectSourceInlineTests(unittest.TestCase):
    """Test inspect_source against inline function source fixtures."""

    def test_list_comp_filter_malformed_reports_malformed(self):
        """Comprehension filtering with isinstance(record, dict) + id match
        must report 'malformed-member filtering'."""
        from scripts.check_provenance_antipatterns import inspect_source  # noqa: F811

        findings = inspect_source(_LIST_COMP_FILTER_MALFORMED)
        # The comprehension uses isinstance(r, dict) to filter bad records,
        # which should be flagged as malformed-member filtering.
        self.assertTrue(
            any("malformed-member filtering" in f for f in findings),
            f"Expected 'malformed-member filtering' in findings, got {findings}",
        )

    def test_list_comp_no_uniqueness_check_reports_uniqueness_ordering(self):
        """Comprehension selecting by id with no preceding uniqueness check
        must report 'uniqueness ordering'."""
        from scripts.check_provenance_antipatterns import inspect_source  # noqa: F811

        findings = inspect_source(_LIST_COMP_NO_UNIQUENESS_CHECK)
        self.assertTrue(
            any("uniqueness ordering" in f for f in findings),
            f"Expected 'uniqueness ordering' in findings, got {findings}",
        )

    def test_later_uniqueness_check_does_not_suppress(self):
        """A `len(set(ids)) != len(ids)` check after id extraction must NOT
        suppress 'uniqueness ordering' — it comes after, not inside the
        comprehension."""
        from scripts.check_provenance_antipatterns import inspect_source  # noqa: F811

        findings = inspect_source(_LATER_UNIQUE_CHECK)
        self.assertTrue(
            any("uniqueness ordering" in f for f in findings),
            "Expected 'uniqueness ordering' when set-check comes after id extraction",
        )

    def test_candidate_reuse_decision_has_no_antipatterns(self):
        """A valid `candidate_reuse_decision` that (1) builds ids from a
        comprehension, (2) guards on uniqueness, then (3) filters by wanted
        must report zero antipatterns. The id-list comprehension is allowed
        because it constructs the uniqueness keys; the final selection must
        come after the guard."""
        from scripts.check_provenance_antipatterns import inspect_source  # noqa: F811

        findings = inspect_source(_VALID_CANDIDATE_REUSE_DECISION)
        self.assertEqual(
            findings,
            [],
            f"Expected no findings for valid candidate_reuse_decision, got {findings}",
        )

    def test_new_findings_ignores_legacy_patterns_and_reports_added_ones(self):
        from scripts.check_provenance_antipatterns import new_findings

        baseline = """\
def legacy(records, wanted):
    ids = [item['id'] for item in records]
    return [item for item in records if item['id'] == wanted]
"""
        current = baseline + """\

def new_unsafe(records):
    return [item for item in records if isinstance(item, dict) and item['id']]
"""
        findings = new_findings(current, baseline)
        self.assertTrue(findings)
        self.assertEqual({finding[0] for finding in findings}, {"new_unsafe"})
        self.assertIn("malformed-member filtering", {finding[2] for finding in findings})


# ---------------------------------------------------------------------------
# Integration test: audit CLI file scope on a scratch repo
# ---------------------------------------------------------------------------

class TestAuditFileScope(unittest.TestCase):
    """Verify _changed_py_files() only returns the slopforge/ tree, not all
    changed .py files inside a feature-branch scratch repo."""

    def test_changed_py_files_limited_to_slopforge(self):
        # 1. Build a temporary git repo on ``main`` with *exactly* two tracked
        #    Python files: slopforge/decision.py and tests/helper.py.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)

            # Create directory layout
            (repo / "slopforge").mkdir()
            (repo / "tests").mkdir()
            (repo / "slopforge" / "decision.py").write_text("# original decision\\n")
            (repo / "tests" / "helper.py").write_text("# original helper\\n")

            # Initialise repo, local config to avoid interactive prompts
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True,
                           capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo,
                           check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo,
                           check=True, capture_output=True)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True,
                           capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo,
                           check=True, capture_output=True)

            # 3a. Clean main: no changed .py files should be returned.
            (repo / "scripts").mkdir()
            clean_stub = repo / "scripts" / "clean_stub.py"
            clean_stub.write_text("# stub\n")
            import scripts.check_provenance_antipatterns as audit_mod
            original_file = audit_mod.__file__
            audit_mod.__file__ = str(clean_stub)
            try:
                self.assertEqual(
                    audit_mod._changed_py_files(),
                    [],
                    "Clean main checkout should return no changed files",
                )
            finally:
                audit_mod.__file__ = original_file

            # 3. Create a feature branch and modify both files.
            subprocess.run(["git", "checkout", "-b", "feat"], cwd=repo,
                           check=True, capture_output=True)
            (repo / "slopforge" / "decision.py").write_text("# modified decision\\n")
            (repo / "tests" / "helper.py").write_text("# modified helper\\n")
            (repo / "slopforge" / "new_decision.py").write_text("# new decision\\n")

            # 4. Temporarily point the audit module's __file__ at the repo.
            repo_script = repo / "scripts" / "stubs.py"
            repo_script.write_text("# stub so __file__ resolves inside repo\\n")
            original_file = audit_mod.__file__
            audit_mod.__file__ = str(repo_script)
            try:
                changed = audit_mod._changed_py_files()
                repo_resolved = repo.resolve()
                relative_names = sorted(
                    str(p.resolve().relative_to(repo_resolved)) for p in changed
                )
                # Assert the audit returns ONLY slopforge/changed files.
                self.assertEqual(
                    relative_names,
                    ["slopforge/decision.py", "slopforge/new_decision.py"],
                    (f"Expected only slopforge/decision.py but got "
                     f"{relative_names}"),
                )
            finally:
                audit_mod.__file__ = original_file


if __name__ == "__main__":
    unittest.main()
