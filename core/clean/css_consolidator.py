"""
CSS consolidator - flatten CSS into a smaller, role-based bundle set.

Output layout:
  - assets/css/globals.css
  - assets/css/selectors.css
  - assets/css/fonts.css
  - assets/css/base.css
  - assets/css/styles.css (+ chunked styles_XXX.css)
  - assets/css/important.css
  - assets/css/keyframes.css
  - assets/css/medias/base_medias.css
  - assets/css/medias/media_XXX.css (only for large media blocks)
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

_ELEM_NAMES = frozenset([
    'html', 'head', 'body', 'a', 'abbr', 'address', 'article', 'aside',
    'audio', 'b', 'blockquote', 'br', 'button', 'canvas', 'caption',
    'cite', 'code', 'col', 'colgroup', 'data', 'datalist', 'dd', 'del',
    'details', 'dfn', 'dialog', 'div', 'dl', 'dt', 'em', 'embed',
    'fieldset', 'figcaption', 'figure', 'footer', 'form',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'i', 'iframe',
    'hgroup',
    'img', 'input', 'ins', 'kbd', 'label', 'legend', 'li', 'main', 'map',
    'mark', 'menu', 'meta', 'meter', 'nav', 'noscript', 'object', 'ol',
    'optgroup', 'option', 'output', 'p', 'picture', 'pre', 'progress',
    'q', 's', 'samp', 'script', 'section', 'select', 'small', 'source',
    'span', 'strong', 'sub', 'summary', 'sup', 'table', 'tbody', 'td',
    'template', 'textarea', 'tfoot', 'th', 'thead', 'time', 'tr', 'track',
    'u', 'ul', 'var', 'video', 'wbr', '*',
])
_FONT_ONLY_PROPS = frozenset({
    'font', 'font-family', 'font-size', 'font-style', 'font-weight',
    'font-stretch', 'font-display', 'font-variation-settings',
    'font-feature-settings', 'font-synthesis', 'font-optical-sizing',
    'font-kerning', 'font-language-override', 'font-size-adjust',
    'line-height', 'src', 'unicode-range', 'ascent-override',
    'descent-override', 'line-gap-override', 'size-adjust',
    '-webkit-font-smoothing', '-moz-osx-font-smoothing', 'text-rendering',
    'speak',
})
_GENERATED_FILES = {
    'base.css',
    'fonts.css',
    'globals.css',
    'important.css',
    'keyframes.css',
    'selectors.css',
    'styles.css',
}
_GENERATED_PREFIXES = ('styles_', 'media_')
_MEDIA_DIRNAME = 'medias'
_MAX_LINES_PER_BUNDLE = 1000
_MAX_MEDIA_LINES_PER_FILE = 300
_WHITESPACE_RE = re.compile(r'\s+')
_FUNCTIONAL_PSEUDO_RE = re.compile(r':(?:where|is|not|has)\(([^()]*)\)')
_CSS_IMPORT_RE = re.compile(r'^@import\s+(?:url\()?\s*["\']?([^"\')\s]+)', re.IGNORECASE)


def _strip_css_comments(css: str) -> str:
    return re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)


def _is_generated_css_path(path: Path, css_dir: Path) -> bool:
    if path.parent == css_dir / _MEDIA_DIRNAME:
        return True
    name = path.name
    return name in _GENERATED_FILES or any(name.startswith(prefix) for prefix in _GENERATED_PREFIXES)


def _is_local_css_import(rule_text: str) -> bool:
    match = _CSS_IMPORT_RE.match(rule_text.strip())
    if not match:
        return False

    target = match.group(1).strip()
    if not target:
        return False

    parsed = urlparse(target)
    if parsed.scheme or target.startswith(('//', 'data:')):
        return False

    target_path = parsed.path.lower()
    return target_path.endswith('.css')


def _iter_entry_html_files(clean_dir: Path):
    assets_dir = clean_dir / 'assets'
    audit_dir = clean_dir / 'audit'
    for html_file in sorted(clean_dir.rglob('*.html')):
        try:
            html_file.relative_to(audit_dir)
            continue
        except ValueError:
            pass
        try:
            html_file.relative_to(assets_dir)
            continue
        except ValueError:
            pass
        yield html_file


def _iter_live_stylesheet_links(soup: BeautifulSoup):
    """
    Yield only stylesheet <link> tags that are still live.

    Malformed heads can cause BeautifulSoup to nest link tags. When one parent
    link gets decomposed, nested siblings in a precomputed list become dead tags
    whose attrs are None, and calling .get() on them raises AttributeError.
    """
    for link in list(soup.find_all('link')):
        if getattr(link, 'name', None) != 'link':
            continue
        if getattr(link, 'attrs', None) is None:
            continue

        rel = link.get('rel', []) or []
        if isinstance(rel, str):
            rel = [rel]
        rel = {value.lower() for value in rel}
        if 'stylesheet' not in rel:
            continue

        yield link


def _resolve_local_stylesheet(href: str, source_file: Path, clean_dir: Path) -> Path | None:
    target = href.split('?', 1)[0].split('#', 1)[0].strip()
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or target.startswith(('//', 'data:', 'blob:')):
        return None
    if not parsed.path.lower().endswith('.css'):
        return None
    if target.startswith('/'):
        return (clean_dir / target.lstrip('/')).resolve()
    return (source_file.parent / target).resolve()


def _collect_css_import_closure(css_file: Path, clean_dir: Path, css_dir: Path, seen: set[Path], ordered: list[Path]) -> None:
    try:
        resolved_css = css_file.resolve()
    except OSError:
        return

    if resolved_css in seen or not resolved_css.exists():
        return
    try:
        resolved_css.relative_to(css_dir.resolve())
    except ValueError:
        return

    seen.add(resolved_css)
    ordered.append(resolved_css)

    try:
        content = resolved_css.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return

    for kind, data in _iter_top_level(content):
        if kind != 'at-other':
            continue
        match = _CSS_IMPORT_RE.match(data.strip())
        if not match:
            continue
        imported = _resolve_local_stylesheet(match.group(1), resolved_css, clean_dir)
        if imported is None:
            continue
        _collect_css_import_closure(imported, clean_dir, css_dir, seen, ordered)


def _collect_html_stylesheet_refs(clean_dir: Path, css_dir: Path) -> list[Path]:
    if not _BS4_AVAILABLE:
        return []

    seen: set[Path] = set()
    ordered: list[Path] = []

    for html_file in _iter_entry_html_files(clean_dir):
        try:
            content = html_file.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        soup = BeautifulSoup(content, 'html.parser')
        for link in _iter_live_stylesheet_links(soup):
            href = (link.get('href') or '').strip()
            css_file = _resolve_local_stylesheet(href, html_file, clean_dir)
            if css_file is None:
                continue
            _collect_css_import_closure(css_file, clean_dir, css_dir, seen, ordered)

    return ordered


def _iter_top_level(css: str):
    css = _strip_css_comments(css)
    i, n = 0, len(css)

    def skip_ws(pos: int) -> int:
        while pos < n and css[pos] in ' \t\r\n':
            pos += 1
        return pos

    def scan_until_block_start(pos: int) -> int:
        quote = ''
        paren_depth = 0
        bracket_depth = 0
        while pos < n:
            ch = css[pos]
            if quote:
                if ch == '\\':
                    pos += 2
                    continue
                if ch == quote:
                    quote = ''
                pos += 1
                continue
            if ch in ('"', "'"):
                quote = ch
            elif ch == '(':
                paren_depth += 1
            elif ch == ')':
                paren_depth = max(0, paren_depth - 1)
            elif ch == '[':
                bracket_depth += 1
            elif ch == ']':
                bracket_depth = max(0, bracket_depth - 1)
            elif ch == '{' and paren_depth == 0 and bracket_depth == 0:
                return pos
            elif ch == ';' and paren_depth == 0 and bracket_depth == 0:
                return pos
            pos += 1
        return pos

    def find_matching_brace(pos: int) -> int:
        depth = 0
        quote = ''
        paren_depth = 0
        bracket_depth = 0
        while pos < n:
            ch = css[pos]
            if quote:
                if ch == '\\':
                    pos += 2
                    continue
                if ch == quote:
                    quote = ''
                pos += 1
                continue
            if ch in ('"', "'"):
                quote = ch
            elif ch == '(':
                paren_depth += 1
            elif ch == ')':
                paren_depth = max(0, paren_depth - 1)
            elif ch == '[':
                bracket_depth += 1
            elif ch == ']':
                bracket_depth = max(0, bracket_depth - 1)
            elif ch == '{' and paren_depth == 0 and bracket_depth == 0:
                depth += 1
            elif ch == '}' and paren_depth == 0 and bracket_depth == 0:
                depth -= 1
                if depth == 0:
                    return pos
            pos += 1
        return -1

    while i < n:
        i = skip_ws(i)
        if i >= n:
            break

        if css[i] == '@':
            header_end = scan_until_block_start(i)
            header = css[i:header_end].strip()
            if header_end >= n:
                break
            if css[header_end] == ';':
                yield ('at-other', css[i:header_end + 1].strip())
                i = header_end + 1
                continue
            block_end = find_matching_brace(header_end)
            if block_end < 0:
                break
            full = css[i:block_end + 1].strip()
            keyword = header[1:].split(None, 1)[0].lower()
            if keyword == 'media':
                yield ('at-media', full)
            elif keyword in ('keyframes', '-webkit-keyframes', '-moz-keyframes', '-o-keyframes'):
                yield ('at-keyframes', full)
            elif keyword == 'font-face':
                yield ('at-font-face', full)
            else:
                yield ('at-other', full)
            i = block_end + 1
            continue

        selector_end = scan_until_block_start(i)
        if selector_end >= n or css[selector_end] != '{':
            break
        selector = css[i:selector_end].strip()
        block_end = find_matching_brace(selector_end)
        if not selector or block_end < 0:
            break
        body = css[selector_end + 1:block_end].strip()
        full = css[i:block_end + 1].strip()
        yield ('rule', (selector, body, full))
        i = block_end + 1


def _split_selector_list(selector: str) -> list[str]:
    parts = []
    current = []
    quote = ''
    paren_depth = 0
    bracket_depth = 0

    for ch in selector:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ''
            elif ch == '\\':
                continue
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == '(':
            paren_depth += 1
        elif ch == ')':
            paren_depth = max(0, paren_depth - 1)
        elif ch == '[':
            bracket_depth += 1
        elif ch == ']':
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == ',' and paren_depth == 0 and bracket_depth == 0:
            part = ''.join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(ch)

    tail = ''.join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_declarations(body: str) -> list[dict]:
    if '{' in body or '}' in body:
        return []

    parts = []
    current = []
    quote = ''
    paren_depth = 0
    bracket_depth = 0

    for ch in body:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ''
            elif ch == '\\':
                continue
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == '(':
            paren_depth += 1
        elif ch == ')':
            paren_depth = max(0, paren_depth - 1)
        elif ch == '[':
            bracket_depth += 1
        elif ch == ']':
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == ';' and paren_depth == 0 and bracket_depth == 0:
            fragment = ''.join(current).strip()
            if fragment:
                parts.append(fragment)
            current = []
            continue
        current.append(ch)

    tail = ''.join(current).strip()
    if tail:
        parts.append(tail)

    declarations = []
    for fragment in parts:
        if ':' not in fragment:
            continue
        prop, value = fragment.split(':', 1)
        prop = prop.strip()
        value = value.strip()
        if not prop or not value:
            continue
        important = bool(re.search(r'!\s*important\s*$', value, flags=re.IGNORECASE))
        if important:
            value = re.sub(r'\s*!\s*important\s*$', '', value, flags=re.IGNORECASE).strip()
        declarations.append({'property': prop, 'value': value, 'important': important})
    return declarations


def _render_rule(selector: str, declarations: list[dict]) -> str:
    if not selector or not declarations:
        return ''
    lines = [f'{selector} {{']
    for decl in declarations:
        suffix = ' !important' if decl.get('important') else ''
        lines.append(f"  {decl['property']}: {decl['value']}{suffix};")
    lines.append('}')
    return '\n'.join(lines)


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(' ', text.strip())


def _normalize_selector(selector: str) -> str:
    return ','.join(_normalize_text(part) for part in _split_selector_list(selector))


def _declaration_signature(declarations: list[dict]) -> tuple:
    return tuple(sorted(
        (_normalize_text(decl['property'].lower()), _normalize_text(decl['value']), bool(decl.get('important')))
        for decl in declarations
    ))


def _simplify_selector_part(part: str) -> str:
    simplified = part.strip()
    previous = None
    while previous != simplified:
        previous = simplified
        simplified = _FUNCTIONAL_PSEUDO_RE.sub(r'\1', simplified)
    return simplified.strip()


def _selector_tokens(part: str) -> list[str]:
    simplified = _simplify_selector_part(part)
    return [token.strip() for token in re.split(r'[\s>+~]+', simplified) if token.strip()]


def _is_base_selector(selector: str) -> bool:
    parts = _split_selector_list(selector)
    if not parts:
        return False
    allowed = {':root', 'html', 'body'}
    for part in parts:
        simple = _simplify_selector_part(part)
        if simple not in allowed:
            return False
    return True


def _is_element_only(selector: str) -> bool:
    parts = _split_selector_list(selector)
    if not parts:
        return False

    saw_target = False
    for part in parts:
        for token in _selector_tokens(part):
            if any(marker in token for marker in ('.', '#', '[', '&')):
                return False
            if token.startswith(':'):
                saw_target = True
                continue

            base = token.split('|', 1)[-1]
            base = re.split(r':', base, 1)[0].strip().lower()
            if not base:
                continue
            if base not in _ELEM_NAMES:
                return False
            saw_target = True
    return saw_target


def _is_selector_dense(selector: str, declarations: list[dict]) -> bool:
    parts = _split_selector_list(selector)
    return len(parts) >= 3 and len(declarations) <= 2


def _is_font_only_rule(declarations: list[dict]) -> bool:
    if not declarations:
        return False
    return all(decl['property'].strip().lower() in _FONT_ONLY_PROPS for decl in declarations)


def _has_selector_combinator(selector: str) -> bool:
    for part in _split_selector_list(selector):
        simplified = _simplify_selector_part(part)
        if re.search(r'[\s>+~]', simplified):
            return True
    return False


def _is_font_rule(selector: str, declarations: list[dict]) -> bool:
    if not _is_font_only_rule(declarations):
        return False
    if _is_base_selector(selector):
        return False
    return not _has_selector_combinator(selector)


def _contains_media_block(text: str) -> bool:
    return '@media' in _strip_css_comments(text).lower()


def _new_rule_bucket() -> dict:
    return {
        'groups': [],
        'index': {},
    }


def _append_rule(bucket: dict, selector: str, declarations: list[dict]) -> bool:
    selector_key = _normalize_selector(selector)
    if not selector_key or not declarations:
        return False

    signature = _declaration_signature(declarations)
    group_idx = bucket['index'].get(signature)
    if group_idx is None:
        bucket['index'][signature] = len(bucket['groups'])
        bucket['groups'].append({
            'selectors': [selector.strip()],
            'selector_keys': {selector_key},
            'declarations': declarations,
        })
        return True

    group = bucket['groups'][group_idx]
    if selector_key in group['selector_keys']:
        return False

    group['selectors'].append(selector.strip())
    group['selector_keys'].add(selector_key)
    return True


def _append_text(bucket: list[str], seen: set[str], text: str) -> bool:
    key = _normalize_text(text)
    if not key or key in seen:
        return False
    seen.add(key)
    bucket.append(text.strip())
    return True


def _chunk_rules(rules: list[str], max_lines: int) -> list[list[str]]:
    if not rules:
        return []
    chunks = []
    current = []
    current_lines = 0
    for rule in rules:
        rule_lines = max(1, len(rule.splitlines())) + 1
        if current and current_lines + rule_lines > max_lines:
            chunks.append(current)
            current = []
            current_lines = 0
        current.append(rule)
        current_lines += rule_lines
    if current:
        chunks.append(current)
    return chunks


def _render_bucket(bucket: dict) -> list[str]:
    rendered = []
    for group in bucket['groups']:
        selector = ',\n'.join(group['selectors'])
        block = _render_rule(selector, group['declarations'])
        if block:
            rendered.append(block)
    return rendered


def consolidate_css(clean_dir: Path, log=None) -> dict:
    _log = log or (lambda m: None)
    clean_dir = Path(clean_dir).resolve()
    css_dir = clean_dir / 'assets' / 'css'
    if not css_dir.exists():
        return {'source_paths': [], 'written_paths': [], 'reference_map': {}, 'stats': {}}

    all_source_files = sorted(
        path for path in css_dir.rglob('*.css')
        if not _is_generated_css_path(path, css_dir)
    )
    if not all_source_files:
        _log('   CSS consolidator: nenhum CSS de origem encontrado')
        return {'source_paths': [], 'written_paths': [], 'reference_map': {}, 'stats': {}}

    source_files = _collect_html_stylesheet_refs(clean_dir, css_dir)
    if source_files:
        _log(
            '   CSS consolidator: '
            f'{len(source_files)} CSS referenciado(s) pelas páginas de entrada selecionado(s) '
            f'de {len(all_source_files)} arquivo(s) disponível(is)'
        )
    else:
        source_files = all_source_files
        _log(
            '   CSS consolidator: referências HTML não detectadas; '
            f'usando fallback com {len(source_files)} arquivo(s)'
        )

    _log(f'   CSS consolidator: reduzindo {len(source_files)} arquivo(s) CSS...')

    globals_bucket = _new_rule_bucket()
    selectors_bucket = _new_rule_bucket()
    fonts_bucket = _new_rule_bucket()
    base_bucket = _new_rule_bucket()
    style_bucket = _new_rule_bucket()
    important_bucket = _new_rule_bucket()
    keyframes_blocks: list[str] = []
    fonts_at_blocks: list[str] = []
    base_at_blocks: list[str] = []
    base_media_blocks: list[str] = []
    large_media_blocks: list[str] = []
    seen_text = {
        'fonts': set(),
        'base': set(),
        'keyframes': set(),
        'base_media': set(),
        'large_media': set(),
    }

    for css_file in source_files:
        content = css_file.read_text(encoding='utf-8', errors='ignore')
        for kind, data in _iter_top_level(content):
            if kind == 'at-media':
                media_lines = len(data.splitlines())
                if media_lines > _MAX_MEDIA_LINES_PER_FILE:
                    _append_text(large_media_blocks, seen_text['large_media'], data)
                else:
                    _append_text(base_media_blocks, seen_text['base_media'], data)
                continue

            if kind == 'at-keyframes':
                _append_text(keyframes_blocks, seen_text['keyframes'], data)
                continue

            if kind == 'at-font-face':
                _append_text(fonts_at_blocks, seen_text['fonts'], data)
                continue

            if kind == 'at-other':
                if _is_local_css_import(data):
                    continue
                if _contains_media_block(data):
                    media_lines = len(data.splitlines())
                    if media_lines > _MAX_MEDIA_LINES_PER_FILE:
                        _append_text(large_media_blocks, seen_text['large_media'], data)
                    else:
                        _append_text(base_media_blocks, seen_text['base_media'], data)
                else:
                    _append_text(base_at_blocks, seen_text['base'], data)
                continue

            selector, body, _full = data
            declarations = _parse_declarations(body)
            if not declarations:
                continue

            normal_decls = [decl for decl in declarations if not decl['important']]
            important_decls = [decl for decl in declarations if decl['important']]

            if important_decls:
                _append_rule(important_bucket, selector, important_decls)

            if not normal_decls:
                continue

            if _is_base_selector(selector):
                _append_rule(base_bucket, selector, normal_decls)
            elif _is_font_rule(selector, normal_decls):
                _append_rule(fonts_bucket, selector, normal_decls)
            elif _is_element_only(selector):
                _append_rule(globals_bucket, selector, normal_decls)
            elif _is_selector_dense(selector, normal_decls):
                _append_rule(selectors_bucket, selector, normal_decls)
            else:
                _append_rule(style_bucket, selector, normal_decls)

    written_paths: list[str] = []
    globals_blocks = _render_bucket(globals_bucket)
    selectors_blocks = _render_bucket(selectors_bucket)
    fonts_blocks = fonts_at_blocks + _render_bucket(fonts_bucket)
    base_blocks = base_at_blocks + _render_bucket(base_bucket)
    style_blocks = _render_bucket(style_bucket)
    important_blocks = _render_bucket(important_bucket)

    def write_output(relative_path: str, blocks: list[str]) -> None:
        if not blocks:
            return
        path = css_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n\n'.join(blocks).strip() + '\n', encoding='utf-8')
        written_paths.append(path.relative_to(clean_dir).as_posix())

    write_output('globals.css', globals_blocks)
    write_output('selectors.css', selectors_blocks)
    write_output('fonts.css', fonts_blocks)
    write_output('base.css', base_blocks)

    for idx, chunk in enumerate(_chunk_rules(style_blocks, _MAX_LINES_PER_BUNDLE), start=1):
        filename = 'styles.css' if idx == 1 else f'styles_{idx:03d}.css'
        write_output(filename, chunk)

    write_output('important.css', important_blocks)
    write_output('keyframes.css', keyframes_blocks)
    write_output(f'{_MEDIA_DIRNAME}/base_medias.css', base_media_blocks)
    for idx, media_block in enumerate(large_media_blocks, start=1):
        write_output(f'{_MEDIA_DIRNAME}/media_{idx:03d}.css', [media_block])

    for path in source_files:
        path.unlink(missing_ok=True)

    reference_map = {}
    primary_bundle = next((path for path in written_paths if path.endswith('styles.css')), '')
    for path in source_files:
        rel = path.relative_to(clean_dir).as_posix()
        if primary_bundle:
            reference_map[rel] = primary_bundle

    plan = {
        'source_paths': [path.relative_to(clean_dir).as_posix() for path in source_files],
        'written_paths': written_paths,
        'reference_map': reference_map,
        'stats': {
            'source_files': len(source_files),
            'output_files': len(written_paths),
            'globals_rules': len(globals_blocks),
            'selector_rules': len(selectors_blocks),
            'font_rules': len(fonts_blocks),
            'base_rules': len(base_blocks),
            'style_rules': len(style_blocks),
            'important_rules': len(important_blocks),
            'keyframes': len(keyframes_blocks),
            'base_media_blocks': len(base_media_blocks),
            'large_media_blocks': len(large_media_blocks),
        },
    }

    names = ', '.join(Path(path).as_posix() for path in written_paths) if written_paths else 'nenhum'
    _log(
        '   CSS consolidator: '
        f"{plan['stats']['source_files']} -> {plan['stats']['output_files']} arquivo(s) [{names}]"
    )
    return plan


def repair_css_references(clean_dir: Path, plan: dict, log=None) -> int:
    _log = log or (lambda m: None)
    clean_dir = Path(clean_dir).resolve()
    source_paths = plan.get('source_paths', [])
    written_paths = plan.get('written_paths', [])
    if not source_paths or not written_paths or not _BS4_AVAILABLE:
        return 0

    source_names = {Path(path).name for path in source_paths}
    written_names = {Path(path).name for path in written_paths}
    updated = 0

    for html_file in _iter_entry_html_files(clean_dir):
        try:
            content = html_file.read_text(encoding='utf-8', errors='ignore')
            soup = BeautifulSoup(content, 'html.parser')
            changed = False

            for link in _iter_live_stylesheet_links(soup):
                name = Path(link.get('href', '')).name
                if name in source_names or name in written_names:
                    link.decompose()
                    changed = True

            head = soup.find('head')
            if head and changed:
                for bundle_path in written_paths:
                    new_link = soup.new_tag('link')
                    new_link['rel'] = 'stylesheet'
                    new_link['href'] = '/' + bundle_path.lstrip('/')
                    head.append(new_link)

            if not changed:
                continue

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
            _log(f'      Aviso: falha ao reparar CSS em {html_file.name}: {exc}')

    if updated:
        _log(f'   CSS consolidator: referências HTML reparadas em {updated} arquivo(s)')
    return updated
