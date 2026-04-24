"""
Runtime data extractors using Playwright.

Each extractor captures data that does not exist in static HTML/CSS/JS.
"""

from __future__ import annotations

import functools
import http.server
import json
import socketserver
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


DEFAULT_SELECTORS = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "a",
    "button",
    "input",
    "textarea",
    "select",
    "nav",
    "header",
    "footer",
    "main",
    ".card",
    ".btn",
    ".button",
    ".hero",
    "label",
    "span",
    "li",
    "img",
    "figure",
    "blockquote",
]

STYLE_PROPERTIES = [
    "fontFamily",
    "fontSize",
    "fontWeight",
    "fontStyle",
    "lineHeight",
    "letterSpacing",
    "textTransform",
    "textDecoration",
    "color",
    "backgroundColor",
    "borderRadius",
    "borderWidth",
    "borderColor",
    "borderStyle",
    "padding",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "margin",
    "marginTop",
    "marginRight",
    "marginBottom",
    "marginLeft",
    "width",
    "height",
    "maxWidth",
    "minHeight",
    "display",
    "position",
    "flexDirection",
    "justifyContent",
    "alignItems",
    "gap",
    "gridTemplateColumns",
    "boxShadow",
    "textShadow",
    "opacity",
    "zIndex",
    "transition",
    "transform",
]

DEFAULT_ANIMATED_SELECTORS = [
    "h1",
    "h2",
    ".hero",
    ".hero-image",
    ".hero-title",
    "section",
    "[data-scroll]",
    "[data-animate]",
    "[data-parallax]",
    "[data-speed]",
    "[data-reveal]",
    "canvas",
    "video",
    ".fade-in",
    ".slide-up",
    ".parallax",
]

SCROLL_PROPERTIES = [
    "opacity",
    "transform",
    "visibility",
    "clipPath",
    "filter",
    "scale",
    "top",
    "left",
    "width",
    "height",
]

