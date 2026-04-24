"""
Single-page download service — uses core.CaptureEngine to reproduce
the exact current behavior of WebsiteDownloader.process().
"""
import os
import shutil
import time
from pathlib import Path

from core.engine import CaptureEngine
from core.clean import clean_site


class SinglePageService:
    """
    Automated headless capture of one URL.

    Public contract identical to the original WebsiteDownloader.process().
    """

    def __init__(self, url, output_dir, log_callback=None):
        self.url = url
        self.output_dir = output_dir
        self.assets_dir = os.path.join(output_dir, 'assets')
        self.log_callback = log_callback or (lambda msg: print(msg))

        # Clean and create output directories
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(self.assets_dir)

        self.engine = CaptureEngine(
            assets_dir=self.assets_dir,
            output_dir=self.output_dir,
            log_callback=self.log_callback,
            headless=True,
        )

    def log(self, message):
        self.log_callback(message)

    def process(self):
        """
        Main processing method — orchestrates the single-page download.
        Returns True on success.
        """
        start_time = time.time()

        # 1. Launch browser + network recording
        self.engine.start()

        # 2. Navigate
        self.engine.navigate(self.url)

        # 3. Stimulate + capture HTML
        html_content, is_iframe, framework_css_urls, dynamic_asset_urls = (
            self.engine.stimulate()
        )

        # 4. Close browser
        self.engine.stop()

        # 5. Save captured resources + fallbacks
        self.engine.save_captured_resources(dynamic_asset_urls)

        # 6. Post-process HTML
        html_output = self.engine.process_html(html_content)

        # 7. Save HTML
        self.engine.save_html(html_output, filename='index.html')

        # 8. Clean pipeline
        self.log("Organizando artefato final...")
        clean_site(self.output_dir, self.log_callback)

        # 9. Create serve.py
        self._create_serve_script()

        # 10. Final report
        elapsed = time.time() - start_time
        self.log(f"\nTempo total: {elapsed:.1f}s")
        self.engine.network.generate_final_report()

        return True

    def _create_serve_script(self):
        """Create root serve.py selector script in output directory."""
        serve_template = Path(__file__).parent.parent / 'core' / 'templates' / 'serve_outside.py'
        serve_script_path = os.path.join(self.output_dir, 'serve.py')
        shutil.copy(serve_template, serve_script_path)
        try:
            os.chmod(serve_script_path, 0o755)
        except Exception:
            pass
        self.log("   Seletor de servidor (serve.py) incluído no download")
