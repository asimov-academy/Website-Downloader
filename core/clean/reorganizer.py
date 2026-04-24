"""
Asset reorganizer - move clean/ assets to type-based subfolders.
Strips bundler hash suffixes, shortens long/random filenames, and
generates a path_mapping dict for downstream path correction.
"""
import re
import shutil
from pathlib import Path

from .file_inventory import classify_file

# Target subfolder for each file type (None = stay at root)
_TYPE_TO_SUBFOLDER = {
    'html':       None,
    'css':        'assets/css',
    'js':         'assets/js',
    'fonts':      'assets/fonts',
    'icons':      'assets/icons',
    'images':     'assets/images',
    'animations': 'assets/animations',
    'models':     'assets/models',
    'media':      'assets/media',
    'data':       'assets/data',
    'other':      'assets/other',
}

# Short prefix used when renaming by type
_TYPE_PREFIX = {
    'css':        'style',
    'js':         'script',
    'fonts':      'font',
    'icons':      'icon',
    'images':     'img',
    'animations': 'anim',
    'models':     'model',
    'media':      'media',
    'data':       'data',
    'other':      'file',
}

# A stem longer than this (after hash removal) triggers a rename
_MAX_STEM_LEN = 25

# Match a trailing bundler hash: '.a3f2c1b2' (6-16 hex chars before extension)
_TRAILING_HASH_RE = re.compile(r'\.[0-9a-f]{6,16}$', re.IGNORECASE)
# Match a leading Webflow/CDN hash prefix: '67b5a02d_' or '67b5a02d-'
_LEADING_HASH_RE = re.compile(r'^[0-9a-f]{8,}[-_]+', re.IGNORECASE)
# Still looks like a hash/random if it contains 8+ consecutive hex chars
_STILL_HEX_RE = re.compile(r'[0-9a-f]{8,}', re.IGNORECASE)


def _strip_hashes(stem: str) -> str:
    """Remove leading and trailing hash segments from a filename stem."""
    stem = _LEADING_HASH_RE.sub('', stem)
    stem = _TRAILING_HASH_RE.sub('', stem)
    return stem


def _needs_rename(stem: str) -> bool:
    """True if the stem (after hash removal) is still too long or hash-like."""
    if not stem:
        return True
    if len(stem) > _MAX_STEM_LEN:
        return True
    if _STILL_HEX_RE.search(stem):
        return True
    return False


def _unique_dest(dest: Path) -> Path:
    """Return dest, or a suffixed variant if it already exists."""
    if not dest.exists():
        return dest
    i = 2
    while True:
        candidate = dest.with_stem(f'{dest.stem}_{i}')
        if not candidate.exists():
            return candidate
        i += 1


def reorganize(clean_dir: Path) -> dict:
    """
    Move files to type-based subfolders in clean/, strip hashes,
    and rename files whose stems remain too long or hash-like.

    Returns path_mapping: {old_relative (POSIX) -> new_relative (POSIX)}.
    HTML files are never moved. Underscore metadata files at root are never moved.
    """
    clean_dir = Path(clean_dir)
    path_mapping: dict = {}
    audit_dir = clean_dir / 'audit'

    # Sequence counters for renamed files, per type prefix
    rename_counters: dict[str, int] = {}

    files_to_process = []
    for path in sorted(clean_dir.rglob('*')):
        if not path.is_file():
            continue

        # Skip audit/ subtree
        try:
            path.relative_to(audit_dir)
            continue
        except ValueError:
            pass

        if path.name == 'serve.py':
            continue

        rel_parts = path.relative_to(clean_dir).parts
        # Skip root-level underscore metadata files
        if len(rel_parts) == 1 and rel_parts[0].startswith('_'):
            continue

        # Skip legacy token sidecars
        if path.name.endswith('_tokens.json'):
            continue

        files_to_process.append(path)

    for old_path in files_to_process:
        old_relative = old_path.relative_to(clean_dir).as_posix()

        if old_path.name == 'resource-map.json':
            target_dir = clean_dir / 'assets'
            target_dir.mkdir(parents=True, exist_ok=True)
            new_path = target_dir / 'resource-map.json'
            new_relative = new_path.relative_to(clean_dir).as_posix()
            if old_path.resolve() != new_path.resolve():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                if new_path.exists():
                    new_path.unlink()
                shutil.move(str(old_path), str(new_path))
                path_mapping[old_relative] = new_relative
            continue

        file_type = classify_file(old_path)
        subfolder = _TYPE_TO_SUBFOLDER.get(file_type)

        # HTML stays wherever it is
        if subfolder is None:
            continue

        ext = old_path.suffix.lower()
        stem = _strip_hashes(old_path.stem)

        if _needs_rename(stem):
            # Assign a short sequential name
            prefix = _TYPE_PREFIX.get(file_type, 'file')
            n = rename_counters.get(prefix, 0) + 1
            rename_counters[prefix] = n
            stem = f'{prefix}_{n:03d}'

        new_name = f'{stem}{ext}'
        target_dir = clean_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        new_path = _unique_dest(target_dir / new_name)
        new_relative = new_path.relative_to(clean_dir).as_posix()

        # No move needed if already in place
        if old_path.resolve() == new_path.resolve():
            continue

        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_path), str(new_path))
        path_mapping[old_relative] = new_relative

    _prune_empty_dirs(clean_dir)
    return path_mapping


def _prune_empty_dirs(root: Path) -> None:
    """Remove empty subdirectories under root (bottom-up)."""
    for dirpath in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if dirpath == root or not dirpath.is_dir():
            continue
        try:
            next(dirpath.iterdir())
        except StopIteration:
            dirpath.rmdir()
