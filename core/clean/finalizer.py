"""
Final clean-up helpers for the AI-focused clean/ output.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

_BLOCK_INTERTAG_WHITESPACE_PATTERN = re.compile(
    r'(</(?:html|head|body|main|section|article|header|footer|nav|aside|div|ul|ol|li|table|thead|tbody|tr|td|th|picture)>)\s+(<(?:html|head|body|main|section|article|header|footer|nav|aside|div|ul|ol|li|table|thead|tbody|tr|td|th|picture)\b)',
    re.IGNORECASE,
)

_TEXT_EXTENSIONS = frozenset({
    '.html', '.css', '.js', '.mjs', '.cjs', '.json', '.svg', '.md',
    '.txt', '.xml', '.webmanifest',
})
_LS_PS_RE = re.compile(r'[\u2028\u2029]')
_LOTTIE_KEYS = {'v', 'fr', 'ip', 'op', 'layers'}
_EXTERNAL_PREFIXES = ('http://', 'https://', 'data:', 'blob:', '//', '#', 'mailto:', 'tel:')
_GENERATED_REFERENCE_NOISE_RE = re.compile(
    r'/\*\s*\[(?:tracking script removed|CODE COVERAGE)[^\]]*\][^*]*\*/',
    re.IGNORECASE,
)
_RUNTIME_ALIAS_EXTENSIONS = frozenset({
    '.js', '.mjs', '.cjs', '.json', '.webmanifest', '.wasm',
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
})


def prune_unreferenced_data_assets(clean_dir: Path, log=None) -> dict:
    """
    Remove data files from assets/data when they are not referenced anywhere in
    clean/ and are not recognizable Lottie animations.
    """
    _log = log or (lambda m: None)
    data_dir = clean_dir / 'assets' / 'data'
    if not data_dir.exists():
        return {'removed': 0, 'kept': 0}

    text_cache: list[str] = []
    for path in sorted(clean_dir.rglob('*')):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _TEXT_EXTENSIONS:
            continue
        is_data_file = False
        try:
            path.relative_to(data_dir)
            is_data_file = True
        except ValueError:
            pass
        if is_data_file and path.name != 'resource-map.json':
            continue
        try:
            text_cache.append(path.read_text(encoding='utf-8', errors='ignore'))
        except Exception:
            continue

    removed = 0
    kept = 0
    for data_file in sorted(data_dir.glob('*')):
        if not data_file.is_file():
            continue

        rel_path = data_file.relative_to(clean_dir).as_posix()
        basename = data_file.name
        if _is_lottie_json(data_file):
            kept += 1
            continue

        referenced = any(
            token in text
            for text in text_cache
            for token in (rel_path, '/' + rel_path, basename)
        )
        if referenced:
            kept += 1
            continue

        data_file.unlink(missing_ok=True)
        removed += 1

    if removed:
        _prune_empty_dirs(data_dir)
        _log(f'   Finalizer: {removed} arquivo(s) órfãos removidos de assets/data')
    return {'removed': removed, 'kept': kept}


def materialize_runtime_aliases(clean_dir: Path, path_mapping: dict, log=None) -> dict:
    """
    Recreate selected legacy code/data paths as compatibility aliases.

    Some runtimes assemble asset URLs dynamically at execution time, so blind
    path correction cannot always touch the final string literal. Keeping a copy
    of the reorganized file at the old code/data path preserves offline boot
    without needing JS-aware rewrites.
    """
    _log = log or (lambda m: None)
    created = 0
    text_cache = _build_text_reference_cache(clean_dir)

    for old_rel, new_rel in sorted((path_mapping or {}).items()):
        old_path = clean_dir / old_rel
        new_path = clean_dir / new_rel
        if old_path == new_path:
            continue
        if old_path.exists() or not new_path.is_file():
            continue
        if new_path.suffix.lower() not in _RUNTIME_ALIAS_EXTENSIONS:
            continue
        if not _should_materialize_alias(old_rel, text_cache):
            continue

        old_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(new_path, old_path)
        created += 1

    if created:
        _log(f'   Finalizer: {created} alias(es) de compatibilidade materializados')
    return {'created': created}


def _build_text_reference_cache(clean_dir: Path) -> list[str]:
    cache = []
    audit_dir = clean_dir / 'audit'
    for path in sorted(clean_dir.rglob('*')):
        if not path.is_file():
            continue
        try:
            path.relative_to(audit_dir)
            continue
        except ValueError:
            pass
        if path.suffix.lower() not in _TEXT_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        normalized_text = _GENERATED_REFERENCE_NOISE_RE.sub('', text)
        if _should_skip_alias_reference_cache(path, normalized_text):
            continue
        cache.append(normalized_text)
    return cache


def _should_materialize_alias(old_rel: str, text_cache: list[str]) -> bool:
    old_rel = old_rel.strip().lstrip('/')
    if not old_rel:
        return False
    tokens = {
        f'"{old_rel}"',
        f"'{old_rel}'",
        f'`{old_rel}`',
        f'"/{old_rel}"',
        f"'/{old_rel}'",
        f'`/{old_rel}`',
        f'url({old_rel})',
        f'url(/{old_rel})',
        f'url("{old_rel}")',
        f"url('{old_rel}')",
        f'url("/{old_rel}")',
        f"url('/{old_rel}')",
    }
    return any(token in text for text in text_cache for token in tokens)


def _should_skip_alias_reference_cache(path: Path, text: str) -> bool:
    lowered = text.lower()
    if path.suffix.lower() == '.md':
        return True
    if path.name in {'resource-map.json', '_ai_context.md'}:
        return True
    if 'const resourcemap =' in lowered and '[fetch interceptor]' in lowered:
        return True
    return False


def normalize_text_files(root_dir: Path, log=None) -> dict:
    """
    Normalize unusual line terminators and convert leading tab indentation to
    spaces across text files.
    """
    _log = log or (lambda m: None)
    updated = 0

    for path in sorted(root_dir.rglob('*')):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _TEXT_EXTENSIONS:
            continue

        try:
            original = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        normalized = _normalize_text(original)
        if normalized == original:
            continue

        path.write_text(normalized, encoding='utf-8')
        updated += 1

    if updated:
        _log(f'   Finalizer: {updated} arquivo(s) normalizados (tabs/line endings)')
    return {'updated': updated}


def prune_missing_local_html_refs(clean_dir: Path, log=None) -> dict:
    """
    Remove local <script>/<link> references from HTML when the target file does
    not exist anymore after reorganization/consolidation.
    """
    _log = log or (lambda m: None)
    if not _BS4_AVAILABLE:
        return {'updated_files': 0, 'removed_refs': 0}

    updated_files = 0
    removed_refs = 0

    for html_file in sorted(clean_dir.rglob('*.html')):
        try:
            content = html_file.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        soup = BeautifulSoup(content, 'html.parser')
        changed = False

        for script in list(soup.find_all('script', src=True)):
            target = _resolve_local_ref(script.get('src', ''), html_file, clean_dir)
            if target is not None and not target.exists():
                script.decompose()
                changed = True
                removed_refs += 1

        for link in list(soup.find_all('link', href=True)):
            rel = link.get('rel', []) or []
            if isinstance(rel, str):
                rel = [rel]
            rel = {value.lower() for value in rel}
            if not rel.intersection({'stylesheet', 'icon', 'preload', 'modulepreload', 'prefetch', 'apple-touch-icon'}):
                continue
            target = _resolve_local_ref(link.get('href', ''), html_file, clean_dir)
            if target is not None and not target.exists():
                link.decompose()
                changed = True
                removed_refs += 1

        if not changed:
            continue

        html_file.write_text(_serialize_html_stable(soup), encoding='utf-8')
        updated_files += 1

    if removed_refs:
        _log(f'   Finalizer: {removed_refs} referência(s) locais quebradas removidas do HTML')
    return {'updated_files': updated_files, 'removed_refs': removed_refs}


def _serialize_html_stable(soup: BeautifulSoup) -> str:
    html = soup.decode(formatter='minimal')
    return _BLOCK_INTERTAG_WHITESPACE_PATTERN.sub(r'\1\2', html)


def compact_ai_metadata(clean_dir: Path, log=None) -> dict:
    """
    Remove AI sidecar files already distilled into _ai_context.md.
    """
    _log = log or (lambda m: None)
    removable = [
        '_site_classification.json',
        '_computed_styles.json',
        '_site_tokens.md',
        '_scroll_physics.md',
    ]
    removed = 0
    for filename in removable:
        path = clean_dir / filename
        if not path.exists():
            continue
        path.unlink(missing_ok=True)
        removed += 1
    if removed:
        _log(f'   Finalizer: {removed} sidecar(s) de contexto absorvidos por _ai_context.md')
    return {'removed': removed}


def strip_generated_text_comments(clean_dir: Path, log=None) -> dict:
    """
    Remove comments generated by the clean pipeline itself so the final output
    stays focused on the extracted site code.
    """
    _log = log or (lambda m: None)
    updated = 0

    for path in sorted(clean_dir.rglob('*')):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _TEXT_EXTENSIONS:
            continue

        try:
            original = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        cleaned = _GENERATED_REFERENCE_NOISE_RE.sub('', original)
        if cleaned == original:
            continue

        path.write_text(cleaned, encoding='utf-8')
        updated += 1

    if updated:
        _log(f'   Finalizer: {updated} arquivo(s) tiveram comentários gerados removidos')
    return {'updated': updated}


def _normalize_text(content: str) -> str:
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    content = _LS_PS_RE.sub('\n', content)

    lines = []
    for line in content.split('\n'):
        prefix_len = len(line) - len(line.lstrip(' \t'))
        prefix = line[:prefix_len].replace('\t', '  ')
        lines.append(prefix + line[prefix_len:])

    normalized = '\n'.join(lines)
    if normalized and not normalized.endswith('\n'):
        normalized += '\n'
    return normalized


def _is_lottie_json(path: Path) -> bool:
    if path.suffix.lower() != '.json':
        return False
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')[:4096]
        data = json.loads(text)
    except Exception:
        return False
    return isinstance(data, dict) and _LOTTIE_KEYS.issubset(data.keys())


def _prune_empty_dirs(root: Path) -> None:
    for dirpath in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if not dirpath.is_dir():
            continue
        try:
            next(dirpath.iterdir())
        except StopIteration:
            dirpath.rmdir()


def _resolve_local_ref(ref: str, source_file: Path, clean_dir: Path) -> Path | None:
    if not ref or any(ref.startswith(prefix) for prefix in _EXTERNAL_PREFIXES):
        return None
    clean_ref = ref.split('?', 1)[0].split('#', 1)[0].strip()
    if not clean_ref or clean_ref == '/':
        return None
    if clean_ref.startswith('/'):
        return clean_dir / clean_ref.lstrip('/')
    return source_file.parent / clean_ref
