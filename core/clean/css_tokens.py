"""
CSS design token extraction helpers.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup


_CUSTOM_PROPERTY_PATTERN = re.compile(r'(--[\w-]+)\s*:\s*([^;]+?)(?:;|$)')
_HEX_COLOR_PATTERN = re.compile(r'#(?:[0-9a-fA-F]{3}){1,2}\b')
_RGB_COLOR_START_PATTERN = re.compile(r'\b(rgba?)\s*\(', re.IGNORECASE)
_HSL_COLOR_START_PATTERN = re.compile(r'\b(hsla?)\s*\(', re.IGNORECASE)
_FONT_FACE_START_PATTERN = re.compile(r'@font-face\s*\{', re.IGNORECASE)
_KEYFRAMES_START_PATTERN = re.compile(
    r'@(?:-\w+-)?keyframes\s+([\w-]+)\s*\{',
    re.IGNORECASE,
)
# Media queries: @media (min-width: 768px), @media screen and (max-width: 1024px), etc.
_MEDIA_QUERY_PATTERN = re.compile(
    r'@media\s+([^{]+)\{',
    re.IGNORECASE,
)
# px/em/rem values inside media conditions
_BREAKPOINT_VALUE_PATTERN = re.compile(r'(\d+(?:\.\d+)?)(px|em|rem)')


def extract_css_tokens(content: str) -> dict:
    """Extrai design tokens de conteudo CSS."""
    return {
        'custom_properties': _extract_custom_properties(content),
        'colors': _extract_color_palette(content),
        'font_faces': _extract_font_faces(content),
        'keyframes': _extract_keyframes(content),
        'breakpoints': _extract_breakpoints(content),
    }


# Palavras-chave que identificam tokens VISUAIS de design (manter)
_VISUAL_TOKEN_KEYWORDS = (
    'color', 'colour', 'cubic', 'easing', 'duration', 'animation',
    'transition', 'radius', 'corner', 'rounded', 'font', 'scale',
)
# Prefixos/padrões que identificam tokens de LAYOUT/ESPAÇAMENTO (remover)
_LAYOUT_TOKEN_PATTERNS = (
    'padding', 'margin', 'gap', 'spacing', 'gutter', 'offset',
    'section-', 'container-', 'nav-', 'grid-', '-vh', '-vw',
    'mask-url', 'max-width', 'min-width', 'max-vh', 'max-vw',
    'fluid-container', 'design-width', 'design-unit',
    'oval', 'podium', 'spacer', 'text-offset',
)


def filter_visual_tokens(tokens: dict) -> dict:
    """Retorna apenas tokens relevantes para replicação visual de design.

    Remove tokens de layout e espaçamento que são óbvios e fáceis de recriar.
    Mantém: cores, fontes, keyframes, animações, radius, tipografia, breakpoints.
    """
    return {
        'custom_properties': _filter_design_custom_props(tokens.get('custom_properties', [])),
        'colors': tokens.get('colors', []),
        'font_faces': tokens.get('font_faces', []),
        'keyframes': tokens.get('keyframes', []),
        'breakpoints': tokens.get('breakpoints', []),
    }


def _filter_design_custom_props(props: list) -> list:
    result = []
    for prop in props:
        name = prop.get('name', '').lower()
        name_core = name.lstrip('-')

        # Remover tokens de layout/espaçamento
        if any(pattern in name_core for pattern in _LAYOUT_TOKEN_PATTERNS):
            continue

        # Manter tokens com palavras-chave visuais
        if any(kw in name_core for kw in _VISUAL_TOKEN_KEYWORDS):
            result.append(prop)
            continue

        # Manter --text-- (typography sizes, ex: --text--h1, --text--btn-primary)
        if '--text--' in name:
            result.append(prop)

    return result


def empty_css_tokens() -> dict:
    """Return a stable empty token payload."""
    return {
        'custom_properties': [],
        'colors': [],
        'font_faces': [],
        'keyframes': [],
        'breakpoints': [],
    }


def extract_css_tokens_from_html(content: str) -> dict:
    """
    Extract CSS tokens from inline <style> blocks inside HTML documents.

    Modern sites often colocate critical styled-components or CSS-in-JS output in
    the HTML shell, so relying on standalone .css files alone misses the site's
    most relevant colors, keyframes, and component-level variables.
    """

    soup = BeautifulSoup(content, 'html.parser')
    style_chunks = []

    for style_tag in soup.find_all('style'):
        css = style_tag.string or style_tag.get_text()
        css = (css or '').strip()
        if css:
            style_chunks.append(css)

    if not style_chunks:
        return empty_css_tokens()

    tokens = extract_css_tokens('\n\n'.join(style_chunks))
    for key in ('custom_properties', 'colors', 'font_faces', 'keyframes'):
        for token in tokens.get(key, []):
            token.setdefault('source', 'inline-style')
    return tokens


def _extract_custom_properties(content: str) -> list[dict]:
    tokens = []
    seen_names = set()

    for block in _iter_css_blocks(content):
        body = block[1:-1]
        if '{' in body or '}' in body:
            continue

        for match in _CUSTOM_PROPERTY_PATTERN.finditer(body):
            name = match.group(1).strip()
            value = match.group(2).strip()
            if name in seen_names:
                continue
            if not _is_valid_custom_property_value(value):
                continue
            seen_names.add(name)
            tokens.append({'name': name, 'value': value})

    return tokens


def _extract_color_palette(content: str) -> list[dict]:
    matches = []
    seen_values = set()

    for match in _HEX_COLOR_PATTERN.finditer(content):
        value = match.group(0).strip()
        if value in seen_values:
            continue
        seen_values.add(value)
        matches.append((match.start(), {'type': 'hex', 'value': value}))

    function_patterns = (
        ('rgb', _RGB_COLOR_START_PATTERN),
        ('hsl', _HSL_COLOR_START_PATTERN),
    )

    for token_type, pattern in function_patterns:
        for match in pattern.finditer(content):
            value = _extract_function_call(content, match.start())
            if not value:
                continue
            value = value.strip()
            if value in seen_values:
                continue
            seen_values.add(value)
            matches.append((match.start(), {'type': token_type, 'value': value}))

    matches.sort(key=lambda item: item[0])
    return [item[1] for item in matches]


def _extract_font_faces(content: str) -> list[dict]:
    tokens = []
    seen_signatures = set()

    for match in _FONT_FACE_START_PATTERN.finditer(content):
        block = _extract_braced_block(content, match.end() - 1)
        if not block:
            continue

        body = block[1:-1].strip()
        token = {
            'family': _clean_css_value(_extract_declaration(body, 'font-family'), strip_quotes=True),
            'weight': _clean_css_value(_extract_declaration(body, 'font-weight')),
            'style': _clean_css_value(_extract_declaration(body, 'font-style')),
            'src': _clean_css_value(_extract_declaration(body, 'src')),
        }

        signature = tuple(token.values())
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        tokens.append(token)

    return tokens


def _extract_keyframes(content: str) -> list[dict]:
    tokens = []
    seen_names = set()

    for match in _KEYFRAMES_START_PATTERN.finditer(content):
        name = match.group(1).strip()
        if not name or name in seen_names:
            continue

        block = _extract_braced_block(content, match.end() - 1)
        if not block:
            continue

        seen_names.add(name)
        tokens.append({'name': name, 'body': block[1:-1].strip()})

    return tokens


def _extract_declaration(block: str, name: str) -> str:
    pattern = re.compile(
        rf'{re.escape(name)}\s*:\s*([^;]+?)(?:;|$)',
        re.IGNORECASE,
    )
    match = pattern.search(block)
    return match.group(1).strip() if match else ''


def _clean_css_value(value: str, strip_quotes: bool = False) -> str:
    cleaned = (value or '').strip()
    if strip_quotes and len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _extract_braced_block(content: str, brace_index: int) -> str:
    if brace_index < 0 or brace_index >= len(content) or content[brace_index] != '{':
        return ''

    depth = 0
    for index in range(brace_index, len(content)):
        char = content[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return content[brace_index:index + 1]
    return ''


def _extract_function_call(content: str, start_index: int) -> str:
    if start_index < 0 or start_index >= len(content):
        return ''

    open_paren_index = content.find('(', start_index)
    if open_paren_index == -1:
        return ''

    depth = 0
    for index in range(open_paren_index, len(content)):
        char = content[index]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return content[start_index:index + 1]

    return ''


def _iter_css_blocks(content: str):
    stack = []
    for index, char in enumerate(content):
        if char == '{':
            stack.append(index)
        elif char == '}' and stack:
            start = stack.pop()
            yield content[start:index + 1]


def _extract_breakpoints(content: str) -> list[dict]:
    """Extrai media queries e seus valores de breakpoint (min-width, max-width)."""
    seen_queries: set = set()
    breakpoints = []

    for match in _MEDIA_QUERY_PATTERN.finditer(content):
        query = match.group(1).strip()
        # Normalizar espaços
        query = re.sub(r'\s+', ' ', query)
        if query in seen_queries:
            continue
        seen_queries.add(query)

        # Extrair valores numéricos (px/em/rem)
        values = []
        for val_match in _BREAKPOINT_VALUE_PATTERN.finditer(query):
            values.append(f'{val_match.group(1)}{val_match.group(2)}')

        breakpoints.append({
            'query': query,
            'values': values,
        })

    # Ordenar por primeiro valor numérico encontrado (menor → maior)
    def _sort_key(bp):
        vals = bp.get('values', [])
        if not vals:
            return 9999
        try:
            return float(re.search(r'[\d.]+', vals[0]).group())
        except Exception:
            return 9999

    breakpoints.sort(key=_sort_key)
    return breakpoints


def _is_valid_custom_property_value(value: str) -> bool:
    if not value:
        return True

    suspicious_fragments = ('{', '}', '@layer', '@media', '@supports', ':before', ':after')
    if any(fragment in value for fragment in suspicious_fragments):
        return False

    selector_like_pattern = re.compile(r'(?:^|\n)\s*[.#][\w-]+\s*[,{:]')
    if selector_like_pattern.search(value):
        return False

    return True
