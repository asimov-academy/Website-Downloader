"""
Extract computed styles from rendered page elements via Playwright.
Reference: AI-Design-Engineering.md Section 4.3
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Iterable

from playwright.async_api import async_playwright

from .. import BROWSER_ARGS, BROWSER_HEADLESS, USER_AGENT
from . import (
    DEFAULT_SELECTORS,
    STYLE_PROPERTIES,
    prepare_runtime_target,
    stabilize_runtime_page,
    write_json,
)


async def _goto_with_fallback(page, target: str, timeout_ms: int) -> None:
    last_error = None
    for wait_until in ("networkidle", "load", "domcontentloaded"):
        try:
            await page.goto(target, wait_until=wait_until, timeout=timeout_ms)
            return
        except Exception as exc:  # pragma: no cover - browser/runtime dependent
            last_error = exc

    if last_error:
        raise last_error


async def extract_computed_styles(
    url: str,
    output_path: str | None = None,
    selectors: list[str] | None = None,
    timeout_ms: int = 30000,
) -> dict:
    """
    Open a URL or local path in Playwright and extract computed styles.
    Returns a selector -> computed-style mapping.
    """

    selectors = dedupe_selectors(selectors or DEFAULT_SELECTORS)
    results: dict[str, dict] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=BROWSER_HEADLESS, args=BROWSER_ARGS)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
        )
        page = await context.new_page()

        try:
            async with prepare_runtime_target(url) as target:
                await _goto_with_fallback(page, target, timeout_ms)
                await stabilize_runtime_page(page)

                for selector in selectors:
                    try:
                        elements = await page.query_selector_all(selector)
                    except Exception:
                        continue

                    if not elements:
                        continue

                    try:
                        styles = await elements[0].evaluate(
                            """(node, props) => {
                                const style = window.getComputedStyle(node);
                                const result = {};
                                for (const prop of props) {
                                    const value = style[prop];
                                    if (
                                        value &&
                                        value !== '' &&
                                        value !== 'none' &&
                                        value !== 'normal' &&
                                        value !== '0px' &&
                                        value !== 'auto' &&
                                        value !== 'rgba(0, 0, 0, 0)'
                                    ) {
                                        result[prop] = value;
                                    }
                                }
                                result._tagName = node.tagName.toLowerCase();
                                result._className = node.className || '';
                                result._textContent = (node.textContent || '').trim().slice(0, 100);
                                return result;
                            }""",
                            STYLE_PROPERTIES,
                        )
                    except Exception:
                        continue

                    if styles and len(styles) > 3:
                        results[selector] = styles

        finally:
            await context.close()
            await browser.close()

    if output_path:
        write_json(output_path, results)

    return results


def dedupe_selectors(selectors: Iterable[str]) -> list[str]:
    """Keep the first occurrence of each selector."""

    seen = set()
    result = []
    for selector in selectors:
        if selector in seen:
            continue
        seen.add(selector)
        result.append(selector)
    return result


def run(
    url: str,
    output_path: str | None = None,
    selectors: list[str] | None = None,
    timeout_ms: int = 30000,
) -> dict:
    """Synchronous wrapper for the extractor."""

    return asyncio.run(
        extract_computed_styles(
            url,
            output_path=output_path,
            selectors=selectors,
            timeout_ms=timeout_ms,
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract computed styles from a rendered page."
    )
    parser.add_argument("target", help="URL or local path to open")
    parser.add_argument(
        "output",
        nargs="?",
        default="computed_styles.json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Navigation timeout in milliseconds",
    )
    parser.add_argument(
        "--selector",
        action="append",
        dest="selectors",
        help="Custom selector to inspect (can be repeated)",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    result = run(
        args.target,
        output_path=args.output,
        selectors=args.selectors,
        timeout_ms=args.timeout_ms,
    )
    print(f"Extraidos estilos de {len(result)} seletores -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
