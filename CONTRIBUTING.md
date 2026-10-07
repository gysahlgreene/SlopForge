# Contributing

SlopForge focuses on reviewed 3D game assets, character rigging, and Unity delivery. Start with the [architecture](docs/ARCHITECTURE.md), [roadmap](docs/CAPABILITY-ROADMAP-2026.md), and [open issues](https://github.com/gysahlgreene/SlopForge/issues).

## Development

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m pytest -q
python scripts/check-docs.py
git diff --check
```

Normal tests use local fixtures and mocks. Blender tests run when a supported Blender installation is available. GPU, Unity, and external rigging integrations are opt-in; their environment switches are documented in the test modules. Passing offline tests does not qualify generated artwork or replace human review.

## Keep changes reviewable

- Reuse the existing CLI, provider, candidate, and manifest flow.
- Preserve source files, provenance, and failed candidates. Never silently promote an unverified output.
- Keep model weights and provider environments outside the core package.
- Add a focused regression for changed behavior and update the relevant guide.
- For a new workflow, include an API graph and adjacent `.requirements.yaml` declaration.
- Record structural checks, visual review, deformation review, and engine validation separately.
- Keep current documentation in `docs/`; put dated experiments in `docs/archive/` or `docs/research/`.

## Publishing evidence

Commit compact reports and readable previews. Keep raw models, large frame sequences, full generated Unity projects, and duplicate texture maps outside Git. Follow the [security checklist](SECURITY.md): reports must not contain credentials, private service addresses, personal absolute paths, or unsanitized logs. Retain source/model hashes and useful measurements.

SlopForge is MIT licensed. Separately installed nodes, weights, and sample assets retain their own terms; see [third-party notices](THIRD_PARTY_NOTICES.md).
