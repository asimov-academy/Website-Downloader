"""
Filter JavaScript by actual execution using CDP code coverage.
Reference: AI-Design-Engineering.md Section 4.4
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict

from playwright.async_api import async_playwright

from .. import BROWSER_ARGS, BROWSER_HEADLESS, USER_AGENT
from . import prepare_runtime_target, stabilize_runtime_page, write_json


def _calculate_executed_bytes(ranges: list[dict]) -> int:
    """
    Convert nested CDP coverage ranges into disjoint executed segments.

    Precise coverage reports nested ranges where an outer function can be
    executed while inner blocks remain cold. We therefore need the innermost
    active count for each segment, not a simple union of positive ranges.
    """

    if not ranges:
        return 0

    events_by_offset = defaultdict(list)
    for index, raw_range in enumerate(ranges):
        start = int(raw_range.get("startOffset", 0))
        end = int(raw_range.get("endOffset", 0))
        count = int(raw_range.get("count", 0))
        if end <= start:
            continue
        events_by_offset[start].append(("start", end, count, index))
        events_by_offset[end].append(("end", start, count, index))

    if not events_by_offset:
        return 0

    active: list[dict] = []
    executed = 0
    previous_offset = None

    for offset in sorted(events_by_offset):
        if previous_offset is not None and active and offset > previous_offset:
            if active[-1]["count"] > 0:
                executed += offset - previous_offset

        events = events_by_offset[offset]
        ending_ids = {event[3] for event in events if event[0] == "end"}
        if ending_ids:
            active = [item for item in active if item["id"] not in ending_ids]

        starting = [event for event in events if event[0] == "start"]
        starting.sort(key=lambda event: event[1], reverse=True)
        for _kind, end, count, identifier in starting:
            active.append({"id": identifier, "end": end, "count": count})

        previous_offset = offset

    return executed


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


async def _scroll_page(page, samples: int) -> None:
    try:
        viewport_height = await page.evaluate("window.innerHeight || 800")
        total_height = await page.evaluate(
            "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
        )
    except Exception:
        return

    max_scroll = max(int(total_height), 0)
    sample_count = max(int(samples), 1)
    if max_scroll <= 0:
        return

    step_size = max(max_scroll // sample_count, int(viewport_height // 2), 200)
    step_size = max(step_size, 1)

    for scroll_y in range(0, max_scroll + 1, step_size):
        try:
            await page.evaluate("(y) => window.scrollTo(0, y)", scroll_y)
            await page.wait_for_timeout(250)
        except Exception:
            continue

    try:
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


async def _start_cdp_coverage(context, page):
    session = await context.new_cdp_session(page)
    await session.send("Profiler.enable")
    await session.send("Debugger.enable")
    await session.send(
        "Profiler.startPreciseCoverage",
        {
            "callCount": True,
            "detailed": True,
            "allowTriggeredUpdates": False,
        },
    )
    return session


async def _get_script_source(session, script_id: str) -> str:
    try:
        payload = await session.send("Debugger.getScriptSource", {"scriptId": script_id})
        return payload.get("scriptSource", "") or ""
    except Exception:
        return ""


async def extract_code_coverage(
    url: str,
    output_path: str | None = None,
    scroll_steps: int = 20,
    timeout_ms: int = 60000,
) -> dict:
    """
    Navigate to a URL, collect JavaScript coverage via CDP and scroll.
    Returns per-file coverage plus a summary.
    """

    results = {
        "url": url,
        "files": [],
        "summary": {
            "total_bytes": 0,
            "executed_bytes": 0,
            "dead_bytes": 0,
            "coverage_pct": 0.0,
            "files_analyzed": 0,
        },
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=BROWSER_HEADLESS, args=BROWSER_ARGS)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
        )
        page = await context.new_page()
        session = None

        try:
            session = await _start_cdp_coverage(context, page)
            async with prepare_runtime_target(url) as target:
                await _goto_with_fallback(page, target, timeout_ms)
                await stabilize_runtime_page(page, settle_ms=1000)
                await _scroll_page(page, scroll_steps)
                await page.wait_for_timeout(1000)

                coverage = await session.send("Profiler.takePreciseCoverage")
                await session.send("Profiler.stopPreciseCoverage")

                grouped = defaultdict(
                    lambda: {
                        "url": "",
                        "script_ids": [],
                        "total_bytes": 0,
                        "executed_bytes": 0,
                        "dead_bytes": 0,
                        "coverage_pct": 0.0,
                    }
                )

                for entry in coverage.get("result", []):
                    script_id = entry.get("scriptId", "")
                    source = await _get_script_source(session, script_id)
                    total_bytes = len(source)

                    raw_ranges = []
                    for function in entry.get("functions", []):
                        for rng in function.get("ranges", []):
                            raw_ranges.append(rng)

                    executed_bytes = _calculate_executed_bytes(raw_ranges)
                    script_url = entry.get("url") or ""
                    key = script_url or f"inline:{script_id}"

                    item = grouped[key]
                    item["url"] = script_url or key
                    item["script_ids"].append(script_id)
                    item["total_bytes"] += total_bytes
                    item["executed_bytes"] += min(executed_bytes, total_bytes)

                files = []
                total_bytes = 0
                executed_bytes = 0
                for item in grouped.values():
                    item["dead_bytes"] = max(item["total_bytes"] - item["executed_bytes"], 0)
                    item["coverage_pct"] = round(
                        (item["executed_bytes"] / item["total_bytes"] * 100)
                        if item["total_bytes"]
                        else 0.0,
                        1,
                    )
                    files.append(item)
                    total_bytes += item["total_bytes"]
                    executed_bytes += item["executed_bytes"]

                files.sort(key=lambda file_info: file_info["dead_bytes"], reverse=True)
                results["files"] = files
                results["summary"] = {
                    "total_bytes": total_bytes,
                    "executed_bytes": executed_bytes,
                    "dead_bytes": max(total_bytes - executed_bytes, 0),
                    "coverage_pct": round(
                        (executed_bytes / total_bytes * 100) if total_bytes else 0.0,
                        1,
                    ),
                    "files_analyzed": len(files),
                }

        finally:
            if session is not None:
                try:
                    await session.send("Profiler.stopPreciseCoverage")
                except Exception:
                    pass
                try:
                    await session.send("Debugger.disable")
                except Exception:
                    pass
                try:
                    await session.send("Profiler.disable")
                except Exception:
                    pass
                try:
                    await session.detach()
                except Exception:
                    pass
            await context.close()
            await browser.close()

    if output_path:
        write_json(output_path, results)

    return results


def run(
    url: str,
    output_path: str | None = None,
    scroll_steps: int = 20,
    timeout_ms: int = 60000,
) -> dict:
    """Synchronous wrapper."""

    return asyncio.run(
        extract_code_coverage(
            url,
            output_path=output_path,
            scroll_steps=scroll_steps,
            timeout_ms=timeout_ms,
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure actual JavaScript execution via CDP coverage."
    )
    parser.add_argument("target", help="URL or local path to open")
    parser.add_argument(
        "output",
        nargs="?",
        default="code_coverage.json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--scroll-steps",
        type=int,
        default=20,
        help="Number of scroll samples to take",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=60000,
        help="Navigation timeout in milliseconds",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    result = run(
        args.target,
        output_path=args.output,
        scroll_steps=args.scroll_steps,
        timeout_ms=args.timeout_ms,
    )
    summary = result["summary"]
    print(
        "Coverage: "
        f"{summary['coverage_pct']}% executado | "
        f"{summary['dead_bytes']} bytes mortos | "
        f"{summary['files_analyzed']} arquivos -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
