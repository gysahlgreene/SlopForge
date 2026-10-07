#!/usr/bin/env python3
"""Check local Markdown links and private machine metadata before publication."""
import re
import subprocess
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[1]
tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
# Include new guides before they have been staged.
paths = {root / p for p in tracked if p}
paths.update(root.glob('*.md'))
paths.update((root / 'docs').rglob('*.md'))
errors = []
for path in sorted(paths):
    if not path.is_file():
        continue
    if path.suffix.lower() in {'.png', '.gif'}:
        with Image.open(path) as image:
            text = str({key: value for key, value in image.info.items()
                        if isinstance(value, (str, bytes))})
    elif path.suffix in {'.md', '.json', '.yaml', '.yml', '.txt', '.cs'}:
        text = path.read_text()
    else:
        continue
    if re.search(r'/Users/(?!<)[^/\s]+/|/home/(?!<)[^/\s]+/|https?://100\.(?:\d+\.){2}\d+', text):
        errors.append(f'{path.relative_to(root)}: private machine metadata')
    if path.suffix != '.md':
        continue
    for target in re.findall(r'\]\(([^)]+)\)', text):
        target = target.strip('<>').split('#')[0]
        if not target or '://' in target or target.startswith('mailto:'):
            continue
        if not (path.parent / target).exists():
            errors.append(f'{path.relative_to(root)}: missing link {target}')
if errors:
    raise SystemExit('\n'.join(errors))
print('Documentation links and machine-metadata checks passed.')
