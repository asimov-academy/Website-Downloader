"""
DOM transformation helpers for post-processing.
"""
from bs4 import BeautifulSoup, NavigableString


class PostProcessTransformersMixin:
    def _restore_empty_runtime_hosts(self, soup):
        """
        Reset server-empty runtime hosts back to their original empty state.

        Scene mounts and canvas containers often start empty in the server HTML
        and are populated only after client boot. Persisting those runtime
        children offline can freeze scene re-initialization on the next load.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup:
            return

        path_lookup, signature_lookup = self._build_original_element_lookups(original_soup)

        cleared = 0

        for current_elem in list(soup.find_all(True)):
            if current_elem.parent is None:
                continue
            if not isinstance(getattr(current_elem, 'attrs', None), dict):
                continue

            original_elem = self._match_original_element(current_elem, path_lookup, signature_lookup)
            if not original_elem:
                continue

            original_children = [child for child in original_elem.children if getattr(child, 'name', None)]
            if original_children:
                continue

            current_children = [child for child in current_elem.children if getattr(child, 'name', None)]
            if not current_children:
                continue

            removable_children = []
            for child in current_children:
                if child.name == 'canvas':
                    removable_children.append(child)
                    continue
                if child.has_attr('data-scene-id') or child.find('canvas'):
                    removable_children.append(child)

            if len(removable_children) != len(current_children):
                continue

            for child in list(current_children):
                child.decompose()
                cleared += 1

        if cleared:
            self.log(f"   Restaurados {cleared} hosts vazios do HTML original para reinicialização em runtime")

    def _is_support_source_node(self, element):
        """Heuristic for original HTML nodes that act as data sources for client boot."""
        if element is None or not isinstance(getattr(element, 'attrs', None), dict):
            return False

        if element.name in {'script', 'style', 'link', 'meta', 'noscript'}:
            return False

        classes = set(self._normalized_classes(element))
        if classes.intersection({'w-dyn-list', 'w-dyn-item'}):
            return True

        descendant_count = len(element.find_all(True))
        text_length = len(' '.join(element.stripped_strings))
        support_markers = {
            'button',
            'list',
            'filter',
            'menu',
            'control',
            'instruction',
            'wrapper',
            'source',
            'template',
        }
        element_id = str(element.get('id') or '').lower()
        if element_id and descendant_count <= 25 and text_length <= 160:
            if any(marker in element_id for marker in support_markers):
                return True

        if classes and descendant_count <= 25 and text_length <= 160:
            if any(any(marker in cls.lower() for marker in support_markers) for cls in classes):
                return True

        for attr in element.attrs:
            if attr.startswith('data-'):
                return True

        if element.find(attrs=lambda attrs: attrs and any(key.startswith('data-') for key in attrs)):
            return True

        if element.find(class_='w-dyn-item') or element.find(class_='w-dyn-list'):
            return True

        return False

    def _find_restore_subtree_root(self, original_elem, current_body, path_lookup, signature_lookup):
        """Return the highest missing ancestor whose parent still matches the current DOM."""
        subtree_root = original_elem
        cursor = original_elem

        while True:
            parent = cursor.parent if getattr(cursor.parent, 'name', None) else None
            if parent is None or parent.name in {'body', 'html'}:
                return subtree_root, current_body

            matched_parent = self._match_original_element(parent, path_lookup, signature_lookup)
            if matched_parent is not None:
                return subtree_root, matched_parent

            subtree_root = parent
            cursor = parent

    def _insert_restored_subtree(self, target_parent, original_root, clone, path_lookup, signature_lookup):
        """Insert a restored subtree near its original sibling position."""
        original_parent = original_root.parent if getattr(original_root.parent, 'name', None) else None
        if original_parent is None:
            target_parent.append(clone)
            return

        siblings = [child for child in original_parent.children if getattr(child, 'name', None)]
        try:
            index = siblings.index(original_root)
        except ValueError:
            target_parent.append(clone)
            return

        for sibling in reversed(siblings[:index]):
            matched_sibling = self._match_original_element(sibling, path_lookup, signature_lookup)
            if matched_sibling is not None and matched_sibling.parent is target_parent:
                matched_sibling.insert_after(clone)
                return

        for sibling in siblings[index + 1:]:
            matched_sibling = self._match_original_element(sibling, path_lookup, signature_lookup)
            if matched_sibling is not None and matched_sibling.parent is target_parent:
                matched_sibling.insert_before(clone)
                return

        target_parent.append(clone)

    def _restore_missing_original_support_nodes(self, soup):
        """
        Restore original source nodes that page.content() may lose after client boot.

        Some sites consume hidden CMS lists/templates during startup and remove them
        from the live DOM. Persisting only the mutated runtime DOM makes the next
        offline boot fail because the source nodes are no longer present.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup:
            return

        current_body = soup.find('body')
        original_body = original_soup.find('body')
        if not current_body or not original_body:
            return

        _, original_signature_lookup = self._build_original_element_lookups(original_soup)
        restored = 0
        attempted_roots = set()

        while True:
            current_path_lookup, current_signature_lookup = self._build_original_element_lookups(soup)
            changed = False

            for original_elem in original_body.find_all(True):
                signature = self._element_identity_signature(original_elem)
                if not signature:
                    continue
                if signature[0] == 'class' and len(original_signature_lookup.get(signature, [])) != 1:
                    continue
                if self._match_original_element(original_elem, current_path_lookup, current_signature_lookup):
                    continue
                if not self._is_support_source_node(original_elem):
                    continue

                subtree_root, target_parent = self._find_restore_subtree_root(
                    original_elem,
                    current_body,
                    current_path_lookup,
                    current_signature_lookup,
                )
                subtree_root_path = self._element_dom_path(subtree_root)
                if subtree_root_path in attempted_roots:
                    continue
                if self._match_original_element(subtree_root, current_path_lookup, current_signature_lookup):
                    continue

                clone_soup = BeautifulSoup(str(subtree_root), 'html.parser')
                clone = clone_soup.find(True)
                if clone is None:
                    continue

                attempted_roots.add(subtree_root_path)
                self._insert_restored_subtree(
                    target_parent,
                    subtree_root,
                    clone,
                    current_path_lookup,
                    current_signature_lookup,
                )
                restored += 1
                changed = True
                break

            if not changed:
                break

        if restored:
            self.log(f"   Restaurados {restored} nós-fonte do HTML original consumidos pelo runtime")

    def _is_content_rich_container(self, element, min_text=80, min_descendants=4):
        """Detect original containers whose children carry meaningful page content."""
        if element is None or not isinstance(getattr(element, 'attrs', None), dict):
            return False

        if not any([
            element.name in {'article', 'section', 'main'},
            element.get('role') == 'article',
            element.has_attr('data-anchor'),
            (
                element.name == 'div'
                and (
                    element.get('id')
                    or self._normalized_classes(element)
                )
            ),
        ]):
            return False

        descendant_count = len(element.find_all(True))
        text_length = len(' '.join(element.stripped_strings))
        has_media = element.find(['img', 'picture', 'video', 'canvas', 'svg']) is not None
        if element.name == 'div' and descendant_count < max(min_descendants, 6):
            return False
        return descendant_count >= min_descendants and (text_length >= min_text or has_media)

    def _is_hollow_runtime_container(self, element, max_text=40, max_children=1):
        """Detect containers that kept their shell but lost their actual content."""
        if element is None or not isinstance(getattr(element, 'attrs', None), dict):
            return False

        child_elements = [child for child in element.children if getattr(child, 'name', None)]
        if len(child_elements) > max_children:
            return False

        text_length = len(' '.join(element.stripped_strings))
        has_media = element.find(['img', 'picture', 'video', 'canvas', 'svg']) is not None
        return text_length <= max_text and not has_media

    def _restore_hollow_content_containers(self, soup):
        """
        Restore original section/article contents when the captured DOM kept only empty shells.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup:
            return

        path_lookup, signature_lookup = self._build_original_element_lookups(original_soup)
        restored = 0

        for current_elem in soup.find_all(True):
            if not self._is_hollow_runtime_container(current_elem):
                continue

            original_elem = self._match_original_element(current_elem, path_lookup, signature_lookup)
            if not original_elem or not self._is_content_rich_container(original_elem):
                continue

            original_children = [child for child in original_elem.children if getattr(child, 'name', None)]
            if not original_children:
                continue

            current_elem.clear()
            for child in original_children:
                clone_soup = BeautifulSoup(str(child), 'html.parser')
                clone = clone_soup.find(True)
                if clone is not None:
                    current_elem.append(clone)

            restored += 1

        if restored:
            self.log(f"   Restaurados {restored} contêineres ricos esvaziados pelo runtime")

    def _looks_runtime_enhanced_form_control(self, original_elem, current_elem):
        """Detect form controls replaced by client-side UI wrappers in the live DOM."""
        if original_elem is None or current_elem is None:
            return False

        if original_elem.name not in {'select', 'input', 'textarea'}:
            return False

        if current_elem.name != original_elem.name:
            return False

        original_hidden = original_elem.has_attr('hidden') or original_elem.get('type') == 'hidden'
        current_hidden = current_elem.has_attr('hidden') or current_elem.get('type') == 'hidden'
        if current_hidden and not original_hidden:
            return True

        if current_elem.has_attr('data-choice') and not original_elem.has_attr('data-choice'):
            return True

        if current_elem.get('tabindex') == '-1' and original_elem.get('tabindex') != '-1':
            return True

        for ancestor in current_elem.parents:
            if not getattr(ancestor, 'name', None) or ancestor.name in {'form', 'body', 'html'}:
                break

            role = str(ancestor.get('role') or '').lower()
            classes = set(self._normalized_classes(ancestor))
            if role in {'listbox', 'combobox'}:
                return True
            if ancestor.get('aria-expanded') is not None and current_hidden:
                return True
            if 'choices' in classes or any(cls.startswith('choices__') for cls in classes):
                return True

        return False

    def _find_runtime_form_wrapper(self, current_elem):
        """Pick the outermost transient wrapper around a runtime-enhanced form control."""
        target = current_elem
        for ancestor in current_elem.parents:
            if not getattr(ancestor, 'name', None) or ancestor.name in {'form', 'body', 'html'}:
                break

            role = str(ancestor.get('role') or '').lower()
            classes = set(self._normalized_classes(ancestor))
            if role in {'listbox', 'combobox'}:
                target = ancestor
                continue
            if ancestor.get('aria-expanded') is not None and current_elem.has_attr('hidden'):
                target = ancestor
                continue
            if 'choices' in classes or any(cls.startswith('choices__') for cls in classes):
                target = ancestor

        return target

    def _match_current_form_control(self, original_elem, current_body, path_lookup, signature_lookup):
        """Match original form controls even when runtime enhancers change classes/parents."""
        matched = self._match_original_element(original_elem, path_lookup, signature_lookup)
        if matched is not None:
            return matched

        stable_data_attrs = {
            attr for attr in original_elem.attrs
            if attr.startswith('data-') and attr not in {'data-choice', 'data-item', 'data-id', 'data-value'}
        }
        if stable_data_attrs:
            candidates = []
            for candidate in current_body.find_all(original_elem.name):
                candidate_data_attrs = {
                    attr for attr in candidate.attrs
                    if attr.startswith('data-') and attr not in {'data-choice', 'data-item', 'data-id', 'data-value'}
                }
                if stable_data_attrs.issubset(candidate_data_attrs):
                    candidates.append(candidate)
            if len(candidates) == 1:
                return candidates[0]

        if original_elem.name == 'select':
            original_options = [
                (option.get('value', ''), option.get_text(' ', strip=True))
                for option in original_elem.find_all('option')
            ]
            candidates = []
            for candidate in current_body.find_all('select'):
                candidate_options = [
                    (option.get('value', ''), option.get_text(' ', strip=True))
                    for option in candidate.find_all('option')
                ]
                if candidate_options == original_options:
                    candidates.append(candidate)
            if len(candidates) == 1:
                return candidates[0]

        return None

    def _restore_original_form_controls(self, soup):
        """
        Restore original form controls when runtime UI libraries replace them in-place.

        Libraries that enhance <select>/<input> often hide the original control and
        inject interactive wrappers. Persisting that mutated DOM causes duplicate
        initialization offline because the library boots again on top of an already
        enhanced control.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup:
            return

        original_body = original_soup.find('body')
        current_body = soup.find('body')
        if not original_body or not current_body:
            return

        restored = 0
        while True:
            current_path_lookup, current_signature_lookup = self._build_original_element_lookups(soup)
            changed = False

            for original_elem in original_body.find_all(['select', 'input', 'textarea']):
                current_elem = self._match_current_form_control(
                    original_elem,
                    current_body,
                    current_path_lookup,
                    current_signature_lookup,
                )
                if current_elem is None:
                    continue
                if not self._looks_runtime_enhanced_form_control(original_elem, current_elem):
                    continue

                clone_soup = BeautifulSoup(str(original_elem), 'html.parser')
                clone = clone_soup.find(original_elem.name)
                if clone is None:
                    continue

                replacement_target = self._find_runtime_form_wrapper(current_elem)
                replacement_target.replace_with(clone)
                restored += 1
                changed = True
                break

            if not changed:
                break

        if restored:
            self.log(f"   Restaurados {restored} controles de formulário ao estado original")

    def _normalized_classes(self, element):
        """Return a normalized list of CSS classes for element matching."""
        if element is None or not isinstance(getattr(element, 'attrs', None), dict):
            return []
        classes = element.get('class', [])
        if isinstance(classes, str):
            classes = classes.split()
        return [cls for cls in classes if cls]

    def _elements_equivalent(self, current_elem, original_elem):
        """Heuristic element matcher that tolerates extra runtime siblings."""
        if current_elem.name != original_elem.name:
            return False

        current_id = current_elem.get('id')
        original_id = original_elem.get('id')
        if current_id or original_id:
            return current_id == original_id

        current_classes = tuple(self._normalized_classes(current_elem))
        original_classes = tuple(self._normalized_classes(original_elem))
        if current_classes or original_classes:
            return current_classes == original_classes

        for attr in ('role', 'aria-label', 'name', 'type'):
            current_value = current_elem.get(attr)
            original_value = original_elem.get(attr)
            if current_value or original_value:
                return current_value == original_value

        return True

    def _is_probable_runtime_only_node(self, element):
        """Heuristic for nodes injected by client runtime after the server HTML."""
        for attr in element.attrs:
            if attr.startswith('data-playwright'):
                return True
            if attr in {
                'data-scene-id',
                'data-lenis-prevent',
                'data-lenis-prevent-touch',
                'data-lenis-prevent-wheel',
            }:
                return True

        classes = set(self._normalized_classes(element))
        if classes.intersection({'word', 'char', 'line'}):
            return True

        marker_values = []
        for attr_value in element.attrs.values():
            if isinstance(attr_value, list):
                marker_values.extend(str(item).lower() for item in attr_value)
            else:
                marker_values.append(str(attr_value).lower())

        vendor_markers = {
            'klaviyo',
            'kl-private-reset-css',
            'cookiebot',
            'cybotcookiebotdialog',
            'web-pixels',
            'web-pixel',
            'shopify-privacy',
            'hotjar',
            'intercom',
            'drift',
            'crisp',
            'zendesk',
            'tawk',
            'livechat',
            'freshchat',
        }
        if any(marker in value for value in marker_values for marker in vendor_markers):
            return True

        return False

    def _prune_runtime_only_nodes(self, soup):
        """
        Remove DOM nodes added only after client boot.

        page.content() captures the hydrated DOM, which may include overlays,
        split-text wrappers, cookie banners and modal trees that were not part
        of the server HTML. Keeping those nodes can freeze client runtimes on
        the offline replay because the app hydrates against an already-mutated
        structure instead of the original baseline.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup:
            return

        current_body = soup.find('body')
        original_body = original_soup.find('body')
        if not current_body or not original_body:
            return

        removed = self._prune_runtime_only_descendants(current_body, original_body)
        if removed:
            self.log(f"   Removidos {removed} nós gerados apenas em runtime")

    def _should_prune_runtime_nodes(self, soup, max_elements=1800):
        """
        Skip recursive runtime-node pruning on very large SSR DOMs.

        The recursive matcher is useful on moderate trees, but on heavily
        hydrated documents it can dominate post-processing time. In those
        cases we keep the cheaper SSR restorations (empty hosts, inline styles,
        style tags) and let targeted tracking/widget removal handle overlays.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup:
            return False

        current_body = soup.find('body')
        original_body = original_soup.find('body')
        if not current_body or not original_body:
            return False

        current_count = len(current_body.find_all(True))
        original_count = len(original_body.find_all(True))
        if max(current_count, original_count) > max_elements:
            self.log(
                f"   Pulando poda recursiva de nós runtime-only em DOM grande "
                f"({current_count}/{original_count} elementos)"
            )
            return False

        return True

    def _prune_runtime_only_descendants(self, current_parent, original_parent):
        """Recursively remove extra runtime-only children while preserving originals."""
        removed = 0

        current_children = [child for child in current_parent.children if getattr(child, 'name', None)]
        original_children = [child for child in original_parent.children if getattr(child, 'name', None)]

        current_index = 0
        original_index = 0

        while current_index < len(current_children):
            current_child = current_children[current_index]
            original_child = original_children[original_index] if original_index < len(original_children) else None

            if original_child and self._elements_equivalent(current_child, original_child):
                removed += self._prune_runtime_only_descendants(current_child, original_child)
                current_index += 1
                original_index += 1
                continue

            if self._is_probable_runtime_only_node(current_child):
                current_child.decompose()
                removed += 1
                current_children = [child for child in current_parent.children if getattr(child, 'name', None)]
                continue

            match_index = None
            if original_child is not None:
                for probe_index in range(current_index + 1, min(current_index + 5, len(current_children))):
                    if self._elements_equivalent(current_children[probe_index], original_child):
                        match_index = probe_index
                        break

            if match_index is not None:
                extra_children = current_children[current_index:match_index]
                for extra_child in extra_children:
                    if extra_child.parent and self._is_probable_runtime_only_node(extra_child):
                        extra_child.decompose()
                        removed += 1
                current_children = [child for child in current_parent.children if getattr(child, 'name', None)]
                continue

            if original_child is not None and current_child.name == original_child.name:
                removed += self._prune_runtime_only_descendants(current_child, original_child)
                current_index += 1
                original_index += 1
                continue

            current_index += 1

        return removed

    def _element_dom_path(self, element):
        """Build a stable nth-of-type DOM path for matching original/current nodes."""
        parts = []
        current = element

        while current and getattr(current, 'name', None):
            parent = getattr(current, 'parent', None)
            index = 1

            if parent and getattr(parent, 'children', None):
                for sibling in parent.children:
                    if getattr(sibling, 'name', None) != current.name:
                        continue
                    if sibling is current:
                        break
                    index += 1

            parts.append(f"{current.name}:{index}")
            current = parent if getattr(parent, 'name', None) else None

        return tuple(reversed(parts))

    def _element_identity_signature(self, element):
        """Return a stable identity signature for fallback original/current matching."""
        if element is None or not isinstance(getattr(element, 'attrs', None), dict):
            return None

        element_id = element.get('id')
        if element_id:
            return ('id', element.name, element_id)

        classes = tuple(self._normalized_classes(element))
        if classes:
            return ('class', element.name, classes)

        name_attr = element.get('name')
        if name_attr:
            return ('name', element.name, name_attr)

        return None

    def _build_original_element_lookups(self, original_soup):
        """Build path and signature lookups for the original HTML."""
        path_lookup = {}
        signature_lookup = {}

        for original_elem in original_soup.find_all(True):
            path_lookup[self._element_dom_path(original_elem)] = original_elem
            signature = self._element_identity_signature(original_elem)
            if signature:
                signature_lookup.setdefault(signature, []).append(original_elem)

        return path_lookup, signature_lookup

    def _path_match_is_compatible(self, current_elem, original_elem):
        """Validate path-based matches before accepting them as equivalent."""
        if current_elem is None or original_elem is None:
            return False
        if current_elem.name != original_elem.name:
            return False

        current_id = current_elem.get('id')
        original_id = original_elem.get('id')
        if current_id or original_id:
            return current_id == original_id

        current_classes = set(self._normalized_classes(current_elem))
        original_classes = set(self._normalized_classes(original_elem))
        if original_classes:
            return original_classes.issubset(current_classes)
        if current_classes:
            return False

        for attr in ('role', 'aria-label', 'name', 'type'):
            current_value = current_elem.get(attr)
            original_value = original_elem.get(attr)
            if current_value or original_value:
                return current_value == original_value

        return True

    def _match_original_element(self, current_elem, path_lookup, signature_lookup):
        """Match a current DOM node back to the original HTML."""
        if current_elem is None or current_elem.parent is None:
            return None
        if not isinstance(getattr(current_elem, 'attrs', None), dict):
            return None

        original_elem = path_lookup.get(self._element_dom_path(current_elem))
        if original_elem and self._path_match_is_compatible(current_elem, original_elem):
            return original_elem

        signature = self._element_identity_signature(current_elem)
        if not signature:
            return None

        candidates = signature_lookup.get(signature, [])
        if len(candidates) == 1:
            return candidates[0]

        return None

    def _normalize_inline_style(self, style):
        """Return a normalized representation of an inline style string."""
        if not style:
            return ()

        declarations = []
        for raw_decl in style.split(';'):
            if ':' not in raw_decl:
                continue
            key, value = raw_decl.split(':', 1)
            key = key.strip().lower()
            value = ' '.join(value.strip().split())
            if key:
                declarations.append((key, value))

        return tuple(declarations)

    def _restore_original_inline_styles(self, soup):
        """
        Restore inline style attributes to the original server-rendered HTML.

        Runtime animation libraries frequently persist transform/opacity/clip-path
        states into the captured DOM. Replaying those mutated inline styles
        offline can freeze entrances, scroll reveals and embedded widgets.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup:
            return

        path_lookup, signature_lookup = self._build_original_element_lookups(original_soup)

        removed = 0
        restored = 0

        for current_elem in soup.find_all(True):
            original_elem = self._match_original_element(current_elem, path_lookup, signature_lookup)
            if not original_elem:
                continue

            current_style = current_elem.get('style')
            original_style = original_elem.get('style')

            if self._normalize_inline_style(current_style) == self._normalize_inline_style(original_style):
                continue

            if original_style is None:
                if current_style is not None:
                    del current_elem['style']
                    removed += 1
                continue

            current_elem['style'] = original_style
            restored += 1

        if removed:
            self.log(f"   Removidos {removed} estilos inline gerados apenas em runtime")
        if restored:
            self.log(f"   Restaurados {restored} estilos inline do HTML original")

    def _restore_original_svg_transforms(self, soup):
        """
        Restore SVG transform attributes to their original server-rendered state.

        Runtime animation libraries often persist matrix transforms into the DOM.
        If those transforms did not exist in the original HTML response, the next
        offline load starts from an already-mutated SVG state and animations drift.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup:
            return

        original_lookup = {}
        for original_elem in original_soup.find_all(True):
            if original_elem.name != 'svg' and not original_elem.find_parent('svg'):
                continue
            original_lookup[self._element_dom_path(original_elem)] = original_elem

        restored = 0
        for current_elem in soup.find_all(True):
            if not current_elem.has_attr('transform'):
                continue
            if current_elem.name != 'svg' and not current_elem.find_parent('svg'):
                continue

            original_elem = original_lookup.get(self._element_dom_path(current_elem))
            if not original_elem:
                continue

            original_transform = original_elem.get('transform')
            current_transform = current_elem.get('transform')
            if original_transform == current_transform:
                continue

            if original_transform is None:
                del current_elem['transform']
            else:
                current_elem['transform'] = original_transform
            restored += 1

        if restored:
            self.log(f"   Restaurados {restored} transforms SVG do HTML original")

    def _restore_original_style_tags(self, soup):
        """
        Restore critical inline <style> tags from the original HTML response.

        CSS-in-JS libraries may leave placeholder tags in the hydrated DOM while
        the real server-rendered CSS still exists in the original HTML response.
        """
        original_soup = self._get_original_html_soup()
        if not original_soup:
            return

        head = soup.find('head')
        original_head = original_soup.find('head')
        if not head or not original_head:
            return

        restored = 0
        deduplicated = 0
        current_styles = head.find_all('style')

        def _style_signature(tag):
            return tuple(sorted((key, str(value)) for key, value in tag.attrs.items()))

        def _css_in_js_key(tag):
            if tag.has_attr('data-styled-version'):
                return ('styled-components', str(tag.get('data-styled-version')))
            if tag.has_attr('data-emotion'):
                return ('emotion', str(tag.get('data-emotion')))
            return None

        current_by_sig = {}
        current_by_css_in_js = {}
        for style_tag in current_styles:
            current_by_sig.setdefault(_style_signature(style_tag), []).append(style_tag)
            css_in_js_key = _css_in_js_key(style_tag)
            if css_in_js_key:
                current_by_css_in_js.setdefault(css_in_js_key, []).append(style_tag)

        for original_style in original_head.find_all('style'):
            original_css = original_style.get_text() or ''
            if not original_css.strip():
                continue

            signature = _style_signature(original_style)
            candidates = current_by_sig.get(signature, [])
            replaced = False

            for candidate in candidates:
                candidate_css = candidate.get_text() or ''
                if candidate_css.strip():
                    replaced = True
                    break
                candidate.clear()
                candidate.append(NavigableString(original_css))
                restored += 1
                replaced = True
                break

            if not replaced:
                css_in_js_key = _css_in_js_key(original_style)
                if css_in_js_key:
                    candidates = current_by_css_in_js.get(css_in_js_key, [])
                    if any((candidate.get_text() or '').strip() for candidate in candidates):
                        replaced = True
                    else:
                        placeholder = next(
                            (
                                candidate for candidate in candidates
                                if not (candidate.get_text() or '').strip()
                            ),
                            None,
                        )
                        if placeholder:
                            placeholder.attrs = dict(original_style.attrs)
                            placeholder.clear()
                            placeholder.append(NavigableString(original_css))
                            restored += 1
                            replaced = True

                            for candidate in candidates:
                                if candidate is placeholder:
                                    continue
                                if not (candidate.get_text() or '').strip():
                                    candidate.decompose()
                                    deduplicated += 1

            if replaced:
                continue

            new_style = soup.new_tag('style')
            for key, value in original_style.attrs.items():
                new_style[key] = value
            new_style.append(NavigableString(original_css))
            head.append(new_style)
            restored += 1

        if restored:
            self.log(f"   Restaurados {restored} blocos <style> críticos do HTML original")
        if deduplicated:
            self.log(f"   Removidos {deduplicated} placeholders duplicados de CSS-in-JS")

    def _remove_wrapper_iframes(self, soup):
        """Remove preview/wrapper iframes from site builders."""
        for iframe in soup.find_all('iframe'):
            srcdoc = iframe.get('srcdoc', '')
            iframe_classes = str(iframe.get('class', '')).lower()
            if srcdoc or 'preview' in iframe_classes:
                iframe.decompose()
