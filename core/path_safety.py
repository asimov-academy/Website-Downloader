"""
Filesystem-safe path helpers for downloaded artifacts.

The downloader keeps URL structure when it can, but OS/filesystem limits still
apply. These helpers normalize path components for Windows compatibility and
shorten hostile URL segments with stable hashes.
"""
import hashlib
import os
import re
import unicodedata
from urllib.parse import unquote, urlparse


WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}

_INVALID_COMPONENT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_UNSAFE_ASCII_RE = re.compile(r'[^A-Za-z0-9._@-]+')
_MULTI_UNDERSCORE_RE = re.compile(r'_+')


def _hash_text(value: str, length: int = 10) -> str:
    return hashlib.md5(value.encode('utf-8', errors='ignore')).hexdigest()[:length]


def _fold_ascii(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value)
    return normalized.encode('ascii', errors='ignore').decode('ascii')


def sanitize_path_component(
    value,
    *,
    fallback: str = 'file',
    max_length: int = 96,
    preserve_extension: bool = True,
) -> str:
    """Return a Windows-safe single path component."""
    original = str(value or '')
    text = _fold_ascii(unicodedata.normalize('NFKC', original))
    text = _INVALID_COMPONENT_RE.sub('_', text)
    text = _UNSAFE_ASCII_RE.sub('_', text)
    text = _MULTI_UNDERSCORE_RE.sub('_', text).strip(' ._')

    safe_fallback = _UNSAFE_ASCII_RE.sub(
        '_',
        _fold_ascii(str(fallback or 'file')),
    ).strip(' ._')
    safe_fallback = safe_fallback or 'file'

    if not text:
        text = safe_fallback

    if preserve_extension:
        stem, ext = os.path.splitext(text)
        if len(ext) > 16:
            stem, ext = text, ''
    else:
        stem, ext = text, ''

    stem = (stem or safe_fallback).strip(' ._') or safe_fallback
    candidate = f'{stem}{ext}'.strip(' ._') or safe_fallback

    reserved_check = stem.upper().split('.')[0]
    if reserved_check in WINDOWS_RESERVED_NAMES:
        candidate = f'_{candidate}'

    max_length = max(24, int(max_length or 96))
    if len(candidate) <= max_length:
        return candidate

    digest = _hash_text(original or candidate)
    ext_for_short_name = ext if preserve_extension and len(ext) <= 16 else ''
    stem_budget = max(8, max_length - len(digest) - len(ext_for_short_name) - 1)
    shortened_stem = stem[:stem_budget].rstrip(' ._-') or safe_fallback
    candidate = f'{shortened_stem}_{digest}{ext_for_short_name}'

    if len(candidate) > max_length:
        candidate = f'{safe_fallback}_{digest}{ext_for_short_name}'

    return candidate[:max_length].rstrip(' ._') or f'{safe_fallback}_{digest}'


def sanitize_relative_path(
    parts,
    *,
    fallback: str = 'asset',
    max_component: int = 96,
    max_path: int = 220,
) -> str:
    """Sanitize and shorten a POSIX-style relative path."""
    if isinstance(parts, str):
        raw_parts = re.split(r'[/\\]+', parts)
    else:
        raw_parts = [str(part) for part in parts]

    raw_parts = [part for part in raw_parts if part and part not in {'.', '..'}]
    if not raw_parts:
        return sanitize_path_component(fallback, fallback=fallback, max_length=max_component)

    safe_parts = [
        sanitize_path_component(
            part,
            fallback=f'{fallback}_{idx + 1}',
            max_length=max_component,
            preserve_extension=(idx == len(raw_parts) - 1),
        )
        for idx, part in enumerate(raw_parts)
    ]

    relative = '/'.join(safe_parts)
    if len(relative) <= max_path:
        return relative

    compact_parts = [
        sanitize_path_component(
            part,
            fallback=f'{fallback}_{idx + 1}',
            max_length=(max_component if idx == len(raw_parts) - 1 else 32),
            preserve_extension=(idx == len(raw_parts) - 1),
        )
        for idx, part in enumerate(raw_parts)
    ]
    compact = '/'.join(compact_parts)
    if len(compact) <= max_path:
        return compact

    digest = _hash_text(relative)
    filename = compact_parts[-1]
    if len(compact_parts) > 1:
        first = sanitize_path_component(
            compact_parts[0],
            fallback=fallback,
            max_length=32,
            preserve_extension=False,
        )
        collapsed = f'{first}/_path_{digest}/{filename}'
    else:
        collapsed = filename

    if len(collapsed) <= max_path:
        return collapsed

    _, ext = os.path.splitext(filename)
    return sanitize_path_component(
        f'{fallback}_{digest}{ext}',
        fallback=fallback,
        max_length=min(max_component, max_path),
        preserve_extension=True,
    )


def sanitize_archive_label(value, *, fallback: str = 'site', max_length: int = 120) -> str:
    """Normalize a user-facing archive/download label without extension."""
    return sanitize_path_component(
        value,
        fallback=fallback,
        max_length=max_length,
        preserve_extension=False,
    )


def site_name_from_url(url, *, max_length: int = 120) -> str:
    """Build a stable ASCII site name for ZIP filenames."""
    parsed = urlparse(url)
    host = parsed.hostname or parsed.netloc or 'site'
    try:
        host = host.encode('idna').decode('ascii')
    except UnicodeError:
        host = _fold_ascii(host) or 'site'

    try:
        port = parsed.port
    except ValueError:
        port = None
    if port:
        host = f'{host}-{port}'

    name = sanitize_archive_label(host.removeprefix('www.'), fallback='site', max_length=72)
    path = unquote(parsed.path or '').strip('/')
    if path:
        path_label = sanitize_archive_label(path.replace('/', '_'), fallback='page', max_length=42)
        name = f'{name}_{path_label}'

    return sanitize_archive_label(name, fallback='site', max_length=max_length)
