"""
HTML cleaning helpers.
"""
import hashlib
import json
import re
from pathlib import Path

try:
    from bs4 import BeautifulSoup, Comment, NavigableString
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

from .. import CLEAN_SVG_THRESHOLD, looks_like_tracking_script

_TRACKING_META_PROPERTY_PREFIXES = ('og:', 'twitter:', 'fb:', 'article:')
_TRACKING_META_NAME_PREFIXES = ('msapplication-', 'twitter:')
_TRACKING_META_HTTP_EQUIV = {'x-ua-compatible', 'content-security-policy'}
_USELESS_LINK_RELS = {'preconnect', 'dns-prefetch', 'preload', 'prefetch', 'modulepreload'}
_TRACKING_DATA_PREFIXES = (
    'data-test',
    'data-testid',
    'data-cy',
    'data-qa',
    'data-gtm',
    'data-analytics',
    'data-tracking',
    'data-g-tag',
    'data-g-tm',
    'data-hs-',
    'data-heap-',
    'data-amplitude-',
    'data-segment-',
    'data-mixpanel-',
    'data-fb-',
    'data-pixel-',
)
_HIDDEN_CLASSES = {
    'hidden',
    'd-none',
    'sr-only',
    'visually-hidden',
    'screen-reader-text',
}
_BLOCKISH_TAGS = {
    'html',
    'head',
    'body',
    'main',
    'section',
    'article',
    'header',
    'footer',
    'nav',
    'aside',
    'div',
    'ul',
    'ol',
    'li',
    'table',
    'thead',
    'tbody',
    'tr',
    'td',
    'th',
    'picture',
}
# Script types that are NOT JavaScript — leave these inline in the HTML
_NON_JS_SCRIPT_TYPES = {
    'application/ld+json',
    'application/json',
    'importmap',
    'text/template',
    'text/x-handlebars-template',
    'text/x-tmpl',
    'text/html',
    'text/x-template',
}
_DISPLAY_NONE_PATTERN = re.compile(r'display\s*:\s*none', re.IGNORECASE)
_BLANK_LINES_PATTERN = re.compile(r'\n\s*\n\s*\n+')
_BLOCK_INTERTAG_WHITESPACE_PATTERN = re.compile(
    r'(</(?:html|head|body|main|section|article|header|footer|nav|aside|div|ul|ol|li|table|thead|tbody|tr|td|th|picture)>)\s+(<(?:html|head|body|main|section|article|header|footer|nav|aside|div|ul|ol|li|table|thead|tbody|tr|td|th|picture)\b)',
    re.IGNORECASE,
)


def _is_next_runtime_script(script_tag, inline_text=''):
    """Identify Next.js runtime/flight scripts that must survive clean pipeline."""
    script_id = (_safe_get(script_tag, 'id', '') or '').strip()
    script_type = (_safe_get(script_tag, 'type', '') or '').lower().strip()
    src = (_safe_get(script_tag, 'src', '') or '').lower()
    text = inline_text or script_tag.get_text(' ', strip=False) or ''

    if script_id == '__NEXT_DATA__':
        return True
    if 'self.__next_f.push' in text:
        return True
    if src.startswith('/_next/static/') or '/_next/static/' in src:
        return True
    if script_type == 'application/json' and script_id.startswith('__NEXT'):
        return True

    return False


def _is_preserved_inline_script(script_tag, inline_text=''):
    """Scripts that must remain inline to preserve bootstrap timing/order."""
    if _is_next_runtime_script(script_tag, inline_text):
        return True

    return False


def clean_html_content(content):
    """
    Clean HTML for AI readability.
    """
    cleaned, _stats = clean_html_content_with_stats(content)
    return cleaned


