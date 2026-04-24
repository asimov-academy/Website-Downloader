"""
Runtime bootstrap and import injection helpers for post-processing.
"""
import json
import os
from urllib.parse import quote, urlparse

from bs4 import NavigableString

from .. import RESOURCE_MAP_INLINE_LIMIT


class PostProcessInjectorsMixin:
    def _inject_runtime_compat_shim(self, soup):
        """
        Inject a tiny local-only compatibility shim before app bootstraps.

        Some captured sites redirect aggressively to local unsupported pages when
        runtime feature detection is too strict for offline/local contexts. We
        only bypass that redirect on local hosts and only for clearly modern
        browsers, so the app can continue booting offline.
        """
        head = soup.find('head')
        if not head:
            return

        if head.find('script', attrs={'data-runtime-compat-shim': 'true'}):
            return

        shim = """
(function () {
  function supportsModernRuntime() {
    try {
      if (!window.fetch || !window.Promise || !window.requestAnimationFrame || !window.URL || !window.Map || !window.Set) {
        return false;
      }
      try {
        if (!eval('(function(){ var obj = { a: { b: 1 } }; return obj?.a?.b === 1; })()')) {
          return false;
        }
      } catch (error) {
        return false;
      }
      return true;
    } catch (error) {
      return false;
    }
  }

  function isLocalHost() {
    var host = String(location.hostname || '').toLowerCase();
    return host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0' || host.endsWith('.local');
  }

  function isUnsupportedTarget(url) {
    return typeof url === 'string' && /unsupported\\.html(?:[?#]|$)/i.test(url);
  }

  function shouldBypassUnsupported(url) {
    return isLocalHost() && supportsModernRuntime() && isUnsupportedTarget(url);
  }

  function patchRedirectMethod(name) {
    var original = Location.prototype[name];
    if (typeof original !== 'function') {
      return;
    }
    Location.prototype[name] = function (url) {
      if (shouldBypassUnsupported(String(url || ''))) {
        console.warn('[Runtime Compat] blocked local unsupported redirect:', url);
        return;
      }
      return original.call(this, url);
    };
  }

  function patchUnsupportedRedirect(target) {
    if (!target || target.__wdmUnsupportedPatched || typeof target.unsupported !== 'function') {
      return target;
    }

    var original = target.unsupported.bind(target);
    target.unsupported = function () {
      var result = original.apply(this, arguments);
      if (result && isLocalHost() && supportsModernRuntime()) {
        console.warn('[Runtime Compat] bypassed UnsupportedRedirect.unsupported() on local modern browser');
        return false;
      }
      return result;
    };
    target.__wdmUnsupportedPatched = true;
    return target;
  }

  patchRedirectMethod('replace');
  patchRedirectMethod('assign');

  var currentUnsupported;
  Object.defineProperty(window, 'UnsupportedRedirect', {
    configurable: true,
    enumerable: true,
    get: function () {
      return currentUnsupported;
    },
    set: function (value) {
      currentUnsupported = patchUnsupportedRedirect(value);
    }
  });
})();
""".strip()

        script_tag = soup.new_tag('script')
        script_tag['data-runtime-compat-shim'] = 'true'
        script_tag.append(NavigableString(shim))

        anchor = (
            head.find('script', attrs={'data-fetch-interceptor': 'true'})
            or head.find('script', attrs={'type': 'importmap'})
            or head.find('script')
        )
        if anchor:
            anchor.insert_after(script_tag)
        else:
            head.insert(0, script_tag)

    def _inject_external_preload_bootstrap(self, soup):
        """
        Materialize external SDK preloads into executable script tags offline.

        Some frameworks preload third-party SDKs but insert the <script> tag later at
        runtime. Offline, that second step may never happen again, so expose the
        local captured asset as a real <script src=...> tag during initial parse.
        """
        resource_map = self.network.get_resource_map()
        if not resource_map:
            return

        site_host = urlparse(self.base_url).netloc.lower()
        original_script_urls = set(self._get_original_script_urls() or [])
        reverse_map = {}
        for remote_url, local_path in resource_map.items():
            reverse_map.setdefault(local_path, []).append(remote_url)

        candidates = []
        seen = set()

        for link in soup.find_all('link', rel=lambda rel: rel and any(item in rel for item in ['preload', 'modulepreload'])):
            href = link.get('href')
            if not href:
                continue

            as_value = (link.get('as') or '').strip().lower()
            rel_values = link.get('rel') or []
            is_module = any(value == 'modulepreload' for value in rel_values)
            if as_value != 'script' and not is_module:
                continue

            remote_matches = reverse_map.get(href, [])
            remote_url = next(
                (
                    remote for remote in remote_matches
                    if urlparse(remote).scheme in {'http', 'https'}
                    and urlparse(remote).netloc.lower() != site_host
                    and remote not in original_script_urls
                ),
                None,
            )
            if not remote_url:
                continue

            key = (href, is_module)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                'local': href,
                'remote': remote_url,
                'module': is_module,
            })

        if not candidates:
            return

        head = soup.find('head')
        if not head:
            return

        injected = 0
        existing_script_srcs = {
            script.get('src')
            for script in soup.find_all('script', src=True)
            if script.get('src')
        }
        inline_script_blob = '\n'.join(
            script.get_text() or ''
            for script in soup.find_all('script')
            if not script.get('src') and not script.has_attr('data-fetch-interceptor')
        )

        for candidate in candidates:
            local_src = self._prefer_original_root_path(candidate['remote'], candidate['local'])
            local_src = self._to_browser_url(local_src)
            if local_src in existing_script_srcs:
                continue
            if candidate['remote'] in inline_script_blob or local_src in inline_script_blob:
                continue

            script_tag = soup.new_tag('script')
            script_tag['src'] = local_src
            script_tag['data-external-preload-bootstrap'] = 'true'
            if candidate['module']:
                script_tag['type'] = 'module'

            first_script = head.find('script')
            if first_script:
                first_script.insert_before(script_tag)
            else:
                head.append(script_tag)
            existing_script_srcs.add(local_src)
            injected += 1

        if injected:
            self.log(f"   Materializados {injected} script(s) externos a partir de preload")

    def _is_shopify_document(self, soup):
        """Detect Shopify storefront documents that expect a global Shopify bootstrap."""
        if soup.find('meta', attrs={'name': 'shopify-checkout-api-token'}):
            return True
        if soup.find('meta', attrs={'id': 'shopify-digital-wallet'}):
            return True

        html_blob = str(soup)[:250000]
        return 'Shopify.designMode' in html_blob or '/cdn/shop/t/' in html_blob

    def _inject_shopify_bootstrap(self, soup):
        """Provide a minimal Shopify global before inline theme scripts execute offline."""
        if not self._is_shopify_document(soup):
            return

        head = soup.find('head')
        if not head:
            return

        existing_bootstrap = head.find(
            'script',
            attrs={'data-generated-shopify-bootstrap': 'true'},
        )
        if existing_bootstrap:
            return

        script_tag = soup.new_tag('script')
        script_tag['data-generated-shopify-bootstrap'] = 'true'
        script_tag.string = (
            "window.Shopify = window.Shopify || {};"
            "if (typeof window.Shopify.designMode === 'undefined') {"
            "window.Shopify.designMode = false;"
            "}"
        )

        first_script = head.find('script')
        if first_script:
            first_script.insert_before(script_tag)
        else:
            head.insert(0, script_tag)

    def _is_authoring_bootstrap_resource(self, remote_url, local_path=''):
        """Skip builder/editor bootstrap assets from generated runtime maps."""
        haystack = ' '.join(
            value.lower()
            for value in (remote_url or '', local_path or '')
            if value
        )
        markers = (
            'framer.com/edit',
            'framer.com/bootstrap.',
            'app.framerstatic.com/editorbar',
            'app.framerstatic.com/',
            '/assets/edit/',
            '/assets/edit?',
            '/edit/init.mjs',
        )
        return any(marker in haystack for marker in markers)

    def _authoring_import_overrides(self):
        """Provide no-op module overrides for builder-only runtime imports."""
        resource_map = self.network.get_resource_map()
        if not resource_map:
            return {}

        joined_urls = ' '.join(resource_map.keys()).lower()
        if 'framer.com/edit/init.mjs' not in joined_urls and 'app.framerstatic.com/' not in joined_urls:
            return {}

        noop_module = (
            "export function createEditorBar(){"
            "return function FramerEditorBar(){return null;};"
            "}"
            "export default { createEditorBar };"
        )
        stub_specifier = f"data:text/javascript;charset=utf-8,{quote(noop_module)}"
        return {
            'https://framer.com/edit/init.mjs': stub_specifier,
            'http://framer.com/edit/init.mjs': stub_specifier,
        }

    def _runtime_resource_map(self):
        """Filter authoring bootstrap assets from the runtime URL map."""
        resource_map = self.network.get_resource_map()
        if not resource_map:
            return {}

        parsed_base = urlparse(self.base_url)
        same_host = parsed_base.netloc.lower()

        normalized_map = {}
        for remote_url, local_path in resource_map.items():
            normalized_remote = remote_url
            parsed_remote = urlparse(remote_url)

            if (
                parsed_remote.scheme in {'http', 'https'}
                and parsed_remote.netloc.lower() == same_host
                and not parsed_remote.path.startswith('/')
                and parsed_remote.path.startswith('assets/')
            ):
                normalized_remote = parsed_remote._replace(path='/' + parsed_remote.path).geturl()

            normalized_map[normalized_remote] = local_path

        return {
            remote_url: local_path
            for remote_url, local_path in normalized_map.items()
            if not self._is_authoring_bootstrap_resource(remote_url, local_path)
        }

    def _build_import_map(self):
        """Map absolute JS module specifiers to local offline assets."""
        resource_map = self._runtime_resource_map()
        if not resource_map:
            return {}

        imports = {}
        for remote_url, local_path in resource_map.items():
            if not local_path.endswith(('.js', '.mjs')):
                continue

            parsed = urlparse(remote_url)
            if parsed.scheme not in {'http', 'https'}:
                continue

            local_specifier = self._prefer_original_root_path(remote_url, local_path)
            local_specifier = self._to_browser_url(local_specifier)
            imports[remote_url] = local_specifier

            if parsed.scheme == 'https':
                imports[f"http://{parsed.netloc}{parsed.path}"] = local_specifier
            elif parsed.scheme == 'http':
                imports[f"https://{parsed.netloc}{parsed.path}"] = local_specifier

        imports.update(self._authoring_import_overrides())

        return imports

    def _inject_import_map(self, soup):
        """Inject an import map for absolute dynamic imports before scripts execute."""
        imports = self._build_import_map()
        if not imports:
            return

        head = soup.find('head')
        if not head:
            return

        script_tag = soup.new_tag('script')
        script_tag['type'] = 'importmap'
        script_tag['data-generated-importmap'] = 'true'
        script_tag.string = json.dumps({'imports': imports}, ensure_ascii=False)

        first_script = head.find('script')
        if first_script:
            first_script.insert_before(script_tag)
        else:
            head.insert(0, script_tag)

    def _inject_fetch_interceptor(self, soup):
        """Read the JS template, inject resource map, and prepend to <head>."""
        self.log("💉 Injetando fetch interceptor aprimorado...")

        resource_map = self._runtime_resource_map()
        if not resource_map:
            self.log("   Resource map vazio, interceptor não injetado")
            return

        try:
            with open(self._interceptor_js_path, 'r', encoding='utf-8') as interceptor_file:
                js_template = interceptor_file.read()
        except OSError as exc:
            self.log(f"   Erro ao ler fetch_interceptor.js: {exc}")
            return

        map_filename = 'resource-map.json'
        map_path = os.path.join(self.output_dir, 'assets', map_filename)
        try:
            with open(map_path, 'w', encoding='utf-8') as resource_file:
                json.dump(resource_map, resource_file)
        except OSError as exc:
            self.log(f"   Erro ao salvar resource-map.json: {exc}")

        if len(resource_map) > RESOURCE_MAP_INLINE_LIMIT:
            map_load_code = (
                f"const response = await fetch('assets/{map_filename}');\n"
                "    const resourceMap = await response.json();"
            )
        else:
            map_load_code = f"const resourceMap = {json.dumps(resource_map, ensure_ascii=False)};"

        interceptor_script = js_template.replace('/* __RESOURCE_MAP_CODE__ */', map_load_code)

        head = soup.find('head')
        if head:
            script_tag = soup.new_tag('script')
            script_tag['data-fetch-interceptor'] = 'true'
            script_tag.append(NavigableString(interceptor_script))
            import_maps = head.find_all('script', attrs={'type': 'importmap'})
            if import_maps:
                import_maps[-1].insert_after(script_tag)
            elif head.contents:
                head.insert(0, script_tag)
            else:
                head.append(script_tag)
            self.log(f"   Fetch interceptor injetado ({len(resource_map)} mapeamentos)")
        else:
            self.log("   <head> não encontrado, interceptor não injetado")
