"""Resolve relocated texture paths within a downloaded asset package."""
from pathlib import Path
import re


def texture_key(name):
    path = Path(name)
    extension = path.suffix.casefold()
    if extension == '.jpeg': extension = '.jpg'
    return re.sub(r'[\s_-]+', '', path.stem.casefold()) + extension


class TextureResolver:
    def __init__(self, asset):
        self.asset = Path(asset).resolve()
        self.root = self.asset.parent
        for parent in self.asset.parents:
            if any((parent / marker).is_file() for marker in ('scene-index.json', 'people-index.json', 'asset.json')):
                self.root = parent
                break
        self.index = None

    def find(self, filepath, resolved_path=None):
        relative = filepath.replace('\\', '/').removeprefix('//')
        filename = relative.rsplit('/', 1)[-1]
        candidates = [self.asset.parent / relative, self.root / relative,
                      self.asset.parent / 'textures' / filename]
        if resolved_path: candidates.insert(0, Path(resolved_path))
        for path in candidates:
            if path.is_file(): return path.resolve()
        if self.index is None:
            self.index = {}
            for path in sorted(self.root.rglob('*')):
                if path.is_file():
                    self.index.setdefault(texture_key(path.name), []).append(path)
        matches = self.index.get(texture_key(filename), [])
        # Prefer exact basenames; never silently choose among multiple candidates.
        exact = [path for path in matches if path.name.casefold() == filename.casefold()]
        matches = exact or matches
        return matches[0].resolve() if len(matches) == 1 else None
