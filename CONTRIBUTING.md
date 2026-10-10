# Contributing

SlopForge focuses on project-aware 3D asset production for Unity, following the
[product contract and document precedence](docs/PRODUCT_CONTRACT.md). Start with the [architecture](docs/ARCHITECTURE.md), [documentation index](docs/README.md), and [open issues](https://github.com/gysahlgreene/SlopForge/issues).

Agents working on SlopForge must follow [AGENTS.md](AGENTS.md): discoveries must become durable pipeline fixes, validation, regression checks, or documented requirements before production resumes.

## Development

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
make verify
```

Normal tests use local fixtures and mocks. Blender tests run when a supported Blender installation is available. GPU, Unity, and external rigging integrations are opt-in; their environment switches are documented in the test modules. Passing offline tests does not qualify generated artwork or replace human review.

Read the [product contract](docs/PRODUCT_CONTRACT.md), [pipeline contract](docs/PIPELINE_CONTRACT.md), [quality contract](docs/QUALITY_CONTRACT.md), [roadmap](ROADMAP.md), and [current state](CURRENT_STATE.md) before substantial work. Complete implementation changes only after `make verify` passes; report skipped coverage. Set `PYTHON` when using a specific interpreter, for example `make verify PYTHON=.venv/bin/python`.

`COMFYUI_URL=<service-url> make verify-live` explicitly runs service preflight and real 2D/3D inference, followed by local Blender preparation. It needs the configured models and Blender (`BLENDER_BIN` can select the executable), consumes inference resources, and does not verify Unity playback. Run the native crop regression with ComfyUI's Python: `python scripts/check_comfy_mask_polarity.py <ComfyUI-directory>`.

## Keep changes reviewable

- Reuse the existing CLI, provider, candidate, and manifest flow.
- Preserve source files, provenance, and failed candidates. Never silently promote an unverified output.
- Keep model weights and provider environments outside the core package.
- Add a focused regression for changed behavior and update the relevant guide.
- For a new workflow, include an API graph and adjacent `.requirements.yaml` declaration.
- Record structural checks, visual review, deformation review, and engine validation separately.
- Keep user and contributor documentation in `docs/`; put personal notes and generated experiments in the ignored `private/` directory.

## Publishing evidence

Commit compact reports and readable previews. Keep raw models, large frame sequences, full generated Unity projects, and duplicate texture maps outside Git. Follow the [security checklist](SECURITY.md): reports must not contain credentials, private service addresses, personal absolute paths, or unsanitized logs. Retain source/model hashes and useful measurements.

SlopForge is MIT licensed. Separately installed nodes, weights, and sample assets retain their own terms; see [third-party notices](THIRD_PARTY_NOTICES.md).
