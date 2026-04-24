"""
Core capture engine — reusable logic shared by single_page.

Encapsulates: browser lifecycle, network recording, page stimulation,
fallback downloads, post-processing, and HTML saving.

Does NOT manage output directory creation, clean pipeline, or serve.py —
those are responsibilities of the individual flows.
"""
import time

from core.browser import BrowserController
from core.network import NetworkRecorder
from core.post_process import PostProcessor


class CaptureEngine:
    """
    Reusable page-capture engine.

    Lifecycle:
        1. start()          — launch browser + attach network recording
        2. navigate(url)    — go to a URL
        3. stimulate()      — scroll, interactions, WebGL, CSS-in-JS, dynamic imports
        4. capture_page()   — collect HTML + save network resources + fallbacks
        5. process_html()   — post-process the captured HTML
        6. save_html(html, filename) — write HTML to disk
        7. stop()           — close browser

    For single-page, steps 2-6 run once.
    staying open between captures.
    """

    def __init__(self, assets_dir, output_dir, log_callback, headless=True, browser_options=None):
        self.assets_dir = assets_dir
        self.output_dir = output_dir
        self.log = log_callback or (lambda msg: print(msg))
        self.headless = headless

        self.browser = BrowserController(
            self.log,
            headless=headless,
            browser_options=browser_options,
        )
        self.network = None  # Initialized after first navigate (needs base_url)
        self.post_processor = None
        self.page = None

        # State
        self._network_attached = False
        self._recording = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Launch browser and return the Playwright page."""
        self.page = self.browser.launch()
        return self.page

    def stop(self):
        """Close browser and clean up."""
        self.browser.close()

    # ------------------------------------------------------------------
    # Navigation + Network
    # ------------------------------------------------------------------

    def navigate(self, url):
        """
        Navigate to URL and set up network recording.

        On first call, creates the NetworkRecorder.
        """
        if self.network is None:
            self.network = NetworkRecorder(url, self.assets_dir, self.log)
            self.network.set_recording(self._recording)
            self._attach_network_handler()

        self.browser.goto(url)

        # Update base_url after navigation (handles redirects)
        self.network.set_base_url(self.browser.base_url)

        # Setup requests session with browser cookies (for fallback downloads)
        cookies = self.browser.get_cookies()
        self.network.setup_session(cookies)

    def _attach_network_handler(self):
        """Attach network response handler to the page (once)."""
        if not self._network_attached:
            self.page.on("response", self.network.get_response_handler())
            self._network_attached = True

    def set_recording(self, enabled):
        """Enable/disable network recording."""
        self._recording = enabled
        if self.network is not None:
            self.network.set_recording(enabled)

    # ------------------------------------------------------------------
    # Stimulation
    # ------------------------------------------------------------------

    def stimulate(self):
        """
        Run full page stimulation: iframe check, scroll, interactions,
        WebGL, network idle, CSS-in-JS, dynamic imports, framework manifests.

        Returns (html_content, is_iframe, framework_css_urls, dynamic_asset_urls).
        """
        # Check for iframe content
        iframe_content, is_iframe = self.browser.extract_iframe_content()

        # Stimulate page if not iframe
        if not is_iframe:
            self.browser.scroll_page()
            self.browser.simulate_interactions()
            self.browser.interact_with_webgl_canvases()

        # Wait for network to settle
        self.browser.wait_for_network_idle()

        # CSS-in-JS injection
        self.browser.wait_for_css_injection()

        # Dynamic imports (Next.js/React code splitting)
        self.browser.trigger_dynamic_imports()

        # Framework manifests (Next.js __BUILD_MANIFEST)
        framework_css_urls = self.browser.extract_framework_manifests()

        # Collect DOM asset URLs for fallback
        self.log("Coletando assets presentes no DOM para fallback...")
        dynamic_asset_urls = self.browser.collect_dynamic_asset_urls()

        # Merge framework CSS with dynamic assets
        if framework_css_urls:
            dynamic_asset_urls.extend(framework_css_urls)

        # Get final HTML
        if is_iframe and iframe_content:
            html_content = iframe_content
            self.log("Usando conteúdo extraído do iframe")
        else:
            html_content = self.browser.get_content()

        return html_content, is_iframe, framework_css_urls, dynamic_asset_urls

    # ------------------------------------------------------------------
    # Capture (save network resources + fallbacks)
    # ------------------------------------------------------------------

    def save_captured_resources(self, dynamic_asset_urls=None):
        """
        Save all network-captured resources to disk and run fallback downloads.
        Call this after stimulate() and before closing the browser (or between captures).
        """
        # Log network stats
        self.network.log_stats()

        # Save all captured resources to disk
        self.log("Salvando recursos capturados...")
        self.network.save_all_captured_resources()

        # Fallback: DOM assets not captured
        if dynamic_asset_urls:
            self.log("Verificando assets do DOM para fallback...")
            self.network.ensure_resources_downloaded(dynamic_asset_urls)

        # Fallback: all URLs seen by browser but not saved/ignored
        self.log("Verificando todos os assets vistos pelo browser para fallback...")
        all_seen_urls = list(dict.fromkeys(url for url, status in self.network.all_seen_urls))
        ignored_urls = {url for url, _reason in self.network.ignored_resources}
        failed_urls = {url for url, _reason in self.network.failed_resources}
        retryable_failed_urls = {
            url for url, reason in self.network.failed_resources
            if self.network._is_retryable_failure(reason)
        }
        already = set(self.network.resource_cache.keys()) | ignored_urls | (failed_urls - retryable_failed_urls)
        fallback_urls = [u for u in all_seen_urls if u not in already]
        if fallback_urls:
            self.log(f"   {len(fallback_urls)} URLs vistas não salvas, tentando fallback...")
            self.network.ensure_resources_downloaded(fallback_urls)

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def process_html(self, html_content, preserve_navigation_links=False):
        """
        Run the PostProcessor pipeline on HTML content.
        Returns processed HTML string.
        """
        self.post_processor = PostProcessor(
            self.browser.base_url,
            self.output_dir,
            self.log,
            self.network,
            preserve_navigation_links=preserve_navigation_links,
        )
        return self.post_processor.process_html(html_content)

    def save_html(self, html_output, filename='index.html'):
        """Save processed HTML to disk with the given filename."""
        self.post_processor.save_html(html_output, filename=filename)
