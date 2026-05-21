"""
URL Rewrite - Post-download file-based URL rewriting (CSS, JSON, HTML string).
Separated from post_process.py to keep concerns isolated.
"""
import os
import re
import json
from urllib.parse import urljoin, urlparse


def _to_local_browser_path(local_path):
    """Convert saved asset paths to root-absolute URLs safe from CSS relocation."""
    if not local_path:
        return local_path

    if local_path.startswith(('http://', 'https://', '/', 'data:', 'blob:')):
        return local_path

    return f'/{local_path.lstrip("/")}'


def rewrite_css_urls(css_content, css_url, network_recorder):
    """Rewrite all url() references in a CSS string using the network resource map."""
    resource_cache = getattr(network_recorder, 'resource_cache', {}) or {}

    def lookup_cached(abs_url):
        parsed_abs = urlparse(abs_url)
        candidates = [abs_url]
        if parsed_abs.fragment:
            candidates.append(parsed_abs._replace(fragment='').geturl())
        if abs_url.startswith('https://'):
            candidates.append(abs_url.replace('https://', 'http://', 1))
        elif abs_url.startswith('http://'):
            candidates.append(abs_url.replace('http://', 'https://', 1))

        for candidate in candidates:
            local_path = resource_cache.get(candidate)
            if local_path:
                return local_path
        return None

    def replacer(match):
        full_match = match.group(0)
        url_content = match.group(1).strip()

        if url_content.startswith(("'", '"')) and url_content.endswith(("'", '"')):
            url_content = url_content[1:-1]

        if not url_content or url_content.startswith('data:'):
            return full_match

        abs_url = urljoin(css_url, url_content)
        parsed_abs = urlparse(abs_url)
        local_path = lookup_cached(abs_url)

        if local_path and local_path.startswith('assets/'):
            browser_path = _to_local_browser_path(local_path)
            if parsed_abs.fragment:
                browser_path = f"{browser_path}#{parsed_abs.fragment}"
            return f'url("{browser_path}")'

        return full_match

    return re.sub(r'url\(\s*([^)]+)\s*\)', replacer, css_content)


