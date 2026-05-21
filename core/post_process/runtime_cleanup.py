"""
Runtime DOM cleanup helpers for post-processing.
"""


class PostProcessRuntimeCleanupMixin:
    def _uses_runtime_scroll_container(self, soup):
        """Detect documents that manage scroll through dedicated runtime containers."""
        if soup.find(attrs={'data-scroll-container': True}) is not None:
            return True

        for element in soup.find_all(True):
            classes = ' '.join(self._normalized_classes(element)).lower()
            if any(marker in classes for marker in ('fullpage', 'fp-', 'smooth-scroll', 'scroll-container')):
                return True

        for script in soup.find_all('script', src=True):
            src = (script.get('src') or '').lower()
            if any(marker in src for marker in ('fullpage', 'scrolloverflow', 'locomotive', 'lenis')):
                return True

        # Detect fixed full-screen scroll containers (e.g. custom WebGL/canvas viewport scroll)
        # Pattern: position:fixed + width:100% + height:100% + overflow containing scroll
        for element in soup.find_all(True):
            style = element.get('style', '')
            if not style:
                continue
            # Normalise for comparison: remove spaces around : and ;
            style_norm = ''.join(style.lower().split())
            if (
                'position:fixed' in style_norm
                and 'width:100%' in style_norm
                and 'height:100%' in style_norm
                and 'overflow' in style_norm
                and 'scroll' in style_norm
            ):
                return True

        return False

    def _is_runtime_enhanced_block(self, element):
        """Detect blocks upgraded by common slider/carousel runtimes."""
        classes = set(self._normalized_classes(element))
        attrs = set(getattr(element, 'attrs', {}).keys())

        exact_markers = {
            'keen-slider',
            'keen-slider--ready',
            'swiper',
            'swiper-initialized',
            'splide',
            'splide--slide',
            'splide--draggable',
            'flickity-enabled',
            'glide',
            'glide__track',
            'slick-slider',
            'slick-initialized',
            'embla',
            'tns-slider',
        }
        prefix_markers = (
            'keen-',
            'swiper',
            'splide',
            'flickity',
            'glide',
            'slick',
            'embla',
            'tns-',
        )
        attr_markers = {
            'data-keen-slider',
            'data-swiper',
            'data-splide',
            'data-flickity',
            'data-glide-el',
            'data-embla',
            'data-tns-role',
        }

        if classes.intersection(exact_markers):
            return True
        if any(cls.startswith(prefix_markers) for cls in classes):
            return True
        if attrs.intersection(attr_markers):
            return True
        return False

    def _meaningful_block_classes(self, element):
        """Return semantic classes, excluding runtime enhancement markers."""
        ignored_exact = {
            'keen-slider',
            'keen-slider--ready',
            'swiper',
            'swiper-initialized',
            'splide',
            'flickity-enabled',
            'glide',
            'slick-slider',
            'slick-initialized',
            'embla',
            'tns-slider',
        }
        ignored_prefixes = (
            'keen-',
            'swiper',
            'splide',
            'flickity',
            'glide',
            'slick',
            'embla',
            'tns-',
        )
        return {
            cls for cls in self._normalized_classes(element)
            if cls not in ignored_exact and not cls.startswith(ignored_prefixes)
        }

    def _runtime_enhancement_score(self, element):
        """Score how fully initialized a runtime-upgraded block looks."""
        classes = set(self._normalized_classes(element))
        score = 0

        if self._is_runtime_enhanced_block(element):
            score += 1

        readiness_markers = {
            'keen-slider--ready',
            'swiper-initialized',
            'swiper-horizontal',
            'splide--initialized',
            'flickity-enabled',
            'slick-initialized',
            'is-initialized',
            'is-ready',
        }
        if classes.intersection(readiness_markers):
            score += 2

        return score

    def _block_text_signature(self, element, limit=240):
        """Return a normalized text signature for block-level deduplication."""
        text = ' '.join(element.stripped_strings).strip().lower()
        if not text:
            return ''
        return ' '.join(text.split())[:limit]

    def _direct_child_signature(self, element):
        """Return the direct child tag sequence for a block."""
        return tuple(child.name for child in element.children if getattr(child, 'name', None))

    def _remove_duplicate_enhanced_fallback_blocks(self, soup):
        """
        Remove duplicate adjacent blocks where a runtime-enhanced widget and its
        plain fallback coexist with the same semantic content.
        """
        removed = 0

        for parent in soup.find_all(True):
            children = [child for child in parent.children if getattr(child, 'name', None)]
            index = 0

            while index < len(children) - 1:
                current = children[index]
                following = children[index + 1]

                if current.name != following.name:
                    index += 1
                    continue

                current_enhanced = self._is_runtime_enhanced_block(current)
                following_enhanced = self._is_runtime_enhanced_block(following)
                current_score = self._runtime_enhancement_score(current)
                following_score = self._runtime_enhancement_score(following)
                if current_enhanced == following_enhanced and current_score == following_score:
                    index += 1
                    continue

                current_text = self._block_text_signature(current)
                following_text = self._block_text_signature(following)
                if not current_text or current_text != following_text:
                    index += 1
                    continue

                current_classes = self._meaningful_block_classes(current)
                following_classes = self._meaningful_block_classes(following)
                if current_classes and following_classes and not (current_classes & following_classes):
                    index += 1
                    continue

                if self._direct_child_signature(current) != self._direct_child_signature(following):
                    index += 1
                    continue

                if current_score != following_score:
                    removable = following if current_score > following_score else current
                else:
                    removable = following if current_enhanced else current
                removable.decompose()
                removed += 1
                children = [child for child in parent.children if getattr(child, 'name', None)]
                continue

        if removed:
            self.log(f"   Removidos {removed} blocos fallback duplicados ao lado de widgets aprimorados")

    def _is_meaningless_empty_section(self, section):
        """Detect top-level sections that are empty wrappers with inherited spacing."""
        if section is None or section.name != 'section':
            return False

        if any(section.stripped_strings):
            return False

        if any(attr.startswith('data-') for attr in getattr(section, 'attrs', {})):
            return False

        if section.find(['img', 'picture', 'video', 'iframe', 'canvas', 'svg', 'form', 'input', 'select', 'textarea', 'button', 'a', 'script', 'style', 'template', 'noscript']):
            return False

        descendants = [child for child in section.find_all(True)]
        if len(descendants) > 4:
            return False

        for descendant in descendants:
            if descendant.name not in {'div', 'span'}:
                return False
            if any(attr.startswith('data-') for attr in getattr(descendant, 'attrs', {})):
                return False
            if descendant.get('id'):
                return False

        return True

    def _remove_canvas_snapshots(self, soup):
        """Remove Playwright-captured canvas elements.

        Detects rendered WebGL canvases by two signals:
        1. Has explicit width + height HTML attributes AND data-engine (Three.js standard)
        2. Has explicit width + height HTML attributes AND pointer-events:none in inline
           style (custom WebGL renderers that don't set data-engine, e.g. Active Theory)
        """
        removed = 0
        for canvas in soup.find_all('canvas'):
            if not (canvas.has_attr('width') and canvas.has_attr('height')):
                continue
            has_data_engine = canvas.has_attr('data-engine')
            style = ''.join((canvas.get('style') or '').lower().split())
            has_pointer_events_none = 'pointer-events:none' in style
            if has_data_engine or has_pointer_events_none:
                self.log(f"   Removendo canvas renderizado: {canvas.get('width')}x{canvas.get('height')}")
                canvas.decompose()
                removed += 1
        if removed:
            self.log(f"   Removidos {removed} canvas renderizados (Playwright snapshots)")

    def _cleanup_runtime_dom_state(self, soup):
        """
        Remove transient runtime flags/styles saved by page.content().

        These markers are useful while the live page is running, but persisting
        them into the offline HTML can block re-initialization on the next load.
        """
        initialized_attrs_removed = 0
        animation_play_state_removed = 0
        transform_style_resets = 0
        playwright_attrs_removed = 0
        scroll_reveal_attrs_removed = 0
        scroll_reveal_style_resets = 0
        runtime_state_classes_removed = 0
        runtime_state_attrs_removed = 0

        transient_style_props = {'translate', 'rotate', 'scale', 'transform-origin'}
        scroll_reveal_style_props = {
            'visibility',
            'opacity',
            'transform',
            'transform-origin',
            'transition',
            'will-change',
        }
        transient_class_markers = {
            'klaviyo',
            'needsclick',
            'kl-private-reset-css',
            'cookiebot',
            'cybotcookiebotdialog',
            'web-pixels',
            'web-pixel',
            'shopify-privacy',
        }
        original_soup = self._get_original_html_soup()
        path_lookup = {}
        signature_lookup = {}
        if original_soup:
            path_lookup, signature_lookup = self._build_original_element_lookups(original_soup)

        for element in soup.find_all(True):
            if not isinstance(getattr(element, 'attrs', None), dict):
                continue

            had_scroll_reveal_state = element.has_attr('data-sr-id')
            for attr in list(element.attrs.keys()):
                if attr.endswith('-initialized'):
                    del element[attr]
                    initialized_attrs_removed += 1
                    continue
                if attr == 'data-sr-id':
                    del element[attr]
                    scroll_reveal_attrs_removed += 1
                    continue
                if attr.startswith('data-playwright'):
                    del element[attr]
                    playwright_attrs_removed += 1

            classes = element.get('class', [])
            if isinstance(classes, str):
                classes = classes.split()
            if classes:
                filtered_classes = [
                    cls for cls in classes
                    if not any(marker in cls.lower() for marker in transient_class_markers)
                ]
                if filtered_classes != classes:
                    element['class'] = filtered_classes
                    classes = filtered_classes

            original_elem = None
            if path_lookup or signature_lookup:
                original_elem = self._match_original_element(element, path_lookup, signature_lookup)

            if classes and original_elem is not None:
                original_classes = set(self._normalized_classes(original_elem))
                has_fullpage_runtime = any(
                    cls.startswith('fp-') and cls not in original_classes
                    for cls in classes
                )
                if has_fullpage_runtime:
                    filtered_classes = [
                        cls for cls in classes
                        if (
                            not cls.startswith('fp-') or cls in original_classes
                        ) and not (
                            cls in {'active', 'fp-completely'} and cls not in original_classes
                        )
                    ]
                    runtime_state_classes_removed += len(classes) - len(filtered_classes)
                    if filtered_classes:
                        element['class'] = filtered_classes
                    else:
                        element.attrs.pop('class', None)
                    classes = filtered_classes

                    if element.has_attr('data-fp-styles') and not original_elem.has_attr('data-fp-styles'):
                        del element['data-fp-styles']
                        runtime_state_attrs_removed += 1

            style = element.get('style')
            if not style:
                continue

            declarations = []
            for raw_decl in style.split(';'):
                if ':' not in raw_decl:
                    continue
                key, value = raw_decl.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                if not key:
                    continue
                declarations.append((key, value))

            if not declarations:
                continue

            kept = [(key, value) for key, value in declarations if key != 'animation-play-state']
            if len(kept) != len(declarations):
                animation_play_state_removed += 1

            if had_scroll_reveal_state:
                reveal_filtered = [
                    (key, value) for key, value in kept
                    if key not in scroll_reveal_style_props
                ]
                if len(reveal_filtered) != len(kept):
                    scroll_reveal_style_resets += 1
                kept = reveal_filtered

            if kept and all(key in transient_style_props for key, _ in kept):
                element.attrs.pop('style', None)
                transform_style_resets += 1
                continue

            if kept:
                element['style'] = '; '.join(f"{key}: {value}" for key, value in kept) + ';'
            else:
                element.attrs.pop('style', None)

        if initialized_attrs_removed:
            self.log(f"   Removidos {initialized_attrs_removed} flags de inicialização em runtime")
        if playwright_attrs_removed:
            self.log(f"   Removidos {playwright_attrs_removed} atributos temporários do Playwright")
        if animation_play_state_removed:
            self.log(f"   Limpos {animation_play_state_removed} estados transitórios de animation-play-state")
        if scroll_reveal_attrs_removed:
            self.log(f"   Removidos {scroll_reveal_attrs_removed} ids transitórios de ScrollReveal")
        if scroll_reveal_style_resets:
            self.log(f"   Limpos {scroll_reveal_style_resets} estilos transitórios de ScrollReveal")
        if transform_style_resets:
            self.log(f"   Limpos {transform_style_resets} estilos transitórios de transform do runtime")
        if runtime_state_classes_removed:
            self.log(f"   Removidas {runtime_state_classes_removed} classes transitórias de runtimes de layout")
        if runtime_state_attrs_removed:
            self.log(f"   Removidos {runtime_state_attrs_removed} atributos transitórios de runtimes de layout")

    def _remove_runtime_duplicate_wrappers(self, soup, min_descendants=8, min_matches=6):
        """
        Remove top-level runtime wrappers that duplicate content already present in the original HTML.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup or not self._body_has_meaningful_ssr_content(original_soup):
            return

        current_body = soup.find('body')
        original_body = original_soup.find('body')
        if not current_body or not original_body:
            return

        current_count = len(current_body.find_all(True))
        original_count = len(original_body.find_all(True))
        if current_count <= int(original_count * 1.15):
            return

        path_lookup, signature_lookup = self._build_original_element_lookups(original_soup)
        removed = 0

        for child in list(current_body.find_all(True)):
            if not getattr(child, 'name', None):
                continue
            if child.name in {'script', 'style', 'noscript'}:
                continue
            parent = child.parent if getattr(child.parent, 'name', None) else None
            if parent is None:
                continue
            if self._match_original_element(parent, path_lookup, signature_lookup) is None:
                continue
            if self._match_original_element(child, path_lookup, signature_lookup):
                continue

            descendants = child.find_all(True)
            if len(descendants) < min_descendants:
                continue

            matched_descendants = 0
            for descendant in descendants:
                signature = self._element_identity_signature(descendant)
                if not signature:
                    continue
                if signature_lookup.get(signature):
                    matched_descendants += 1
                    if matched_descendants >= min_matches:
                        break

            text_length = len(' '.join(child.stripped_strings))
            media_count = len(child.find_all(['img', 'video', 'canvas', 'svg']))
            looks_like_visual_runtime_layer = (
                len(descendants) >= 40 and
                text_length <= 120 and
                media_count >= 6
            )

            if matched_descendants < min_matches and not looks_like_visual_runtime_layer:
                continue

            child.decompose()
            removed += 1

        if removed:
            self.log(f"   Removidos {removed} wrappers top-level gerados em runtime")

    def _fix_scroll_blocking(self, soup):
        """Remove scroll-blocking classes/attrs and inject minimal scroll-fix CSS."""
        self.log("🔧 Corrigindo problemas de scroll para visualização offline...")

        html_elem = soup.find('html')
        if html_elem:
            classes = html_elem.get('class', [])
            if isinstance(classes, str):
                classes = classes.split()
            blocking = {'overflow-hidden', 'no-scroll', 'scroll-lock', 'fixed', 'modal-open'}
            new_cls = [cls for cls in classes if cls.lower() not in blocking]
            if new_cls != classes:
                html_elem['class'] = new_cls

        body = soup.find('body')
        if body:
            classes = body.get('class', [])
            if isinstance(classes, str):
                classes = classes.split()
            blocking = {'overflow-hidden', 'no-scroll', 'scroll-lock', 'fixed', 'modal-open'}
            new_cls = [cls for cls in classes if cls.lower() not in blocking]
            if 'items-center' in new_cls and 'flex' in new_cls:
                new_cls = ['items-start' if cls == 'items-center' else cls for cls in new_cls]
                self.log("   Corrigida centralização vertical do body")
            if new_cls != classes:
                body['class'] = new_cls

        uses_runtime_scroll = self._uses_runtime_scroll_container(soup)
        scroll_fix_css = """
        /* Scroll fixes - MINIMAL SCOPE */
        .loader, .preloader, .loading, [class*="loader"], [class*="preloader"] {
            display: none !important;
            opacity: 0 !important;
        }
        /* Hide native scrollbars on JS-managed scroll containers.
           Fixed-position overflow containers use JS for scroll logic;
           the visual scrollbar is unwanted and may appear incorrectly offline. */
        [style*="overflow"][style*="scroll"]::-webkit-scrollbar {
            display: none !important;
        }
        [style*="overflow"][style*="scroll"] {
            scrollbar-width: none !important;
            -ms-overflow-style: none !important;
        }
        """
        if not uses_runtime_scroll:
            scroll_fix_css = """
            /* Scroll fixes - MINIMAL SCOPE */
            html, body {
                overflow: auto !important;
                overflow-x: hidden !important;
                height: auto !important;
                min-height: 100% !important;
                scroll-behavior: auto !important;
            }
            .loader, .preloader, .loading, [class*="loader"], [class*="preloader"] {
                display: none !important;
                opacity: 0 !important;
            }
            """

        head = soup.find('head')
        if head:
            fix_style = soup.new_tag('style')
            fix_style['data-scroll-fix'] = 'true'
            fix_style.string = scroll_fix_css
            head.append(fix_style)
            if uses_runtime_scroll:
                self.log("   CSS de scroll reduzido para preservar runtime de container dedicado")
            else:
                self.log("   Injetado CSS para corrigir scroll")
