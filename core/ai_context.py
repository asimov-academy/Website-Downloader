"""
Generate AI-ready context from all extracted data.

This file is meant to become the single AI-facing artifact inside clean/.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def generate_ai_context(
    site_dir: str | Path,
    output_path: str | Path | None = None,
    tokens: dict | None = None,
) -> Path:
    """Generate clean/_ai_context.md.

    tokens: pre-computed visual design tokens (from manager pipeline).
    If omitted, falls back to reading _site_tokens.json from disk (legacy).
    """
    site_dir = Path(site_dir)
    clean_dir = site_dir / 'clean'
    if not clean_dir.exists():
        clean_dir = site_dir

    classification = _load_json(clean_dir / '_site_classification.json')
    if tokens is None:
        tokens = _load_json(clean_dir / '_site_tokens.json')
    computed = _load_json(clean_dir / '_computed_styles.json')
    scroll_physics_md = _load_text(clean_dir / '_scroll_physics.md')

    lines: list[str] = []

    def h1(t): lines.extend([f'# {t}', ''])
    def h2(t): lines.extend(['', f'## {t}', ''])
    def h3(t): lines.extend([f'### {t}', ''])
    def add(*args): lines.extend(args)

    # -------------------------------------------------------------------------
    # Header
    # -------------------------------------------------------------------------
    h1(f'AI Context — {site_dir.name}')
    add('> Auto-generated. Single source of truth for AI design replication.', '')

    css_files = sorted((clean_dir / 'assets' / 'css').rglob('*.css')) if (clean_dir / 'assets' / 'css').exists() else []
    js_files = sorted((clean_dir / 'assets' / 'js').glob('*.js')) if (clean_dir / 'assets' / 'js').exists() else []

    h2('1. Site')
    flags = []
    if classification.get('has_canvas'):    flags.append('canvas')
    if classification.get('has_webgl'):     flags.append('WebGL')
    if classification.get('has_rive'):      flags.append('Rive')
    if classification.get('has_lottie'):    flags.append('Lottie')
    if classification.get('has_scroll_jacking'): flags.append('scroll-jacking')

    add(
        f"- **Type:** {classification.get('site_type', 'unknown')}",
        f"- **Framework:** {classification.get('framework', 'unknown')}",
        f"- **Features:** {', '.join(flags) if flags else 'none'}",
    )

    asset_counts = classification.get('asset_counts', {})
    if asset_counts:
        dom_assets = ', '.join(
            f"{ext}:{n}" for ext, n in
            sorted(asset_counts.items(), key=lambda x: -x[1])[:8]
        )
        add(f'- **Assets:** {dom_assets}')
    if css_files or js_files:
        add(
            f"- **Bundles:** CSS {len(css_files)} arquivo(s) | JS {len(js_files)} arquivo(s)"
        )
    add('')

    # -------------------------------------------------------------------------
    # 2. Design Tokens
    # -------------------------------------------------------------------------
    h2('2. Design Tokens')

    # 2.1 CSS Custom Properties (compact: one per line)
    custom_props = tokens.get('custom_properties', [])
    if custom_props:
        h3('CSS Variables')
        add('```css')
        for prop in custom_props:
            add(f"{prop['name']}: {prop['value']};")
        add('```', '')

    # 2.2 Color Palette
    colors = tokens.get('colors', [])
    if colors:
        _generic = {
            '#000', '#000000', '#fff', '#ffffff', '#333', '#666', '#999',
            '#ccc', '#ddd', '#eee', '#222', '#444', '#555', '#777', '#888',
            '#aaa', '#bbb', '#f0f0f0', '#f5f5f5', '#fafafa',
        }
        design_colors = [
            c for c in colors
            if c.get('value', '').lower() not in _generic
        ]
        if design_colors:
            h3('Color Palette')
            # Show hex colors as a compact CSS comment list
            hex_colors = [c['value'] for c in design_colors if c.get('type') == 'hex']
            other_colors = [c['value'] for c in design_colors if c.get('type') != 'hex']
            if hex_colors:
                add('```css')
                # 4 per line for compactness
                for i in range(0, len(hex_colors), 4):
                    add('  '.join(hex_colors[i:i+4]))
                add('```', '')
            if other_colors:
                add('```css')
                for c in other_colors[:12]:
                    add(c)
                add('```', '')

    # 2.3 Breakpoints / Responsive
    breakpoints = tokens.get('breakpoints', [])
    if breakpoints:
        h3('Breakpoints (Media Queries)')
        add('```css')
        for bp in breakpoints:
            add(f"@media {bp['query']}")
        add('```', '')

    if css_files:
        h3('CSS Files')
        for css_path in css_files[:20]:
            add(f'- `{css_path.relative_to(clean_dir).as_posix()}`')
        add('')

    # 2.4 Typography — Fonts
    fonts = tokens.get('font_faces', [])
    if fonts:
        h3('Font Faces')
        for f in fonts:
            family = f.get('family', '')
            weight = f.get('weight', '')
            style = f.get('style', 'normal')
            src = f.get('src', '')
            # Shorten src: extract filename only from url()
            src_short = re.sub(r"url\(['\"]?([^'\")\s]+)['\"]?\)", lambda m: Path(m.group(1)).name, src)
            src_short = src_short[:60] + '…' if len(src_short) > 60 else src_short
            add(f'- **{family}** weight:{weight} style:{style} → `{src_short}`')
        add('')

    # 2.5 Keyframes (with body)
    keyframes = tokens.get('keyframes', [])
    if keyframes:
        h3('Keyframes')
        add('```css')
        for kf in keyframes:
            name = kf.get('name', '')
            body = kf.get('body', '').strip()
            add(f'@keyframes {name} {{')
            for body_line in body.splitlines():
                add(f'  {body_line}')
            add('}')
        add('```', '')

    # -------------------------------------------------------------------------
    # 3. Computed Typography (Runtime)
    # -------------------------------------------------------------------------
    if computed:
        h2('3. Computed Typography')
        add('> Values computed by the browser (source of truth over CSS declarations).', '')

        typo_selectors = ['h1', 'h2', 'h3', 'h4', 'p', 'button', 'a', 'span']
        typo_props = [
            'fontFamily', 'fontSize', 'fontWeight', 'lineHeight',
            'letterSpacing', 'textTransform', 'color',
        ]

        rows = []
        for sel in typo_selectors:
            style = computed.get(sel, {})
            if not style:
                continue
            size = style.get('fontSize', '')
            weight = style.get('fontWeight', '')
            lh = style.get('lineHeight', '')
            ls = style.get('letterSpacing', '')
            tt = style.get('textTransform', 'none')
            color = style.get('color', '')
            family = style.get('fontFamily', '').split(',')[0].strip().strip('"\'')
            row = f'| `{sel}` | {family} | {size} | {weight} | {lh} | {ls} | {tt} | {color} |'
            rows.append(row)

        if rows:
            add('| Selector | Font | Size | Weight | Line-H | Letter-S | Transform | Color |')
            add('|---|---|---|---|---|---|---|---|')
            add(*rows)
            add('')

    if js_files:
        h2('4. Runtime Files')
        preview = ', '.join(f'`{path.name}`' for path in js_files[:12])
        add(f'- JS bundles: {preview}')
        add('')

    has_rive = classification.get('has_rive', False)
    has_lottie = classification.get('has_lottie', False)

    if has_rive or has_lottie:
        h2('5. Animations')

        if has_rive:
            riv_files = list((site_dir / 'raw').rglob('*.riv')) if (site_dir / 'raw').exists() else []
            if riv_files:
                add(f'**Rive** — {len(riv_files)} file(s):')
                for riv in riv_files[:10]:
                    add(f'- `{riv.name}`')
                add('')
                add('> Use `@rive-app/canvas` runtime. Each `.riv` contains named state machines.', '')

        if has_lottie:
            lottie_files = list((site_dir / 'raw').rglob('*lottie*.json')) if (site_dir / 'raw').exists() else []
            if lottie_files:
                add(f'**Lottie** — {len(lottie_files)} file(s):')
                for f in lottie_files[:10]:
                    add(f'- `{f.name}`')
                add('')

    if scroll_physics_md:
        h2('6. Scroll Animations')
        # Embed the pre-generated compact markdown (table format)
        for md_line in scroll_physics_md.splitlines():
            add(md_line)
        add('')

    h2('7. Assets')
    if asset_counts:
        images = sum(n for ext, n in asset_counts.items()
                     if ext in ['jpg', 'jpeg', 'png', 'webp', 'avif', 'gif', 'svg'])
        fonts_n = sum(n for ext, n in asset_counts.items() if ext in ['woff', 'woff2'])
        models_n = sum(n for ext, n in asset_counts.items() if ext in ['glb', 'gltf'])
        anims_n = sum(n for ext, n in asset_counts.items() if ext in ['riv', 'json'])
        add(f'- Images: {images} | Fonts: {fonts_n} | 3D Models: {models_n} | Animations: {anims_n}')
        # Top 8 extensions by count
        top_ext = sorted(asset_counts.items(), key=lambda x: -x[1])[:8]
        add('- **By type:** ' + ', '.join(f'{ext}:{n}' for ext, n in top_ext))
    add('')

    h2('8. Rules for AI')
    add(
        '1. **DO NOT** invent colors, fonts or spacing outside the tokens above',
        '2. **DO NOT** normalize to Bootstrap/Tailwind defaults',
        '3. **DO** use exact palette, font families and keyframes extracted',
        '4. **DO** preserve visual DNA (dark site → keep dark, neon → keep neon)',
        '5. **DO** use computed styles as source of truth for layout/spacing',
        '6. **DO** maintain the component hierarchy from the structure section',
        '',
    )

    add('---', '')
    add('*Auto-generated — all data evidence-based, no assumptions.*', '')

    content = '\n'.join(lines)

    if output_path is None:
        output_path = clean_dir / '_ai_context.md'
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding='utf-8')
    return output_path


def _load_json(path: Path) -> dict:
    """Load JSON or return empty dict."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8', errors='ignore'))
    except Exception:
        return {}


def _load_text(path: Path) -> str:
    """Load text file or return empty string."""
    if not path.exists():
        return ''
    try:
        return path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return ''
