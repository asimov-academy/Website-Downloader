"""
File inventory - classify all files in a directory by type.
Generates a compact summary (not a verbose per-file listing).
"""
import json
from datetime import datetime
from pathlib import Path

_EXTENSION_TO_TYPE = {
    '.html': 'html',
    '.htm': 'html',
    '.css': 'css',
    '.js': 'js',
    '.mjs': 'js',
    '.cjs': 'js',
    '.woff': 'fonts',
    '.woff2': 'fonts',
    '.ttf': 'fonts',
    '.otf': 'fonts',
    '.eot': 'fonts',
    '.svg': 'icons',
    '.ico': 'icons',
    '.png': 'images',
    '.jpg': 'images',
    '.jpeg': 'images',
    '.webp': 'images',
    '.avif': 'images',
    '.gif': 'images',
    '.bmp': 'images',
    '.glb': 'models',
    '.gltf': 'models',
    '.obj': 'models',
    '.fbx': 'models',
    '.bin': 'models',
    '.hdr': 'models',
    '.riv': 'animations',
    '.mp4': 'media',
    '.webm': 'media',
    '.mov': 'media',
    '.ogg': 'media',
    '.mp3': 'media',
    '.wav': 'media',
    '.m3u8': 'media',
    '.wasm': 'other',
    '.xml': 'data',
    '.csv': 'data',
    '.txt': 'other',
    '.map': 'other',
    '.webmanifest': 'data',
    '.json': 'data',
}

# Types where every filename is listed (small groups, always relevant for AI)
_ENUMERATE_TYPES = {'html', 'css', 'js', 'fonts', 'animations', 'models', 'media'}
# Types where only a sample is shown (can be hundreds of files)
_SAMPLE_TYPES = {'images', 'icons', 'data', 'other'}
_SAMPLE_SIZE = 5

_LOTTIE_KEYS = {'v', 'fr', 'ip', 'op', 'layers'}


def _is_lottie_json(filepath: Path) -> bool:
    try:
        text = filepath.read_text(encoding='utf-8', errors='ignore')[:4096]
        data = json.loads(text)
        if not isinstance(data, dict):
            return False
        return _LOTTIE_KEYS.issubset(data.keys())
    except Exception:
        return False


def classify_file(filepath: Path) -> str:
    """Return the type category for a single file."""
    ext = filepath.suffix.lower()
    file_type = _EXTENSION_TO_TYPE.get(ext, 'other')
    if file_type == 'data' and ext == '.json' and filepath.is_file():
        if _is_lottie_json(filepath):
            return 'animations'
    return file_type


def generate_inventory(source_dir: Path) -> dict:
    """Scan source_dir and return a compact categorized inventory.

    For small groups (html, css, js, fonts, animations, models, media):
      lists every filename.
    For large groups (images, icons, data, other):
      lists only a sample + total count.
    """
    source_dir = Path(source_dir)
    audit_dir = source_dir / 'audit'

    # Accumulate per-type: list of (name, size_bytes)
    raw: dict[str, list] = {t: [] for t in _ENUMERATE_TYPES | _SAMPLE_TYPES}

    total_files = 0
    total_bytes = 0

    for path in sorted(source_dir.rglob('*')):
        if not path.is_file():
            continue
        try:
            path.relative_to(audit_dir)
            continue
        except ValueError:
            pass

        # Skip internal metadata files (underscore prefix at root)
        rel_parts = path.relative_to(source_dir).parts
        if len(rel_parts) == 1 and rel_parts[0].startswith('_'):
            continue
        if path.name == 'serve.py':
            continue

        try:
            size = path.stat().st_size
            file_type = classify_file(path)
            raw.setdefault(file_type, []).append((path.name, size))
            total_files += 1
            total_bytes += size
        except Exception:
            pass

    # Build compact output
    by_type: dict = {}
    for type_name, entries in raw.items():
        if not entries:
            continue
        count = len(entries)
        type_bytes = sum(s for _, s in entries)

        if type_name in _ENUMERATE_TYPES:
            # Full list: just filenames sorted by size desc
            files = [name for name, _ in sorted(entries, key=lambda x: -x[1])]
            by_type[type_name] = {'count': count, 'bytes': type_bytes, 'files': files}
        else:
            # Sample: top-N by size + total
            sample = [name for name, _ in sorted(entries, key=lambda x: -x[1])[:_SAMPLE_SIZE]]
            by_type[type_name] = {'count': count, 'bytes': type_bytes, 'sample': sample}

    return {
        '_meta': {
            'total_files': total_files,
            'total_bytes': total_bytes,
            'generated_at': datetime.now().isoformat(),
        },
        **by_type,
    }


def save_inventory(source_dir: Path) -> dict:
    """Generate and save _file_inventory.json inside source_dir."""
    source_dir = Path(source_dir)
    inventory = generate_inventory(source_dir)
    output_path = source_dir / '_file_inventory.json'
    output_path.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    return inventory
