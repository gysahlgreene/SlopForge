# Props provisional evidence: qualification record, criterion v3

Criterion version 3, declared on 2026-10-21 before any v3 run. Results are in the
[evidence report](README.md). Six runs cannot make anything Qualified.

## What changed from v2

Only the pipeline commit. The [v2 runs](../props-provisional-2026-10-v2/README.md) passed five of
six. B2 failed because the local background-removal step aborted in ONNX Runtime's teardown while
exiting, after writing its outputs. A record cannot replace a failed run, so the fix is tested
under a new criterion version with six fresh runs.

- **Fix:** `processing/prepare_3d_input.py` and `processing/prepare_views.py` end with
  `os._exit(0)` once their work succeeds, which skips that teardown. Errors still exit non-zero.
- **Regression test:** a stand-in `rembg` that aborts at exit must not fail either script
  (`tests/test_rembg_exit.py`).
- **Evidence:** the crash was reproduced 2 times in 64 unfixed runs on B2's concept. The fixed script
  ran 96 times under the same load (four in parallel): every run exited 0, and every output was
  byte-identical.

Everything else is unchanged from [criterion v2](../props-provisional-2026-10-v2/QUALIFICATION-RECORD.md):
- the owner's decisions;
- scope, target profile and declared runtime budget;
- the three briefs, word for word, with the same canvases;
- the concept selection criteria, including criterion 4 for round props;
- the stage conditions and the five owner-accepted thresholds;
- independent runs and the procedure;
- permitted and not-permitted interventions;
- review authority, unchecked gates and the status this evidence can support.

The pipeline commit is recorded per run.
