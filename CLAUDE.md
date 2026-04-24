# DeepMirror WebSites

Baixa sites com alta fidelidade via **Runtime Network Recording** (Playwright intercepta toda a rede em tempo de execução) para AI Design e Style Transfer. Captura WebGL, Three.js, Rive, SPAs (Next.js, Nuxt, Gatsby) funcionando offline.

**Stack:** Flask + SSE, Playwright, BeautifulSoup, `uv`

## Regras de Ouro

### Network Truth
- Confiar **exclusivamente** em `page.on('response')`. O HTML estático é mentiroso.
- Se o browser requisitou → salvar. Não julgue se é importante.
- Se está no HTML mas deu 404 na rede → ignorar.

### Blind Mapping
- Dict global `{"URL_ORIGINAL": "CAMINHO_LOCAL"}` construído pelo `NetworkRecorder`.
- Find-and-replace **bruto** em todos os arquivos de texto (HTML, CSS, JS, JSON).
- Sem regex de sintaxe de arquivo. Trate tudo como texto. Isso resolve Webflow, React, Three.js, Rive — tudo.

### Minimal Invasion
- Site preservado como é. Não injete CSS agressivo.
- CSS fix **limitado a**: `html/body` (scroll) e loaders (`display: none`).
- **Manter** scripts de framework (Next.js, Nuxt, Gatsby) — funcionam offline com URL rewriting.
- **Remover apenas** scripts de tracking (Analytics, Ads, Chat widgets).
- Não manipule inline styles de elementos individuais (`clip-path`, `transform`, `opacity` são estados legítimos do JS).

### Graceful Failure
- Download **nunca para** por causa de 1 asset. 404/timeout → logar e continuar.
- HTML aponta para arquivo local mesmo que não exista (erro no console, não trava o download).
- Retry: 2 tentativas com backoff exponencial.

## O que NÃO Fazer

- **NÃO** use parse estático (BeautifulSoup) para descobrir recursos — use runtime (Playwright)
- **NÃO** crie funções específicas por site ou biblioteca (`fix_rive_export`, `fix_threejs_textures`)
- **NÃO** use regex complexo para interpretar sintaxe JS — substituição é por string literal de URLs
- **NÃO** force CSS em elementos animados (`opacity`, `transform`, `visibility`, `clip-path`)
- **NÃO** remova `<script>` de framework (Next.js, Nuxt, Gatsby)
- **NÃO** manipule inline styles de elementos individuais
- **NÃO** altere estrutura de pastas ou nomes de arquivos existentes
- **NÃO** crie arquivos auxiliares (scripts, configs, docs) sem pedido explícito
- **NÃO** tente interpretar ou "consertar" lógica de JS minificado

## Fluxo Principal

```
downloader.py → WebsiteDownloader.process()
single_page/app.py → app web oficial
```

1. **Launch** → Playwright abre browser + `page.on('response')` registra TODAS as respostas de rede
2. **Stimulate** → Scroll + mouse interactions + WebGL canvas → trigger lazy loading completo
3. **Capture** → Network idle wait → salva todos assets capturados no disco (`network.save_all_captured_resources()`)
4. **Fallback** → Download de assets do DOM e URLs vistas pelo browser que não foram salvas
5. **Rewrite** → `URLRewriter` faz find-and-replace global de URLs remotas → paths locais em todos os arquivos texto
6. **Post-Process** → `PostProcessor` seleciona baseline HTML (SSR vs DOM capturado), injeta fetch interceptor, remove artefatos runtime
7. **Clean** → `SiteCleaner` gera `raw/` (backup fiel) + `clean/` (otimizado para IA) + `audit/` (snapshots por etapa)

## Pipeline Clean

```
core/clean/manager.py → SiteCleaner.process()
```

