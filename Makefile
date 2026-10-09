PYTHON ?= python3

.PHONY: verify verify-live

verify:
	$(PYTHON) -m compileall -q slopforge processing blender scripts
	$(PYTHON) -m pytest -q -rs
	$(PYTHON) scripts/check-docs.py
	git diff --check

# Explicitly opt in: these checks perform inference on the configured service.
verify-live:
	$(PYTHON) -c 'import os; from pathlib import Path; from slopforge.paths import blender_executable; assert os.environ.get("COMFYUI_URL"), "Set COMFYUI_URL to the intended inference service"; assert Path(blender_executable()).is_file(), "Set BLENDER_BIN to an installed Blender executable"'
	SLOPFORGE_COMFYUI_PREFLIGHT=1 SLOPFORGE_COMFYUI_INTEGRATION=1 SLOPFORGE_COMFYUI_3D_INTEGRATION=1 $(PYTHON) -m pytest -q -rs tests/test_workflow_preflight_live.py tests/test_comfyui_integration.py
