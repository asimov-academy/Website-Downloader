"""
Post-processing orchestration for HTML/DOM transformations.

File-based URL rewriting is handled by url_rewrite.URLRewriter.
"""
import os

from bs4 import BeautifulSoup

from ..url_rewrite import URLRewriter
from .baseline import PostProcessBaselineMixin
from .injectors import PostProcessInjectorsMixin
from .processors import PostProcessProcessorsMixin
from .runtime_cleanup import PostProcessRuntimeCleanupMixin
from .transformers import PostProcessTransformersMixin


class PostProcessor(
    PostProcessBaselineMixin,
    PostProcessRuntimeCleanupMixin,
    PostProcessTransformersMixin,
    PostProcessProcessorsMixin,
    PostProcessInjectorsMixin,
):
    def __init__(
        self,
        base_url,
        output_dir,
        log_callback,
        network_recorder,
        preserve_navigation_links=False,
    ):
        self.base_url = base_url
        self.output_dir = output_dir
        self.log = log_callback
        self.network = network_recorder
        self.preserve_navigation_links = preserve_navigation_links
        self.rewriter = URLRewriter(base_url, output_dir, log_callback, network_recorder)
        self._original_script_urls = None
        self._original_html_soup = None
        self._interceptor_js_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'fetch_interceptor.js',
        )

    def process_html(self, html_content):
        """Apply all HTML transformations and trigger file-based rewriting."""
        self.log("🔧 Processando HTML e assets...")
        baseline_html = self._select_document_baseline(html_content)
        soup = BeautifulSoup(baseline_html, 'html.parser')
        is_ssr_framework = self._is_ssr_framework(soup)

        self._cleanup_runtime_dom_state(soup)
        self._remove_runtime_duplicate_wrappers(soup)
        original_soup = self._get_original_html_soup()
        run_original_dom_restorers = not self._dom_pair_too_large_for_original_matching(
            soup,
            original_soup,
            'restaurações baseadas no HTML original',
            max_elements=1000,
        )
        if run_original_dom_restorers:
            if is_ssr_framework:
                if self._should_prune_runtime_nodes(soup):
                    self._prune_runtime_only_nodes(soup)
                self._restore_empty_runtime_hosts(soup)
            self._restore_missing_original_support_nodes(soup)
            self._restore_hollow_content_containers(soup)
            self._restore_original_form_controls(soup)
            self._restore_original_inline_styles(soup)
            self._restore_original_svg_transforms(soup)
            self._restore_original_style_tags(soup)
        self._remove_duplicate_enhanced_fallback_blocks(soup)
        self._remove_canvas_snapshots(soup)
        self._fix_scroll_blocking(soup)
        self._remove_wrapper_iframes(soup)
        self._process_stylesheets(soup)
        self._process_inline_styles(soup)
        self._process_scripts(soup)
        self._promote_plain_scripts(soup)
        self._sanitize_structured_data_scripts(soup)
        self._process_images(soup)
        self._process_inline_style_attrs(soup)
        self._process_favicons(soup)
        self._process_meta_images(soup)
        self._process_background_attrs(soup)
        self._fix_navigation_links(soup)
        self._handle_spa_frameworks(soup)
        self._remove_preconnects(soup)
        self._process_preloads(soup)
        self._inject_external_preload_bootstrap(soup)
        self._remove_tracking_scripts(soup)
        self._remove_tracking_widgets(soup)
        self._remove_authoring_bootstrap(soup)
        self._inject_import_map(soup)
        self._inject_shopify_bootstrap(soup)
        self._inject_fetch_interceptor(soup)
        self._inject_runtime_compat_shim(soup)
        self._remove_authoring_bootstrap(soup)

        html_output = str(soup)

        self.rewriter.rewrite_css_files()
        self.rewriter.process_json_files()
        self.rewriter.remove_sourcemaps()

        html_output = self.rewriter.rewrite_basenames_in_html(html_output)
        html_output = self.rewriter.rewrite_nextjs_images_in_html(html_output)
        html_output = self._finalize_authoring_cleanup(html_output)
        return html_output

    def save_html(self, html_output, filename='index.html'):
        """Save final HTML to disk."""
        output_path = os.path.join(self.output_dir, filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as output_file:
            output_file.write(html_output)

    def _finalize_authoring_cleanup(self, html_output):
        """Run a final authoring-bootstrap cleanup on the serialized HTML."""
        if (
            '__framer-editorbar' not in html_output
            and 'framer.com/edit' not in html_output
            and 'app.framerstatic.com/' not in html_output
        ):
            return html_output

        soup = BeautifulSoup(html_output, 'html.parser')
        self._remove_authoring_bootstrap(soup)
        return str(soup)
