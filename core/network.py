"""
Network Recorder - Intercept and save all network resources
"""
import os
import re
import hashlib
import requests
import urllib3
import mimetypes
from urllib.parse import urlparse, urljoin
from . import RESOURCE_TIMEOUT, SKIP_DOMAINS, MAX_RETRIES, RETRY_BACKOFF
import time

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class NetworkRecorder:
    _RETRYABLE_FAILURE_PREFIXES = (
        'capture error:',
        'exact-byte refetch error:',
        'original-image refetch error:',
    )

    def extract_css_from_js_files(self):
        """
        Extract lazily-referenced assets from saved JS/JSON files.

        Modern bundlers frequently keep chunk URLs as string literals inside JS
        (Vite __vite__mapDeps, webpack runtime manifests, Next.js split chunks).
        Rich runtime data files also keep asset URLs in JSON payloads. This scans
        saved text assets for those literal paths and downloads missing
        JS/CSS/media/images/fonts without attempting to parse the syntax.
        """
        import re
        from urllib.parse import urljoin, urlparse

        self.log("Extraindo assets referenciados em arquivos JS/JSON...")

        asset_refs_found = 0
        assets_downloaded = 0
        seen_refs = set()
        scanned_js_urls = set()
        text_queue = [
            (url, local_path)
            for url, local_path in self.resource_cache.items()
            if local_path.endswith(('.js', '.mjs', '.json', '.webmanifest'))
        ]
        text_extensions = (
            'css', 'js', 'mjs', 'png', 'jpe?g', 'svg', 'webp', 'avif', 'gif',
            'woff2?', 'ttf', 'otf', 'eot', 'json', 'webmanifest', 'wasm',
            'ico', 'xml', 'txt', 'mp4', 'webm', 'mov', 'bin', 'ktx2',
            'mp3', 'ogg', 'm4a', 'aac', 'wav', 'flac', 'opus',
        )
        text_ext_pattern = '|'.join(text_extensions)
        # Inline extension list used in patterns that don't use text_ext_pattern
        _inline_media_exts = r'png|jpe?g|svg|webp|avif|gif|woff2?|ttf|otf|eot|json|webmanifest|wasm|ico|xml|txt|mp4|webm|mov|bin|ktx2|mp3|ogg|m4a|aac|wav|flac|opus'

        asset_patterns = [
            rf'["\']((?:https?:)?//[^"\']+\.(?:{text_ext_pattern})(?:\?[^"\']*)?)["\']',
            rf'["\']((?:\./|\.\./)[A-Za-z0-9@_%./ -]+\.(?:{text_ext_pattern})(?:\?[^"\']*)?)["\']',
            rf'["\']((?:\./|\.\./|/)?(?:_next/static/(?:css|chunks)|assets|static)/(?:[A-Za-z0-9@_./ -]+)\.(?:{text_ext_pattern})(?:\?[^"\']*)?)["\']',
            rf'["\']((?:\./|\.\./)?[A-Za-z0-9][A-Za-z0-9_. -]*-[A-Za-z0-9_. -]+\.(?:{text_ext_pattern})(?:\?[^"\']*)?)["\']',
            rf'["\']((?:/[A-Za-z0-9@_./ -]+)\.(?:{text_ext_pattern})(?:\?[^"\']*)?)["\']',
            rf'["\']([A-Za-z0-9][A-Za-z0-9_. -]*\.(?:{_inline_media_exts})(?:\?[^"\']*)?)["\']',
            rf'`((?:\./|\.\./)[A-Za-z0-9@_%./ -]+\.(?:{text_ext_pattern})(?:\?[^`]*)?)`',
            rf'`((?:/[A-Za-z0-9@_./ -]+)\.(?:{text_ext_pattern})(?:\?[^`]*)?)`',
            rf'`([A-Za-z0-9][A-Za-z0-9_. -]*\.(?:{_inline_media_exts})(?:\?[^`]*)?)`',
        ]

        # Scan JS files recursively because newly-downloaded chunks can reveal
        # additional imports that were not present in the initial cache snapshot.
        while text_queue:
            url, local_path = text_queue.pop(0)
            if url in scanned_js_urls:
                continue
            scanned_js_urls.add(url)

            abs_path = os.path.join(self.assets_dir, local_path.replace('assets/', '', 1))
            if not os.path.isfile(abs_path):
                continue

            try:
                with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                for pattern in asset_patterns:
                    matches = re.findall(pattern, content)
                    for asset_ref in matches:
                        if asset_ref in seen_refs:
                            continue

                        seen_refs.add(asset_ref)
                        asset_refs_found += 1

                        if asset_ref.startswith('http'):
                            asset_url = asset_ref
                        elif asset_ref.startswith('//'):
                            parsed_base = urlparse(url)
                            asset_url = f"{parsed_base.scheme}:{asset_ref}"
                        elif asset_ref.startswith(('/', 'assets/', '_next/', 'static/')):
                            # Bundler manifests often store site-root asset paths without a
                            # leading slash (e.g. "assets/chunk.js"). Resolving those
                            # against the current JS file creates bogus ".../assets/assets/"
                            # URLs, so they must resolve from the site base instead.
                            asset_url = urljoin(self.base_url, asset_ref)
                        else:
                            # Resolve relative chunk paths against the JS file URL itself.
                            asset_url = urljoin(url, asset_ref)

                        local_asset = self.resource_cache.get(asset_url)
                        if not local_asset:
                            local_asset = self._download_fallback(asset_url)
                            if local_asset:
                                assets_downloaded += 1

                        if local_asset and local_asset.endswith(('.js', '.mjs', '.json', '.webmanifest')):
                            text_queue.append((asset_url, local_asset))

            except Exception as e:
                # Silent failure - don't break on parse errors
                pass

        if assets_downloaded > 0:
            self.log(f"   {assets_downloaded} asset(s) baixados via extração de JS")
        elif asset_refs_found > 0:
            self.log(f"   {asset_refs_found} referência(s) de asset encontradas (já baixadas)")

    def postprocess_m3u8_files(self):
        """
        Após salvar todos os assets, parseia arquivos .m3u8 baixados e força o download de todas as variantes e chunks referenciados.
        """
        import re
        from urllib.parse import urljoin
        m3u8_files = []
        for url, local_path in self.resource_cache.items():
            if local_path.endswith('.m3u8'):
                m3u8_files.append((url, local_path))
        for url, local_path in m3u8_files:
            try:
                abs_path = os.path.join(self.assets_dir, local_path.replace('assets/', '', 1))
                if not os.path.isfile(abs_path):
                    continue
                with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                # Regex para capturar URIs de chunks e variantes
                uris = re.findall(r'^(?!#)([^\r\n]+)$', content, re.MULTILINE)
                base_url = url.rsplit('/', 1)[0] + '/'
                for ref in uris:
                    ref = ref.strip()
                    if not ref or ref.startswith('#'):
                        continue
                    # Se for URL absoluta, usa direto; senão, resolve relativa ao .m3u8
                    ref_url = ref if ref.startswith('http') else urljoin(base_url, ref)
                    # Força o download se ainda não baixado
                    if ref_url not in self.resource_cache:
                        self._download_fallback(ref_url)
            except Exception as e:
                self.log(f"Erro ao processar {local_path}: {e}")
    def __init__(self, base_url, assets_dir, log_callback):
        self.base_url = self._normalize_base_url(base_url)
        self.assets_dir = assets_dir
        self.log = log_callback
        self.network_resources = {}  # url -> {'body': bytes, 'content_type': str}
        self.resource_cache = {}  # url -> local_path (resource_map)
        self.session = None
        self.recording_enabled = True
        # Stats by resource type
        self.stats_by_type = {
            'image': 0,
            'script': 0,
            'stylesheet': 0,
            'font': 0,
            'media': 0,
            'other': 0
        }
        # FASE 6: Tracking de falhas e ignorados
        self.failed_resources = []  # [(url, reason), ...]
        self.ignored_resources = []  # [(url, reason), ...]
        # Debug: Track all seen URLs
        self.all_seen_urls = []  # For debugging

    def _normalize_base_url(self, base_url):
        """Keep base_url in a urljoin-safe form."""
        if not base_url:
            return ''
        return base_url if base_url.endswith('/') else base_url + '/'

    def set_base_url(self, base_url):
        """Update base_url after navigation or redirect resolution."""
        self.base_url = self._normalize_base_url(base_url)

    def set_recording(self, enabled):
        """Enable or disable runtime network capture without detaching listeners."""
        self.recording_enabled = bool(enabled)

    def _resolve_url(self, url, base_url=None, context='resource'):
        """
        Resolve a candidate URL without letting malformed bracketed hosts abort the run.

        Some sites leak template placeholders such as `[${n.value}]` into asset URLs.
        Python's stdlib url parser raises ValueError for those netlocs, so we treat
        them as failed resources and keep the download alive.
        """
        if not url:
            return None

        candidate = str(url).strip()
        if not candidate or candidate.startswith(('data:', 'blob:', '#', 'javascript:', 'mailto:', 'tel:')):
            return None

        base = base_url if base_url is not None else self.base_url
        if base and not base.endswith('/'):
            base = base + '/'

        try:
            resolved = urljoin(base, candidate) if base else candidate
            parsed = urlparse(resolved)
        except ValueError as exc:
            self.failed_resources.append((candidate, f'invalid URL ({context}): {str(exc)[:80]}'))
            self.log(f"   Ignorando URL inválida em {context}: {candidate[:100]}")
            return None

        if parsed.scheme and parsed.scheme not in {'http', 'https'}:
            return None
        if not parsed.netloc:
            return None

        return resolved

    def get_document_html(self, url=None):
        """
        Return the captured HTML body for the main document when available.

        The network recorder stores HTML responses in-memory alongside assets.
        Post-processing can use the original response HTML as a baseline to
        detect runtime-injected external scripts that should not be persisted.
        """
        candidates = []

        def _add_candidate(candidate):
            if not candidate:
                return
            candidates.append(candidate)
            trimmed = candidate.rstrip('/')
            if trimmed:
                candidates.append(trimmed)
                candidates.append(trimmed + '/')

        _add_candidate(url)
        _add_candidate(self.base_url)

        captured_html = None
        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)

            resource = self.network_resources.get(candidate)
            if not resource:
                continue

            content_type = (resource.get('content_type') or '').lower()
            if 'html' not in content_type:
                continue

            body = resource.get('body') or b''
            if not body:
                continue

            charset_match = re.search(r'charset=([^\s;]+)', content_type)
            encoding = charset_match.group(1).strip('"\'') if charset_match else 'utf-8'

            try:
                captured_html = body.decode(encoding, errors='ignore')
            except LookupError:
                captured_html = body.decode('utf-8', errors='ignore')
            break

        # Fallback: refetch the main document with the browser session cookies.
        # Some sites mutate the DOM heavily and the network recorder may miss the
        # initial document body for comparison purposes, but post-processing still
        # needs the original server HTML to detect runtime-only scripts/nodes.
        if self.session:
            for candidate in candidates:
                if not candidate:
                    continue
                try:
                    parsed = urlparse(candidate)
                except ValueError:
                    continue
                if parsed.scheme not in {'http', 'https'}:
                    continue

                try:
                    response = self.session.get(candidate, timeout=RESOURCE_TIMEOUT, verify=False)
                except Exception:
                    continue

                if response.status_code != 200:
                    continue

                content_type = (response.headers.get('content-type') or '').lower()
                if 'html' not in content_type:
                    continue

                fetched_html = response.text

                # Streaming Next.js/app-router documents are frequently richer in the
                # refetched response than in Playwright's buffered response hook.
                # Prefer the richer version when it contains more flight chunks.
                if captured_html and 'self.__next_f.push' in fetched_html:
                    fetched_pushes = fetched_html.count('self.__next_f.push')
                    captured_pushes = captured_html.count('self.__next_f.push')
                    if (
                        fetched_pushes > captured_pushes
                        or len(fetched_html) > len(captured_html)
                    ):
                        return fetched_html

                return captured_html or fetched_html

        return captured_html

    def setup_session(self, cookies):
        """Setup requests session with browser cookies"""
        self.session = requests.Session()
        parsed_base = urlparse(self.base_url)
        origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': self.base_url,
            'Origin': origin,
        })
        for cookie in cookies:
            self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', ''))

    def _is_retryable_failure(self, reason):
        """Failures caused by browser capture should still fall back to requests."""
        if not reason:
            return False
        lowered = reason.lower()
        return any(lowered.startswith(prefix) for prefix in self._RETRYABLE_FAILURE_PREFIXES)

    def _clear_failures(self, url):
        """Drop stale failure records once a URL was persisted successfully."""
        if not url or not self.failed_resources:
            return
        self.failed_resources = [
            (failed_url, reason)
            for failed_url, reason in self.failed_resources
            if failed_url != url
        ]

    def _validate_content_type(self, url, content_type, body):
        """
        Validate that content-type matches expected file extension.
        Prevents saving Soft 404s (HTML error pages as .js/.css files).

        Returns False if content is invalid (mismatch detected).
        """
        if not content_type or not body:
            return True  # No validation possible, allow

        ct_lower = content_type.lower().split(';')[0].strip()
        url_lower = url.lower()

        # CRITICAL: Detect HTML content masquerading as other types (Soft 404)
        if ct_lower in ('text/html', 'application/xhtml+xml'):
            # HTML is only valid for .html files or directory endpoints
            if not (url_lower.endswith(('.html', '.htm')) or url.rstrip('?#').endswith('/')):
                # Soft 404: server returned HTML error page for a .js/.css request
                return False

        # Validate JavaScript files - strict check against HTML disguised as JS
        if url_lower.endswith('.js'):
            # Content-type must be JS-compatible
            valid_js_types = ('javascript', 'ecmascript', 'text/plain', 'application/octet-stream')

            # If content-type is explicitly HTML, reject immediately
            if ct_lower in ('text/html', 'application/xhtml+xml'):
                return False

            # If content-type is unknown/generic, inspect body
            if ct_lower in ('', 'application/octet-stream', 'text/plain'):
                try:
                    body_start = body[:500].decode('utf-8', errors='ignore').lstrip()
                    # JS files should NOT start with HTML tags
                    if body_start.startswith(('<!DOCTYPE', '<html', '<HTML', '<!doctype')):
                        return False
                    # Check for common HTML patterns (even without doctype)
                    if '<head>' in body_start[:200].lower() or '<body>' in body_start[:200].lower():
                        return False
                except:
                    pass

        # Validate CSS files - strict check against HTML disguised as CSS
        if url_lower.endswith('.css'):
            # Content-type must be CSS-compatible
            valid_css_types = ('css', 'text/plain', 'application/octet-stream')

            # If content-type is explicitly HTML, reject immediately
            if ct_lower in ('text/html', 'application/xhtml+xml'):
                return False

            # If content-type is unknown/generic, inspect body
            if ct_lower in ('', 'application/octet-stream', 'text/plain'):
                try:
                    body_start = body[:500].decode('utf-8', errors='ignore').lstrip()
                    # CSS files should NOT start with HTML tags
                    if body_start.startswith(('<!DOCTYPE', '<html', '<HTML', '<!doctype')):
                        return False
                    # Check for common HTML patterns
                    if '<head>' in body_start[:200].lower() or '<body>' in body_start[:200].lower():
                        return False
                except:
                    pass

        # Validate JSON files (API responses)
        if 'json' in ct_lower or url_lower.endswith('.json'):
            # JSON should not start with HTML tags (Soft 404 from API)
            try:
                body_start = body[:100].decode('utf-8', errors='ignore').lstrip()
                if body_start.startswith(('<!DOCTYPE', '<html', '<HTML', '<!doctype')):
                    return False
            except:
                pass

        return True

    def _classify_resource(self, content_type, url=''):
        """Classify resource by type for statistics"""
        ct = content_type.lower()
        if 'image' in ct:
            return 'image'
        elif 'javascript' in ct or 'ecmascript' in ct or url.endswith('.js'):
            return 'script'
        elif 'css' in ct or url.endswith('.css'):
            return 'stylesheet'
        elif 'font' in ct or any(url.endswith(ext) for ext in ['.woff', '.woff2', '.ttf', '.otf', '.eot']):
            return 'font'
        elif 'video' in ct or 'audio' in ct:
            return 'media'
        elif 'json' in ct or url.endswith('.json'):
            return 'other'  # JSON APIs classified as 'other' for now
        else:
            return 'other'

    def get_response_handler(self):
        """Return handler for page.on('response')"""
        def capture_response(response):
            try:
                if not self.recording_enabled:
                    return

                url = response.url

                # Debug: Track all URLs we see
                self.all_seen_urls.append((url, response.status))

                # Skip data/blob URLs
                if url.startswith(('data:', 'blob:')):
                    return

                # FASE 6: Track ignored resources (tracking domains)
                parsed = urlparse(url)
                if any(skip in parsed.netloc for skip in SKIP_DOMAINS):
                    self.ignored_resources.append((url, 'tracking domain'))
                    return

                # Only save successful responses
                if response.status == 200:
                    try:
                        body = response.body()
                        content_type = response.headers.get('content-type', '')

                        # FASE 6: Check size limit
                        from . import MAX_RESOURCE_SIZE
                        if len(body) > MAX_RESOURCE_SIZE:
                            self.ignored_resources.append((url, f'size > {MAX_RESOURCE_SIZE/1024/1024:.0f}MB'))
                            return

                        # CRITICAL FIX: Validate content-type matches expected file extension
                        # Prevents saving HTML error pages as .js/.css files
                        if not self._validate_content_type(url, content_type, body):
                            self.failed_resources.append((url, 'content-type mismatch'))
                            return

                        resource_data = {
                            'body': body,
                            'content_type': content_type
                        }
                        # Store by final URL
                        self.network_resources[url] = resource_data

                        # Also store by original request URL (handles redirects)
                        request_url = response.request.url
                        if request_url != url:
                            self.network_resources[request_url] = resource_data

                        # Update stats
                        res_type = self._classify_resource(content_type, url)
                        self.stats_by_type[res_type] += 1
                    except Exception as e:
                        self.failed_resources.append((url, f'capture error: {str(e)[:50]}'))
                elif response.status >= 400:
                    self.failed_resources.append((url, f'HTTP {response.status}'))
            except:
                pass

        return capture_response

    def _get_extension(self, url, content_type=''):
        """Get file extension from URL or content-type"""
        parsed = urlparse(url)
        path = parsed.path
        _, ext = os.path.splitext(path)

        preferred_ext = self._prefer_content_extension(ext, content_type)
        if preferred_ext:
            return preferred_ext

        return ''

    def _normalize_extension(self, ext):
        """Normalize equivalent extensions to a stable canonical form."""
        aliases = {
            '.htm': '.html',
            '.jpeg': '.jpg',
            '.jpe': '.jpg',
        }
        normalized = (ext or '').strip().lower()
        return aliases.get(normalized, normalized)

    def _extension_from_content_type(self, content_type=''):
        """Infer the most specific extension from a response content-type."""
        if not content_type:
            return ''

        mime = content_type.split(';')[0].strip().lower()
        if not mime:
            return ''

        explicit = {
            'application/javascript': '.js',
            'application/json': '.json',
            'application/ld+json': '.json',
            'application/manifest+json': '.webmanifest',
            'application/wasm': '.wasm',
            'font/otf': '.otf',
            'font/ttf': '.ttf',
            'font/woff': '.woff',
            'font/woff2': '.woff2',
            'image/avif': '.avif',
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/svg+xml': '.svg',
            'image/webp': '.webp',
            'model/gltf+json': '.gltf',
            'model/gltf-binary': '.glb',
            'text/css': '.css',
            'text/html': '.html',
            'text/javascript': '.js',
        }
        if mime in explicit:
            return explicit[mime]

        if 'json' in mime:
            return '.json'

        if mime == 'text/plain':
            return ''

        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return self._normalize_extension(guessed)

        return ''

    def _prefer_content_extension(self, url_ext, content_type=''):
        """
        Prefer the response MIME when it materially disagrees with the URL.

        This keeps runtime-captured assets on disk with the real binary format,
        which is critical for images negotiated as AVIF/WebP behind .png/.jpg
        URLs and for opaque media/font payloads.
        """
        normalized_url_ext = self._normalize_extension(url_ext)
        if normalized_url_ext and len(normalized_url_ext) > 6:
            normalized_url_ext = ''

        mime = (content_type or '').split(';')[0].strip().lower()
        mime_ext = self._extension_from_content_type(content_type)

        if not mime_ext:
            return normalized_url_ext

        if not normalized_url_ext:
            return mime_ext

        if normalized_url_ext == mime_ext:
            return normalized_url_ext

        if mime in {'application/octet-stream', 'binary/octet-stream'}:
            return normalized_url_ext

        if mime.startswith(('image/', 'audio/', 'video/', 'font/')):
            return mime_ext

        if mime in {'application/wasm', 'model/gltf+json', 'model/gltf-binary'}:
            return mime_ext

        return normalized_url_ext

    def _generate_filename(self, url, content_type='', preserve_structure=True):
        """
        Generate a filename for a resource.

        Args:
            url: Original URL
            content_type: MIME type
            preserve_structure: If True, preserves URL path structure for better compatibility

        Returns:
            Relative path within assets/ (e.g., "gl/textures/diffuse.webp" or "file_hash.ext")
        """
        from urllib.parse import unquote

        parsed = urlparse(url)
        path = parsed.path
        query = parsed.query

        # URL decode path to handle %2C, %20, etc
        path = unquote(path)

        # Remove leading slash
        if path.startswith('/'):
            path = path[1:]

        # Remove "assets/" prefix if present (avoid duplication)
        if path.startswith('assets/'):
            path = path[7:]  # len('assets/') = 7

        # Detect API endpoints (REST APIs, GraphQL, etc) by content-type
        is_api_endpoint = False
        if content_type:
            ct_lower = content_type.lower()
            if 'json' in ct_lower or 'graphql' in ct_lower:
                is_api_endpoint = True

        # CRITICAL FIX: Any URL with query strings must use hash-based naming
        # to avoid collisions. Examples:
        # - /rest/v1/properties?select=A -> properties_hash1.json
        # - /rest/v1/properties?select=B -> properties_hash2.json
        # - /_next/image/?url=X&w=256 -> image_hash3.jpg
        has_query_string = bool(query)

        def _normalize_host(netloc):
            return netloc.lower().lstrip('www.')

        # If preserve_structure and path looks like a real file path (no query string, not an API),
        # preserve the original filename. This keeps runtime relative imports working offline.
        if preserve_structure and path and not has_query_string and not is_api_endpoint:
            # Strip trailing slash — it's a directory-like URL, not a file
            path_clean = path.rstrip('/')
            parts = [part for part in path_clean.split('/') if part]
            # Check: last part must have a file extension or be a meaningful name
            last_part = parts[-1] if parts else ''
            if '?' not in path_clean and last_part:
                stem, current_ext = os.path.splitext(last_part)
                preferred_ext = self._prefer_content_extension(current_ext, content_type)
                if preferred_ext and preferred_ext != self._normalize_extension(current_ext):
                    parts[-1] = f"{stem}{preferred_ext}"
                    last_part = parts[-1]

                clean_parts = []
                parsed_base = urlparse(self.base_url)
                same_origin = _normalize_host(parsed.netloc) == _normalize_host(parsed_base.netloc)

                # Cross-origin root-level files need a stable directory to preserve
                # sibling relative imports without colliding with same-origin assets.
                if len(parts) == 1 and not same_origin and parsed.netloc:
                    host_part = re.sub(r'[^a-zA-Z0-9_@.-]', '_', parsed.netloc)[:100]
                    if host_part:
                        clean_parts.append(host_part)

                for part in parts:
                    if part == parts[-1]:  # Last part (filename)
                        clean_parts.append(part)
                    else:  # Folder names
                        # Preserve @ for npm packages (@rive-app, @react, etc)
                        clean_part = re.sub(r'[^a-zA-Z0-9_@.-]', '_', part)[:50]
                        if clean_part:
                            clean_parts.append(clean_part)

                if clean_parts:
                    structured_path = '/'.join(clean_parts)
                    # Ensure JSON API endpoints get .json extension
                    if is_api_endpoint and not structured_path.endswith('.json'):
                        structured_path += '.json'
                    return structured_path

        # Fallback: hashed filename — includes full URL (with query) for uniqueness
        ext = self._get_extension(url, content_type)

        # Force .json for API endpoints without extension
        if is_api_endpoint and not ext:
            ext = '.json'

        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]

        name = os.path.basename(path.rstrip('/')) if path.rstrip('/') else 'resource'
        if name:
            name = re.sub(r'[^a-zA-Z0-9_-]', '_', name.split('.')[0])[:30]
        else:
            name = 'resource'

        return f"{name}_{url_hash}{ext}"

    def _save_resource(self, url, content, content_type='', overwrite=False):
        """Save a resource to disk and return relative path"""
        existing_rel_path = self.resource_cache.get(url)
        if existing_rel_path and not overwrite:
            return existing_rel_path

        if not content:
            return None

        filename = self._generate_filename(url, content_type, preserve_structure=True)
        filepath = os.path.join(self.assets_dir, filename)

        # If the generated filename has no extension (directory-like URL ending in /),
        # and the URL actually ends with /, save as index.html inside it.
        # BUT: only if the filename doesn't already have an extension (hash-based names do).
        _, filename_ext = os.path.splitext(filename.rstrip('/'))
        if not filename_ext and url.rstrip('?#').endswith('/'):
            filepath = os.path.join(filepath, 'index.html')
            filename = os.path.join(filename, 'index.html')

        # Create directories if needed
        file_dir = os.path.dirname(filepath)
        if file_dir and not os.path.exists(file_dir):
            os.makedirs(file_dir, exist_ok=True)

        # Safety: if filepath collides with existing directory, append index.html
        if os.path.isdir(filepath):
            filepath = os.path.join(filepath, 'index.html')
            filename = os.path.join(filename, 'index.html')

        with open(filepath, 'wb') as f:
            f.write(content if isinstance(content, bytes) else content.encode('utf-8'))

        rel_path = f"assets/{filename}"
        if overwrite and existing_rel_path and existing_rel_path != rel_path:
            existing_path = os.path.join(self.assets_dir, existing_rel_path.replace('assets/', '', 1))
            if os.path.isfile(existing_path):
                try:
                    os.remove(existing_path)
                except OSError:
                    pass
        self.resource_cache[url] = rel_path
        self._clear_failures(url)
        return rel_path

    def _looks_binary_like(self, body, sample_size=4096):
        """Detect opaque payloads that should preserve their exact bytes."""
        if not body:
            return False

        sample = body[:sample_size]
        if not sample:
            return False

        if b'\x00' in sample:
            return True

        control_bytes = sum(1 for byte in sample if byte < 9 or 13 < byte < 32)
        return control_bytes > max(8, len(sample) // 100)

    def _needs_exact_byte_refetch(self, url, body, content_type=''):
        """
        Detect captured resources whose bytes were altered by the browser bridge.

        Some opaque assets arrive through `response.body()` with UTF-8 replacement
        characters already injected. When that happens we refetch the exact bytes
        through the requests session before writing the file to disk.
        """
        if not self.session or not body or b'\xef\xbf\xbd' not in body:
            return False

        parsed = urlparse(url)
        ext = os.path.splitext(parsed.path)[1].lower()
        text_extensions = {
            '.css', '.csv', '.htm', '.html', '.js', '.json', '.map', '.mjs',
            '.svg', '.txt', '.webmanifest', '.xml', '.xhtml',
        }

        if ext in text_extensions:
            return False

        if ext:
            return True

        content_type = (content_type or '').lower().split(';')[0].strip()
        binary_markers = (
            'image/', 'font/', 'audio/', 'video/', 'application/wasm',
            'application/octet-stream', 'application/pdf',
        )
        if any(marker in content_type for marker in binary_markers):
            return True

        return self._looks_binary_like(body)

    def _refetch_exact_bytes(self, url):
        """Refetch a resource with requests to preserve exact bytes on disk."""
        if not self.session:
            return None

        try:
            response = self.session.get(url, timeout=RESOURCE_TIMEOUT, verify=False)
        except Exception as exc:
            self.failed_resources.append((url, f'exact-byte refetch error: {str(exc)[:50]}'))
            return None

        if response.status_code != 200:
            self.failed_resources.append((url, f'exact-byte refetch HTTP {response.status_code}'))
            return None

        from . import MAX_RESOURCE_SIZE
        if len(response.content) > MAX_RESOURCE_SIZE:
            self.ignored_resources.append((url, f'size > {MAX_RESOURCE_SIZE/1024/1024:.0f}MB'))
            return None

        content_type = response.headers.get('content-type', '')
        if not self._validate_content_type(url, content_type, response.content):
            self.failed_resources.append((url, 'content-type mismatch after exact-byte refetch'))
            return None

        return {
            'body': response.content,
            'content_type': content_type,
        }

    def _should_refetch_original_image_variant(self, url, content_type=''):
        """
        Prefer a deterministic HTTP fallback when the browser negotiated a
        different raster format than the one encoded in the original URL.
        """
        if not self.session:
            return False

        url_ext = self._normalize_extension(os.path.splitext(urlparse(url).path)[1])
        if url_ext not in {'.gif', '.jpg', '.png', '.webp'}:
            return False

        mime = (content_type or '').split(';')[0].strip().lower()
        if not mime.startswith('image/'):
            return False

        captured_ext = self._normalize_extension(self._extension_from_content_type(content_type))
        return bool(captured_ext and captured_ext != url_ext)

    def _refetch_original_image_variant(self, url):
        """Refetch negotiated raster images with an Accept header matching the URL."""
        if not self.session:
            return None

        url_ext = self._normalize_extension(os.path.splitext(urlparse(url).path)[1])
        accept_by_ext = {
            '.gif': 'image/gif,image/*;q=0.9,*/*;q=0.8',
            '.jpg': 'image/jpeg,image/*;q=0.9,*/*;q=0.8',
            '.png': 'image/png,image/*;q=0.9,*/*;q=0.8',
            '.webp': 'image/webp,image/*;q=0.9,*/*;q=0.8',
        }
        accept = accept_by_ext.get(url_ext)
        if not accept:
            return None

        try:
            response = self.session.get(
                url,
                timeout=RESOURCE_TIMEOUT,
                verify=False,
                headers={'Accept': accept},
            )
        except Exception as exc:
            self.failed_resources.append((url, f'original-image refetch error: {str(exc)[:50]}'))
            return None

        if response.status_code != 200:
            self.failed_resources.append((url, f'original-image refetch HTTP {response.status_code}'))
            return None

        content_type = response.headers.get('content-type', '')
        if not self._validate_content_type(url, content_type, response.content):
            self.failed_resources.append((url, 'content-type mismatch after original-image refetch'))
            return None

        refreshed_ext = self._normalize_extension(self._extension_from_content_type(content_type))
        if refreshed_ext and refreshed_ext != url_ext:
            return None

        return {
            'body': response.content,
            'content_type': content_type,
        }

    def _prepare_captured_resource_for_save(self, url, resource_data):
        """Normalize captured resources before persisting them to disk."""
        if not resource_data:
            return None

        body = resource_data.get('body') or b''
        content_type = resource_data.get('content_type', '')
        if not self._needs_exact_byte_refetch(url, body, content_type):
            return resource_data

        refreshed = self._refetch_exact_bytes(url)
        if not refreshed:
            return resource_data

        if refreshed['body'] != body:
            resource_data['body'] = refreshed['body']
            resource_data['content_type'] = refreshed.get('content_type', content_type)
            self.log(f"   Refetch exato de bytes: {url[:100]}")
            body = resource_data['body']
            content_type = resource_data['content_type']

        if self._should_refetch_original_image_variant(url, content_type):
            refreshed = self._refetch_original_image_variant(url)
            if refreshed and refreshed['body'] != body:
                resource_data['body'] = refreshed['body']
                resource_data['content_type'] = refreshed.get('content_type', content_type)
                self.log(f"   Refetch da variante original da imagem: {url[:100]}")

        return resource_data

    def _download_fallback(self, url):
        """
        Download a resource with retry logic (FASE 6: 2 attempts with backoff).

        CRITICAL FIX: Block API endpoints from fallback downloads.
        APIs require dynamic headers (Auth tokens, CORS) that requests.get doesn't have.
        Attempting to download them results in 406/401 errors and pollutes logs.
        """
        if not url or url.startswith(('data:', 'blob:', '#')):
            return url

        url = self._resolve_url(url, context='fallback')
        if not url:
            return None

        if url in self.resource_cache:
            return self.resource_cache[url]

        # CRITICAL: Block API endpoints - they need browser context (auth headers, cookies)
        # Attempting requests.get on APIs will ALWAYS fail with 406/401/CORS
        url_lower = url.lower()
        api_indicators = [
            'supabase.co',
            '/rest/v1/',
            '/api/',
            '/graphql',
            'api.',  # api.domain.com
        ]

        if any(indicator in url_lower for indicator in api_indicators):
            # This is an API endpoint - don't attempt fallback download
            # Let the fetch_interceptor handle it with mocks
            self.log(f"   Bloqueando fallback de API: {url[:80]}...")
            return None

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(url, timeout=RESOURCE_TIMEOUT, verify=False)
                if response.status_code == 200:
                    # FASE 6: Check size limit
                    from . import MAX_RESOURCE_SIZE
                    if len(response.content) > MAX_RESOURCE_SIZE:
                        self.ignored_resources.append((url, f'size > {MAX_RESOURCE_SIZE/1024/1024:.0f}MB'))
                        return None

                    content_type = response.headers.get('content-type', '')

                    # CRITICAL FIX: Validate content-type to prevent Soft 404
                    if not self._validate_content_type(url, content_type, response.content):
                        self.failed_resources.append((url, 'content-type mismatch (Soft 404)'))
                        return None

                    local_path = self._save_resource(url, response.content, content_type)
                    return local_path
                else:
                    last_error = f'HTTP {response.status_code}'
            except Exception as e:
                last_error = str(e)[:50]
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF ** attempt)
                    continue

        # FASE 6: Track failed download
        if last_error:
            self.failed_resources.append((url, last_error))

        return None

    def get_resource(self, url, base=None):
        """Get a resource - from cache, network capture, or fallback download"""
        if not url or url.startswith(('data:', 'blob:', '#')):
            return url

        # CRITICAL FIX: Ensure base URL ends with / for correct urljoin behavior
        # Without this, urljoin("https://domain.com", "assets/file.png")
        # becomes "https://domain.comassets/file.png" (missing slash)
        base_url = base or self.base_url
        if not base_url.endswith('/'):
            base_url = base_url + '/'

        # Make absolute URL
        abs_url = self._resolve_url(url, base_url=base_url, context='resource lookup')
        if not abs_url:
            return url
        parsed_abs = urlparse(abs_url)
        lookup_urls = [abs_url]
        if parsed_abs.fragment:
            lookup_urls.append(parsed_abs._replace(fragment='').geturl())

        # Check cache first
        for candidate in lookup_urls:
            if candidate in self.resource_cache:
                local_path = self.resource_cache[candidate]
                if candidate != abs_url:
                    self.resource_cache[abs_url] = local_path
                return local_path

        # Check network captures
        for candidate in lookup_urls:
            if candidate in self.network_resources:
                res = self._prepare_captured_resource_for_save(candidate, self.network_resources[candidate])
                local_path = self._save_resource(candidate, res['body'], res.get('content_type', ''))
                if local_path and candidate != abs_url:
                    self.resource_cache[abs_url] = local_path
                return local_path

        # Fallback download
        download_url = lookup_urls[-1]
        local_path = self._download_fallback(download_url)
        if local_path:
            if download_url != abs_url:
                self.resource_cache[abs_url] = local_path
            return local_path

        # Return original if all fails
        return url

    def save_all_captured_resources(self):
        """FASE 3: Save all network-captured resources to disk"""
        saved_count = 0
        for url, resource_data in self.network_resources.items():
            if url not in self.resource_cache:
                resource_data = self._prepare_captured_resource_for_save(url, resource_data)
                local_path = self._save_resource(url, resource_data['body'], resource_data.get('content_type', ''))
                if local_path:
                    saved_count += 1

        if saved_count > 0:
            self.log(f"   {saved_count} recursos salvos em disco")

        self._normalize_negotiated_raster_images()

        # NOVO: pós-processamento de .m3u8 para garantir todos os chunks/variantes
        self.postprocess_m3u8_files()

        # CRITICAL: Extract chunks/assets referenced in JS files (Vite, Next.js, Webpack)
        self.extract_css_from_js_files()

    def ensure_resources_downloaded(self, urls):
        """
        Download any URLs from the list that are not already in resource_cache.

        Used to ensure dynamically-injected stylesheets (e.g. Next.js router CSS)
        are saved even if they were missed by the Playwright response handler.
        """
        if not urls:
            return

        ignored_urls = {url for url, _reason in self.ignored_resources}
        failed_urls = {url for url, _reason in self.failed_resources}
        retryable_failed_urls = {
            url for url, reason in self.failed_resources
            if self._is_retryable_failure(reason)
        }
        seen_urls = set()
        downloaded = 0

        for url in urls:
            if not url:
                continue
            normalized_url = self._resolve_url(url, context='fallback queue')
            if not normalized_url:
                continue
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)

            if normalized_url in self.resource_cache:
                continue
            if normalized_url in ignored_urls or normalized_url in failed_urls:
                if normalized_url not in retryable_failed_urls:
                    continue

            local_path = self._download_fallback(normalized_url)
            if local_path:
                downloaded += 1
        if downloaded:
            self.log(f"   {downloaded} recurso(s) baixados via fallback")

    def _normalize_negotiated_raster_images(self):
        """
        Replace negotiated raster variants whose saved extension no longer
        matches the explicit raster extension encoded in the original URL.
        """
        normalized_count = 0
        for url, local_path in list(self.resource_cache.items()):
            url_ext = self._normalize_extension(os.path.splitext(urlparse(url).path)[1])
            local_ext = self._normalize_extension(os.path.splitext(local_path)[1])

            if url_ext not in {'.gif', '.jpg', '.png', '.webp'}:
                continue
            if not local_ext or local_ext == url_ext:
                continue

            refreshed = self._refetch_original_image_variant(url)
            if not refreshed:
                continue

            new_path = self._save_resource(
                url,
                refreshed['body'],
                refreshed.get('content_type', ''),
                overwrite=True,
            )
            if new_path:
                normalized_count += 1

        if normalized_count:
            self.log(f"   {normalized_count} imagem(ns) raster normalizada(s) para o formato original")

    def get_resource_map(self):
        """Return the resource_map for URL rewriting"""
        return self.resource_cache.copy()

    def get_stats(self):
        """Return statistics"""
        return {
            'captured': len(self.network_resources),
            'saved': len(self.resource_cache),
            'by_type': self.stats_by_type.copy()
        }

    def log_stats(self):
        """Log detailed statistics"""
        stats = self.get_stats()
        self.log(f"Recursos capturados por tipo:")
        if stats['by_type']['image'] > 0:
            self.log(f"   Imagens: {stats['by_type']['image']}")
        if stats['by_type']['script'] > 0:
            self.log(f"   Scripts: {stats['by_type']['script']}")
        if stats['by_type']['stylesheet'] > 0:
            self.log(f"   CSS: {stats['by_type']['stylesheet']}")
        if stats['by_type']['font'] > 0:
            self.log(f"   Fonts: {stats['by_type']['font']}")
        if stats['by_type']['media'] > 0:
            self.log(f"   Mídia: {stats['by_type']['media']}")
        if stats['by_type']['other'] > 0:
            self.log(f"   Outros: {stats['by_type']['other']}")

    def generate_final_report(self):
        """FASE 6: Generate comprehensive final report"""
        self.log("\n" + "="*60)
        self.log("RELATÓRIO FINAL")
        self.log("="*60)

        # Resources by type
        total = sum(self.stats_by_type.values())
        self.log(f"\nTotal baixado: {total} recursos")
        for res_type, count in self.stats_by_type.items():
            if count > 0:
                percentage = (count / total * 100) if total > 0 else 0
                emoji = {'image': '🖼️', 'script': '📝', 'stylesheet': '🎨',
                        'font': '✍️', 'media': '🎬', 'other': '📦'}[res_type]
                self.log(f"   {emoji} {res_type.capitalize()}: {count} ({percentage:.1f}%)")

        # Debug: Critical URLs seen but not captured
        critical_patterns = ['webgl', 'draco', 'texture', 'wasm', '.glb', '.gltf']
        critical_seen = []
        for url, status in self.all_seen_urls:
            if any(pattern in url.lower() for pattern in critical_patterns):
                if url not in self.network_resources:
                    critical_seen.append((url, status))

        if critical_seen:
            self.log(f"\nURLs críticas vistas mas NÃO capturadas: {len(critical_seen)}")
            for url, status in critical_seen[:10]:
                short_url = url[:80] + '...' if len(url) > 80 else url
                self.log(f"   - [HTTP {status}] {short_url}")
            if len(critical_seen) > 10:
                self.log(f"   ... e mais {len(critical_seen) - 10}")

        # Failed resources
        if self.failed_resources:
            self.log(f"\nFalhas: {len(self.failed_resources)} recursos")
            # Show up to 20
            for url, reason in self.failed_resources[:20]:
                short_url = url[:60] + '...' if len(url) > 60 else url
                self.log(f"   - {short_url}")
                self.log(f"     Motivo: {reason}")
            if len(self.failed_resources) > 20:
                self.log(f"   ... e mais {len(self.failed_resources) - 20}")

        # Ignored resources
        if self.ignored_resources:
            self.log(f"\nIgnorados: {len(self.ignored_resources)} recursos")
            # Group by reason
            by_reason = {}
            for url, reason in self.ignored_resources:
                by_reason.setdefault(reason, []).append(url)
            for reason, urls in by_reason.items():
                self.log(f"   - {reason}: {len(urls)}")

        self.log("="*60 + "\n")