class URLRewriter:
    """Handles file-based URL rewriting after all resources have been saved."""

    def __init__(self, base_url, output_dir, log_callback, network_recorder):
        self.base_url = base_url
        self.output_dir = output_dir
        self.log = log_callback
        self.network = network_recorder

    def rewrite_css_urls(self, css_content, css_url):
        return rewrite_css_urls(css_content, css_url, self.network)

    def rewrite_css_files(self):
        """
        Safe URL rewriting for CSS files only.

        JavaScript files are handled exclusively by the Fetch Interceptor at runtime
        to prevent syntax corruption from blind string replacement in minified JS.
        """
        self.log("Aplicando substituição de URLs em arquivos CSS...")

        resource_map = self.network.get_resource_map()
        if not resource_map:
            return

        assets_dir = os.path.join(self.output_dir, 'assets')
        files_to_process = []
        local_to_original = {}
        for original_url, local_path in resource_map.items():
            normalized_local = local_path.replace('\\', '/')
            local_to_original[normalized_local] = original_url

        if os.path.exists(assets_dir):
            for root, dirs, files in os.walk(assets_dir):
                for filename in files:
                    if os.path.splitext(filename)[1].lower() == '.css':
                        files_to_process.append(os.path.join(root, filename))

        replacements_count = 0
        for filepath in files_to_process:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                original_content = content
                rel_filepath = os.path.relpath(filepath, self.output_dir).replace(os.sep, '/')
                original_css_url = local_to_original.get(rel_filepath)
                if original_css_url:
                    content = rewrite_css_urls(content, original_css_url, self.network)

                # Replace each full URL from resource_map
                for original_url, local_path in resource_map.items():
                    if original_url.startswith(('assets/', 'data:', 'blob:')):
                        continue

                    variants = [original_url]
                    if original_url.startswith('https://'):
                        variants.append(original_url.replace('https://', '//'))
                    elif original_url.startswith('http://'):
                        variants.append(original_url.replace('http://', '//'))

                    for variant in variants:
                        if variant in content:
                            replacement = (
                                _to_local_browser_path(local_path)
                                if local_path.startswith('assets/')
                                else local_path
                            )
                            content = content.replace(variant, replacement)

                # Generate CDN domain patterns automatically from resource_map
                cdn_domains = set()
                for original_url in resource_map.keys():
                    if original_url.startswith(('http://', 'https://')):
                        parsed = urlparse(original_url)
                        if parsed.netloc:
                            cdn_domains.add(parsed.netloc)

                for domain in cdn_domains:
                    for prefix, replacement in [
                        (f'https://{domain}/', '/assets/'),
                        (f'http://{domain}/', '/assets/'),
                    ]:
                        if prefix in content:
                            content = content.replace(prefix, replacement)

                    for quote in ['"', "'"]:
                        pattern = f'{quote}{domain}/'
                        if pattern in content:
                            content = content.replace(pattern, f'{quote}assets/')

                # Expand relative basenames (url("basename.svg") -> url("/assets/.../basename.svg"))
                for original_url, local_path in resource_map.items():
                    if local_path.startswith('assets/'):
                        basename = os.path.basename(local_path)
                        for pattern in [f'url("{basename}")', f"url('{basename}')", f'url({basename})']:
                            if pattern in content:
                                replacement = pattern.replace(basename, f'/{local_path}')
                                content = content.replace(pattern, replacement)

                if content != original_content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    replacements_count += 1

            except Exception as e:
                self.log(f"Erro ao processar {os.path.basename(filepath)}: {e}")

        if replacements_count > 0:
            self.log(f"   {replacements_count} arquivos CSS reescritos")
        else:
            self.log("   Nenhum arquivo CSS precisou de reescrita")

    def process_json_files(self):
        """Rewrite URLs inside JSON and webmanifest files using proper JSON parsing."""
        self.log("Processando arquivos JSON/manifest...")

        resource_map = self.network.get_resource_map()
        if not resource_map:
            return

        assets_dir = os.path.join(self.output_dir, 'assets')
        files_to_process = []
        if os.path.exists(assets_dir):
            for root, dirs, files in os.walk(assets_dir):
                for filename in files:
                    if os.path.splitext(filename)[1].lower() in ('.json', '.webmanifest'):
                        files_to_process.append(os.path.join(root, filename))

        for ext in ('.json', '.webmanifest'):
            root_manifest = os.path.join(self.output_dir, f'manifest{ext}')
            if os.path.exists(root_manifest):
                files_to_process.append(root_manifest)

        def _make_relative_path(json_filepath, resource_path):
            # JSON values are commonly consumed later by runtime code that resolves
            # URLs against the current document location, not against the JSON file
            # itself. Use root-absolute local asset paths to avoid nested-route 404s.
            return '/' + resource_path.lstrip('/')

        def _rewrite_value(value, json_filepath):
            if isinstance(value, str):
                if value.startswith(('http://', 'https://', '//', '/')):
                    abs_url = urljoin(self.base_url, value)
                    if abs_url in resource_map:
                        return _make_relative_path(json_filepath, resource_map[abs_url])
                    if value.startswith('//'):
                        https_variant = 'https:' + value
                        if https_variant in resource_map:
                            return _make_relative_path(json_filepath, resource_map[https_variant])
                return value
            elif isinstance(value, dict):
                return {k: _rewrite_value(v, json_filepath) for k, v in value.items()}
            elif isinstance(value, list):
                return [_rewrite_value(item, json_filepath) for item in value]
            return value

        processed_count = 0
        for filepath in files_to_process:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    data = json.load(f)

                original_str = json.dumps(data, sort_keys=True)
                rewritten = _rewrite_value(data, filepath)
                new_str = json.dumps(rewritten, sort_keys=True)

                if new_str != original_str:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(rewritten, f, indent=2, ensure_ascii=False)
                    processed_count += 1
                    self.log(f"   Reescrito: {os.path.basename(filepath)}")

            except json.JSONDecodeError:
                pass
            except Exception as e:
                self.log(f"   Erro ao processar {os.path.basename(filepath)}: {e}")

        if processed_count > 0:
            self.log(f"   {processed_count} arquivos JSON/manifest reescritos")

    def rewrite_basenames_in_html(self, content):
        """
        Rewrite relative basenames in an HTML string (inline CSS/JS).
        Pattern: url("basename.svg") -> url("/assets/path/basename.svg")
        """
        resource_map = self.network.get_resource_map()
        if not resource_map:
            return content

        for original_url, local_path in resource_map.items():
            if local_path.startswith('assets/'):
                basename = os.path.basename(local_path)
                patterns = [
                    (f'url("{basename}")', f'url("/{local_path}")'),
                    (f"url('{basename}')", f"url('/{local_path}')"),
                    (f'url({basename})', f'url(/{local_path})'),
                    (f'src="{basename}"', f'src="/{local_path}"'),
                    (f"src='{basename}'", f"src='/{local_path}'"),
                ]
                for old, new in patterns:
                    if old in content:
                        content = content.replace(old, new)

        return content

    def rewrite_nextjs_images_in_html(self, html_content):
        """
        Rewrite Next.js Image API URLs in HTML string.
        Pattern: /_next/image/?url=%2Fpath%2Fimage.png&w=96&q=75 -> assets/image_hash.png
        """
        from urllib.parse import parse_qs, urlparse, unquote

        resource_map = self.network.get_resource_map()
        if not resource_map:
            return html_content

        pattern = r'/_next/image/?\?[^"\'<>\s]+'

        def _replace(match):
            full_match = match.group(0)
            try:
                normalized = full_match.replace('&amp;', '&')
                parsed = urlparse(normalized)
                query_params = parse_qs(parsed.query)
                if 'url' not in query_params:
                    return full_match

                original_url = unquote(query_params['url'][0])

                full_abs = urljoin(self.base_url, normalized)
                local_path = resource_map.get(full_abs)

                if not local_path:
                    abs_url = urljoin(self.base_url, original_url)
                    local_path = resource_map.get(abs_url) or resource_map.get(original_url)

                if local_path:
                    self.log(f"   Reescrito Next.js no HTML: {full_match[:60]}... -> {local_path}")
                    return local_path
            except Exception:
                pass
            return full_match

        return re.sub(pattern, _replace, html_content)

    def remove_sourcemaps(self):
        """
        Remove only trailing sourceMappingURL comments from JS/CSS files.

        Some minified bundles generate CSS/source-map comments inside runtime
        strings. Stripping those inline fragments corrupts the JavaScript, so
        this cleanup is intentionally limited to real EOF comments only.
        """
        self.log("Removendo sourcemaps...")
        assets_dir = os.path.join(self.output_dir, 'assets')
        cleaned = 0

        if os.path.exists(assets_dir):
            for root, dirs, files in os.walk(assets_dir):
                for filename in files:
                    if filename.endswith(('.js', '.mjs', '.css')):
                        filepath = os.path.join(root, filename)
                        try:
                            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()

                            new_content = content
                            previous_content = None

                            # Remove only true trailing sourcemap comments at EOF.
                            while new_content != previous_content:
                                previous_content = new_content
                                if filename.endswith(('.js', '.mjs')):
                                    new_content = re.sub(
                                        r'(?:\r?\n)?//# sourceMappingURL=[^\r\n]*\s*\Z',
                                        '',
                                        new_content,
                                    )
                                new_content = re.sub(
                                    r'/\*# sourceMappingURL=.*?\*/\s*\Z',
                                    '',
                                    new_content,
                                    flags=re.DOTALL,
                                )

                            if new_content != content:
                                with open(filepath, 'w', encoding='utf-8') as f:
                                    f.write(new_content)
                                cleaned += 1
                        except Exception:
                            pass

        if cleaned > 0:
            self.log(f"   {cleaned} arquivos JS/CSS limpos")
