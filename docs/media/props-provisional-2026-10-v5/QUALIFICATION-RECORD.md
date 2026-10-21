# Props provisional evidence: qualification record, criterion v5

Criterion version 5, declared on 2026-10-21 before any v5 run. Results are in the
[evidence report](README.md). Six runs cannot make anything Qualified.

## What changed from v4

The [v4 runs](../props-provisional-2026-10-v4/README.md) showed that the colour check measured the whole
texture atlas, including hidden insides and bases. It failed a cobalt jug on saturation and passed a teal
one. The check now renders the candidate's base colour from the concept's fitted view
(`blender/concept_view.py`, silhouette fit at least 0.8) and compares that with the concept.
- If no such view fits, only hue is checked, on the whole atlas. A warning records that saturation was not
  checked.
- The thresholds are unchanged and owner-accepted: dH* at most 4, and saturation at least 0.6 of the
  concept's.
- A failing candidate retries the next seed.
- Candidate failure messages now name their failure codes.

Everything else is unchanged from [criterion v4](../props-provisional-2026-10-v4/QUALIFICATION-RECORD.md) and
the criteria it builds on: the briefs, concept criteria, stage conditions and thresholds, procedure,
interventions, review authority and unchecked gates. The pipeline commit is recorded per run.
