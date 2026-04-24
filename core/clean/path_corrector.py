"""
Path corrector - update HTML/CSS/JS references after asset reorganization.
"""
import json
import re
from urllib.parse import quote, unquote
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

_BLOCK_INTERTAG_WHITESPACE_PATTERN = re.compile(
    r'(</(?:html|head|body|main|section|article|header|footer|nav|aside|div|ul|ol|li|table|thead|tbody|tr|td|th|picture)>)\s+(<(?:html|head|body|main|section|article|header|footer|nav|aside|div|ul|ol|li|table|thead|tbody|tr|td|th|picture)\b)',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Lookup table helpers
# ---------------------------------------------------------------------------

def _build_lookup(path_mapping: dict) -> tuple:
    """
    Build two lookup structures:
    - exact:       {normalized_old (no leading /) -> new_path}
    - by_basename: {filename -> [new_path, ...]}
    """
    exact: dict = {}
    by_basename: dict = {}
    for old, new in path_mapping.items():
        norm = old.lstrip('/')
        exact[norm] = new
        bn = Path(old).name
        if bn:
            by_basename.setdefault(bn, []).append(new)
    return exact, by_basename


def _normalize_browser_path(path: str) -> str:
    if not path:
        return path
    if path.startswith(('http://', 'https://', '//', 'data:', 'blob:', '#', 'mailto:')):
        return path
    return '/' + path.lstrip('/')


def _load_resource_map(clean_dir: Path, log=None) -> tuple[dict, dict]:
    _log = log or (lambda msg: None)
    resource_map_path = clean_dir / 'assets' / 'resource-map.json'
    if not resource_map_path.exists():
        return {}, {}

    try:
        data = json.loads(resource_map_path.read_text(encoding='utf-8', errors='ignore'))
    except Exception as exc:
        _log(f'   Aviso: falha ao ler resource-map.json para rewrite final: {exc}')
        return {}, {}

    if not isinstance(data, dict):
        return {}, {}

    remote_exact = {}
    local_alias_exact = {}
    for original_url, local_path in data.items():
        if not isinstance(original_url, str) or not isinstance(local_path, str):
            continue
        if not original_url.startswith(('http://', 'https://', '//')):
            continue

        browser_path = _normalize_browser_path(local_path)
        normalized_local = browser_path.lstrip('/')
        remote_exact[original_url] = browser_path

        try:
            parsed = urlsplit(original_url)
        except ValueError:
            continue
        if not parsed.netloc:
            continue

        local_candidates = []
        parsed_path = parsed.path.lstrip('/')
        decoded_path = unquote(parsed_path)
        for candidate in (parsed_path, decoded_path):
            if not candidate:
                continue
            local_candidates.append(candidate)
            if not candidate.startswith('assets/'):
                local_candidates.append(f'assets/{candidate}')
        for candidate in local_candidates:
            local_alias_exact.setdefault(candidate.lstrip('/'), normalized_local)

        protocol_relative = urlunsplit(('', parsed.netloc, parsed.path, parsed.query, parsed.fragment))
        if protocol_relative:
            remote_exact.setdefault(protocol_relative, browser_path)

        if parsed.scheme == 'https':
            remote_exact.setdefault(
                urlunsplit(('http', parsed.netloc, parsed.path, parsed.query, parsed.fragment)),
                browser_path,
            )
        elif parsed.scheme == 'http':
            remote_exact.setdefault(
                urlunsplit(('https', parsed.netloc, parsed.path, parsed.query, parsed.fragment)),
                browser_path,
            )

    return remote_exact, local_alias_exact


def _candidate_remote_refs(ref: str) -> list[str]:
    ref = (ref or '').strip()
    if not ref.startswith(('http://', 'https://', '//')):
        return []

    candidates = []
    seen = set()

    def add(value: str):
        if value and value not in seen:
            seen.add(value)
            candidates.append(value)

    add(ref)
    try:
        parsed = urlsplit(ref)
    except ValueError:
        return candidates
    if parsed.fragment:
        add(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, '')))
    if parsed.query:
        add(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', '')))
    if parsed.query and parsed.fragment:
        add(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', parsed.fragment)))

    if ref.startswith('//'):
        add('https:' + ref)
        add('http:' + ref)

    return candidates


def _lookup_remote(ref: str, remote_exact: dict) -> str | None:
    if not remote_exact:
        return None

    for candidate in _candidate_remote_refs(ref):
        mapped = remote_exact.get(candidate)
        if mapped:
            return mapped
    return None


def _remap(ref: str, exact: dict, by_basename: dict, remote_exact: dict | None = None) -> str:
    """Translate a single path reference. Returns original if no match found."""
    if not ref:
        return ref
    if '${' in ref:
        return ref

    # Strip query/fragment for lookup (reattach after)
    query_part = ''
    frag_part = ''
    base = ref
    if '?' in base:
        base, query_part = base.split('?', 1)
        query_part = '?' + query_part
    if '#' in base:
        base, frag_part = base.split('#', 1)
        frag_part = '#' + frag_part

    remote_match = _lookup_remote(ref, remote_exact or {})
    if remote_match:
        return remote_match + query_part + frag_part

    # Leave non-file external / data / anchor refs unchanged
    if ref.startswith(('http://', 'https://', 'data:', 'blob:', '//', '#', 'mailto:')):
        return ref

    had_slash = base.startswith('/')
    norm = base.lstrip('/')
    decoded_norm = unquote(norm)

    # 1. Exact match
    if norm in exact:
        new = exact[norm]
        return '/' + new + query_part + frag_part
    if decoded_norm in exact:
        new = exact[decoded_norm]
        return '/' + new + query_part + frag_part

    # 1b. Alias root-relative runtime requests to the mirrored assets/ tree.
    #     Example: "/_next/static/chunk.js" -> "assets/_next/static/chunk.js"
    asset_norm = norm if norm.startswith('assets/') else f'assets/{norm}'
    asset_decoded_norm = decoded_norm if decoded_norm.startswith('assets/') else f'assets/{decoded_norm}'
    if asset_norm in exact:
        new = exact[asset_norm]
        return '/' + new + query_part + frag_part
    if asset_decoded_norm in exact:
        new = exact[asset_decoded_norm]
        return '/' + new + query_part + frag_part

    # 2. Basename fallback (only if unambiguous)
    # Always use root-relative here: the file may have been relocated to a different
    # subdirectory, so a relative path would point to the wrong place.
    bn = Path(norm).name
    decoded_bn = Path(decoded_norm).name
    if bn and bn in by_basename and len(by_basename[bn]) == 1:
        new = by_basename[bn][0]
        return '/' + new + query_part + frag_part
    if decoded_bn and decoded_bn in by_basename and len(by_basename[decoded_bn]) == 1:
        new = by_basename[decoded_bn][0]
        return '/' + new + query_part + frag_part

    return ref


def _encode_browser_url(ref: str) -> str:
    if not ref or ref.startswith(('http://', 'https://', 'data:', 'blob:', '//', '#', 'mailto:')):
        return ref
    return quote(ref, safe="/:@?&=#%+-._~!$'()*;")


def _should_keep_root_relative_literal(value: str) -> bool:
    """
    Root-relative remaps are required for module specifiers and asset manifests.
    Bare "assets/..." strings become invalid ESM specifiers if we drop the slash.
    """
    return value.startswith(('/', './', '../', 'assets/', '_next/', 'published-assets-v3/', 'flags/', 'static/'))


def _rewrite_quoted_local_literals(
    content: str,
    exact: dict,
    by_basename: dict,
    remote_exact: dict | None = None,
    rewrite_remote: bool = False,
) -> str:
    """Remap quoted local-ish literals inside JS/JSON while preserving slash style."""

    def replace(match):
        quote_char = match.group(1)
        value = match.group(2)
        if not value:
            return match.group(0)

        is_remote = value.startswith(('http://', 'https://', '//'))
        if value.startswith(('data:', 'blob:', '#', 'mailto:')):
            return match.group(0)
        if is_remote and not rewrite_remote:
            return match.group(0)
        if (
            not is_remote
            and not any(value.startswith(prefix) for prefix in ('/', 'assets/', './', '../', '_next/', 'published-assets-v3/', 'flags/'))
        ):
            return match.group(0)

        remapped = _remap(value, exact, by_basename, remote_exact)
        if remapped == value:
            return match.group(0)

        # Only drop the leading slash for truly relative string literals.
        # Asset-root paths like "assets/foo.js" must stay root-relative after remap.
        if (
            not _should_keep_root_relative_literal(value)
            and not value.startswith('/')
            and remapped.startswith('/')
        ):
            remapped = remapped.lstrip('/')

        return f'{quote_char}{remapped}{quote_char}'

    return re.sub(r'(["\'`])([^"\'`]+)\1', replace, content)


# ---------------------------------------------------------------------------
# CSS content fixer (url() and @import)
# ---------------------------------------------------------------------------

def _fix_css(css: str, exact: dict, by_basename: dict, remote_exact: dict | None = None) -> str:
    def replace_url(m):
        q = m.group(1) or ''
        path = m.group(2)
        return f'url({q}{_remap(path, exact, by_basename, remote_exact)}{q})'

    result = re.sub(r'url\((["\']?)([^)"\']+)\1\)', replace_url, css)

    def replace_import(m):
        q = m.group(1)
        path = m.group(2)
        return f'@import {q}{_remap(path, exact, by_basename, remote_exact)}{q}'

    return re.sub(r'@import\s+(["\'])([^"\']+)\1', replace_import, result)


# ---------------------------------------------------------------------------
# Per-file correctors
# ---------------------------------------------------------------------------

_HTML_SINGLE_ATTRS: dict = {
    'link':   ['href'],
    'script': ['src'],
    'img':    ['src', 'data-src'],
    'source': ['src'],
    'video':  ['src', 'poster'],
    'audio':  ['src'],
    'iframe': ['src'],
    'use':    ['href', 'xlink:href'],
    'image':  ['href', 'xlink:href'],
    'a':      ['href'],
}
_HTML_SRCSET_TAGS = {'img', 'source'}


def _fix_srcset(srcset: str, exact: dict, by_basename: dict, remote_exact: dict | None = None) -> str:
    descriptor_pattern = re.compile(r'^\d+(?:\.\d+)?[wx]$')
    parts = srcset.split(',')
    fixed = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue

        url_part = stripped
        descriptor = ''
        if ' ' in stripped:
            possible_url, possible_descriptor = stripped.rsplit(None, 1)
            if descriptor_pattern.match(possible_descriptor):
                url_part = possible_url
                descriptor = possible_descriptor

        remapped = _encode_browser_url(_remap(url_part, exact, by_basename, remote_exact))
        fixed.append(f'{remapped} {descriptor}'.strip())
    return ', '.join(fixed)


def _remap_importmap_value(
    value: str,
    exact: dict,
    by_basename: dict,
    remote_exact: dict | None = None,
) -> str:
    remapped = _remap(value, exact, by_basename, remote_exact)
    if remapped == value:
        return value

    if (
        not _should_keep_root_relative_literal(value)
        and not value.startswith('/')
        and remapped.startswith('/')
    ):
        return remapped.lstrip('/')
    return remapped


def _rewrite_importmap_script(
    script_text: str,
    exact: dict,
    by_basename: dict,
    remote_exact: dict | None = None,
) -> str:
    try:
        data = json.loads(script_text)
    except Exception:
        return script_text

    if not isinstance(data, dict):
        return script_text

    changed = False

    imports = data.get('imports')
    if isinstance(imports, dict):
        for specifier, target in list(imports.items()):
            if not isinstance(target, str):
                continue
            remapped = _remap_importmap_value(target, exact, by_basename, remote_exact)
            if remapped != target:
                imports[specifier] = remapped
                changed = True

    scopes = data.get('scopes')
    if isinstance(scopes, dict):
        new_scopes = {}
        for scope_key, scope_imports in scopes.items():
            new_scope_key = scope_key
            if isinstance(scope_key, str) and not scope_key.startswith(('http://', 'https://', '//')):
                new_scope_key = _remap_importmap_value(scope_key, exact, by_basename, remote_exact)
                if new_scope_key != scope_key:
                    changed = True

            new_scope_imports = scope_imports
            if isinstance(scope_imports, dict):
                new_scope_imports = dict(scope_imports)
                for specifier, target in list(new_scope_imports.items()):
                    if not isinstance(target, str):
                        continue
                    remapped = _remap_importmap_value(target, exact, by_basename, remote_exact)
                    if remapped != target:
                        new_scope_imports[specifier] = remapped
                        changed = True

            new_scopes[new_scope_key] = new_scope_imports

        if new_scopes != scopes:
            data['scopes'] = new_scopes

    if not changed:
        return script_text

    return json.dumps(data, ensure_ascii=False, separators=(', ', ': '))


def _correct_html(filepath: Path, exact: dict, by_basename: dict, remote_exact: dict) -> bool:
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return False

    if not _BS4_AVAILABLE:
        # Minimal regex fallback
        changed = False
        for old_norm, new in exact.items():
            for variant in (old_norm, '/' + old_norm):
                for q in ('"', "'"):
                    old_q = f'{q}{variant}{q}'
                    new_q = f'{q}{new}{q}'
                    if old_q in content:
                        content = content.replace(old_q, new_q)
                        changed = True
        if changed:
            filepath.write_text(content, encoding='utf-8')
        return changed

    soup = BeautifulSoup(content, 'html.parser')
    changed = False

    for tag_name, attrs in _HTML_SINGLE_ATTRS.items():
        for el in soup.find_all(tag_name):
            for attr in attrs:
                val = el.get(attr)
                if not val or not isinstance(val, str):
                    continue
                new_val = _remap(val, exact, by_basename, remote_exact)
                if new_val != val:
                    el[attr] = new_val
                    changed = True

    for tag_name in _HTML_SRCSET_TAGS:
        for el in soup.find_all(tag_name):
            val = el.get('srcset')
            if val and isinstance(val, str):
                new_val = _fix_srcset(val, exact, by_basename, remote_exact)
                if new_val != val:
                    el['srcset'] = new_val
                    changed = True

    for meta in soup.find_all('meta'):
        val = meta.get('content')
        if not val or not isinstance(val, str) or not val.startswith(('http://', 'https://', '//', '/')):
            continue
        new_val = _remap(val, exact, by_basename, remote_exact)
        if new_val != val:
            meta['content'] = new_val
            changed = True

    # Inline style="... url() ..."
    for el in soup.find_all(True):
        style = el.get('style')
        if style and isinstance(style, str):
            new_style = _fix_css(style, exact, by_basename, remote_exact)
            if new_style != style:
                el['style'] = new_style
                changed = True

    # <style> blocks
    for style_tag in soup.find_all('style'):
        if style_tag.string:
            new_css = _fix_css(style_tag.string, exact, by_basename, remote_exact)
            if new_css != style_tag.string:
                style_tag.string.replace_with(new_css)
                changed = True

    # Inline <script> tags can embed import maps and runtime resource maps whose
    # local paths must follow the clean/ asset reorganization too.
    for script_tag in soup.find_all('script'):
        if script_tag.get('src'):
            continue
        script_text = script_tag.string or script_tag.get_text()
        if not script_text:
            continue
        if script_tag.get('data-generated-importmap') == 'true':
            new_script_text = _rewrite_importmap_script(
                script_text,
                exact,
                by_basename,
                remote_exact,
            )
            if new_script_text != script_text:
                script_tag.clear()
                script_tag.append(new_script_text)
                changed = True
            continue
        if script_tag.get('data-fetch-interceptor') == 'true':
            continue
        new_script_text = _rewrite_quoted_local_literals(
            script_text,
            exact,
            by_basename,
            remote_exact,
            rewrite_remote=False,
        )
        if new_script_text != script_text:
            script_tag.clear()
            script_tag.append(new_script_text)
            changed = True

    output = content
    if changed:
        output = _serialize_html_stable(soup)

    # Blind literal rewrite closes the gaps left by HTML parser normalization,
    # especially in auxiliary HTML snapshots that still carry old local paths.
    output = _rewrite_quoted_local_literals(
        output,
        exact,
        by_basename,
        remote_exact,
        rewrite_remote=False,
    )

    if output != content:
        filepath.write_text(output, encoding='utf-8')
        return True
    return False


def _serialize_html_stable(soup: BeautifulSoup) -> str:
    html = soup.decode(formatter='minimal')
    return _BLOCK_INTERTAG_WHITESPACE_PATTERN.sub(r'\1\2', html)


def _correct_css(filepath: Path, exact: dict, by_basename: dict, remote_exact: dict) -> bool:
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return False
    new_content = _fix_css(content, exact, by_basename, remote_exact)
    if remote_exact:
        for original_url, local_path in remote_exact.items():
            if original_url in new_content:
                new_content = new_content.replace(original_url, local_path)
    if new_content != content:
        filepath.write_text(new_content, encoding='utf-8')
        return True
    return False


def _correct_js(filepath: Path, exact: dict, by_basename: dict, remote_exact: dict) -> bool:
    """Replace whole-string path literals in JS (conservative: exact match only)."""
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return False

    result = _rewrite_quoted_local_literals(
        content,
        exact,
        by_basename,
        remote_exact,
        rewrite_remote=True,
    )

    if result != content:
        filepath.write_text(result, encoding='utf-8')
        return True
    return False


def _correct_json(
    filepath: Path,
    exact: dict,
    by_basename: dict,
    remote_exact: dict,
    rewrite_remote: bool = True,
) -> bool:
    """Rewrite local-ish literals inside JSON/webmanifest text files."""
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return False

    try:
        payload = json.loads(content)
    except Exception:
        result = _rewrite_quoted_local_literals(
            content,
            exact,
            by_basename,
            remote_exact,
            rewrite_remote=rewrite_remote,
        )
    else:
        rewritten_payload = _rewrite_json_values(
            payload,
            exact,
            by_basename,
            remote_exact,
            rewrite_remote=rewrite_remote,
        )
        result = json.dumps(rewritten_payload, ensure_ascii=False, separators=(', ', ': '))

    if result != content:
        filepath.write_text(result, encoding='utf-8')
        return True
    return False


def _rewrite_json_values(
    payload,
    exact: dict,
    by_basename: dict,
    remote_exact: dict,
    rewrite_remote: bool = True,
):
    if isinstance(payload, dict):
        return {
            key: _rewrite_json_values(value, exact, by_basename, remote_exact, rewrite_remote)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [
            _rewrite_json_values(item, exact, by_basename, remote_exact, rewrite_remote)
            for item in payload
        ]
    if not isinstance(payload, str):
        return payload

    is_remote = payload.startswith(('http://', 'https://', '//'))
    if is_remote and not rewrite_remote:
        return payload
    return _remap(payload, exact, by_basename, remote_exact)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def correct_all_paths(clean_dir: Path, path_mapping: dict, log_callback=None) -> dict:
    """
    Update all HTML/CSS/JS path references using path_mapping.
    Returns stats: {html: N, css: N, js: N, json: N}.
    """
    log = log_callback or (lambda msg: None)
    clean_dir = Path(clean_dir)

    if not path_mapping:
        log('   Sem mapeamento de paths para corrigir')
        return {'html': 0, 'css': 0, 'js': 0, 'json': 0}

    exact, by_basename = _build_lookup(path_mapping)
    remote_exact, local_alias_exact = _load_resource_map(clean_dir, log)
    if local_alias_exact:
        for old_ref, new_ref in local_alias_exact.items():
            exact.setdefault(old_ref, new_ref)
            basename = Path(old_ref).name
            if basename:
                by_basename.setdefault(basename, [])
                if new_ref not in by_basename[basename]:
                    by_basename[basename].append(new_ref)
    stats = {'html': 0, 'css': 0, 'js': 0, 'json': 0}
    audit_dir = clean_dir / 'audit'

    for path in sorted(clean_dir.rglob('*')):
        if not path.is_file():
            continue
        # Skip audit/ subtree
        try:
            path.relative_to(audit_dir)
            continue
        except ValueError:
            pass

        ext = path.suffix.lower()
        if ext in ('.html', '.htm'):
            if _correct_html(path, exact, by_basename, remote_exact):
                stats['html'] += 1
        elif ext == '.css':
            if _correct_css(path, exact, by_basename, remote_exact):
                stats['css'] += 1
        elif ext in ('.js', '.mjs', '.cjs'):
            if _correct_js(path, exact, by_basename, remote_exact):
                stats['js'] += 1
        elif ext in ('.json', '.webmanifest'):
            if _correct_json(
                path,
                exact,
                by_basename,
                remote_exact,
                rewrite_remote=path.name != 'resource-map.json',
            ):
                stats['json'] += 1

    log(
        f"   Paths corrigidos: {stats['html']} HTML, "
        f"{stats['css']} CSS, {stats['js']} JS, {stats['json']} JSON"
    )
    return stats
