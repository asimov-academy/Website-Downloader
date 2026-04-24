"""
Site classification based on downloaded artifacts.

Analyzes raw/ content to detect site type, framework, and asset patterns.
Reference: AI-Design-Engineering.md Section 2.2
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal

# Framework detection patterns in HTML/JS
FRAMEWORK_PATTERNS = {
    'next': [r'_next/static', r'__NEXT_DATA__', r'next\.js'],
    'nuxt': [r'_nuxt/', r'__NUXT__', r'nuxt\.js'],
    'gatsby': [r'gatsby-', r'__GATSBY', r'public-page-data'],
    'react-router': [r'react-router', r'ReactRouter'],
    'webflow': [r'webflow\.js', r'w-nav', r'w-dropdown', r'data-wf-page'],
    'framer': [r'framer\.js', r'framer-motion', r'__framer'],
}

# Scroll-jacking libraries
SCROLL_JACKING_PATTERNS = [
    r'gsap',
    r'ScrollTrigger',
    r'locomotive-scroll',
    r'lenis',
    r'barba',
    r'smoothscroll',
]

# Lottie detection in JSON
LOTTIE_KEYS = {'v', 'fr', 'ip', 'op', 'layers', 'assets'}


def classify_site(site_dir: str | Path) -> dict:
    """
    Classify a downloaded site based on its raw/ content.

    Returns:
        {
            "site_type": "static" | "spa" | "webgl" | "rive" | "lottie" | "scroll-jacking",
            "framework": "next" | "nuxt" | "gatsby" | "react-router" | "webflow" | "framer" | "vanilla",
            "dominant_assets": ["woff2", "webp", "glb", ...],
            "has_canvas": bool,
            "has_webgl": bool,
            "has_rive": bool,
            "has_lottie": bool,
            "has_scroll_jacking": bool,
            "asset_counts": {"html": N, "css": N, "js": N, ...},
            "evidence": {"framework": [...], "scroll_jacking": [...], ...}
        }
    """
    site_dir = Path(site_dir)
    raw_dir = site_dir / 'raw'

    if not raw_dir.exists():
        raw_dir = site_dir

    evidence = {
        'framework': [],
        'scroll_jacking': [],
        'canvas': [],
        'webgl': [],
    }

    # Collect all files
    html_files = list(raw_dir.glob('**/*.html'))
    css_files = list(raw_dir.glob('**/*.css'))
    js_files = list(raw_dir.glob('**/*.js'))
    json_files = list(raw_dir.glob('**/*.json'))

    # Count assets by extension
    all_files = list(raw_dir.rglob('*'))
    asset_counter = Counter()
    for file_path in all_files:
        if file_path.is_file():
            ext = file_path.suffix.lower().lstrip('.')
            if ext:
                asset_counter[ext] += 1

    # Detect framework
    framework = 'vanilla'
    combined_text = ''

    # Read HTML files
    for html_path in html_files[:5]:  # Sample first 5 HTML files
        try:
            html_text = html_path.read_text(encoding='utf-8', errors='ignore')
            combined_text += html_text + '\n'
        except Exception:
            continue

    # Read JS files (sample)
    for js_path in js_files[:10]:  # Sample first 10 JS files
        try:
            if js_path.stat().st_size > 500_000:  # Skip huge files
                continue
            js_text = js_path.read_text(encoding='utf-8', errors='ignore')
            combined_text += js_text + '\n'
        except Exception:
            continue

    # Detect framework
    for fw_name, patterns in FRAMEWORK_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                framework = fw_name
                evidence['framework'].append(f'Pattern: {pattern}')
                break
        if framework != 'vanilla':
            break

    # Detect scroll-jacking
    has_scroll_jacking = False
    for pattern in SCROLL_JACKING_PATTERNS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            has_scroll_jacking = True
            evidence['scroll_jacking'].append(f'Pattern: {pattern}')

    # Detect canvas/WebGL
    has_canvas = bool(re.search(r'<canvas', combined_text, re.IGNORECASE))
    has_webgl = bool(
        re.search(r'getContext\(["\']webgl', combined_text, re.IGNORECASE)
        or re.search(r'THREE\.', combined_text)
        or re.search(r'gl_FragColor|gl_Position', combined_text)
    )

    if has_canvas:
        evidence['canvas'].append('Found <canvas> tags')
    if has_webgl:
        evidence['webgl'].append('Found WebGL context or Three.js or GLSL')

    # Detect Rive
    has_rive = asset_counter.get('riv', 0) > 0

    # Detect Lottie
    has_lottie = False
    for json_path in json_files[:20]:  # Sample first 20 JSONs
        try:
            if json_path.stat().st_size > 100_000:  # Skip huge JSONs
                continue
            json_data = json.loads(json_path.read_text(encoding='utf-8', errors='ignore'))
            if isinstance(json_data, dict) and LOTTIE_KEYS.issubset(json_data.keys()):
                has_lottie = True
                break
        except Exception:
            continue

    # Determine primary site type
    site_type: Literal['static', 'spa', 'webgl', 'rive', 'lottie', 'scroll-jacking'] = 'static'

    if has_rive:
        site_type = 'rive'
    elif has_webgl and asset_counter.get('glb', 0) + asset_counter.get('gltf', 0) > 0:
        site_type = 'webgl'
    elif has_lottie:
        site_type = 'lottie'
    elif has_scroll_jacking:
        site_type = 'scroll-jacking'
    elif framework in {'next', 'nuxt', 'gatsby', 'react-router'}:
        site_type = 'spa'

    # Get dominant asset types (top 10)
    dominant_assets = [ext for ext, _ in asset_counter.most_common(10)]

    return {
        'site_type': site_type,
        'framework': framework,
        'dominant_assets': dominant_assets,
        'has_canvas': has_canvas,
        'has_webgl': has_webgl,
        'has_rive': has_rive,
        'has_lottie': has_lottie,
        'has_scroll_jacking': has_scroll_jacking,
        'asset_counts': dict(asset_counter),
        'evidence': evidence,
    }


def save_classification(site_dir: str | Path, output_path: str | Path | None = None) -> Path:
    """
    Classify site and save to clean/_site_classification.json.
    """
    site_dir = Path(site_dir)
    classification = classify_site(site_dir)

    if output_path is None:
        clean_dir = site_dir / 'clean'
        if not clean_dir.exists():
            clean_dir = site_dir
        output_path = clean_dir / '_site_classification.json'
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(classification, indent=2, ensure_ascii=False), encoding='utf-8')

    return output_path
