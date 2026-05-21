"""
Validator - check clean/ path integrity and generate _validation_report.json.
"""
import json
import re
from datetime import datetime
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

_EXTERNAL_PREFIXES = (
    'http://', 'https://', 'data:', 'blob:', '//', '#', '%23',
    'mailto:', 'tel:',
)


def _is_external(ref: str) -> bool:
    return not ref or any(ref.startswith(p) for p in _EXTERNAL_PREFIXES)


_DYNAMIC_PREFIXES = ('/_next/image', '/_next/data', '/api/', '/__nextjs_')


def _resolve_ref(ref: str, source_file: Path, clean_dir: Path):
    """Resolve a path reference to an absolute path, or None if external/dynamic."""
    if _is_external(ref):
        return None
    # Skip dynamic routes: Next.js image optimization, API routes, etc.
    if any(ref.startswith(p) for p in _DYNAMIC_PREFIXES):
        return None
    # Skip references that only exist as query-string endpoints (no static file)
    if ref.startswith('/') and '?' in ref and not ref.split('?')[0].endswith(
        ('.html', '.css', '.js', '.json', '.svg', '.woff2', '.woff', '.ttf',
         '.png', '.jpg', '.webp', '.avif', '.gif')
    ):
        return None
    ref_clean = ref.split('?')[0].split('#')[0].strip()
    if not ref_clean or ref_clean in ('/', ''):
        return None
    if ref_clean.startswith('/') and not Path(ref_clean).suffix and len(ref_clean.split('/')) > 2:
        return None
    if ref_clean.startswith('/'):
        return (clean_dir / ref_clean.lstrip('/')).resolve()
    return (source_file.parent / ref_clean).resolve()


def _collect_html_refs(html_file: Path, clean_dir: Path) -> list:
    refs = []
    try:
        content = html_file.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return refs

    file_rel = html_file.relative_to(clean_dir).as_posix()

    if not _BS4_AVAILABLE:
        for m in re.finditer(
            r'(?:src|href|data-src|poster)=["\']([^"\']+)["\']', content
        ):
            val = m.group(1)
            if not _is_external(val):
                refs.append({'file': file_rel, 'attribute': 'attr', 'path': val})
        return refs

    soup = BeautifulSoup(content, 'html.parser')
    _ATTRS = {
        'link':   ['href'],
        'script': ['src'],
        'img':    ['src', 'data-src', 'srcset'],
        'source': ['src', 'srcset'],
        'video':  ['src', 'poster'],
        'audio':  ['src'],
    }
    for tag_name, attrs in _ATTRS.items():
        for el in soup.find_all(tag_name):
            for attr in attrs:
                val = el.get(attr)
                if not val or _is_external(val):
                    continue
                if attr == 'srcset':
                    for part in val.split(','):
                        tokens = part.strip().split()
                        if tokens and not _is_external(tokens[0]):
                            refs.append({
                                'file': file_rel,
                                'attribute': attr,
                                'path': tokens[0],
                            })
                else:
                    refs.append({'file': file_rel, 'attribute': attr, 'path': val})
    return refs


def _collect_css_refs(css_file: Path, clean_dir: Path) -> list:
    refs = []
    try:
        content = css_file.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return refs

    file_rel = css_file.relative_to(clean_dir).as_posix()

    for m in re.finditer(r'url\(["\']?([^)"\']+)["\']?\)', content):
        path = m.group(1).strip()
        if not _is_external(path):
            refs.append({'file': file_rel, 'attribute': 'url()', 'path': path})

    for m in re.finditer(r'@import\s+["\']([^"\']+)["\']', content):
        path = m.group(1).strip()
        if not _is_external(path):
            refs.append({'file': file_rel, 'attribute': '@import', 'path': path})

    return refs


def validate_clean(clean_dir: Path) -> dict:
    """
    Check all referenced paths in HTML/CSS exist in clean/.
    Returns a validation report dict.
    """
    clean_dir = Path(clean_dir)
    audit_dir = clean_dir / 'audit'
    all_refs = []

    for path in sorted(clean_dir.rglob('*')):
        if not path.is_file():
            continue
        try:
            path.relative_to(audit_dir)
            continue
        except ValueError:
            pass

        ext = path.suffix.lower()
        if ext in ('.html', '.htm'):
            all_refs.extend(_collect_html_refs(path, clean_dir))
        elif ext == '.css':
            all_refs.extend(_collect_css_refs(path, clean_dir))

    broken = []
    total_checked = 0
    for ref_info in all_refs:
        total_checked += 1
        resolved = _resolve_ref(
            ref_info['path'],
            clean_dir / ref_info['file'],
            clean_dir,
        )
        if resolved is None:
            continue
        if not resolved.exists():
            broken.append(ref_info)

    return {
        'generated_at': datetime.now().isoformat(),
        'total_references_checked': total_checked,
        'total_broken': len(broken),
        'passed': len(broken) == 0,
        'broken_references': broken[:50],
    }


def save_validation_report(clean_dir: Path) -> dict:
    """Run validation and write _validation_report.json."""
    clean_dir = Path(clean_dir)
    report = validate_clean(clean_dir)
    output_path = clean_dir / '_validation_report.json'
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    return report
