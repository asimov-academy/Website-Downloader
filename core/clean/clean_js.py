"""
JavaScript cleaning helpers.
"""
import re

from .. import SKIP_DOMAINS, TRACKING_SCRIPTS

try:
    import jsbeautifier
    _JSBEAUTIFIER_AVAILABLE = True
except ImportError:
    _JSBEAUTIFIER_AVAILABLE = False

try:
    import rjsmin
    _RJSMIN_AVAILABLE = True
except ImportError:
    _RJSMIN_AVAILABLE = False


_VENDOR_JS_PATTERNS = [
    'jquery', 'react', 'react-dom', 'vue', 'angular', 'gsap', 'three',
    'framer-motion', 'lottie', 'swiper', 'locomotive', 'lenis', 'split-type',
    'bootstrap', 'tailwind', 'normalize', 'modernizr', 'lodash', 'underscore',
    'moment', 'dayjs', 'axios', 'babel', 'polyfill', 'webpack', 'vite',
    'alpinejs', 'alpine', 'stimulus', 'turbo', 'htmx', 'preact', 'solid-js',
    'svelte', 'lit', 'stencil', 'qwik', 'chart', 'd3', 'highcharts',
    'leaflet', 'mapbox', 'socket.io', 'firebase', 'supabase', 'stripe',
    'sentry', 'datadog', 'newrelic', 'bugsnag', 'prism', 'highlight',
    'shiki', 'katex', 'mathjax',
]
_VENDOR_PATH_PATTERNS = (
    'node_modules/',
    'vendor/',
    'lib/',
    'dist/',
    'chunks/',
    'chunk-',
    '.chunk.',
    '.min.',
    '.bundle.',
)
_GENERATED_JS_COMMENT_RE = re.compile(
    r'^\s*/\*\s*\[(?:tracking script removed|CODE COVERAGE)[^\]]*\][^*]*\*/\s*',
    re.IGNORECASE,
)


def _matches_tracking_pattern(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    for pattern in patterns:
        escaped = re.escape(pattern.lower())
        if re.search(rf'(?<![a-z0-9]){escaped}(?![a-z0-9])', lowered):
            return True
    return False


def clean_js_content(content, filename=''):
    """
    Clean JS conservatively for AI readability.
    """
    cleaned, _stats = clean_js_content_with_stats(content, filename)
    return cleaned


def clean_js_content_with_stats(content, filename=''):
    """Limpa JS e retorna (js_limpo, stats_dict)."""
    filename_lower = filename.lower()
    tracking_patterns = [pattern.lower() for pattern in TRACKING_SCRIPTS]
    tracking_domains = [domain.lower() for domain in SKIP_DOMAINS]
    preview = content[:500].lower()

    is_tracking = _matches_tracking_pattern(filename_lower, tracking_patterns)
    if not is_tracking:
        is_tracking = _matches_tracking_pattern(preview, tracking_patterns)
    if not is_tracking:
        is_tracking = any(domain in preview for domain in tracking_domains)

    is_vendor = any(pattern in filename_lower for pattern in _VENDOR_JS_PATTERNS)
    if not is_vendor:
        is_vendor = any(pattern in filename_lower for pattern in _VENDOR_PATH_PATTERNS)

    lines = content.split('\n')
    is_minified = len(lines) < 10 or (len(content) / max(len(lines), 1)) > 200

    stats = {
        'is_tracking': is_tracking,
        'is_vendor': is_vendor,
        'is_minified': is_minified,
    }

    if is_tracking:
        return '\n', stats

    content = _GENERATED_JS_COMMENT_RE.sub('', content, count=1)
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    content = _strip_js_comments(content)
    content = _format_js_content(content, should_beautify=True)
    content = _clean_formatted_js(content)

    return re.sub(r'\n\s*\n\s*\n+', '\n\n', content).strip() + '\n', stats


def _format_js_content(content, should_beautify):
    if not should_beautify or not _JSBEAUTIFIER_AVAILABLE:
        return content

    opts = jsbeautifier.default_options()
    opts.indent_size = 2
    opts.end_with_newline = True
    opts.preserve_newlines = True
    opts.max_preserve_newlines = 2
    opts.keep_array_indentation = False

    try:
        return jsbeautifier.beautify(content, opts)
    except Exception:
        return content


def _clean_formatted_js(content):
    lines = content.split('\n')
    cleaned = []

    for line in lines:
        stripped = line.strip()
        if re.match(r'^debugger\s*;?\s*$', stripped):
            continue
        if stripped.startswith('//'):
            if _is_important_comment(line):
                cleaned.append(line)
            continue
        cleaned.append(line)

    return '\n'.join(cleaned)


def _is_important_comment(line):
    keywords = ['@license', 'copyright', '(c)', 'mit license', 'bsd license', 'apache', 'gpl']
    lower = line.lower()
    return any(keyword in lower for keyword in keywords)


def _remove_block_comments(content):
    def replacer(match):
        block = match.group(0)
        if _is_important_comment(block):
            return block
        return ''

    return re.sub(r'/\*.*?\*/', replacer, content, flags=re.DOTALL)


def _strip_js_comments(content):
    if _RJSMIN_AVAILABLE:
        try:
            return rjsmin.jsmin(content, keep_bang_comments=False)
        except TypeError:
            return rjsmin.jsmin(content)
        except Exception:
            pass

    content = _remove_block_comments(content)
    cleaned_lines = []
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('//') and not _is_important_comment(line):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)
