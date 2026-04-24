"""
CSS cleaning helpers.
"""
import re

from .css_tokens import extract_css_tokens

try:
    import cssbeautifier
    _CSSBEAUTIFIER_AVAILABLE = True
except ImportError:
    _CSSBEAUTIFIER_AVAILABLE = False

try:
    import rcssmin
    _RCSSMIN_AVAILABLE = True
except ImportError:
    _RCSSMIN_AVAILABLE = False


_TRACKING_CSS_COMMENT = re.compile(
    r'/\*[^*]*(?:google|analytics|tracking|gtm|pixel|hotjar|clarity|segment)[^*]*\*/',
    re.DOTALL | re.IGNORECASE,
)
# Regras vazias: seletor { } ou seletor { /* só comentário */ }
_EMPTY_RULE_PATTERN = re.compile(
    r'(?:^|(?<=\n))[ \t]*[^@{}\n/][^{}\n]*\{[ \t]*\}[ \t]*\n?',
    re.MULTILINE,
)
# Blocos @media / @supports vazios
_EMPTY_AT_RULE_PATTERN = re.compile(
    r'@(?:media|supports)[^{]+\{[ \t]*\}[ \t]*\n?',
    re.MULTILINE,
)


def clean_css_content(content):
    """
    Clean CSS for AI readability:
    1. Desminify with cssbeautifier (Format Document).
    2. Remove tracking comments.
    3. Remove all block comments.
    4. Remove empty rule blocks (dead code).
    5. Remove duplicate rule blocks.
    6. Normalize blank lines.
    """
    content = content.replace('\r\n', '\n').replace('\r', '\n')

    if _RCSSMIN_AVAILABLE:
        try:
            content = rcssmin.cssmin(content, keep_bang_comments=False)
        except TypeError:
            content = rcssmin.cssmin(content)
        except Exception:
            pass

    content = _TRACKING_CSS_COMMENT.sub('', content)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = _beautify_css(content)
    content = _remove_empty_rules(content)
    content = _remove_duplicate_rules(content)
    content = re.sub(r'\n\s*\n\s*\n+', '\n\n', content)
    content = re.sub(r'[ \t]+$', '', content, flags=re.MULTILINE)
    return content.strip() + '\n'


def clean_css_content_with_tokens(content):
    """Limpa CSS e extrai tokens. Retorna (css_limpo, tokens_dict)."""
    cleaned = clean_css_content(content)
    tokens = extract_css_tokens(cleaned)
    return cleaned, tokens


def _remove_empty_rules(content):
    """Remove blocos de regras sem propriedades (código morto óbvio)."""
    # Iterar até não haver mais regras vazias (regras podem ficar vazias após remover comentários)
    prev = None
    while prev != content:
        prev = content
        content = _EMPTY_RULE_PATTERN.sub('', content)
        content = _EMPTY_AT_RULE_PATTERN.sub('', content)
    return content


def _remove_duplicate_rules(content):
    """Remove blocos de regras idênticos (mesmo seletor e mesmo corpo)."""
    # Extrai blocos individuais como strings e remove duplicatas mantendo a última ocorrência
    # Abordagem conservadora: só remove blocos que são string-identicos
    block_pattern = re.compile(r'([^{}\n][^{}]*)\{([^{}]*)\}', re.MULTILINE)
    seen = {}
    for match in block_pattern.finditer(content):
        selector = match.group(1).strip()
        body = re.sub(r'\s+', ' ', match.group(2).strip())
        key = f'{selector}{{{body}}}'
        seen.setdefault(key, []).append(match)

    # Remover todas as ocorrências anteriores de blocos duplicados (manter a última)
    spans_to_remove = set()
    for matches in seen.values():
        if len(matches) > 1:
            for m in matches[:-1]:  # Manter a última, remover as anteriores
                spans_to_remove.add((m.start(), m.end()))

    if not spans_to_remove:
        return content

    result = []
    pos = 0
    for start, end in sorted(spans_to_remove):
        result.append(content[pos:start])
        pos = end
    result.append(content[pos:])
    return ''.join(result)


def _beautify_css(content):
    if not _CSSBEAUTIFIER_AVAILABLE:
        return content

    opts = cssbeautifier.default_options()
    opts.indent_size = 2
    opts.end_with_newline = True
    opts.newline_between_rules = True

    try:
        return cssbeautifier.beautify(content, opts)
    except Exception:
        return content