def clean_html_content_with_stats(content, filepath=None):
    """Retorna (html_limpo, stats_dict).

    filepath: Path ou str — necessário para extrair assets inline para arquivos externos.
    """
    stats = {
        'scripts_removed': 0,
        'iframes_removed': 0,
        'tracking_meta_removed': 0,
        'hidden_elements_removed': 0,
        'svgs_replaced': 0,
        'tracking_attrs_removed': 0,
        'tracking_scripts_removed': 0,
        'sections_detected': [],
        'inline_styles_extracted': 0,
        'inline_scripts_extracted': 0,
        'invalid_structured_data_removed': 0,
        'structured_data_normalized': 0,
    }

    if not _BS4_AVAILABLE:
        return content, stats

    soup = BeautifulSoup(content, 'html.parser')
    structured_data_stats = _sanitize_structured_data_scripts(soup)
    stats['invalid_structured_data_removed'] = structured_data_stats['removed']
    stats['structured_data_normalized'] = structured_data_stats['normalized']
    promoted_plain_scripts = _promote_local_plain_scripts(soup, Path(filepath) if filepath is not None else None)
    stats['promoted_plain_scripts'] = promoted_plain_scripts

    # Etapa A: Extrair <style> e <script> inline para arquivos externos
    if filepath is not None:
        extracted = _extract_inline_assets(soup, Path(filepath))
        stats['inline_styles_extracted'] = extracted['styles']
        stats['inline_scripts_extracted'] = extracted['scripts']

    # Etapa B: Remover tracking scripts (antes de qualquer outra limpeza)
    tracking_scripts_removed = _remove_tracking_scripts(soup)

    # Etapa C: Remover <noscript> e <iframe> (NÃO <script> — esses agora apontam para arquivos)
    noscript_stats = _remove_noscript_and_iframes(soup)

    tracking_meta_removed = _remove_tracking_meta(soup)
    _remove_useless_links(soup)
    tracking_attrs_removed = _remove_tracking_data_attrs(soup)
    _remove_empty_data_attrs(soup)
    hidden_elements_removed = _remove_hidden_elements(soup)
    svgs_replaced = _replace_complex_svgs(soup, filepath=filepath)
    _strip_comments(soup)
    sections_detected = _insert_section_markers(soup)
    _strip_block_intertag_whitespace(soup)

    stats['tracking_scripts_removed'] = tracking_scripts_removed
    stats['scripts_removed'] = tracking_scripts_removed
    stats['iframes_removed'] = noscript_stats['iframes_removed']
    stats['tracking_meta_removed'] = tracking_meta_removed
    stats['tracking_attrs_removed'] = tracking_attrs_removed
    stats['hidden_elements_removed'] = hidden_elements_removed
    stats['svgs_replaced'] = svgs_replaced
    stats['sections_detected'] = sections_detected

    # `prettify()` injeta whitespace entre tags irmãs e pode quebrar layouts
    # baseados em inline-block. Serializar sem pretty-print preserva a geometria.
    cleaned = _BLANK_LINES_PATTERN.sub('\n\n', soup.decode(formatter='minimal'))
    cleaned = _BLOCK_INTERTAG_WHITESPACE_PATTERN.sub(r'\1\2', cleaned)
    return cleaned, stats


# ---------------------------------------------------------------------------
# Inline asset extraction
# ---------------------------------------------------------------------------

