"""B5 for creatures: a creature type's video settings and the prompt for one motion (AI motion sources plan, package
B5; docs/CREATURES.md, "Video generation"). The wording, the graph, the frames, the retry budget and the intake limits
are the type's data; this module only checks them and fills the template. Pure Python.
"""
INTAKE_LIMITS = ("max_video_duplicate_share", "max_video_frame0_difference", "min_video_presence",
                 "max_video_backdrop_drift",
                 "min_video_motion_share", "max_video_turn", "max_video_view_disagreement",
                 "max_video_limb_disagreement")


def video_settings(asset_type, motion):
    """{workflow, frames, retries, prompt, negative, views, limits} for `motion`; ValueError names a bad declaration."""
    name = asset_type.get("name")
    workflow = asset_type.get("video_workflow")
    if not isinstance(workflow, str) or not workflow:
        raise ValueError(f"asset type {name!r}: video_workflow must name the image-to-video graph")
    motions = asset_type.get("video_motions")
    if not isinstance(motions, dict) or motion not in motions:
        known = ", ".join(sorted(motions)) if isinstance(motions, dict) else "none"
        raise ValueError(f"asset type {name!r} has no video motion {motion!r} (declared: {known})")
    spec = motions[motion]
    frames, retries = spec.get("frames"), spec.get("retries")
    # Wan's latent holds 1 + 4k frames (WanImageToVideo's length steps by 4)
    if isinstance(frames, bool) or not isinstance(frames, int) or not 17 <= frames <= 241 or (frames - 1) % 4:
        raise ValueError(f"video motion {motion!r}: frames must be 1 + 4k from 17 to 241, got {frames!r}")
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 16:
        raise ValueError(f"video motion {motion!r}: retries must be 0 to 16, got {retries!r}")
    prompt, negative = spec.get("prompt"), spec.get("negative", "")
    if not isinstance(prompt, str) or "{left}" not in prompt or "{right}" not in prompt:
        raise ValueError(f"video motion {motion!r}: prompt must place each panel's camera with {{left}} and {{right}}")
    if not isinstance(negative, str):
        raise ValueError(f"video motion {motion!r}: negative must be text")
    views = asset_type.get("video_views")
    if not isinstance(views, dict) or not all(isinstance(text, str) and text for text in views.values()):
        raise ValueError(f"asset type {name!r}: video_views must give each view's wording")
    declared = asset_type.get("video_intake")
    declared = declared if isinstance(declared, dict) else {}
    for key in INTAKE_LIMITS:
        value = declared.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"asset type {name!r}: video_intake.{key} must be a number of 0 or more, got {value!r}")
    return {"workflow": workflow, "frames": frames, "retries": retries, "prompt": prompt, "negative": negative,
            "views": dict(views), "limits": {key: declared[key] for key in INTAKE_LIMITS}}


def video_prompt(settings, *, description, name, views, side):
    """(prompt, negative) for a project whose start frame shows `views` (left panel first) with the side camera on
    the creature's `side`. `description` is the asset's (its first letter lower-cased to sit mid-sentence)."""
    missing = [view for view in views if view not in settings["views"]]
    if missing:
        raise ValueError(f"no video_views wording for the view {missing[0]!r}; declare it in the creature type")
    words = {"name": name, "side": side}
    left, right = (settings["views"][view].format(**words) for view in views)
    subject = description[:1].lower() + description[1:]
    fill = {"subject": subject, "left": left, "right": right, **words}
    return settings["prompt"].format(**fill), settings["negative"].format(**fill)
