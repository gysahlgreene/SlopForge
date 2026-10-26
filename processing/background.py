"""Background removal for concept and view cut-outs, with its model named.

rembg's default model became BRIA RMBG-2.0, which is licensed CC BY-NC 4.0 (non-commercial use only), and every
cut-out used it through that default until 2026-10-26. BiRefNet's general model (MIT,
https://github.com/ZhengPeng7/BiRefNet) is named instead. The conditioning stage records this file's hash, so
changing the model cuts the concepts out again on resume.
"""

MODEL = "birefnet-general"
_sessions = {}


def remove_background(image):
    """The image (PIL) with its background removed by MODEL, as RGBA."""
    from rembg import new_session, remove
    if MODEL not in _sessions:
        _sessions[MODEL] = new_session(MODEL)
    return remove(image, session=_sessions[MODEL]).convert("RGBA")
