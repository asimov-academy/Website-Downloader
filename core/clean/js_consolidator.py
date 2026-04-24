"""
JS consolidator - merge very small extracted JS files into a single utils.js.

Reference repair is performed in a dedicated follow-up step so audit snapshots
can separate "file reduction" from "link repair".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

_UTILS_FILENAME = 'utils.js'
_SMALL_SCRIPT_MAX_BYTES = 12000
_LINEAR_SCRIPT_MAX_BYTES = 25000
_NEXT_FLIGHT_MARKERS = ('self.__next_f.push', '\"/_next/static/chunks/', "'/_next/static/chunks/")
_EXCLUDED_JS_NAMES = {'utils.js', 'sw.js', 'service-worker.js'}
_EXCLUDED_JS_PREFIXES = ('workbox-',)


def consolidate_js(clean_dir: Path, log=None) -> dict:
    """
    Merge small JS files referenced by HTML into one or more utils bundles.

    Returns:
      {
        "mapping": {old_relative_path -> new_relative_path},
        "bundles": [
          {
            "path": "assets/js/utils.js",
            "source_paths": [...],
            "source_names": [...],
            "attrs": {...},
          },
        ],
      }
    """
    _log = log or (lambda m: None)
    js_dir = clean_dir / 'assets' / 'js'
    if not js_dir.exists() or not _BS4_AVAILABLE:
        return {'mapping': {}, 'bundles': []}

    html_refs = _collect_html_script_refs(clean_dir, js_dir)
    candidates_by_group: dict[str, list[Path]] = {}
    group_meta: dict[str, dict] = {}
    candidate_refs: list[dict] = []

    for ref in html_refs:
        js_file = ref['path']
        try:
            size = js_file.stat().st_size
        except OSError:
            continue
        try:
            content = js_file.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        if not _should_merge_js(js_file.name, content, size):
            continue

        candidate_refs.append(ref)

    if not candidate_refs:
        _log('   JS consolidator: nenhum script pequeno referenciado no HTML encontrado')
        return {'mapping': {}, 'bundles': []}

    candidate_refs.sort(key=lambda ref: (ref['html'].as_posix(), ref['order_index']))

    current_group_key = None
    current_html = None
    current_sig = None
    current_order = None
    group_sequence = 0

    for ref in candidate_refs:
        attrs_sig = ref['group_key']
        should_start_new_group = (
            current_html != ref['html']
            or current_sig != attrs_sig
            or current_order is None
            or ref['order_index'] != current_order + 1
        )
        if should_start_new_group:
            group_sequence += 1
            current_group_key = f"{ref['html'].as_posix()}::{group_sequence}::{attrs_sig}"

        existing = candidates_by_group.setdefault(current_group_key, [])
        if ref['path'] not in existing:
            existing.append(ref['path'])
        group_meta[current_group_key] = {
            'attrs': ref['attrs'],
            'tag_name': ref['tag_name'],
        }
        current_html = ref['html']
        current_sig = attrs_sig
        current_order = ref['order_index']

    total_candidates = sum(len(files) for files in candidates_by_group.values())
    _log(f'   JS consolidator: mesclando {total_candidates} script(s) pequeno(s)...')

    old_to_new: dict[str, str] = {}
    bundles: list[dict] = []

    for bundle_index, (group_key, candidates) in enumerate(candidates_by_group.items(), start=1):
        parts: list[str] = []
        seen_content: set[str] = set()

        for js_file in candidates:
            if not js_file.is_file():
                continue
            raw = js_file.read_text(encoding='utf-8', errors='ignore').strip()
            if not raw:
                continue

            lines = raw.splitlines()
            if lines and lines[0].startswith('/* [CODE COVERAGE]'):
                lines = lines[1:]
            content = '\n'.join(lines).strip()
            if not content:
                continue

            norm = re.sub(r'\s+', ' ', content)
            if norm in seen_content:
                continue
            seen_content.add(norm)
            parts.append(content)

        if not parts:
            continue

        bundle_name = _UTILS_FILENAME if bundle_index == 1 else f'utils_{bundle_index:03d}.js'
        bundle_rel = f'assets/js/{bundle_name}'
        bundle_path = js_dir / bundle_name
        bundle_path.write_text('\n;\n'.join(parts) + '\n', encoding='utf-8')

        source_paths = []
        for js_file in candidates:
            old_rel = js_file.relative_to(clean_dir).as_posix()
            old_to_new[old_rel] = bundle_rel
            source_paths.append(old_rel)
            js_file.unlink(missing_ok=True)

        _log(f'   JS consolidator: → {bundle_name} ({len(parts)} scripts mesclados)')
        bundles.append({
            'path': bundle_rel,
            'source_paths': source_paths,
            'source_names': [Path(path).name for path in source_paths],
            'attrs': group_meta[group_key]['attrs'],
            'tag_name': group_meta[group_key]['tag_name'],
        })

    return {'mapping': old_to_new, 'bundles': bundles}


def _should_merge_js(name: str, content: str, size: int) -> bool:
    if size <= _SMALL_SCRIPT_MAX_BYTES:
        return True

    line_count = max(1, len(content.splitlines()))
    if size <= _LINEAR_SCRIPT_MAX_BYTES and line_count <= 4:
        return True

    if size <= _LINEAR_SCRIPT_MAX_BYTES and any(marker in content for marker in _NEXT_FLIGHT_MARKERS):
        return True

    return False


def repair_js_references(
    clean_dir: Path,
    plan: dict,
    log,
) -> int:
    """
    Replace multiple small <script src="..."> tags with the generated bundle tag.
    """
    if not _BS4_AVAILABLE:
        return 0

    bundles = plan.get('bundles', [])
    if not bundles:
        return 0

    updated = 0

    for html_file in clean_dir.rglob('*.html'):
        try:
            content = html_file.read_text(encoding='utf-8', errors='ignore')
            soup = BeautifulSoup(content, 'html.parser')
            changed = False

            for bundle in bundles:
                source_names = set(bundle['source_names'])
                old_scripts = [
                    tag for tag in soup.find_all('script')
                    if Path(tag.get('src', '')).name in source_names
                ]
                if not old_scripts:
                    continue

                first = old_scripts[0]
                new_script = soup.new_tag(bundle.get('tag_name') or 'script')
                for key, value in bundle.get('attrs', {}).items():
                    new_script.attrs[key] = value
                new_script['src'] = '/' + bundle['path'].lstrip('/')
                first.insert_before(new_script)

                for tag in old_scripts:
                    tag.decompose()
                changed = True

            if not changed:
                continue

            # Reserialize with 2-space indentation
            raw = soup.prettify()
            lines = raw.split('\n')
            result = []
            for line in lines:
                stripped = line.lstrip(' ')
                n_spaces = len(line) - len(stripped)
                result.append('  ' * n_spaces + stripped)
            html_file.write_text('\n'.join(result), encoding='utf-8')
            updated += 1

        except Exception as exc:
            log(f'      Aviso: falha ao atualizar HTML {html_file.name}: {exc}')

    if updated:
        log(f'   JS consolidator: referências HTML reparadas em {updated} arquivo(s)')
    return updated


def _collect_html_script_refs(clean_dir: Path, js_dir: Path) -> list[dict]:
    refs = []
    for html_file in sorted(clean_dir.rglob('*.html')):
        try:
            content = html_file.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        soup = BeautifulSoup(content, 'html.parser')
        for tag in soup.find_all('script', src=True):
            src = tag.get('src', '').strip()
            resolved = _resolve_local_script(src, html_file, clean_dir)
            if resolved is None or not resolved.exists():
                continue
            try:
                resolved.relative_to(js_dir)
            except ValueError:
                continue
            if _should_ignore_script(resolved.name):
                continue

            attrs = {
                key: value
                for key, value in tag.attrs.items()
                if key != 'src'
            }
            refs.append({
                'html': html_file,
                'path': resolved,
                'src': src,
                'attrs': attrs,
                'tag_name': tag.name,
                'order_index': len(refs),
                'group_key': json.dumps(_serialize_attrs(attrs), sort_keys=True, ensure_ascii=True),
            })
    return refs


def _serialize_attrs(attrs: dict) -> dict:
    serialized = {}
    for key, value in attrs.items():
        if isinstance(value, list):
            serialized[key] = [str(item) for item in value]
        elif value is None:
            serialized[key] = ''
        else:
            serialized[key] = str(value)
    return serialized


def _resolve_local_script(src: str, html_file: Path, clean_dir: Path) -> Path | None:
    clean_src = src.split('?', 1)[0].split('#', 1)[0].strip()
    if not clean_src or clean_src.startswith(('http://', 'https://', 'data:', 'blob:', '//')):
        return None
    if clean_src.startswith('/'):
        return clean_dir / clean_src.lstrip('/')
    return (html_file.parent / clean_src).resolve()


def _should_ignore_script(name: str) -> bool:
    lowered = name.lower()
    if lowered in _EXCLUDED_JS_NAMES:
        return True
    return any(lowered.startswith(prefix) for prefix in _EXCLUDED_JS_PREFIXES)
