import asyncio
import json
import platform
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


def collect_page_data(url: str):
    json_hits = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        def handle_response(response):
            content_type = response.headers.get("content-type", "")

            if "json" not in content_type.lower():
                return

            try:
                data = response.json()
                dumped = json.dumps(data, ensure_ascii=False).lower()

                if any(
                    keyword in dumped
                    for keyword in [
                        "probability",
                        "prediction",
                        "forecast",
                        "correct score",
                        "both teams",
                        "over 2.5",
                        "under 2.5",
                        "value tip",
                        "value_tip",
                        "value tips",
                        "value_tips",
                        "confidence",
                        "confidence rating",
                        "rating",
                        "tip_recommendation",
                        "recommendation",
                    ]
                ):
                    json_hits.append(
                        {
                            "url": response.url,
                            "status": response.status,
                            "data": data,
                        }
                    )
            except Exception:
                pass

        page.on("response", handle_response)

        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        page.wait_for_timeout(3000)

        # Scroll through the page so lazy-loaded sections/widgets render.
        for _ in range(8):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(700)

        # Go back up a bit and wait again, just in case some sections render after scrolling.
        page.mouse.wheel(0, -800)
        page.wait_for_timeout(1500)

        # Collect visible body text, deeper DOM text and useful attributes.
        rendered_text_parts = []
        rendered_html_parts = []

        try:
            rendered_text_parts.append(page.locator("body").inner_text(timeout=15000))
        except Exception:
            pass

        try:
            rendered_html_parts.append(page.content())
        except Exception:
            pass

        # Deeper DOM extraction.
        # This helps catch text rendered inside custom cards, buttons, aria-labels, titles, alt text, etc.
        try:
            dom_text = page.evaluate(
                """
                () => {
                    const rows = [];

                    for (const el of Array.from(document.querySelectorAll('*'))) {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);

                        const isVisible =
                            rect.width > 0 &&
                            rect.height > 0 &&
                            style.display !== 'none' &&
                            style.visibility !== 'hidden';

                        const parts = [];

                        if (isVisible && el.innerText) parts.push(el.innerText);
                        if (isVisible && el.textContent) parts.push(el.textContent);
                        if (el.getAttribute('aria-label')) parts.push(el.getAttribute('aria-label'));
                        if (el.getAttribute('title')) parts.push(el.getAttribute('title'));
                        if (el.getAttribute('alt')) parts.push(el.getAttribute('alt'));
                        if (el.getAttribute('data-testid')) parts.push(el.getAttribute('data-testid'));
                        if (el.getAttribute('data-title')) parts.push(el.getAttribute('data-title'));
                        if (el.getAttribute('data-value')) parts.push(el.getAttribute('data-value'));

                        const text = parts
                            .join(' | ')
                            .replace(/\\s+/g, ' ')
                            .trim();

                        if (text) rows.push(text);
                    }

                    return Array.from(new Set(rows)).join('\\n');
                }
                """
            )

            if dom_text:
                rendered_text_parts.append(dom_text)
        except Exception:
            pass

        # Collect text from all frames as well.
        for frame in page.frames:
            try:
                frame_text = frame.locator("body").inner_text(timeout=5000)
                if frame_text:
                    rendered_text_parts.append(frame_text)
            except Exception:
                pass

            try:
                frame_html = frame.content()
                if frame_html:
                    rendered_html_parts.append(frame_html)
            except Exception:
                pass

        rendered_text = "\n\n--- TEXT BREAK ---\n\n".join(rendered_text_parts)
        rendered_html = "\n\n<!-- HTML BREAK -->\n\n".join(rendered_html_parts)

        browser.close()

    browser_data = {
        "rendered_text": rendered_text,
        "rendered_html": rendered_html,
        "json_hits": json_hits,
    }

    output_file = DATA_DIR / "latest_browser_data.json"

    output_file.write_text(
        json.dumps(browser_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (DATA_DIR / "debug_kickform_rendered_text.txt").write_text(
        rendered_text,
        encoding="utf-8",
    )

    (DATA_DIR / "debug_kickform_rendered_html.html").write_text(
        rendered_html,
        encoding="utf-8",
    )

    (DATA_DIR / "debug_kickform_network.json").write_text(
        json.dumps(json_hits, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "output_file": str(output_file),
        "json_hits_count": len(json_hits),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "Missing URL argument"}))
        sys.exit(1)

    url = sys.argv[1]

    try:
        result = collect_page_data(url)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)