def _extract_inline_assets(soup, html_path):
    """Extrai tags <style> e <script> inline para arquivos externos.

    Cria arquivos .css e .js no mesmo diretório do HTML e substitui as tags
    originais por <link rel="stylesheet"> e <script src="...">.

    Retorna dict com contagens: {'styles': N, 'scripts': N}.
    """
    html_path = Path(html_path)
    stem = html_path.stem
    parent = html_path.parent
    extracted = {'styles': 0, 'scripts': 0}

    # --- Extrair <style> → arquivos CSS ---
    for style_tag in list(soup.find_all('style')):
        # Skip styles injected by DeepMirror WebSites (not original site content)
        if style_tag.get('data-scroll-fix') == 'true':
            style_tag.decompose()
            continue

        css_content = style_tag.string or ''
        if not css_content.strip():
            style_tag.decompose()
            continue

        count = extracted['styles'] + 1
        filename = f'{stem}_style_{count}.css'
        css_path = parent / filename
        css_path.write_text(css_content, encoding='utf-8')

        link_tag = soup.new_tag('link')
        link_tag['rel'] = 'stylesheet'
        link_tag['href'] = filename
        style_tag.replace_with(link_tag)
        extracted['styles'] += 1

    # --- Extrair <script> inline → arquivos JS ---
    for script_tag in list(soup.find_all('script')):
        # Scripts com src já são referências externas — manter como estão
        if _safe_get(script_tag, 'src'):
            continue

        # Tipos não-JavaScript ficam inline (JSON-LD, templates, etc.)
        script_type = (_safe_get(script_tag, 'type', '') or '').lower().strip()
        if script_type in _NON_JS_SCRIPT_TYPES:
            continue

        js_content = script_tag.string or ''
        if not js_content.strip():
            script_tag.decompose()
            continue

        if _is_preserved_inline_script(script_tag, js_content):
            continue

        is_generated_runtime_script = (
            _safe_get(script_tag, 'data-fetch-interceptor', '') == 'true'
            or _safe_get(script_tag, 'data-runtime-compat-shim', '') == 'true'
        )

        # Scripts de tracking serão removidos pelo _remove_tracking_scripts — pular aqui
        if not is_generated_runtime_script and looks_like_tracking_script(js_content):
            continue

        count = extracted['scripts'] + 1
        filename = f'{stem}_script_{count}.js'
        js_path = parent / filename
        js_path.write_text(js_content, encoding='utf-8')

        new_script = soup.new_tag('script')
        new_script['src'] = filename
        # Preservar atributo type se for module
        if script_type in ('module', 'text/javascript'):
            if script_type == 'module':
                new_script['type'] = 'module'
        script_tag.replace_with(new_script)
        extracted['scripts'] += 1

    return extracted


# ---------------------------------------------------------------------------
# Cleaning helpers
# ---------------------------------------------------------------------------

def _remove_tracking_scripts(soup):
    removed = 0

    for script in list(soup.find_all('script')):
        script_type = (_safe_get(script, 'type', '') or '').lower().strip()
        if script_type in _NON_JS_SCRIPT_TYPES:
            continue
        if _safe_get(script, 'data-generated-importmap', '') == 'true':
            continue
        if _safe_get(script, 'data-fetch-interceptor', '') == 'true':
            continue
        if _safe_get(script, 'data-runtime-compat-shim', '') == 'true':
            continue

        src = _safe_get(script, 'src', '')
        inline = script.get_text(' ', strip=True)
        if _is_preserved_inline_script(script, inline):
            continue
        attr_values = []
        if isinstance(getattr(script, 'attrs', None), dict):
            for attr_value in script.attrs.values():
                if isinstance(attr_value, list):
                    attr_values.extend(str(item) for item in attr_value)
                else:
                    attr_values.append(str(attr_value))
        if looks_like_tracking_script(src, inline, *attr_values):
            script.decompose()
            removed += 1

    return removed


def _promote_local_plain_scripts(soup, html_path=None):
    promoted = 0
    for script in list(soup.find_all('script', src=True)):
        script_type = (_safe_get(script, 'type', '') or '').lower().strip()
        if script_type != 'text/plain':
            continue
        src = (_safe_get(script, 'src', '') or '').strip()
        if not src or src.startswith(('http://', 'https://', '//', 'data:', 'blob:')):
            continue

        target_path = _resolve_local_script_path(src, html_path)
        if target_path is None or not target_path.is_file():
            continue

        file_text = ''
        try:
            file_text = target_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            file_text = ''

        haystack = '\n'.join(
            part for part in (
                src.lower(),
                (_safe_get(script, 'id', '') or '').lower(),
                file_text.lower(),
            ) if part
        )
        if looks_like_tracking_script(haystack):
            continue

        del script['type']
        promoted += 1

    return promoted


def _resolve_local_script_path(src, html_path):
    if not src or html_path is None:
        return None
    html_path = Path(html_path)
    if src.startswith('/'):
        for candidate in (html_path.parent, *html_path.parents):
            if (candidate / 'assets').exists():
                direct = candidate / src.lstrip('/')
                if direct.exists():
                    return direct
                asset_mirror = candidate / 'assets' / src.lstrip('/')
                if asset_mirror.exists():
                    return asset_mirror
                return direct
        return html_path.parent / src.lstrip('/')
    return (html_path.parent / src).resolve()


