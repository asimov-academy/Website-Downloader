#!/usr/bin/env python3
"""
Servidor Local para Site Baixado via DeepMirror WebSites
Execute este script para visualizar o site offline.

Uso:
    python3 serve.py
    python serve.py

Requisitos: Python 3.7+
"""
import http.server
import socketserver
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# MIME types para formatos especiais
MIME_TYPES = {
    '.avif': 'image/avif',
    '.wasm': 'application/wasm',
    '.glb': 'model/gltf-binary',
    '.gltf': 'model/gltf+json',
    '.riv': 'application/octet-stream',
    '.webp': 'image/webp',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.otf': 'font/otf',
    '.js': 'application/javascript',
    '.mjs': 'application/javascript',
    '.json': 'application/json',
}

_EXTENSION_FAMILIES = (
    {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'},
    {'.mp4', '.webm', '.mov', '.m4v', '.ogv'},
    {'.mp3', '.wav', '.ogg', '.m4a', '.aac'},
    {'.woff', '.woff2', '.ttf', '.otf', '.eot'},
)

_RESOURCE_MAP_CACHE = None


def _compatible_extensions(ext):
    ext = (ext or '').lower()
    for family in _EXTENSION_FAMILIES:
        if ext in family:
            return family
    return {ext} if ext else set()


def _directory_similarity(request_path, candidate_path):
    request_parts = Path(request_path).parts[:-1]
    candidate_parts = Path(candidate_path).parts[:-1]
    score = 0
    for left, right in zip(request_parts, candidate_parts):
        if left != right:
            break
        score += 1
    return score


def _to_browser_path(local_path):
    if not local_path:
        return None

    normalized = str(local_path).replace('\\', '/').strip()
    if not normalized:
        return None

    if normalized.startswith(('http://', 'https://')):
        return normalized

    return '/' + normalized.lstrip('/')


def _load_resource_map():
    global _RESOURCE_MAP_CACHE
    if _RESOURCE_MAP_CACHE is not None:
        return _RESOURCE_MAP_CACHE

    resource_map = {}
    resource_map_path = Path('assets/resource-map.json')
    if resource_map_path.is_file():
        try:
            resource_map = json.loads(resource_map_path.read_text(encoding='utf-8'))
            _RESOURCE_MAP_CACHE = resource_map
            return resource_map
        except Exception:
            pass

    index_path = Path('index.html')
    if index_path.is_file():
        try:
            html_content = index_path.read_text(encoding='utf-8', errors='ignore')
            match = re.search(
                r'const resourceMap = (\{.*?\});',
                html_content,
                re.DOTALL,
            )
            if match:
                resource_map = json.loads(match.group(1))
        except Exception:
            resource_map = {}

    _RESOURCE_MAP_CACHE = resource_map
    return resource_map


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler with CORS and special MIME types"""

    def _resource_map_lookup(self, request_path):
        resource_map = _load_resource_map()
        if not resource_map:
            return None

        normalized = request_path if request_path.startswith('/') else f'/{request_path}'
        parsed_request = urlparse(normalized)
        request_paths = [parsed_request.path]
        if parsed_request.path.startswith('/assets/'):
            request_paths.append('/' + parsed_request.path[len('/assets/'):].lstrip('/'))
        request_paths = list(dict.fromkeys(path for path in request_paths if path))

        request_key = parsed_request.path
        if parsed_request.query:
            request_key = f'{request_key}?{parsed_request.query}'

        basename_matches = []
        request_basename = Path(parsed_request.path).name
        for original_url, local_path in resource_map.items():
            parsed_original = urlparse(original_url)
            original_key = parsed_original.path or '/'
            if parsed_original.query:
                original_key = f'{original_key}?{parsed_original.query}'

            if original_key == request_key:
                return _to_browser_path(local_path)

            same_path = parsed_original.path in request_paths
            suffix_alias = any(
                parsed_original.path.endswith(path)
                for path in request_paths
                if path not in {'', '/'} and Path(path).suffix
            )
            same_plain_path = same_path and not parsed_original.query and not parsed_request.query
            same_rsc_route = same_path and ('_rsc=' in parsed_original.query) and ('_rsc=' in parsed_request.query)
            same_next_image_route = (
                same_path
                and parsed_request.path.startswith('/_next/image')
                and 'url=' in parsed_original.query
                and 'url=' in parsed_request.query
            )
            same_query = parsed_original.query == parsed_request.query
            suffix_with_compatible_query = suffix_alias and (
                same_query or not parsed_original.query or not parsed_request.query
            )

            if same_plain_path or same_rsc_route or same_next_image_route or suffix_with_compatible_query:
                return _to_browser_path(local_path)

            if (
                request_basename
                and request_basename == Path(parsed_original.path).name
                and (same_query or not parsed_request.query)
            ):
                browser_path = _to_browser_path(local_path)
                if browser_path:
                    basename_matches.append(browser_path)

        basename_matches = list(dict.fromkeys(basename_matches))
        if len(basename_matches) == 1:
            return basename_matches[0]

        return None

    def _asset_alias_path(self, request_path):
        """Map root-relative asset requests to the saved assets/ mirror."""
        if not request_path or request_path.startswith('/assets/'):
            return None

        normalized = request_path if request_path.startswith('/') else f'/{request_path}'
        return f'/assets{normalized}'

    def _candidate_request_paths(self, request_path):
        normalized = request_path if request_path.startswith('/') else f'/{request_path}'
        candidates = [normalized]

        normalized_path = self.translate_path(normalized)
        if os.path.isdir(normalized_path):
            candidates.append(normalized.rstrip('/') + '/index.html')

        if normalized.endswith('/'):
            candidates.append(normalized + 'index.html')

        if normalized in {'', '/'}:
            candidates.append('/index.html')

        asset_alias = self._asset_alias_path(normalized)
        if asset_alias:
            candidates.append(asset_alias)
            alias_path = self.translate_path(asset_alias)
            if os.path.isdir(alias_path):
                candidates.append(asset_alias.rstrip('/') + '/index.html')
            if asset_alias.endswith('/'):
                candidates.append(asset_alias + 'index.html')

        # Preserve order but drop duplicates.
        return list(dict.fromkeys(candidates))

    def _next_image_source_path(self, request_path):
        parsed = urlparse(request_path)
        if not parsed.path.startswith('/_next/image'):
            return None

        source = parse_qs(parsed.query).get('url', [None])[0]
        if not source:
            return None

        source = unquote(source)
        source_parsed = urlparse(source)
        if source_parsed.scheme or source_parsed.netloc:
            source = source_parsed.path

        if not source.startswith('/'):
            source = '/' + source.lstrip('/')

        return source

    def _resolve_request_target(self, request_path):
        parsed = urlparse(request_path)
        clean_path = parsed.path or '/'

        next_image_source = self._next_image_source_path(request_path)
        if next_image_source:
            clean_path = next_image_source

        fallback_candidate = None
        for candidate in self._candidate_request_paths(clean_path):
            candidate_path = self.translate_path(candidate)
            if os.path.isfile(candidate_path):
                return candidate, candidate_path
            if candidate.startswith('/assets/'):
                fallback_candidate = (candidate, candidate_path)

        mapped_local_path = self._resource_map_lookup(clean_path)
        if mapped_local_path:
            mapped_fs_path = self.translate_path(mapped_local_path)
            if os.path.isfile(mapped_fs_path):
                return mapped_local_path, mapped_fs_path

        if fallback_candidate:
            return fallback_candidate

        return clean_path, self.translate_path(clean_path)

    def _global_asset_fallback(self, missing_path):
        filename = os.path.basename(missing_path)
        if not filename or '.' not in filename:
            return None

        assets_root = self.translate_path('/assets')
        if not os.path.isdir(assets_root):
            return None

        stem, ext = os.path.splitext(filename)
        if not ext:
            return None

        stem_candidates = [stem]
        for separator in ('.', '-'):
            if separator in stem:
                prefix = stem.split(separator, 1)[0]
                if prefix and prefix not in stem_candidates:
                    stem_candidates.append(prefix)

        compatible_exts = _compatible_extensions(ext)
        matches = []
        for root, _dirs, files in os.walk(assets_root):
            for candidate in files:
                candidate_stem, candidate_ext = os.path.splitext(candidate)
                candidate_ext = candidate_ext.lower()
                if candidate_ext not in compatible_exts:
                    continue
                if candidate == filename or any(
                    candidate_stem == prefix or candidate_stem.startswith(prefix + '_')
                    for prefix in stem_candidates
                ):
                    matches.append(os.path.join(root, candidate))

        if len(matches) != 1:
            scored = sorted(
                (
                    (_directory_similarity(missing_path, match), match)
                    for match in matches
                ),
                reverse=True,
            )
            if scored:
                best_score, best_match = scored[0]
                if best_score > 0 and (len(scored) == 1 or best_score > scored[1][0]):
                    matches = [best_match]
            if len(matches) != 1:
                return None

        if len(matches) != 1:
            return None

        relative = os.path.relpath(matches[0], os.getcwd()).replace(os.sep, '/')
        return '/' + relative.lstrip('/')

    def _send_empty(self, status=204, content_type='application/json', body=b''):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _resolve_and_set_path(self):
        """Resolve path aliases and hash-suffix fallbacks. Returns final fs path or None on miss."""
        resolved_request_path, path = self._resolve_request_target(self.path)
        if not os.path.isfile(path):
            filename = os.path.basename(path)
            directory = os.path.dirname(path)
            if '.' in filename and os.path.isdir(directory):
                stem, _, ext = filename.rpartition('.')
                ext = '.' + ext
                candidates = [
                    f for f in os.listdir(directory)
                    if os.path.isfile(os.path.join(directory, f))
                    and os.path.splitext(f)[1] == ext
                    and (
                        os.path.splitext(f)[0].startswith(stem + '_')
                        or os.path.splitext(f)[0].rstrip('_') == stem.rstrip('_')
                    )
                ]
                if len(candidates) == 1:
                    resolved_request_path = os.path.join(os.path.dirname(resolved_request_path), candidates[0])
            if not os.path.isfile(self.translate_path(resolved_request_path)):
                global_fallback = self._global_asset_fallback(path)
                if global_fallback:
                    resolved_request_path = global_fallback
        self.path = resolved_request_path
        return self.translate_path(self.path)

    def do_GET(self):
        """
        Serve files with basename-prefix fallback for hash-suffixed filenames.

        When a file is not found at the exact path (e.g. /assets/chunk.js),
        look for a file whose stem starts with 'chunk_' in the same directory
        (e.g. chunk_03efa892a380.js). This transparently resolves ES dynamic
        imports and any other request that uses the original filename while the
        saved file has a hash suffix appended by the downloader.

        Also handles HTTP Range requests so browsers can stream video/audio
        files correctly (required for <video> and <audio> elements).
        """
        if self.path.startswith('/.well-known/appspecific/'):
            self._send_empty()
            return

        fs_path = self._resolve_and_set_path()

        range_header = self.headers.get('Range', '')
        if range_header.startswith('bytes=') and os.path.isfile(fs_path):
            self._serve_range(fs_path, range_header)
            return

        try:
            super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_range(self, fs_path, range_header):
        """Serve a partial file response (HTTP 206) for Range requests."""
        file_size = os.path.getsize(fs_path)
        range_spec = range_header[6:]  # strip 'bytes='
        try:
            start_str, end_str = range_spec.split('-', 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
        except ValueError:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{file_size}')
            self.end_headers()
            return

        end = min(end, file_size - 1)
        if start < 0 or start > end or start >= file_size:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{file_size}')
            self.end_headers()
            return

        chunk_size = end - start + 1
        ctype = self.guess_type(fs_path)
        self.send_response(206)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
        self.send_header('Content-Length', str(chunk_size))
        self.end_headers()

        try:
            with open(fs_path, 'rb') as f:
                f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    data = f.read(min(65536, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self._send_empty()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', '0') or '0')
        if content_length > 0:
            self.rfile.read(content_length)
        self._send_empty(status=200, body=b'{}')

    def end_headers(self):
        # CORS headers for local development
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        # Allow browsers to make range requests (required for video/audio streaming)
        self.send_header('Accept-Ranges', 'bytes')
        # Cache control
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

    def guess_type(self, path):
        """Override guess_type to handle special MIME types"""
        # Get extension
        ext = Path(path).suffix.lower()

        # Check custom MIME types first
        if ext in MIME_TYPES:
            return MIME_TYPES[ext]

        # Fallback to default
        return super().guess_type(path)

    def log_request(self, code='-', size='-'):
        """Log ALL requests — Zero Suppression policy"""
        super().log_request(code, size)


def find_available_port(start_port=8000, max_attempts=10):
    """Find an available port starting from start_port"""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socketserver.TCPServer(("", port), None) as s:
                return port
        except OSError:
            continue
    raise RuntimeError(f"Não foi possível encontrar porta disponível entre {start_port} e {start_port + max_attempts}")


def main():
    # Change to script directory
    os.chdir(Path(__file__).parent)

    # Find available port
    try:
        PORT = find_available_port(8000)
    except RuntimeError as e:
        print(f"Erro: {e}")
        sys.exit(1)

    # Create server — ThreadingTCPServer handles concurrent connections
    # (required when browsers stream large files like video while also
    # fetching other assets in parallel)
    Handler = CustomHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("", PORT), Handler)
    httpd.daemon_threads = True

    url = f"http://localhost:{PORT}"

    print("=" * 60)
    print("DeepMirror WebSites - Servidor Local")
    print("=" * 60)
    print(f"\nServidor rodando em: {url}")
    print(f"Diretório: {os.getcwd()}")
    print("\nAbra a URL acima no navegador de sua preferência.")
    print("\n Para parar o servidor: Ctrl+C")
    print("=" * 60 + "\n")

    # Start server
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nServidor encerrado pelo usuário.")
        httpd.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
