# Props provisional evidence: qualification record, criterion v4

Criterion version 4, declared on 2026-10-21 before any v4 run. Results are in the
[evidence report](README.md). Six runs cannot make anything Qualified.

## What changed from v3

The owner rated all three [v3](../props-provisional-2026-10-v3/README.md) props better than v2 and said
colour accuracy against the concept is important. The v3 B2 jug baked a teal glaze from a cobalt concept,
and no v3 threshold measured that. The owner accepted a colour check on 2026-10-21, and it is now part of
the pipeline (`75f21a1`, in the [materials guide](../../MATERIALS.md)):

| Measure | Pass condition | Where it is checked |
| --- | --- | --- |
| Base colour hue against the concept (CIE dH*, median CIELAB chromaticity) | at most 4 | Pipeline (`max_concept_hue_difference: 4`); above it fails as `colour_hue_shift` and the next seed is tried |
| Base colour saturation against the concept | at least 0.6 of the concept's | Pipeline (`min_concept_chroma_ratio: 0.6`); below it fails as `colour_desaturated` and the next seed is tried |

Near-grey concepts (chroma under 10), such as the lantern's granite, are not checked.

Everything else is unchanged from [criterion v3](../props-provisional-2026-10-v3/QUALIFICATION-RECORD.md)
and [criterion v2](../props-provisional-2026-10-v2/QUALIFICATION-RECORD.md):
- the briefs and canvases;
- the concept criteria;
- the stage conditions and the earlier thresholds;
- the procedure;
- the interventions;
- review authority and unchecked gates.

The pipeline commit is recorded per run.