def _sanitize_structured_data_scripts(soup):
    stats = {'removed': 0, 'normalized': 0}
    broken_markers = (
        '<br',
        '<b>notice',
        'array to string conversion',
        'warning:',
        'fatal error:',
        'stack trace:',
    )

    for script in list(soup.find_all('script')):
        script_type = (_safe_get(script, 'type', '') or '').lower().strip()
        if script_type != 'application/ld+json':
            continue

        script_text = script.string or script.get_text() or ''
        stripped = script_text.strip()
        if not stripped:
            script.decompose()
            stats['removed'] += 1
            continue

        lowered = stripped.lower()
        if any(marker in lowered for marker in broken_markers):
            script.decompose()
            stats['removed'] += 1
            continue

        try:
            payload = json.loads(stripped)
        except Exception:
            continue

        compact = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        if compact != stripped:
            script.clear()
            script.append(compact)
            stats['normalized'] += 1

    return stats


def _remove_noscript_and_iframes(soup):
    """Remove <noscript> e <iframe>. NÃO remove <script> — esses ficam como refs locais."""
    stats = {'noscripts_removed': 0, 'iframes_removed': 0}

    for tag in list(soup.find_all('noscript')):
        tag.decompose()
        stats['noscripts_removed'] += 1

    for tag in list(soup.find_all('iframe')):
        tag.decompose()
        stats['iframes_removed'] += 1

    return stats


def _remove_tracking_meta(soup):
    removed = 0

    for meta in list(soup.find_all('meta')):
        prop = (_safe_get(meta, 'property', '') or '').strip().lower()
        name = (_safe_get(meta, 'name', '') or '').strip().lower()
        http_equiv = (_safe_get(meta, 'http-equiv', '') or '').strip().lower()

        if any(prop.startswith(prefix) for prefix in _TRACKING_META_PROPERTY_PREFIXES):
            meta.decompose()
            removed += 1
            continue

        if name == 'description':
            continue

        if any(name.startswith(prefix) for prefix in _TRACKING_META_NAME_PREFIXES):
            meta.decompose()
            removed += 1
            continue

        if http_equiv in _TRACKING_META_HTTP_EQUIV:
            meta.decompose()
            removed += 1

    return removed


def _remove_useless_links(soup):
    removed = 0

    for link in list(soup.find_all('link')):
        rel_values = _safe_get(link, 'rel', []) or []
        if isinstance(rel_values, str):
            rel_values = [rel_values]
        rel_values = {value.lower() for value in rel_values}
        if rel_values.intersection(_USELESS_LINK_RELS):
            link.decompose()
            removed += 1

    return removed


def _remove_tracking_data_attrs(soup):
    removed = 0

    for element in soup.find_all(True):
        attrs = _safe_attrs(element)
        for attr_name in list(attrs):
            normalized = attr_name.lower()
            if any(normalized.startswith(prefix) for prefix in _TRACKING_DATA_PREFIXES):
                del attrs[attr_name]
                removed += 1

    return removed


def _remove_empty_data_attrs(soup):
    removed = 0

    for element in soup.find_all(True):
        attrs = _safe_attrs(element)
        for attr_name in list(attrs):
            normalized = attr_name.lower()
            value = attrs.get(attr_name)
            if not normalized.startswith('data-'):
                continue
            if any(normalized.startswith(prefix) for prefix in _TRACKING_DATA_PREFIXES):
                if value is None:
                    del attrs[attr_name]
                    removed += 1
                    continue
                if isinstance(value, (list, tuple)) and not any(str(item).strip() for item in value):
                    del attrs[attr_name]
                    removed += 1
                    continue
                if isinstance(value, str) and not value.strip():
                    del attrs[attr_name]
                    removed += 1

    return removed


def _remove_hidden_elements(soup):
    removed = 0

    for element in list(soup.find_all(True)):
        if element.parent is None:
            continue
        classes = _safe_get(element, 'class', []) or []
        if isinstance(classes, str):
            classes = classes.split()
        class_tokens = {token.lower() for token in classes}
        style = _safe_get(element, 'style', '')

        if class_tokens.intersection(_HIDDEN_CLASSES) or _DISPLAY_NONE_PATTERN.search(style):
            element.decompose()
            removed += 1

    return removed


