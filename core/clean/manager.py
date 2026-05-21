"""
Site cleaner orchestration.
"""
import asyncio
import json
import os
import shutil
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

from .. import CLEAN_MAX_SIZE_MB, CLEAN_MAX_SIZE_MB_INVALID, CLEAN_MODE
from ..ai_context import generate_ai_context
from ..classifier import classify_site
from .clean_css import clean_css_content_with_tokens
from .clean_html import clean_html_content_with_stats
from .clean_js import clean_js_content_with_stats
from .css_tokens import extract_css_tokens_from_html


class SiteCleaner:
    """Clean downloaded sites and organize raw/clean/audit artifacts."""

    _SITE_ROOT_INFRA_ENTRIES = {'raw', 'clean', 'audit', 'serve.py', 'tools'}

    def __init__(self, site_dir, log_callback):
        self.site_dir = Path(site_dir)
        self.log = log_callback
        self.clean_root = None
        self.stats = {
            'html_cleaned': 0,
            'css_cleaned': 0,
            'js_cleaned': 0,
            'total_bytes_saved': 0,
            'all_css_tokens': {
                'custom_properties': [],
                'colors': [],
                'font_faces': [],
                'keyframes': [],
                'breakpoints': [],
            },
            'tracking_js_removed': 0,
            'tracking_scripts_removed': 0,
            'tracking_meta_removed': 0,
            'tracking_attrs_removed': 0,
            'svgs_replaced': 0,
            'hidden_elements_removed': 0,
            'sections_detected': {},
            'inline_styles_extracted': 0,
            'inline_scripts_extracted': 0,
        }

    def _site_size_bytes(self):
        total = 0
        for path in self.site_dir.rglob('*'):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def _should_skip_clean_copy(self):
        if CLEAN_MODE == 'raw-only':
            self.log("   Modo raw-only ativo: versão clean será pulada")
            return True

        if CLEAN_MAX_SIZE_MB_INVALID:
            self.log(
                f"   Aviso: DM_CLEAN_MAX_SIZE_MB inválido ({CLEAN_MAX_SIZE_MB_INVALID}), ignorando limite"
            )
            return False

        if CLEAN_MAX_SIZE_MB is None:
            return False

        size_limit_bytes = int(CLEAN_MAX_SIZE_MB * 1024 * 1024)
        current_size = self._site_size_bytes()
        if current_size >= size_limit_bytes:
            self.log(
                f"   Site com {current_size / (1024 * 1024):.1f} MB excede limite de "
                f"{CLEAN_MAX_SIZE_MB:g} MB: versão clean será pulada"
            )
            return True

        return False

    def _source_root(self):
        source_entries = [
            item for item in self.site_dir.iterdir()
            if item.name not in self._SITE_ROOT_INFRA_ENTRIES
        ]
        if source_entries:
            return self.site_dir

        raw_dir = self.site_dir / 'raw'
        if raw_dir.exists():
            return raw_dir

        return self.site_dir

    def _copy_site_snapshot(self, source_root, destination):
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True, exist_ok=True)

        for item in source_root.iterdir():
            if source_root == self.site_dir and item.name in self._SITE_ROOT_INFRA_ENTRIES:
                continue
            if item.name == 'serve.py':
                continue

            target = destination / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)

    def _has_streaming_next_runtime(self, root: Path) -> bool:
        """Detect framework runtimes that are sensitive to JS/CSS rebundling."""
        try:
            for html_file in root.rglob('*.html'):
                try:
                    content = html_file.read_text(encoding='utf-8', errors='ignore')
                except Exception:
                    continue

                if not any(
                    marker in content
                    for marker in (
                        '__NEXT_DATA__',
                        'self.__next_f.push',
                        '/_next/static/',
                        'framerusercontent.com/sites/',
                        'data-framer-name=',
                        'data-framer-component-type=',
                        'ElementorProFrontendConfig',
                        'elementorFrontendConfig',
                        '/wp-content/plugins/elementor',
                    )
                ):
                    continue

                if (
                    'framerusercontent.com/sites/' in content
                    or 'data-framer-name=' in content
                    or 'data-framer-component-type=' in content
                    or 'ElementorProFrontendConfig' in content
                    or 'elementorFrontendConfig' in content
                    or '/wp-content/plugins/elementor' in content
                ):
                    return True

                if not _BS4_AVAILABLE:
                    if '__NEXT_DATA__' in content:
                        return True
                    continue

                soup = BeautifulSoup(content, 'html.parser')
                if soup.find('script', id='__NEXT_DATA__'):
                    return True

                for script in soup.find_all('script'):
                    src = (script.get('src') or '').strip()
                    if src and '/_next/static/' in src:
                        return True
                    if script.get('data-fetch-interceptor') == 'true':
                        continue
                    if 'self.__next_f.push' in (script.get_text() or ''):
                        return True

                for link in soup.find_all('link', href=True):
                    href = (link.get('href') or '').strip()
                    if href and '/_next/static/' in href:
                        return True
        except Exception:
            return False
        return False

    def process(self):
        self.log("Iniciando limpeza inteligente para consumo por IA...")

        raw_dir = self.site_dir / 'raw'
        clean_dir = self.site_dir / 'clean'
        audit_dir = self.site_dir / 'audit'
        source_root = self._source_root()

        # --- Raw backup ---
        if source_root == self.site_dir:
            self.log("   Criando versão raw (backup original)...")
            self._copy_site_snapshot(source_root, raw_dir)
        else:
            self.log("   Reutilizando versão raw existente como fonte para recriar clean/")

        skip_clean_copy = self._should_skip_clean_copy()
        if clean_dir.exists():
            shutil.rmtree(clean_dir)
        if audit_dir.exists():
            shutil.rmtree(audit_dir)

        if not skip_clean_copy:
            # ---------------------------------------------------------------
            # Etapa 1: Copiar raw/ → clean/ (cópia fiel inicial)
            # ---------------------------------------------------------------
            self.log("   Criando versão clean (otimizada para IA)...")
            self._copy_site_snapshot(source_root, clean_dir)
            preserve_framework_runtime = self._has_streaming_next_runtime(clean_dir)
            if preserve_framework_runtime:
                self.log(
                    "   Site com runtime de framework detectado: mantendo HTML/CSS/JS em modo conservador no clean/"
                )

            # Inicializar sistema de auditoria
            from ..audit import AuditRecorder
            audit = AuditRecorder(audit_dir, self.log)
            audit.snapshot('01_raw', clean_dir, 'Cópia fiel antes de qualquer limpeza')

            # ---------------------------------------------------------------
            # Etapa 2: Limpeza de HTML
            # ---------------------------------------------------------------
            if preserve_framework_runtime:
                self.log("   [Etapa 2] Pulando limpeza de HTML para preservar hydration do framework...")
            else:
                self.log("   [Etapa 2] Limpando HTML...")
                self._clean_directory(clean_dir, types={'.html'})
            audit.snapshot('02_after_html_clean', clean_dir, 'Após remoção de tracking e limpeza HTML')

            # ---------------------------------------------------------------
            # Etapa 3: Limpeza de CSS
            # ---------------------------------------------------------------
            if preserve_framework_runtime:
                self.log("   [Etapa 3] Pulando limpeza de CSS para preservar ordem/semântica do framework...")
            else:
                self.log("   [Etapa 3] Limpando CSS...")
                self._clean_directory(clean_dir, types={'.css'})
            audit.snapshot('03_after_css_clean', clean_dir, 'Após desminificação e limpeza CSS')

            # ---------------------------------------------------------------
            # Etapa 4: Limpeza de JS
            # ---------------------------------------------------------------
            if preserve_framework_runtime:
                self.log("   [Etapa 4] Pulando limpeza de JS para preservar runtime do framework...")
            else:
                self.log("   [Etapa 4] Limpando JS...")
                self._clean_directory(clean_dir, types={'.js', '.mjs', '.cjs'})
            audit.snapshot('04_after_js_clean', clean_dir, 'Após desminificação e limpeza JS')

            # ---------------------------------------------------------------
            # Etapa 5: Inventário (log only, sem arquivo)
            # ---------------------------------------------------------------
            from .file_inventory import generate_inventory
            inventory = generate_inventory(clean_dir)
            meta = inventory.get('_meta', {})
            html_n = inventory.get('html', {}).get('count', 0)
            css_n = inventory.get('css', {}).get('count', 0)
            js_n = inventory.get('js', {}).get('count', 0)
            img_n = inventory.get('images', {}).get('count', 0)
            self.log(f"   [Etapa 5] {meta.get('total_files', 0)} arquivos — "
                     f"HTML:{html_n} CSS:{css_n} JS:{js_n} imgs:{img_n}")

            # ---------------------------------------------------------------
            # Etapa 6: Reorganização de assets por tipo
            # ---------------------------------------------------------------
            self.log("   [Etapa 6] Reorganizando assets por tipo...")
            from .reorganizer import reorganize
            path_mapping = reorganize(clean_dir)
            self.log(f"      {len(path_mapping)} arquivo(s) reorganizado(s) em assets/")
            audit.snapshot('05_after_reorganization', clean_dir, 'Assets movidos para subpastas por tipo')

            # ---------------------------------------------------------------
            # Etapa 7: Correção de paths (crítico)
            # ---------------------------------------------------------------
            self.log("   [Etapa 7] Corrigindo referências de paths...")
            from .path_corrector import correct_all_paths
            path_stats = correct_all_paths(clean_dir, path_mapping, self.log)
            if path_stats.get('json'):
                self.log("      Reaplicando correção com resource-map atualizado...")
                correct_all_paths(clean_dir, {}, self.log)
            audit.snapshot('06_after_path_correction', clean_dir, 'Referências de paths atualizadas')

            # ---------------------------------------------------------------
            # Etapa 7b/7c: Redução de arquivos CSS/JS
            # ---------------------------------------------------------------
            from .css_consolidator import consolidate_css, repair_css_references
            if preserve_framework_runtime:
                self.log("   [Etapa 7b] Pulando consolidação de CSS para preservar cascata do framework...")
                css_plan = {'mapping': {}, 'bundles': []}
            else:
                self.log("   [Etapa 7b] Reduzindo e reorganizando CSS...")
                css_plan = consolidate_css(clean_dir, self.log)

            from .js_consolidator import repair_js_references
            if preserve_framework_runtime:
                self.log("   [Etapa 7c] Pulando consolidação de JS para preservar ordem do runtime...")
                js_plan = {'mapping': {}, 'bundles': []}
            else:
                self.log("   [Etapa 7c] Consolidando JS pequenos...")
                from .js_consolidator import consolidate_js
                js_plan = consolidate_js(clean_dir, self.log)
            audit.snapshot(
                '07_after_file_reduction',
                clean_dir,
                'Quantidade de arquivos CSS/JS reduzida antes do reparo das referências',
            )

            # ---------------------------------------------------------------
            # Etapa 7d: Reparar referências após redução
            # ---------------------------------------------------------------
            self.log("   [Etapa 7d] Reparando referências após rebundle...")
            repair_css_references(clean_dir, css_plan, self.log)
            repair_js_references(clean_dir, js_plan, self.log)

            rebundle_mapping = {}
            rebundle_mapping.update(css_plan.get('reference_map', {}))
            rebundle_mapping.update(js_plan.get('mapping', {}))
            if rebundle_mapping:
                correct_all_paths(clean_dir, rebundle_mapping, self.log)
            from .finalizer import (
                materialize_runtime_aliases,
                prune_missing_local_css_urls,
                prune_missing_local_html_refs,
            )
            compatibility_mapping = {}
            compatibility_mapping.update(path_mapping)
            compatibility_mapping.update(rebundle_mapping)
            materialize_runtime_aliases(clean_dir, compatibility_mapping, self.log)
            prune_missing_local_html_refs(clean_dir, self.log)
            prune_missing_local_css_urls(clean_dir, self.log)
            audit.snapshot(
                '08_after_bundle_reference_repair',
                clean_dir,
                'Referências HTML/CSS/JS reparadas após consolidação de CSS e JS',
            )

            # ---------------------------------------------------------------
            # Etapa 7e: Poda de data assets órfãos
            # ---------------------------------------------------------------
            self.log("   [Etapa 7e] Removendo data assets órfãos...")
            from .finalizer import prune_unreferenced_data_assets
            prune_unreferenced_data_assets(clean_dir, self.log)
            audit.snapshot(
                '09_after_data_pruning',
                clean_dir,
                'Arquivos órfãos em assets/data removidos do clean/',
            )

            # ---------------------------------------------------------------
            # Etapa 8: Classificação do site
            # ---------------------------------------------------------------
            self.log("   [Etapa 8] Classificando tipo de site...")
            classification = classify_site(self.site_dir)
            self._write_classification(clean_dir, classification)

            # ---------------------------------------------------------------
            # Etapa 8b: Extractors de runtime
            # ---------------------------------------------------------------
            self.log("   Executando extractors de runtime...")
            coverage_data = asyncio.run(self._run_extractors(clean_dir, classification))

            # Anotar JS files com dados de coverage (sem salvar JSON)
            self._annotate_js_with_coverage(clean_dir, coverage_data)

            # ---------------------------------------------------------------
            # Etapa 8c: Tokens visuais
            # ---------------------------------------------------------------
            self.log("   Destilando tokens de design...")
            self._enrich_tokens_with_computed_styles(clean_dir)
            visual_tokens = self._write_site_tokens(clean_dir)

            # ---------------------------------------------------------------
            # Etapa 8d: Contexto AI-ready
            # ---------------------------------------------------------------
            self.log("   Gerando contexto AI-ready...")
            generate_ai_context(self.site_dir, tokens=visual_tokens)
            from .finalizer import compact_ai_metadata, strip_generated_text_comments
            compact_ai_metadata(clean_dir, self.log)
            strip_generated_text_comments(clean_dir, self.log)

            # ---------------------------------------------------------------
            # Etapa 8e: Normalização final de texto
            # ---------------------------------------------------------------
            self.log("   [Etapa 8e] Normalizando tabs e terminadores de linha...")
            from .finalizer import normalize_text_files
            normalize_text_files(clean_dir, self.log)
            audit.snapshot(
                '10_after_text_normalization',
                clean_dir,
                'Texto normalizado com espaços e terminadores de linha consistentes',
            )

            # ---------------------------------------------------------------
            # Etapa 9: Validação (log only, sem arquivo)
            # ---------------------------------------------------------------
            self.log("   [Etapa 9] Validando integridade do clean/...")
            from .validator import validate_clean
            validation = validate_clean(clean_dir)
            broken = validation.get('total_broken', 0)
            checked = validation.get('total_references_checked', 0)
            status = 'OK' if validation.get('passed') else f'{broken} refs quebradas'
            self.log(f"      Validação: {checked} refs verificadas — {status}")

            # ---------------------------------------------------------------
            # Audit final + relatório
            # ---------------------------------------------------------------
            audit.snapshot('11_final', clean_dir, 'Estado final do clean/')
            audit.generate_report()

        # Copiar serve.py para raw/ e clean/
        serve_template = Path(__file__).parent.parent / 'templates' / 'serve_template.py'
        if serve_template.exists():
            shutil.copy(serve_template, raw_dir / 'serve.py')
            if not skip_clean_copy:
                shutil.copy(serve_template, clean_dir / 'serve.py')

        # Remover arquivos soltos da raiz do site_dir
        for item in self.site_dir.iterdir():
            if item.name not in self._SITE_ROOT_INFRA_ENTRIES:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        bytes_saved = self.stats['total_bytes_saved']
        if bytes_saved > 1024 * 1024:
            size_str = f"{bytes_saved / (1024 * 1024):.2f} MB"
        elif bytes_saved > 1024:
            size_str = f"{bytes_saved / 1024:.2f} KB"
        else:
            size_str = f"{bytes_saved} bytes"

        self.log("   Limpeza completa:")
        self.log(f"      - {self.stats['html_cleaned']} arquivos HTML")
        self.log(f"      - {self.stats['css_cleaned']} arquivos CSS")
        self.log(f"      - {self.stats['js_cleaned']} arquivos JS")
        self.log(f"      - ~{size_str} economizados")
        self.log(f"      - {self.stats['svgs_replaced']} SVGs substituídos")
        self.log(f"      - {self.stats['hidden_elements_removed']} elementos ocultos removidos")
        self.log(f"      - {self.stats['tracking_scripts_removed']} scripts de tracking removidos do HTML")
        self.log(f"      - {self.stats['tracking_js_removed']} arquivos JS marcados como tracking")
        self.log(f"      - {self.stats['inline_styles_extracted']} <style> extraídos para CSS")
        self.log(f"      - {self.stats['inline_scripts_extracted']} <script> extraídos para JS")
        return True

    def _clean_directory(self, directory, types=None):
        """Clean files in directory. `types` is a set of extensions to process (e.g. {'.html'})."""
        self.clean_root = directory
        allowed = set(types) if types is not None else {'.html', '.css', '.js', '.mjs', '.cjs'}
        audit_dir = Path(directory) / 'audit'

        for root, _dirs, files in os.walk(directory):
            root_path = Path(root)
            # Skip audit/ subdirectory
            try:
                root_path.relative_to(audit_dir)
                continue
            except ValueError:
                pass

            for filename in files:
                filepath = root_path / filename
                ext = filepath.suffix.lower()
                if ext not in allowed:
                    continue
                if ext == '.html':
                    self._clean_html_file(filepath)
                elif ext == '.css':
                    self._clean_css_file(filepath)
                elif ext in ('.js', '.mjs', '.cjs'):
                    self._clean_js_file(filepath)

    def _clean_html_file(self, filepath):
        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
            # Passa filepath para que assets inline sejam extraídos para arquivos externos
            cleaned, html_stats = clean_html_content_with_stats(content, filepath=filepath)
            filepath.write_text(cleaned, encoding='utf-8')
            self.stats['html_cleaned'] += 1
            self._record_bytes_saved(content, cleaned)
            self.stats['svgs_replaced'] += html_stats.get('svgs_replaced', 0)
            self.stats['hidden_elements_removed'] += html_stats.get('hidden_elements_removed', 0)
            self.stats['tracking_scripts_removed'] += html_stats.get('tracking_scripts_removed', 0)
            self.stats['tracking_meta_removed'] += html_stats.get('tracking_meta_removed', 0)
            self.stats['tracking_attrs_removed'] += html_stats.get('tracking_attrs_removed', 0)
            self.stats['inline_styles_extracted'] += html_stats.get('inline_styles_extracted', 0)
            self.stats['inline_scripts_extracted'] += html_stats.get('inline_scripts_extracted', 0)
            self._merge_css_tokens(extract_css_tokens_from_html(cleaned))

            relative_path = filepath.name
            if self.clean_root:
                relative_path = filepath.relative_to(self.clean_root).as_posix()
            self.stats['sections_detected'][relative_path] = html_stats.get('sections_detected', [])
        except Exception as exc:
            self.log(f"   Aviso: falha ao limpar HTML {filepath}: {exc}")

    def _clean_css_file(self, filepath):
        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
            cleaned, tokens = clean_css_content_with_tokens(content)
            filepath.write_text(cleaned, encoding='utf-8')
            self.stats['css_cleaned'] += 1
            self._record_bytes_saved(content, cleaned)
            self._merge_css_tokens(tokens)
            # Tokens consolidados em _site_tokens.json — sem sidecars por arquivo
        except Exception as exc:
            self.log(f"   Aviso: falha ao limpar CSS {filepath}: {exc}")

    def _clean_js_file(self, filepath):
        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
            cleaned, js_stats = clean_js_content_with_stats(content, filepath.as_posix())
            if cleaned != content:
                filepath.write_text(cleaned, encoding='utf-8')
            self.stats['js_cleaned'] += 1
            self._record_bytes_saved(content, cleaned)
            if js_stats.get('is_tracking'):
                self.stats['tracking_js_removed'] += 1
        except Exception as exc:
            self.log(f"   Aviso: falha ao limpar JS {filepath}: {exc}")

    def _record_bytes_saved(self, original_content, cleaned_content):
        saved = len(original_content) - len(cleaned_content)
        if saved > 0:
            self.stats['total_bytes_saved'] += saved

    def _merge_css_tokens(self, new_tokens):
        existing = self.stats['all_css_tokens']

        custom_names = {item['name'] for item in existing['custom_properties']}
        for token in new_tokens.get('custom_properties', []):
            if token['name'] in custom_names:
                continue
            existing['custom_properties'].append(token)
            custom_names.add(token['name'])

        color_values = {item['value'] for item in existing['colors']}
        for token in new_tokens.get('colors', []):
            if token['value'] in color_values:
                continue
            existing['colors'].append(token)
            color_values.add(token['value'])

        font_signatures = {
            (item['family'], item['weight'], item['style'], item['src'])
            for item in existing['font_faces']
        }
        for token in new_tokens.get('font_faces', []):
            signature = (token['family'], token['weight'], token['style'], token['src'])
            if signature in font_signatures:
                continue
            existing['font_faces'].append(token)
            font_signatures.add(signature)

        keyframe_names = {item['name'] for item in existing['keyframes']}
        for token in new_tokens.get('keyframes', []):
            if token['name'] in keyframe_names:
                continue
            existing['keyframes'].append(token)
            keyframe_names.add(token['name'])

        seen_queries = {item['query'] for item in existing.get('breakpoints', [])}
        existing.setdefault('breakpoints', [])
        for bp in new_tokens.get('breakpoints', []):
            if bp['query'] in seen_queries:
                continue
            existing['breakpoints'].append(bp)
            seen_queries.add(bp['query'])

    def _write_site_tokens(self, clean_dir) -> dict:
        """Salva _site_tokens.md (Markdown compacto) e retorna tokens filtrados."""
        from .css_tokens import filter_visual_tokens
        visual_tokens = filter_visual_tokens(self.stats['all_css_tokens'])
        _write_tokens_md(clean_dir, visual_tokens)
        return visual_tokens

    def _write_classification(self, clean_dir, classification):
        output_path = clean_dir / '_site_classification.json'
        output_path.write_text(
            json.dumps(classification, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )

    async def _run_extractors(self, clean_dir, classification):
        """Run extractors based on site classification. Returns coverage_data dict."""
        from ..extractors.computed_styles import extract_computed_styles
        from ..extractors.code_coverage import extract_code_coverage
        from ..extractors.scroll_physics import extract_scroll_physics
        from ..extractors.shader_extractor import extract_shaders_from_directory

        target = clean_dir / 'index.html'
        coverage_data = {}

        if not target.exists():
            self.log("      Aviso: index.html não encontrado, pulando extractors")
            return coverage_data

        # 1. Computed styles (always run) — salvo para ai_context.md
        try:
            self.log("      Extraindo computed styles...")
            computed_styles = await extract_computed_styles(
                str(target), output_path=None, timeout_ms=30000
            )
            (clean_dir / '_computed_styles.json').write_text(
                json.dumps(computed_styles, indent=2, ensure_ascii=False), encoding='utf-8'
            )
        except Exception as exc:
            self.log(f"      Aviso: falha ao extrair computed styles: {exc}")

        # 2. Code coverage — usado internamente para anotação, sem salvar JSON
        try:
            self.log("      Extraindo code coverage...")
            coverage_data = await extract_code_coverage(
                str(target), output_path=None, timeout_ms=30000
            )
            summary = coverage_data.get('summary', {})
            pct = summary.get('coverage_pct', 0)
            dead_kb = summary.get('dead_bytes', 0) / 1024
            self.log(f"         Coverage: {pct:.1f}% executado | {dead_kb:.0f} KB mortos")
        except Exception as exc:
            self.log(f"      Aviso: falha ao extrair code coverage: {exc}")

        # 3. Scroll physics → _scroll_physics.md (readable, sem array de keyframes)
        if classification.get('has_scroll_jacking'):
            try:
                self.log("      Extraindo scroll physics...")
                scroll_physics = await extract_scroll_physics(
                    str(target), output_path=None, timeout_ms=30000
                )
                self._write_scroll_physics_md(clean_dir, scroll_physics)
            except Exception as exc:
                self.log(f"      Aviso: falha ao extrair scroll physics: {exc}")

        # 4. Shaders GLSL (only if WebGL detected)
        if classification.get('has_webgl'):
            try:
                self.log("      Extraindo shaders GLSL...")
                assets_dir = clean_dir / 'assets'
                if assets_dir.exists():
                    shader_summary = extract_shaders_from_directory(
                        str(assets_dir), str(clean_dir / '_shaders')
                    )
                    if shader_summary.get('shaders'):
                        self.log(f"         {len(shader_summary['shaders'])} shaders encontrados")
            except Exception as exc:
                self.log(f"      Aviso: falha ao extrair shaders: {exc}")

        return coverage_data

    def _write_scroll_physics_md(self, clean_dir, scroll_physics):
        """Gera _scroll_physics.md com resumo legível por IA (sem array gigante de keyframes)."""
        elements = scroll_physics.get('elements', {})
        animated = {sel: data for sel, data in elements.items() if data.get('animated')}
        if not animated:
            return

        lines = ['# Scroll Physics\n',
                 '> Elementos com CSS properties que mudam durante scroll (capturado via Playwright).\n']

        # Tabela: apenas elementos com CSS properties reais mudando (não só _rect.top)
        css_animated = {
            sel: data for sel, data in animated.items()
            if any(not p.startswith('_rect.') for p in data.get('changed_properties', []))
        }
        if css_animated:
            lines.append('## CSS Animations on Scroll\n')
            lines.append('| Element | Changed CSS Properties | Initial Values |\n')
            lines.append('|---|---|---|\n')
            for sel, data in list(css_animated.items())[:10]:
                css_props = [p for p in data.get('changed_properties', []) if not p.startswith('_rect.')]
                initial = data.get('initial_state', {})
                init_str = ' | '.join(
                    f'{k}:{v}' for k, v in list(initial.items())[:3]
                    if not k.startswith('_rect')
                )
                lines.append(f'| `{sel}` | `{", ".join(css_props)}` | {init_str} |\n')
            lines.append('\n')

        # Elementos que só movem com scroll (posição muda, CSS não)
        rect_only = {
            sel: data for sel, data in animated.items()
            if sel not in css_animated
        }
        if rect_only:
            lines.append('## Position Changes on Scroll\n')
            lines.append(', '.join(f'`{sel}`' for sel in list(rect_only.keys())[:8]))
            lines.append('\n\n')

        lines.append(f'*{len(animated)} elementos animados de {len(elements)} observados.*\n')
        (clean_dir / '_scroll_physics.md').write_text(''.join(lines), encoding='utf-8')

    def _annotate_js_with_coverage(self, clean_dir, coverage_data=None):
        """Adiciona comentário de coverage no topo de cada JS com alto dead code."""
        if not coverage_data:
            return

        try:
            files_data = coverage_data.get('files', [])
            if not files_data:
                return

            # Mapeia basename do arquivo → dados de coverage
            coverage_map = {}
            for file_info in files_data:
                url = file_info.get('url', '')
                if not url:
                    continue
                basename = Path(url).name
                coverage_map[basename] = {
                    'pct': file_info.get('coverage_pct', 100.0),
                    'dead_bytes': file_info.get('dead_bytes', 0),
                    'total_bytes': file_info.get('total_bytes', 0),
                }

            annotated = 0
            js_dirs = [clean_dir / 'assets' / 'js', clean_dir]
            for js_dir in js_dirs:
                if not js_dir.exists():
                    continue
                for js_file in js_dir.glob('*.js'):
                    info = coverage_map.get(js_file.name)
                    if not info:
                        continue
                    pct = info['pct']
                    dead_kb = info['dead_bytes'] / 1024
                    total_kb = info['total_bytes'] / 1024
                    try:
                        content = js_file.read_text(encoding='utf-8', errors='ignore')
                        if content.startswith('/* [CODE COVERAGE]'):
                            continue
                        annotation = (
                            f'/* [CODE COVERAGE] {pct:.1f}% executado | '
                            f'{dead_kb:.1f} KB código morto / {total_kb:.1f} KB total */\n'
                        )
                        js_file.write_text(annotation + content, encoding='utf-8')
                        annotated += 1
                    except Exception:
                        continue

            if annotated:
                self.log(f"      {annotated} arquivo(s) JS anotados com coverage")
        except Exception as exc:
            self.log(f"      Aviso: falha ao anotar coverage: {exc}")


    def _enrich_tokens_with_computed_styles(self, clean_dir):
        """Enrich CSS tokens with computed styles from extractor."""
        computed_path = clean_dir / '_computed_styles.json'
        if not computed_path.exists():
            return

        try:
            computed_data = json.loads(computed_path.read_text(encoding='utf-8', errors='ignore'))

            computed_colors = set()
            selector_map = computed_data.get('selectors', computed_data)
            if not isinstance(selector_map, dict):
                return

            for selector_data in selector_map.values():
                if not isinstance(selector_data, dict):
                    continue
                if 'color' in selector_data:
                    computed_colors.add(selector_data['color'])
                if 'backgroundColor' in selector_data:
                    computed_colors.add(selector_data['backgroundColor'])
                if 'borderColor' in selector_data:
                    computed_colors.add(selector_data['borderColor'])

            existing_color_values = {item['value'] for item in self.stats['all_css_tokens']['colors']}
            for color in computed_colors:
                if color and color != 'transparent' and color not in existing_color_values:
                    self.stats['all_css_tokens']['colors'].append({
                        'value': color,
                        'source': 'computed',
                    })

        except Exception as exc:
            self.log(f"      Aviso: falha ao enriquecer tokens: {exc}")


def _write_tokens_md(clean_dir: Path, tokens: dict) -> None:
    """Escreve _site_tokens.md em formato Markdown compacto."""
    import re as _re
    lines = ['# Design Tokens\n']

    custom_props = tokens.get('custom_properties', [])
    if custom_props:
        lines.append('\n## CSS Variables\n\n```css')
        for p in custom_props:
            lines.append(f"{p['name']}: {p['value']};")
        lines.append('```')

    colors = tokens.get('colors', [])
    if colors:
        _generic = {
            '#000', '#000000', '#fff', '#ffffff', '#333', '#666', '#999',
            '#ccc', '#ddd', '#eee', '#222', '#444', '#555', '#777', '#888',
            '#aaa', '#bbb', '#f0f0f0', '#f5f5f5', '#fafafa',
        }
        hex_colors = [c['value'] for c in colors
                      if c.get('type') == 'hex' and c.get('value', '').lower() not in _generic]
        other_colors = [c['value'] for c in colors
                        if c.get('type') != 'hex' and c.get('value', '').lower() not in _generic]
        if hex_colors or other_colors:
            lines.append('\n## Color Palette')
            if hex_colors:
                for i in range(0, len(hex_colors), 8):
                    lines.append('  '.join(hex_colors[i:i + 8]))
            if other_colors:
                for c in other_colors[:10]:
                    lines.append(c)

    fonts = tokens.get('font_faces', [])
    if fonts:
        lines.append('\n## Fonts')
        for f in fonts:
            family = f.get('family', '')
            weight = f.get('weight', '')
            style = f.get('style', 'normal')
            src = f.get('src', '')
            m = _re.search(r"url\(['\"]?([^'\")\s]+)['\"]?\)", src)
            fname = (Path(m.group(1)).name if m else src)[:40]
            lines.append(f'{family} · {weight} · {style} → {fname}')

    keyframes = tokens.get('keyframes', [])
    if keyframes:
        lines.append('\n## Keyframes')
        for kf in keyframes:
            name = kf.get('name', '')
            body = _re.sub(r'\s+', ' ', kf.get('body', '').strip())
            body = body[:80] + ('…' if len(body) > 80 else '')
            lines.append(f'{name} → {body}')

    breakpoints = tokens.get('breakpoints', [])
    if breakpoints:
        lines.append('\n## Breakpoints')
        lines.append(' · '.join(f"({bp['query']})" for bp in breakpoints))

    content = '\n'.join(lines) + '\n'
    (clean_dir / '_site_tokens.md').write_text(content, encoding='utf-8')


def clean_site(site_dir, log_callback):
    """Public API for cleaning a downloaded site."""
    cleaner = SiteCleaner(site_dir, log_callback)
    return cleaner.process()
