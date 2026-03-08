import json
import os
import re
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup


class BusinessRuleExtractor:
    """Analyze downloaded HTML to extract business rules and site structure."""

    def __init__(self, html_content, base_url):
        self.soup = BeautifulSoup(html_content, 'html.parser')
        self.base_url = base_url
        self.parsed_base = urlparse(base_url)
        self.report = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self):
        """Run all extractors and return structured report dict."""
        self.report = {
            'site_url': self.base_url,
            'meta_info': self._extract_meta_info(),
            'navigation': self._extract_navigation(),
            'buttons_ctas': self._extract_buttons(),
            'forms': self._extract_forms(),
            'content_structure': self._extract_headings(),
            'external_links': self._extract_external_links(),
            'media': self._extract_media(),
            'tech_stack': self._extract_tech_stack(),
        }
        return self.report

    def save(self, output_dir):
        """Save report as JSON and Markdown files."""
        if not self.report:
            self.extract()

        # JSON
        json_path = os.path.join(output_dir, 'business_rules.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.report, f, ensure_ascii=False, indent=2)

        # Markdown
        md_path = os.path.join(output_dir, 'business_rules.md')
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(self._render_markdown())

    # ------------------------------------------------------------------
    # Extractors
    # ------------------------------------------------------------------

    def _extract_meta_info(self):
        """Extract title, description, OG tags, favicon."""
        info = {}

        # Title
        title_tag = self.soup.find('title')
        info['title'] = title_tag.get_text(strip=True) if title_tag else None

        # Meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        info['description'] = meta_desc['content'] if meta_desc and meta_desc.get('content') else None

        # OG tags
        og_tags = {}
        for meta in self.soup.find_all('meta', attrs={'property': True}):
            prop = meta.get('property', '')
            if prop.startswith('og:'):
                og_tags[prop] = meta.get('content', '')
        info['og_tags'] = og_tags if og_tags else None

        # Favicon
        favicon = self.soup.find('link', rel=lambda r: r and 'icon' in ' '.join(r).lower())
        info['favicon'] = favicon.get('href') if favicon else None

        # Language
        html_tag = self.soup.find('html')
        info['language'] = html_tag.get('lang') if html_tag else None

        return info

    def _extract_navigation(self):
        """Extract navigation menus and header links."""
        nav_items = []

        # Find <nav> elements
        for nav in self.soup.find_all('nav'):
            nav_data = {
                'source': 'nav',
                'aria_label': nav.get('aria-label', ''),
                'links': []
            }
            for a in nav.find_all('a', href=True):
                text = a.get_text(strip=True)
                if text:
                    nav_data['links'].append({
                        'text': text,
                        'href': a['href'],
                        'classes': ' '.join(a.get('class', [])),
                    })
            if nav_data['links']:
                nav_items.append(nav_data)

        # Also check header for links not inside <nav>
        header = self.soup.find('header')
        if header:
            header_links = []
            # Exclude links already captured inside <nav>
            nav_tags = header.find_all('nav')
            nav_link_texts = set()
            for nav in nav_tags:
                for a in nav.find_all('a'):
                    nav_link_texts.add(a.get_text(strip=True))

            for a in header.find_all('a', href=True):
                text = a.get_text(strip=True)
                if text and text not in nav_link_texts:
                    header_links.append({
                        'text': text,
                        'href': a['href'],
                        'classes': ' '.join(a.get('class', [])),
                    })
            if header_links:
                nav_items.append({
                    'source': 'header',
                    'links': header_links,
                })

        return nav_items

    def _extract_buttons(self):
        """Extract all buttons and CTAs with context."""
        buttons = []

        # <button> elements
        for btn in self.soup.find_all('button'):
            text = btn.get_text(strip=True)
            if not text:
                continue
            btn_data = {
                'text': text,
                'type': btn.get('type', 'button'),
                'classes': ' '.join(btn.get('class', [])),
                'onclick': btn.get('onclick', ''),
                'disabled': btn.has_attr('disabled'),
            }
            # Check if inside a form
            form_parent = btn.find_parent('form')
            if form_parent:
                btn_data['form_action'] = form_parent.get('action', '')
                btn_data['form_method'] = form_parent.get('method', 'GET')
            buttons.append(btn_data)

        # <a> styled as buttons (role="button" or common CTA classes)
        cta_patterns = re.compile(
            r'btn|button|cta|call-to-action|action|hero-link|primary-link',
            re.IGNORECASE
        )
        for a in self.soup.find_all('a', href=True):
            classes_str = ' '.join(a.get('class', []))
            role = a.get('role', '')
            if role == 'button' or cta_patterns.search(classes_str):
                text = a.get_text(strip=True)
                if text:
                    buttons.append({
                        'text': text,
                        'type': 'link-button',
                        'href': a['href'],
                        'classes': classes_str,
                    })

        # <input type="submit">
        for inp in self.soup.find_all('input', attrs={'type': 'submit'}):
            buttons.append({
                'text': inp.get('value', 'Submit'),
                'type': 'submit',
                'classes': ' '.join(inp.get('class', [])),
            })

        return buttons

    def _extract_forms(self):
        """Extract all forms with their fields."""
        forms = []
        for form in self.soup.find_all('form'):
            form_data = {
                'action': form.get('action', ''),
                'method': form.get('method', 'GET').upper(),
                'id': form.get('id', ''),
                'name': form.get('name', ''),
                'classes': ' '.join(form.get('class', [])),
                'fields': [],
            }

            # Inputs
            for inp in form.find_all(['input', 'select', 'textarea']):
                field_type = inp.get('type', inp.name)
                if field_type in ('hidden', 'submit'):
                    continue
                label_text = ''
                label = inp.find_previous('label')
                if label and label.get('for') == inp.get('id'):
                    label_text = label.get_text(strip=True)
                elif not label:
                    # Try to find label by wrapping
                    parent_label = inp.find_parent('label')
                    if parent_label:
                        label_text = parent_label.get_text(strip=True)

                field = {
                    'name': inp.get('name', ''),
                    'type': field_type,
                    'placeholder': inp.get('placeholder', ''),
                    'required': inp.has_attr('required'),
                    'label': label_text,
                }

                # Options for select
                if inp.name == 'select':
                    field['options'] = [
                        opt.get_text(strip=True)
                        for opt in inp.find_all('option')
                        if opt.get_text(strip=True)
                    ]

                form_data['fields'].append(field)

            forms.append(form_data)
        return forms

    def _extract_headings(self):
        """Extract heading hierarchy as content structure map."""
        headings = []
        for tag in self.soup.find_all(re.compile(r'^h[1-6]$')):
            text = tag.get_text(strip=True)
            if text:
                headings.append({
                    'level': int(tag.name[1]),
                    'text': text,
                })
        return headings

    def _extract_external_links(self):
        """Extract links pointing to external domains, grouped by domain."""
        domains = {}
        for a in self.soup.find_all('a', href=True):
            href = a['href']
            if href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue

            parsed = urlparse(urljoin(self.base_url, href))
            if parsed.netloc and parsed.netloc != self.parsed_base.netloc:
                domain = parsed.netloc
                if domain not in domains:
                    domains[domain] = []
                text = a.get_text(strip=True) or '(sem texto)'
                url = parsed.geturl()
                # Avoid duplicates
                if not any(l['url'] == url for l in domains[domain]):
                    domains[domain].append({
                        'text': text,
                        'url': url,
                    })
        return domains

    def _extract_media(self):
        """Count and list media elements."""
        images = self.soup.find_all('img')
        videos = self.soup.find_all('video')
        iframes = self.soup.find_all('iframe')

        media = {
            'images_count': len(images),
            'videos_count': len(videos),
            'iframes_count': len(iframes),
        }

        # Top images with alt text
        media['images'] = []
        for img in images[:20]:  # Limit to first 20
            src = img.get('src', img.get('data-src', ''))
            alt = img.get('alt', '')
            if src:
                media['images'].append({'src': src, 'alt': alt})

        # Iframes (embeds)
        media['iframes'] = []
        for iframe in iframes:
            src = iframe.get('src', '')
            title = iframe.get('title', '')
            if src:
                media['iframes'].append({'src': src, 'title': title})

        return media

    def _extract_tech_stack(self):
        """Detect frameworks, libraries, and analytics."""
        tech = {
            'frameworks': [],
            'analytics': [],
            'libraries': [],
        }

        # Framework detection by IDs
        if self.soup.find(id='__next'):
            tech['frameworks'].append('Next.js')
        if self.soup.find(id='__nuxt'):
            tech['frameworks'].append('Nuxt.js')
        if self.soup.find(id='___gatsby'):
            tech['frameworks'].append('Gatsby')
        if self.soup.find(id='app') or self.soup.find(id='root'):
            # Could be React/Vue — check scripts
            pass

        # Script-based detection
        all_scripts = self.soup.find_all('script')
        script_srcs = [s.get('src', '') for s in all_scripts if s.get('src')]
        all_script_text = ' '.join(s.string or '' for s in all_scripts)

        # Frameworks from scripts
        framework_patterns = {
            'React': [r'react', r'__REACT'],
            'Vue.js': [r'vue\.', r'Vue\.'],
            'Angular': [r'angular', r'ng-'],
            'Svelte': [r'svelte'],
            'jQuery': [r'jquery'],
            'Bootstrap': [r'bootstrap'],
            'Tailwind CSS': [r'tailwind'],
            'WordPress': [r'wp-content', r'wp-includes'],
            'Webflow': [r'webflow'],
            'Wix': [r'wix\.com', r'parastorage'],
            'Shopify': [r'shopify', r'cdn\.shopify'],
            'Squarespace': [r'squarespace'],
        }

        for name, patterns in framework_patterns.items():
            for pat in patterns:
                if any(re.search(pat, src, re.IGNORECASE) for src in script_srcs):
                    if name not in tech['frameworks']:
                        tech['frameworks'].append(name)
                    break
                if re.search(pat, all_script_text, re.IGNORECASE):
                    if name not in tech['frameworks']:
                        tech['frameworks'].append(name)
                    break

        # Also check link/style tags for CSS frameworks
        for link in self.soup.find_all('link', rel='stylesheet'):
            href = link.get('href', '')
            if 'bootstrap' in href.lower() and 'Bootstrap' not in tech['frameworks']:
                tech['frameworks'].append('Bootstrap')
            if 'tailwind' in href.lower() and 'Tailwind CSS' not in tech['frameworks']:
                tech['frameworks'].append('Tailwind CSS')

        # Analytics
        analytics_patterns = {
            'Google Analytics': [r'google-analytics\.com', r'gtag', r'ga\.js', r'analytics\.js'],
            'Google Tag Manager': [r'googletagmanager\.com', r'gtm\.js'],
            'Facebook Pixel': [r'connect\.facebook\.net', r'fbevents\.js', r'fbq\('],
            'Hotjar': [r'hotjar\.com', r'hj\('],
            'Clarity': [r'clarity\.ms'],
            'Mixpanel': [r'mixpanel'],
            'Segment': [r'segment\.com', r'analytics\.js'],
            'HubSpot': [r'hubspot', r'hs-scripts'],
        }

        for name, patterns in analytics_patterns.items():
            for pat in patterns:
                combined = ' '.join(script_srcs) + ' ' + all_script_text
                if re.search(pat, combined, re.IGNORECASE):
                    if name not in tech['analytics']:
                        tech['analytics'].append(name)
                    break

        return tech

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    def _render_markdown(self):
        """Render the report as a readable Markdown document."""
        r = self.report
        lines = []

        lines.append(f"# 📋 Regras de Negócio — {r['site_url']}\n")

        # Meta Info
        meta = r['meta_info']
        lines.append("## ℹ️ Informações Gerais\n")
        lines.append(f"| Campo | Valor |")
        lines.append(f"|---|---|")
        lines.append(f"| **Título** | {meta.get('title') or '—'} |")
        lines.append(f"| **Descrição** | {meta.get('description') or '—'} |")
        lines.append(f"| **Idioma** | {meta.get('language') or '—'} |")
        if meta.get('og_tags'):
            for key, val in meta['og_tags'].items():
                lines.append(f"| **{key}** | {val[:80]}{'…' if len(val) > 80 else ''} |")
        lines.append("")

        # Tech Stack
        tech = r['tech_stack']
        if tech['frameworks'] or tech['analytics']:
            lines.append("## 🔧 Tecnologias Detectadas\n")
            if tech['frameworks']:
                lines.append(f"**Frameworks/Plataformas:** {', '.join(tech['frameworks'])}\n")
            if tech['analytics']:
                lines.append(f"**Analytics/Tracking:** {', '.join(tech['analytics'])}\n")
            lines.append("")

        # Navigation
        nav = r['navigation']
        if nav:
            lines.append("## 🧭 Navegação\n")
            for group in nav:
                source = group.get('source', 'nav')
                label = group.get('aria_label', '')
                title = f"### Menu ({source})"
                if label:
                    title += f" — {label}"
                lines.append(title + "\n")
                lines.append("| Texto | Link | Classes |")
                lines.append("|---|---|---|")
                for link in group['links']:
                    lines.append(f"| {link['text']} | `{link['href']}` | {link.get('classes', '')} |")
                lines.append("")

        # Buttons & CTAs
        btns = r['buttons_ctas']
        if btns:
            lines.append("## 🔘 Botões e CTAs\n")
            lines.append("| Texto | Tipo | Ação/Link | Classes |")
            lines.append("|---|---|---|---|")
            for b in btns:
                action = b.get('href', b.get('onclick', b.get('form_action', '')))
                lines.append(f"| {b['text'][:50]} | {b['type']} | `{action}` | {b.get('classes', '')[:40]} |")
            lines.append("")

        # Forms
        forms = r['forms']
        if forms:
            lines.append("## 📝 Formulários\n")
            for i, form in enumerate(forms, 1):
                name = form.get('name') or form.get('id') or f'Formulário {i}'
                lines.append(f"### {name}\n")
                lines.append(f"- **Action:** `{form['action']}`")
                lines.append(f"- **Método:** {form['method']}\n")
                if form['fields']:
                    lines.append("| Campo | Tipo | Placeholder | Obrigatório |")
                    lines.append("|---|---|---|---|")
                    for field in form['fields']:
                        req = '✅' if field['required'] else '—'
                        label = field.get('label') or field.get('name') or '—'
                        lines.append(f"| {label} | {field['type']} | {field['placeholder']} | {req} |")
                lines.append("")

        # Content Structure
        headings = r['content_structure']
        if headings:
            lines.append("## 📄 Estrutura de Conteúdo (Headings)\n")
            for h in headings:
                indent = '  ' * (h['level'] - 1)
                lines.append(f"{indent}- **H{h['level']}**: {h['text']}")
            lines.append("")

        # External Links
        ext = r['external_links']
        if ext:
            lines.append("## 🔗 Links Externos\n")
            for domain, links in ext.items():
                lines.append(f"### {domain}\n")
                for link in links:
                    lines.append(f"- [{link['text']}]({link['url']})")
                lines.append("")

        # Media
        media = r['media']
        lines.append("## 🎬 Mídias\n")
        lines.append(f"| Tipo | Quantidade |")
        lines.append(f"|---|---|")
        lines.append(f"| Imagens | {media['images_count']} |")
        lines.append(f"| Vídeos | {media['videos_count']} |")
        lines.append(f"| Iframes/Embeds | {media['iframes_count']} |")
        lines.append("")

        if media.get('iframes'):
            lines.append("### Iframes detectados\n")
            for iframe in media['iframes']:
                lines.append(f"- `{iframe['src']}` — {iframe['title'] or '(sem título)'}")
            lines.append("")

        return '\n'.join(lines)