def _strip_block_intertag_whitespace(soup):
    for node in list(soup.find_all(string=True)):
        if not isinstance(node, NavigableString):
            continue
        if node.parent is None or node.strip():
            continue

        prev_sibling = node.previous_sibling
        while isinstance(prev_sibling, NavigableString) and not prev_sibling.strip():
            prev_sibling = prev_sibling.previous_sibling

        next_sibling = node.next_sibling
        while isinstance(next_sibling, NavigableString) and not next_sibling.strip():
            next_sibling = next_sibling.next_sibling

        if (
            getattr(prev_sibling, 'name', None) in _BLOCKISH_TAGS
            and getattr(next_sibling, 'name', None) in _BLOCKISH_TAGS
        ):
            node.extract()


def _replace_complex_svgs(soup, filepath=None):
    replaced = 0
    html_path = Path(filepath) if filepath is not None else None

    for svg in list(soup.find_all('svg')):
        serialized = str(svg)
        if len(serialized) <= CLEAN_SVG_THRESHOLD:
            continue

        metadata = []
        for attr_name in ('id', 'class', 'aria-label', 'width', 'height', 'viewBox'):
            value = _safe_get(svg, attr_name)
            if isinstance(value, (list, tuple)):
                value = ' '.join(str(item) for item in value if str(item).strip())
            if value:
                metadata.append(f'{attr_name}="{value}"')

        label = ' '.join(metadata) if metadata else 'inline svg'
        exported_name = None
        if html_path is not None:
            digest = hashlib.sha1(serialized.encode('utf-8')).hexdigest()[:12]
            exported_name = f'inline_svg_{digest}.svg'
            exported_path = html_path.parent / exported_name
            if not exported_path.exists():
                exported_path.write_text(serialized, encoding='utf-8')

        if exported_name:
            placeholder = soup.new_tag('img')
            placeholder['src'] = exported_name
            placeholder['alt'] = '' if label == 'inline svg' else label
            placeholder['data-clean-placeholder'] = 'svg'
            placeholder['data-clean-origin'] = 'inline-svg'
            placeholder['data-clean-bytes'] = str(len(serialized))
        else:
            placeholder = soup.new_tag('svg')
            placeholder['data-clean-placeholder'] = 'svg'
            placeholder['data-clean-bytes'] = str(len(serialized))
            placeholder['aria-label'] = label

        svg_class = _safe_get(svg, 'class', [])
        if isinstance(svg_class, str):
            svg_class = svg_class.split()
        if svg_class:
            placeholder['class'] = svg_class

        for attr_name in ('id', 'width', 'height', 'viewBox', 'style', 'role', 'aria-hidden'):
            value = _safe_get(svg, attr_name)
            if value:
                if attr_name == 'viewBox' and exported_name:
                    placeholder['data-clean-viewbox'] = value
                else:
                    placeholder[attr_name] = value

        if not exported_name:
            placeholder.string = '...'
        svg.replace_with(placeholder)
        replaced += 1

    return replaced


def _strip_comments(soup):
    for comment in list(soup.find_all(string=lambda value: isinstance(value, Comment))):
        comment.extract()


def _insert_section_markers(soup):
    sections = [
        ('header', soup.find('header')),
        ('nav', soup.find('nav')),
        ('hero', _find_hero_section(soup)),
        ('main', soup.find('main')),
        ('footer', soup.find('footer')),
    ]

    detected = []
    seen_tags = set()

    for name, tag in sections:
        if not tag or id(tag) in seen_tags:
            continue
        detected.append(name)
        seen_tags.add(id(tag))

    return detected


def _find_hero_section(soup):
    for tag in soup.find_all(True):
        tag_id = (_safe_get(tag, 'id', '') or '').lower()
        if 'hero' in tag_id:
            return tag

        classes = _safe_get(tag, 'class', []) or []
        if isinstance(classes, str):
            classes = classes.split()
        for class_name in classes:
            if 'hero' in class_name.lower():
                return tag

    return None


def _safe_attrs(tag):
    attrs = getattr(tag, 'attrs', None)
    if isinstance(attrs, dict):
        return attrs
    return {}


def _safe_get(tag, key, default=None):
    attrs = _safe_attrs(tag)
    return attrs.get(key, default)
