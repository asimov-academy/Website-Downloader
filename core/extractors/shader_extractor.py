"""
Extract GLSL shaders embedded in JavaScript files.
Reference: AI-Design-Engineering.md Section 10.1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from . import slugify, write_json


GLSL_INDICATORS = [
    r"gl_FragColor",
    r"gl_Position",
    r"gl_PointSize",
    r"precision\s+(?:lowp|mediump|highp)\s+float",
    r"uniform\s+(?:float|vec[234]|mat[234]|sampler2D|samplerCube)",
    r"varying\s+(?:float|vec[234]|mat[234])",
    r"attribute\s+(?:float|vec[234]|mat[234])",
]

_SHADER_BLOCK_PATTERNS = [
    re.compile(
        r"`([^`]{50,}?(?:void\s+main|gl_FragColor|gl_Position)[^`]{10,}?)`",
        re.DOTALL,
    ),
    re.compile(
        r'"((?:[^"\\]|\\.){50,}?(?:void\s+main|gl_FragColor|gl_Position)(?:[^"\\]|\\.){10,}?)"',
        re.DOTALL,
    ),
    re.compile(
        r"'((?:[^'\\]|\\.){50,}?(?:void\s+main|gl_FragColor|gl_Position)(?:[^'\\]|\\.){10,}?)'",
        re.DOTALL,
    ),
]


def _classify_shader(code: str) -> str:
    if "gl_FragColor" in code or "gl_FragData" in code:
        return "fragment"
    if "gl_Position" in code:
        return "vertex"
    return "unknown"


def _has_glsl_content(content: str) -> bool:
    return any(re.search(pattern, content) for pattern in GLSL_INDICATORS)


def _unescape_js_string(value: str) -> str:
    value = value.replace("\\r", "")
    value = value.replace("\\n", "\n")
    value = value.replace("\\t", "\t")
    value = value.replace("\\'", "'")
    value = value.replace('\\"', '"')
    value = value.replace("\\\\", "\\")

    def replace_unicode(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    return re.sub(r"\\u([0-9a-fA-F]{4})", replace_unicode, value)


def extract_shaders_from_file(filepath: str) -> list[dict]:
    """
    Search a JS file for embedded GLSL shader strings.
    Returns a list of shader dictionaries.
    """

    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    if not _has_glsl_content(content):
        return []

    shaders = []
    seen_hashes = set()

    for pattern in _SHADER_BLOCK_PATTERNS:
        for match in pattern.finditer(content):
            raw_code = match.group(1)
            code = _unescape_js_string(raw_code).strip()

            if "void main" not in code:
                continue

            digest = hashlib.sha1(code[:500].encode("utf-8", errors="ignore")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)

            shaders.append(
                {
                    "type": _classify_shader(code),
                    "code": code,
                    "source_file": str(filepath),
                    "char_offset": match.start(),
                    "char_length": len(raw_code),
                }
            )

    return shaders


def extract_shaders_from_directory(directory: str, output_dir: str | None = None) -> dict:
    """
    Walk a directory and extract GLSL shaders from .js/.mjs/.cjs files.
    """

    results = {
        "source_directory": directory,
        "shaders_found": 0,
        "files_scanned": 0,
        "files_with_shaders": 0,
        "shaders": [],
    }

    js_files = []
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.endswith((".js", ".mjs", ".cjs")):
                js_files.append(os.path.join(root, filename))

    results["files_scanned"] = len(js_files)

    for js_file in js_files:
        shaders = extract_shaders_from_file(js_file)
        if not shaders:
            continue
        results["files_with_shaders"] += 1
        results["shaders"].extend(shaders)

    results["shaders_found"] = len(results["shaders"])

    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        for index, shader in enumerate(results["shaders"], start=1):
            source_stem = slugify(Path(shader["source_file"]).stem)
            shader_type = shader["type"]
            filename = f"shader_{index:03d}_{source_stem}_{shader_type}.glsl"
            output_file = out_path / filename
            output_file.write_text(shader["code"], encoding="utf-8")
            shader["output_file"] = str(output_file)

        manifest = {k: v for k, v in results.items() if k != "shaders"}
        manifest["shader_files"] = [
            {
                "file": shader.get("output_file", ""),
                "type": shader["type"],
                "source": shader["source_file"],
            }
            for shader in results["shaders"]
        ]
        write_json(out_path / "_shaders_manifest.json", manifest)

    return results


def run(directory: str, output_dir: str | None = None) -> dict:
    """Entry point wrapper."""

    return extract_shaders_from_directory(directory, output_dir)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract GLSL shaders embedded in JavaScript."
    )
    parser.add_argument("directory", help="Directory to scan for JS files")
    parser.add_argument(
        "output",
        nargs="?",
        default="shaders_output",
        help="Directory for extracted shaders and manifest",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    result = run(args.directory, args.output)
    print(
        f"Escaneados {result['files_scanned']} JS | "
        f"{result['files_with_shaders']} com shaders | "
        f"{result['shaders_found']} shaders extraidos -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