| # | Etapa | Módulo |
|---|-------|--------|
| 1 | Snapshot raw → `audit/01_raw` | `manager.py` |
| 2 | HTML: remove tracking, extrai inline `<style>`/`<script>`, externaliza SVGs grandes | `clean_html.py` |
| 3 | CSS: desminifica, deduplica, remove ruído | `clean_css.py` |
| 4 | JS: desminifica, detecta tracking | `clean_js.py` |
| 5 | Inventário de tipos de arquivo (log only) | `file_inventory.py` |
| 6 | Reorganiza assets → `assets/{css,js,fonts,images,...}/nome_curto.ext` | `reorganizer.py` |
| 7 | Corrige paths após reorganização | `path_corrector.py` |
| 7b | CSS consolidado → `globals.css`, `selectors.css`, `fonts.css`, `base.css`, `styles*.css`, `important.css`, `keyframes.css`, `medias/` | `css_consolidator.py` |
| 7c | JS consolidado → `utils*.js` | `js_consolidator.py` |
| 7d | Repara refs pós-rebundle + poda refs HTML quebradas | `finalizer.py` |
| 7e | Poda data assets órfãos | `finalizer.py` |
| 8 | Classificação do site + extractors (computed_styles, coverage, scroll_physics, shaders) | `classifier.py` + `extractors/` |
| 8d | `_ai_context.md` | `ai_context.py` + `css_tokens.py` |
| 8e | Normalização de texto (tabs→espaços, line endings) | `finalizer.py` |
| 9 | Validação de integridade + audit final | `validator.py` |

## Mapa de Arquivos

```
downloader.py                       # Fachada pública: WebsiteDownloader.process()
core/
  __init__.py                       # Constantes e config (.env)
  browser.py                        # BrowserController
  network.py                        # NetworkRecorder
  url_rewrite.py                    # URLRewriter
  fetch_interceptor.js              # Interceptor de fetch/XHR
  ai_context.py                     # Gera _ai_context.md
  audit.py                          # Snapshots textuais do clean
  classifier.py                     # Detecta tipo/framework do site
  post_process/
    core.py
    baseline.py
    transformers.py
    processors.py
    injectors.py
    runtime_cleanup.py
  clean/
    manager.py
    clean_html.py
    clean_css.py
    clean_js.py
    reorganizer.py
    path_corrector.py
    css_consolidator.py
    js_consolidator.py
    css_tokens.py
    finalizer.py
    file_inventory.py
    validator.py
  extractors/
    computed_styles.py
    code_coverage.py
    scroll_physics.py
    shader_extractor.py
single_page/
  app.py                            # Flask + SSE (porta 5001)
  service.py                        # Fluxo single-page isolado
  templates/
  static/
```

## Saída por Site Baixado

```
downloads/site.com/
  serve.py          # Servidor local para visualizar o site
  raw/              # Backup fiel do download original
  clean/            # Versão otimizada para leitura por IA
    index.html
    assets/
      css/          # globals.css, selectors.css, fonts.css, base.css, styles*.css, ...
      js/           # utils*.js + scripts do site
      fonts/
      images/
      media/
      data/
    _ai_context.md
  audit/            # Snapshots de cada etapa do clean pipeline
```

## Comandos Úteis

```bash
# Setup (instala deps + Playwright Chromium)
bash setup.sh

# Servidor web oficial do single-page (porta 5001)
uv run python -m single_page.app

# Uso programático
uv run python -c "
from downloader import WebsiteDownloader
WebsiteDownloader('https://site.com', 'downloads/site.com', print).process()
"

# Re-rodar APENAS o clean (a partir do raw/ existente)
uv run python -c "
from core.clean import clean_site
clean_site('downloads/site.com', print)
"

# Estrutura do site baixado
uv run python development/get_site_structure.py

# Limpar cache Python (resolver bugs de import)
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
rm -rf .venv && bash setup.sh
```

## Configuração (.env)

| Variável | Default | Descrição |
|----------|---------|-----------|
| `DM_BROWSER_TIMEOUT_MS` | 60000 | Timeout de carregamento de página |
| `DM_RESOURCE_TIMEOUT_S` | 15 | Timeout por recurso individual |
| `DM_MAX_RESOURCE_SIZE_MB` | 100 | Limite de tamanho por arquivo |
| `DM_MAX_SCROLL_ITERATIONS` | 20 | Máximo de iterações de scroll |
| `DM_NETWORK_IDLE_SILENCE_MS` | 10000 | Silêncio necessário para idle |
| `DM_CLEAN_MODE` | full | `full` ou `raw-only` |
| `DM_SKIP_DOMAINS` | (analytics, ads, chat) | Domínios ignorados na captura |
| `DM_BROWSER_HEADLESS` | true | Rodar browser sem UI |
