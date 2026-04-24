"""
Map scroll-driven animations by capturing element state at each scroll position.
Reference: AI-Design-Engineering.md Section 6.4
"""

from __future__ import annotations

import argparse
import asyncio

from playwright.async_api import async_playwright

from .. import BROWSER_ARGS, BROWSER_HEADLESS, USER_AGENT
from . import (
    DEFAULT_ANIMATED_SELECTORS,
    SCROLL_PROPERTIES,
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


async def _detect_active_selectors(page, selectors: list[str]) -> list[str]:
    active = []
    for selector in selectors:
        try:
            count = await page.evaluate(
                "(selector) => document.querySelectorAll(selector).length",
                selector,
            )
        except Exception:
            continue
        if count:
            active.append(selector)
    return active


async def _capture_state(page, selector: str) -> dict | None:
    try:
        return await page.evaluate(
            """({ selector, props }) => {
                const els = document.querySelectorAll(selector);
                if (!els.length) {
                    return null;
                }
                const el = els[0];
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                const result = {};
                for (const prop of props) {
                    const value = style[prop];
                    if (value && value !== 'none' && value !== 'auto') {
                        result[prop] = value;
                    }
                }
                result._rect = {
                    top: Math.round(rect.top),
                    left: Math.round(rect.left),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                };
                return result;
            }""",
            {
                "selector": selector,
                "props": SCROLL_PROPERTIES,
            },
        )
    except Exception:
        return None


async def extract_scroll_physics(
    url: str,
    output_path: str | None = None,
    selectors: list[str] | None = None,
    scroll_step: int = 100,
    max_scroll: int = 5000,
    timeout_ms: int = 60000,
) -> dict:
    """
    Scroll the page and capture computed state for scroll-linked elements.
    """

    selectors = selectors or DEFAULT_ANIMATED_SELECTORS
    results = {
        "url": url,
        "scroll_step": scroll_step,
        "max_scroll_captured": 0,
        "elements": {},
        "keyframes": [],
    }

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
                await stabilize_runtime_page(page, settle_ms=1500)

                try:
                    total_height = await page.evaluate(
                        "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
                    )
                except Exception:
                    total_height = 0

                actual_max = min(max_scroll, int(total_height or max_scroll))
                active_selectors = await _detect_active_selectors(page, selectors)

                if not active_selectors:
                    results["warning"] = "Nenhum seletor animado encontrado na pagina"
                    return results

                first_frame: dict[str, dict] = {}
                for scroll_y in range(0, actual_max + 1, max(scroll_step, 1)):
                    try:
                        await page.evaluate("(y) => window.scrollTo(0, y)", scroll_y)
                        await page.wait_for_timeout(150)
                    except Exception:
                        continue

                    frame = {"scrollY": scroll_y, "elements": {}}
                    for selector in active_selectors:
                        state = await _capture_state(page, selector)
                        if state is not None:
                            frame["elements"][selector] = state
                            if selector not in first_frame:
                                first_frame[selector] = state

                    results["keyframes"].append(frame)
                    results["max_scroll_captured"] = scroll_y

                for selector in active_selectors:
                    initial_state = first_frame.get(selector, {})
                    changed_properties = set()
                    animated = False
                    for frame in results["keyframes"][1:]:
                        current_state = frame.get("elements", {}).get(selector, {})
                        for prop in SCROLL_PROPERTIES:
                            if current_state.get(prop) != initial_state.get(prop):
                                animated = True
                                changed_properties.add(prop)

                        initial_rect = initial_state.get("_rect", {})
                        current_rect = current_state.get("_rect", {})
                        for rect_prop in ("top", "left", "width", "height"):
                            if current_rect.get(rect_prop) != initial_rect.get(rect_prop):
                                animated = True
                                changed_properties.add(f"_rect.{rect_prop}")
                    results["elements"][selector] = {
                        "animated": animated,
                        "initial_state": initial_state,
                        "changed_properties": sorted(changed_properties),
                        "frames_observed": len(results["keyframes"]),
                    }

        finally:
            await context.close()
            await browser.close()

    if output_path:
        write_json(output_path, results)

    return results


def run(
    url: str,
    output_path: str | None = None,
    selectors: list[str] | None = None,
    scroll_step: int = 100,
    max_scroll: int = 5000,
    timeout_ms: int = 60000,
) -> dict:
    """Synchronous wrapper."""

    return asyncio.run(
        extract_scroll_physics(
            url,
            output_path=output_path,
            selectors=selectors,
            scroll_step=scroll_step,
            max_scroll=max_scroll,
            timeout_ms=timeout_ms,
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture scroll-linked physics from a rendered page."
    )
    parser.add_argument("target", help="URL or local path to open")
    parser.add_argument(
        "output",
        nargs="?",
        default="scroll_physics.json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=100,
        help="Scroll increment in pixels",
    )
    parser.add_argument(
        "--max-scroll",
        type=int,
        default=5000,
        help="Maximum scroll distance to sample",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=60000,
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
        scroll_step=args.step,
        max_scroll=args.max_scroll,
        timeout_ms=args.timeout_ms,
    )
    animated = sum(1 for data in result.get("elements", {}).values() if data.get("animated"))
    total = len(result.get("elements", {}))
    print(
        f"Mapeados {len(result.get('keyframes', []))} frames | "
        f"{animated}/{total} elementos animados -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