LOCAL_RUNTIME_MIME_TYPES = {
    ".avif": "image/avif",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".js": "application/javascript",
    ".json": "application/json",
    ".mjs": "application/javascript",
    ".otf": "font/otf",
    ".riv": "application/octet-stream",
    ".ttf": "font/ttf",
    ".wasm": "application/wasm",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _LocalCaptureRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serve downloaded snapshots with asset aliases and loose hashed lookups."""

    def _asset_alias_path(self, request_path: str) -> str | None:
        if not request_path or request_path.startswith("/assets/"):
            return None

        normalized = request_path if request_path.startswith("/") else f"/{request_path}"
        return f"/assets{normalized}"

    def _candidate_request_paths(self, request_path: str) -> list[str]:
        normalized = request_path if request_path.startswith("/") else f"/{request_path}"
        candidates = [normalized]

        normalized_path = self.translate_path(normalized)
        if Path(normalized_path).is_dir():
            candidates.append(normalized.rstrip("/") + "/index.html")

        if normalized.endswith("/"):
            candidates.append(normalized + "index.html")

        if normalized in {"", "/"}:
            candidates.append("/index.html")

        asset_alias = self._asset_alias_path(normalized)
        if asset_alias:
            candidates.append(asset_alias)
            alias_path = self.translate_path(asset_alias)
            if Path(alias_path).is_dir():
                candidates.append(asset_alias.rstrip("/") + "/index.html")
            if asset_alias.endswith("/"):
                candidates.append(asset_alias + "index.html")

        return list(dict.fromkeys(candidates))

    def _next_image_source_path(self, request_path: str) -> str | None:
        parsed = urlparse(request_path)
        if not parsed.path.startswith("/_next/image"):
            return None

        source = parse_qs(parsed.query).get("url", [None])[0]
        if not source:
            return None

        source = unquote(source)
        source_parsed = urlparse(source)
        if source_parsed.scheme or source_parsed.netloc:
            source = source_parsed.path

        if not source.startswith("/"):
            source = "/" + source.lstrip("/")

        return source

    def _resolve_request_target(self, request_path: str) -> tuple[str, str]:
        parsed = urlparse(request_path)
        clean_path = parsed.path or "/"

        next_image_source = self._next_image_source_path(request_path)
        if next_image_source:
            clean_path = next_image_source

        fallback_candidate = None
        for candidate in self._candidate_request_paths(clean_path):
            candidate_path = self.translate_path(candidate)
            if Path(candidate_path).is_file():
                return candidate, candidate_path
            if candidate.startswith("/assets/"):
                fallback_candidate = (candidate, candidate_path)

        if fallback_candidate:
            return fallback_candidate

        return clean_path, self.translate_path(clean_path)

    def _send_empty(self, status: int = 204, content_type: str = "application/json", body: bytes = b"") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/.well-known/appspecific/"):
            self._send_empty()
            return

        resolved_request_path, path = self._resolve_request_target(self.path)
        if not Path(path).is_file():
            filename = Path(path).name
            directory = Path(path).parent
            if "." in filename and directory.is_dir():
                stem = Path(filename).stem
                ext = Path(filename).suffix
                candidates = [
                    candidate.name
                    for candidate in directory.iterdir()
                    if candidate.is_file()
                    and candidate.suffix == ext
                    and candidate.stem.startswith(stem + "_")
                ]
                if len(candidates) == 1:
                    resolved_request_path = str(Path(resolved_request_path).parent / candidates[0])
        self.path = resolved_request_path
        try:
            super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self) -> None:
        self._send_empty()

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length > 0:
            self.rfile.read(content_length)
        self._send_empty(status=200, body=b"{}")

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def guess_type(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        if ext in LOCAL_RUNTIME_MIME_TYPES:
            return LOCAL_RUNTIME_MIME_TYPES[ext]
        return super().guess_type(path)

    def log_message(self, format: str, *args) -> None:
        return


def resolve_target(target: str) -> str:
    """Resolve a URL or local path into something Playwright can open."""

    if _looks_like_url(target):
        return target

    path = Path(target).expanduser()
    if not path.exists():
        return target

    if path.is_dir():
        candidates = [
            path / "clean" / "index.html",
            path / "raw" / "index.html",
            path / "index.html",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve().as_uri()

    return path.resolve().as_uri()


@asynccontextmanager
async def prepare_runtime_target(target: str):
    """
    Yield a browser-openable target.

    Local snapshots are served over HTTP so runtime assets like fonts, dynamic
    imports, and root-relative requests behave like a real website.
    """

    if _looks_like_url(target):
        yield target
        return

    path = Path(target).expanduser()
    if not path.exists():
        yield target
        return

    root_dir, request_path = _resolve_local_runtime_target(path)
    handler = functools.partial(_LocalCaptureRequestHandler, directory=str(root_dir))
    server = _ThreadingTCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}{request_path}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


async def stabilize_runtime_page(page, settle_ms: int = 750) -> None:
    """Wait for hydration and fonts before sampling runtime state."""

    try:
        await page.wait_for_selector("body", state="attached", timeout=5000)
    except Exception:
        pass

    try:
        await page.wait_for_load_state("networkidle", timeout=2500)
    except Exception:
        pass

    try:
        await page.evaluate(
            """async () => {
                if (document.fonts && document.fonts.ready) {
                    try {
                        await document.fonts.ready;
                    } catch (error) {
                    }
                }

                await new Promise((resolve) => {
                    requestAnimationFrame(() => requestAnimationFrame(resolve));
                });
            }"""
        )
    except Exception:
        pass

    if settle_ms > 0:
        await page.wait_for_timeout(settle_ms)


def write_json(path: str | Path, payload: Any) -> None:
    """Write JSON with stable formatting."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def slugify(value: str, default: str = "item") -> str:
    """Convert arbitrary text into a safe filename fragment."""

    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or default


def dedupe_preserve_order(items: list[str]) -> list[str]:
    """Return a list without duplicates, preserving first-seen order."""

    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _looks_like_url(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target))


def _resolve_local_runtime_target(path: Path) -> tuple[Path, str]:
    resolved = path.resolve()
    if resolved.is_dir():
        candidates = [
            resolved / "clean" / "index.html",
            resolved / "raw" / "index.html",
            resolved / "index.html",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.parent, f"/{candidate.name}"
        return resolved, "/"

    return resolved.parent, f"/{resolved.name}"
