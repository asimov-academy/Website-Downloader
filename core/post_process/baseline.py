"""
Baseline selection helpers for post-processing.
"""
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class PostProcessBaselineMixin:
    def _body_has_meaningful_ssr_content(self, soup):
        """Heuristic to detect whether the original HTML already contains useful body markup."""
        body = soup.find('body')
        if not body:
            return False

        element_children = [child for child in body.children if getattr(child, 'name', None)]
        if len(element_children) >= 3:
            return True

        text_content = ' '.join(body.stripped_strings)
        return len(text_content) >= 200

    def _runtime_dom_mutation_stats(self, html_content, soup):
        """Measure how far a captured DOM drifted from the original response."""
        element_count = 0
        inline_style_count = 0
        animated_style_count = 0
        aria_hidden_count = 0
        split_wrapper_count = 0

        animated_style_markers = (
            'transform:',
            'translate:',
            'rotate:',
            'scale:',
            'clip-path:',
            'transform-origin:',
        )

        for element in soup.find_all(True):
            element_count += 1

            if element.get('aria-hidden') == 'true':
                aria_hidden_count += 1

            classes = self._normalized_classes(element)
            if any(cls in {'split-parent', 'split-child', 'secondline'} for cls in classes):
                split_wrapper_count += 1

            style = (element.get('style') or '').lower()
            if not style:
                continue

            inline_style_count += 1
            if any(marker in style for marker in animated_style_markers):
                animated_style_count += 1

        string_marker_count = sum(
            html_content.count(marker)
            for marker in (
                'split-parent',
                'split-child',
                'aria-hidden="true"',
                'transform: translate',
                'clip-path: inset',
            )
        )

        return {
            'elements': element_count,
            'inline_styles': inline_style_count,
            'animated_styles': animated_style_count,
            'aria_hidden': aria_hidden_count,
            'split_wrappers': split_wrapper_count,
            'string_markers': string_marker_count,
        }

    def _content_richness_stats(self, soup):
        """Estimate whether the DOM still preserves meaningful section content."""
        section_like_total = 0
        section_like_nonempty = 0
        media_count = 0

        for element in soup.find_all(True):
            if element.name in {'img', 'picture', 'video', 'canvas', 'svg'}:
                media_count += 1

            is_section_like = any([
                element.name in {'article', 'section'},
                element.get('role') == 'article',
                element.has_attr('data-anchor'),
            ])
            if not is_section_like:
                continue

            section_like_total += 1
            text_length = len(' '.join(element.stripped_strings))
            has_media = element.find(['img', 'picture', 'video', 'canvas', 'svg']) is not None
            if text_length >= 80 or has_media:
                section_like_nonempty += 1

        return {
            'section_like_total': section_like_total,
            'section_like_nonempty': section_like_nonempty,
            'media': media_count,
        }

    def _should_prefer_original_runtime_baseline(self, current_html, current_soup, original_html, original_soup):
        """
        Prefer the original response when page.content() clearly captured a
        highly mutated animation/runtime state instead of the page baseline.
        """
        current_stats = self._runtime_dom_mutation_stats(current_html, current_soup)
        original_stats = self._runtime_dom_mutation_stats(original_html, original_soup)
        current_content_stats = self._content_richness_stats(current_soup)
        original_content_stats = self._content_richness_stats(original_soup)

        if (
            current_stats['split_wrappers'] >= original_stats['split_wrappers'] + 8
            and current_stats['animated_styles'] >= original_stats['animated_styles'] + 8
        ):
            return True

        if (
            current_stats['elements'] >= int(original_stats['elements'] * 1.2)
            and current_stats['inline_styles'] >= original_stats['inline_styles'] + 25
            and current_stats['animated_styles'] >= original_stats['animated_styles'] + 10
        ):
            return True

        if (
            current_stats['string_markers'] >= original_stats['string_markers'] + 20
            and current_stats['aria_hidden'] >= original_stats['aria_hidden'] + 20
        ):
            return True

        if (
            original_content_stats['section_like_nonempty'] >= 4
            and current_content_stats['section_like_total'] >= max(4, original_content_stats['section_like_total'] - 1)
            and current_content_stats['section_like_nonempty'] <= max(
                1,
                int(original_content_stats['section_like_nonempty'] * 0.5),
            )
            and (
                original_content_stats['section_like_nonempty'] - current_content_stats['section_like_nonempty']
            ) >= 3
        ):
            return True

        if (
            original_content_stats['media'] >= 8
            and current_content_stats['media'] <= int(original_content_stats['media'] * 0.6)
            and (original_content_stats['media'] - current_content_stats['media']) >= 6
        ):
            return True

        return False

    def _select_document_baseline(self, html_content):
        """
        Choose the safest HTML baseline for post-processing.

        For SSR frameworks, page.content() can capture a heavily mutated runtime
        DOM that no longer matches the server response expected by hydration.
        In those cases prefer the original HTML captured from the network.
        """
        original_html = self.network.get_document_html(self.base_url)
        if not original_html or original_html == html_content:
            return html_content

        original_soup = BeautifulSoup(original_html, 'html.parser')
        self._original_html_soup = original_soup
        is_ssr_framework = any([
            original_soup.find(id='__next') is not None,
            original_soup.find(id='__nuxt') is not None,
            original_soup.find(id='___gatsby') is not None,
            'self.__next_f.push' in original_html,
            '__NEXT_DATA__' in original_html,
        ])

        if not self._body_has_meaningful_ssr_content(original_soup):
            return html_content

        if is_ssr_framework:
            self.log("   Usando HTML original da resposta como baseline do documento")
            return original_html

        current_soup = BeautifulSoup(html_content, 'html.parser')
        if self._should_prefer_original_runtime_baseline(
            html_content,
            current_soup,
            original_html,
            original_soup,
        ):
            self.log("   Usando HTML original da resposta para evitar estado de runtime persistido")
            return original_html

        return html_content

    def _get_original_script_urls(self):
        """Return the external script URLs present in the original HTML response."""
        original_soup = self._get_original_html_soup()
        if not original_soup:
            self._original_script_urls = None
            return None

        if self._original_script_urls is not None:
            return self._original_script_urls

        self._original_script_urls = {
            urljoin(self.base_url, script.get('src'))
            for script in original_soup.find_all('script', src=True)
            if script.get('src')
        }
        return self._original_script_urls

    def _get_original_html_soup(self):
        """Return the original HTML response parsed as BeautifulSoup."""
        if self._original_html_soup is not None:
            return self._original_html_soup

        original_html = self.network.get_document_html(self.base_url)
        if not original_html:
            return None

        self._original_html_soup = BeautifulSoup(original_html, 'html.parser')
        return self._original_html_soup
