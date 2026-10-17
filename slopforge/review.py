import hashlib
import html
import json
import os
import shlex
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .character_quality import is_character_source_review_active


def _safe_project_file(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError(f"Review board asset paths must be project-relative: {relative!r}")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Review board paths must stay within the project: {relative!r}")
    resolved = (root / Path(*path.parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Review board paths must stay within the project: {relative!r}")
    return resolved


def _file_link(root, board_dir, relative):
    path = _safe_project_file(root, relative)
    if not path.is_file():
        return f'<span class="missing">Missing file: {html.escape(relative)}</span>'
    href = quote(Path(os.path.relpath(path, board_dir)).as_posix(), safe="/")
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return f'<a href="{html.escape(href, quote=True)}"><img loading="lazy" src="{html.escape(href, quote=True)}" alt="{html.escape(Path(relative).name, quote=True)}"></a>'
    return f'<a href="{html.escape(href, quote=True)}">{html.escape(relative)}</a>'


def _pre(value):
    return f"<pre>{html.escape(json.dumps(value, indent=2, ensure_ascii=False, default=str))}</pre>"


def _action(command, label):
    return f'<div class="action"><span>{html.escape(label)}</span><code>{html.escape(command)}</code></div>'


def generate_review_board(project_root, manifest, destination="slopforge-review.html"):
    root = Path(project_root).expanduser().resolve()
    destination = Path(destination).expanduser()
    destination = destination.resolve() if destination.is_absolute() else (root / destination).resolve()
    if not destination.is_relative_to(root):
        raise ValueError("Review board output must stay within the project")
    destination.parent.mkdir(parents=True, exist_ok=True)
    assets = manifest.get("assets", {})
    by_id = {asset.get("id"): (key, asset) for key, asset in assets.items() if asset.get("id")}
    anchors = {key: "asset-" + hashlib.sha1(key.encode()).hexdigest()[:12] for key in assets}
    project_arg = shlex.quote(str(root))
    cards = []
    for key, asset in sorted(assets.items(), key=lambda item: (item[1].get("type", ""), item[1].get("name", item[0]))):
        name = str(asset.get("name", key))
        asset_type = str(asset.get("type", "asset"))
        mode = asset.get("generation_mode")
        mode_label = str(mode)
        if asset.get("quality_tier"):
            mode_label += " · " + str(asset["quality_tier"])
        mode_badge = f'<span class="status">{html.escape(mode_label)}</span>' if mode else ""
        anchor = anchors[key]
        relations = []
        parent = by_id.get(asset.get("parent_id"))
        if parent:
            parent_key, parent_asset = parent
            relations.append(f'Parent: <a href="#{anchors[parent_key]}">{html.escape(parent_asset.get("name", parent_key))}</a>')
        children = [(child_key, child) for child_key, child in assets.items() if child.get("parent_id") == asset.get("id")]
        if children:
            links = ", ".join(f'<a href="#{anchors[child_key]}">{html.escape(child.get("name", child_key))}</a>'
                               for child_key, child in sorted(children))
            relations.append(f"Children: {links}")
        if asset.get("dependencies"):
            dependencies = []
            for dependency in asset["dependencies"]:
                pair = by_id.get(dependency.get("asset_id"))
                label = pair[1].get("name", pair[0]) if pair else dependency.get("asset_id", "missing")
                suffix = f" / {dependency['output_id']}" if dependency.get("output_id") else ""
                value = html.escape(str(label) + suffix)
                if pair:
                    value = f'<a href="#{anchors[pair[0]]}">{value}</a>'
                dependencies.append(value)
            relations.append("Dependencies: " + ", ".join(dependencies))
        recipe = asset.get("recipe_instance")
        if recipe:
            stages = ", ".join(f"{html.escape(stage_id)}: {html.escape(stage.get('status', 'unknown'))}"
                                for stage_id, stage in recipe.get("stages", {}).items())
            relations.append(f"Recipe stages: {stages}")
        relation_html = f'<p class="relations">{" · ".join(relations)}</p>' if relations else ""
        sections = []
        candidates = asset.get("candidates", {}).get("items", [])
        for candidate in candidates:
            number = candidate.get("number", "?")
            candidate_anchor = f"{anchor}-candidate-{html.escape(str(number), quote=True)}"
            path = candidate.get("path")
            media = _file_link(root, destination.parent, path) if path else '<span class="missing">No candidate path recorded</span>'
            status = candidate.get("status", "unknown")
            selected = asset.get("candidates", {}).get("selected") == number
            prompt = candidate.get("prompt", candidate.get("description", asset.get("generation_prompt", "")))
            seed = candidate.get("seed", "not recorded")
            generator = candidate.get("generator", asset.get("generator", {}))
            validation = candidate.get("validation", {})
            code = f"slopforge --project {project_arg}"
            exploring = asset.get("generation_mode") == "explore"
            approve = f"{code} approve {shlex.quote(name)} {shlex.quote(str(number))}"
            promote = (f"{code} promote {shlex.quote(name)} {shlex.quote(str(number))} "
                       f"--name {shlex.quote(name + '_asset')}")
            reject = f"{code} reject {shlex.quote(name)} {shlex.quote(str(number))} --reason 'Not selected'"
            regenerate = (f"{code} generate {shlex.quote(asset_type)} {shlex.quote(name)} "
                          f"{shlex.quote(str(asset.get('description', '')))} --count 1 --force")
            provenance = {"generator": generator, "conditioning": asset.get("conditioning"),
                          "candidate": {field: candidate[field] for field in
                                        ("seed", "prompt", "description", "variation", "validation", "approval", "generator")
                                        if field in candidate}}
            actions = []
            if status == "candidate" and not selected and candidate.get("approval") != "approved":
                if exploring:
                    actions.append(_action(promote, "Promote to production"))
                else:
                    actions.append(_action(approve, "Approve"))
                actions.append(_action(reject, "Reject"))
            if not exploring:
                actions.append(_action(regenerate, "Regenerate"))
            actions.append(_action(f"{code} inspect {shlex.quote(name)}", "Inspect provenance"))
            comparisons = " · ".join(
                f'<a href="#{anchor}-candidate-{html.escape(str(other.get("number", "?")), quote=True)}">Compare {html.escape(str(other.get("number", "?")))}</a>'
                for other in candidates if other is not candidate)
            variation = candidate.get("variation")
            variation_html = (f'<p class="variation">Variation: {html.escape(json.dumps(variation, ensure_ascii=False))}</p>'
                              if variation else "")
            sections.append(
                f'<article class="candidate" id="{candidate_anchor}"><div class="preview">{media}</div>'
                f'<h3>Candidate {html.escape(str(number))}{" · selected" if selected else ""}</h3>'
                f'<p><span class="status {html.escape(str(status), quote=True)}">{html.escape(str(status))}</span>'
                f' · Seed {html.escape(str(seed))}</p><p class="prompt">{html.escape(str(prompt))}</p>'
                f'{variation_html}'
                f'<details><summary>Validation and provenance</summary>{_pre({"validation": validation, **provenance})}</details>'
                f'<nav>{comparisons} · <a href="{html.escape(f"#{anchor}", quote=True)}">Asset</a></nav>'
                f'{"".join(actions)}</article>')
        material_items = asset.get("material_candidates", {}).get("items", [])
        for candidate in material_items:
            views = []
            for view in ("preview_front", "preview_side", "preview_rear"):
                relative = candidate.get("outputs", {}).get(view)
                if relative:
                    views.append(f'<div><strong>{html.escape(view.removeprefix("preview_"))}</strong>'
                                 f'{_file_link(root, destination.parent, relative)}</div>')
            sections.append(f'<article class="candidate"><div class="views">{"".join(views)}</div>'
                            f'<h3>Material {html.escape(str(candidate.get("number", "?")))}</h3>'
                            f'<p>Status: {html.escape(str(candidate.get("status", "unknown")))}'
                            f' · Normal map: {html.escape(str(candidate.get("normal_source", "not recorded")))}</p>'
                            f'{_action(f"{code} approve-texture {shlex.quote(name)} {shlex.quote(str(candidate.get("number", "")))}", "Approve texture")}'
                            f'<details><summary>Validation and provenance</summary>{_pre(candidate)}</details></article>')
        outputs = []
        tracked = asset.get("artifacts")
        if tracked:
            output_paths = [(output_id, record.get("path")) for output_id, record in tracked.items()]
        else:
            output_paths = list(asset.get("outputs", {}).items())
        for output_id, path in output_paths:
            if path:
                outputs.append(f'<div><strong>{html.escape(output_id)}</strong>{_file_link(root, destination.parent, path)}</div>')
        if outputs:
            sections.append(f'<article class="candidate"><h3>Tracked outputs</h3><div class="views">{"".join(outputs)}</div></article>')
        for source_review in asset.get("source_quality_reviews", []):
            comparisons = []
            paired_views = (("front", "front"), ("left", "side"), ("rear", "rear"))
            for concept_view, render_view in paired_views:
                concept = source_review.get("concept_views", {}).get(concept_view, {}).get("path")
                render = source_review.get("previews", {}).get(render_view, {}).get("path")
                concept_html = _file_link(root, destination.parent, concept) if concept else '<span class="missing">Concept view missing</span>'
                render_html = _file_link(root, destination.parent, render) if render else '<span class="missing">Model view missing</span>'
                comparisons.append(f'<div><strong>{html.escape(concept_view)} concept</strong>{concept_html}</div>'
                                   f'<div><strong>{html.escape(render_view)} model</strong>{render_html}</div>')
            all_previews = []
            for view, evidence in source_review.get("previews", {}).items():
                path = evidence.get("path")
                if path:
                    all_previews.append(f'<div><strong>{html.escape(view)}</strong>{_file_link(root, destination.parent, path)}</div>')
            closeups = []
            for region in source_review.get("critical_regions", []):
                for field in ("concept_crop", "model_closeup"):
                    evidence = region.get(field, {})
                    path = evidence.get("path")
                    if path:
                        closeups.append(f'<div><strong>{html.escape(region.get("name", "region"))} {html.escape(field.replace("_", " "))}</strong>'
                                        f'{_file_link(root, destination.parent, path)}</div>')
            evidence = {"id": source_review.get("id"), "status": source_review.get("status"),
                        "conditioning": source_review.get("conditioning"), "missing": source_review.get("missing"),
                        "findings": source_review.get("findings"), "unknowns": source_review.get("unknowns"),
                        "sha256": source_review.get("sha256")}
            report_link = _file_link(root, destination.parent, source_review["report_path"]) if source_review.get("report_path") else ""
            inspection_data = source_review.get("inspection")
            inspection = inspection_data.get("path") if isinstance(inspection_data, dict) else None
            inspection_link = _file_link(root, destination.parent, inspection) if inspection else '<span class="missing">Inspection report missing</span>'
            decisions = source_review.get("decisions", [])
            latest = decisions[-1] if decisions else {}
            fresh = is_character_source_review_active(root, asset, source_review)
            decision_text = latest.get("decision", "pending")
            if latest.get("decision") == "rejected":
                decision_text += ": " + str(latest.get("reason", "reason not recorded"))
            sections.append(f'<article class="candidate source-review"><h3>Source geometry review</h3>'
                            f'<p>Completeness: <span class="status">{html.escape(str(source_review.get("status", "unknown")))}</span>'
                            f' · Decision: {html.escape(str(decision_text))} · Evidence: {"current" if fresh else "stale or incomplete"}</p>'
                            f'<div class="views">{"".join(comparisons)}</div><h4>Four model views</h4>'
                            f'<div class="views">{"".join(all_previews)}</div><h4>Critical region close-ups</h4>'
                            f'<div class="views">{"".join(closeups)}</div><h4>Structural evidence</h4>{inspection_link}'
                            f'<h4>Immutable review record</h4>{report_link}<details><summary>Source review facts</summary>{_pre(evidence)}</details></article>')
        sections_html = f'<div class="grid">{"".join(sections)}</div>' if sections else '<p>No candidates or preview outputs yet.</p>'
        description = asset.get("description", "")
        asset_details = {field: asset[field] for field in ("generator", "conditioning", "validation", "approval") if field in asset}
        cards.append(f'<section class="asset" id="{anchor}"><header><h2>{html.escape(name)}</h2>'
                     f'<span class="status">{html.escape(str(asset.get("status", "unknown")))}</span>'
                     f'{mode_badge}<span>{html.escape(asset_type)}</span></header>{relation_html}'
                     f'<p>{html.escape(str(description))}</p>{sections_html}'
                     f'<details><summary>Asset provenance</summary>{_pre(asset_details)}</details></section>')
    page = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SlopForge review</title><style>
body{font:15px system-ui,sans-serif;margin:0;background:#11151b;color:#e8edf2}main{max-width:1500px;margin:auto;padding:24px}
h1{margin:0 0 8px}.muted,.relations{color:#aab6c2}.asset{border:1px solid #34404c;border-radius:12px;margin:24px 0;padding:18px;background:#1a212a}
header{display:flex;align-items:center;gap:12px;flex-wrap:wrap}h2{margin:0}.status{background:#303d4a;border-radius:999px;padding:4px 9px;text-transform:capitalize}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}.candidate{min-width:0;background:#111820;border:1px solid #35414d;border-radius:10px;padding:12px}
.preview{height:260px;background:#090c10;display:grid;place-items:center}.preview img,.views img{max-width:100%;max-height:250px;object-fit:contain}.views{display:flex;gap:12px;overflow:auto}.views>div{min-width:30%}
.prompt{white-space:pre-wrap;overflow-wrap:anywhere}.missing{display:block;padding:12px;color:#ffb4a2;background:#3a211e}details{margin:10px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0c1117;padding:12px;border-radius:8px;max-height:360px;overflow:auto}
.action{margin:8px 0}.action span{display:block;color:#aab6c2;font-size:12px}.action code{display:block;white-space:pre-wrap;overflow-wrap:anywhere;background:#26313c;padding:7px;border-radius:6px;user-select:all}a{color:#89c7ff}
</style><main><h1>SlopForge review board</h1><p class="muted">Static project-local review of candidates and packs. Commands below run through the SlopForge CLI and preserve its approval checks.</p>
""" + "\n".join(cards) + "</main></html>\n"
    destination.write_text(page, encoding="utf-8")
    return destination
