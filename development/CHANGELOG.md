# Changelog

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

## [Unreleased]

### Fixed - Paths seguros para assets/ZIP e controle de concorrência no Playwright

**Objetivo:** evitar falhas de filesystem por nomes/caminhos longos ou caracteres inválidos (`Errno 36`) e reduzir falhas temporárias de inicialização do browser em execuções concorrentes (`Errno 11`/`BlockingIOError`).

- `core/path_safety.py`
  - Adicionado módulo central para normalizar componentes de path em ASCII seguro
  - Componentes e caminhos relativos agora são encurtados com hash estável quando passam dos limites configurados
  - Nomes reservados do Windows, caracteres inválidos e extensões excessivamente longas são tratados antes de escrever arquivos no disco
  - Nomes de arquivo ZIP passaram a usar a mesma política de sanitização por URL

- `core/network.py`
  - Geração de nomes de assets passou a sanitizar host, diretórios e arquivo final antes de salvar em `assets/`
  - Caminhos preservados a partir da URL agora respeitam limite global de comprimento, mantendo hash estável para evitar colisões
  - Fallback hash-based de arquivos com query string também passou a gerar nomes ASCII seguros e curtos

- `downloader.py`
  - `get_site_name()` passou a delegar para o helper seguro de URL, evitando nomes de ZIP longos, Unicode problemático ou caracteres inválidos

- `core/browser.py`
  - Inicialização do browser passou a usar semáforo global com limite configurável por `DM_MAX_CONCURRENT_BROWSERS` (`2` por padrão)
  - `sync_playwright().start()` ganhou retry progressivo configurável para erros temporários de recurso (`DM_BROWSER_LAUNCH_RETRIES` e `DM_BROWSER_LAUNCH_RETRY_DELAY_S`)
  - `close()` ficou idempotente e libera a vaga do semáforo mesmo quando o launch falha parcialmente

- `core/__init__.py` e `.env.example`
  - Adicionadas as configs:
    - `DM_MAX_CONCURRENT_BROWSERS=2`
    - `DM_BROWSER_LAUNCH_RETRIES=3`
    - `DM_BROWSER_LAUNCH_RETRY_DELAY_S=2`

**Validação técnica executada:**
- `uv run python -m py_compile core/path_safety.py core/browser.py core/network.py downloader.py core/__init__.py`
- Teste isolado dos helpers de path com segmentos longos, Unicode e extensões problemáticas
- Teste isolado de `get_site_name()` para URL com acento/espaços no path
- Teste isolado do semáforo do browser confirmando acquire/release com limite default `2`, sem abrir Chromium

**Estado desta entrada:** correção implementada e validada sinteticamente. Confirmação final depende de teste manual do usuário em download real.

### Changed - Robustez da pipeline `clean/` para externalização, rewrite final e serve local

**Objetivo:** corrigir resíduos no `clean/` que ainda deixavam JS/CSS inline, comentários artificiais, refs antigas após reorganização e comportamento inconsistente ao abrir o artefato offline pelo `serve.py`.

- `core/clean/clean_html.py`
  - Extração de inline CSS/JS ajustada para externalizar também scripts gerados pelo próprio runtime do DeepMirror WebSites quando eles não são conteúdo legítimo a preservar no HTML final
  - Remoção de comentários HTML tornada total, sem reinserção de marcadores de seção no output final
  - Promoção de scripts locais `type="text/plain"` ficou mais segura: a heurística de tracking deixou de usar substring bruta em todo o arquivo e passou a reconhecer marcadores fortes de vendor/consent, evitando falso positivo em libs legítimas como `jquery`, `TweenMax` e scripts de formulário
  - Atributos `data-*` vazios deixaram de ser removidos genericamente; o clean preserva flags de runtime como `data-bottom-top=""` e `data-emit-events=""`, que são semanticamente válidas para motores de animação/scroll
  - Serialização final do HTML deixou de depender de `prettify()` e passou a usar saída estável sem whitespace visual entre tags blocantes, evitando quebra de layout em estruturas com `inline-block`

- `core/clean/clean_css.py`
  - Fluxo de limpeza reforçado com minificação segura (`rcssmin`) antes do beautify
  - CSS final passa por desminificação consistente e termina normalizado com newline

- `core/clean/clean_js.py`
  - Minificação removida com `rjsmin` antes da formatação, em vez de pular arquivos `.min`/vendor
  - Comentários gerados pela própria pipeline e placeholders de tracking deixam de reaparecer no JS final
  - Scripts de tracking agora são neutralizados sem deixar comentários residuais no arquivo salvo

- `core/clean/js_consolidator.py`
  - Removidos banners `// ...` inseridos entre scripts mesclados
  - Bundle final usa separador por `;` para manter segurança sintática sem reintroduzir comentários

- `core/clean/path_corrector.py`
  - Rewrite final passou a usar também o `resource-map.json` para remapear URLs remotas exatas em HTML/CSS/JS/JSON
  - Adicionado tratamento específico para `importmap`, reescrevendo apenas os valores dos specifiers para os caminhos finais reorganizados em `assets/js`
  - HTMLs auxiliares capturados em `assets/*.html` agora também entram corretamente no rewrite final de refs locais/remotas
  - Rewrite de JSON passou a parsear payloads válidos antes do remap, cobrindo valores Unicode escapados (`\uXXXX`) que escapavam do replace textual bruto
  - HTML final ganhou uma segunda passada cega de replace literal seguro após a serialização do DOM, fechando refs locais que o parser não normalizava de forma suficiente
  - Reserialização de HTML após correção de paths foi alinhada com a serialização estável do clean, sem reinjetar whitespace entre tags blocantes

- `core/clean/finalizer.py`
  - Etapa final agora remove comentários gerados pelo DeepMirror WebSites de arquivos texto antes da entrega do `clean/`
  - Materialização de aliases de compatibilidade ficou mais restrita: deixa de considerar documentação/mapeamentos gerados pela própria pipeline e passa a exigir referências literais reais de runtime
  - Regravação final de HTML deixou de usar `prettify()`, evitando reintroduzir gaps visuais que quebravam grids/colunas baseados em `inline-block`

- `core/clean/manager.py`
  - Proteção contra tratar `tools/` como conteúdo do site durante recriação do `clean/`
  - Detecção de runtime streaming do Next.js ficou mais estrita para não pular indevidamente a limpeza completa por causa de strings injetadas pelo fetch interceptor

- `core/templates/serve_template.py`
  - `serve.py` gerado passou a priorizar arquivos locais explícitos (`/`, `/index.html`, aliases locais existentes) antes de consultar o `resource-map.json`
  - **Causa raiz:** o servidor estava resolvendo `/` para um HTML auxiliar mapeado no `resource-map`, servindo a página errada no smoke offline e induzindo 404s/erros de runtime que não pertenciam à homepage limpa

- `core/__init__.py`
  - `fbq` incluído na lista global de padrões de tracking para remover bootstrap inline de pixel que ainda escapava para bundles `utils*.js`

- `core/post_process/processors.py`
  - Preloads de script passaram a ser removidos quando o HTML final mantém o recurso correspondente como `type="text/plain"`, eliminando warnings de `link preload` inútil no `raw`
  - Blocos `application/ld+json` contaminados por notices/HTML do servidor passam a ser descartados, preservando apenas JSON-LD válido

- `pyproject.toml`
  - Dependências adicionadas para suportar limpeza/desminificação mais efetiva de CSS/JS: `rcssmin`, `rjsmin`, `jsbeautifier`

**Validação técnica executada:**
- Rebuild de ambiente via `bash setup.sh` após limpeza de `.venv`, `__pycache__` e `.pyc`
- `clean_site('downloads/don-barber.gr_en')` reexecutado múltiplas vezes sobre o site já baixado
- Fluxo completo reexecutado em `https://don-barber.gr/en/` com geração nova de `raw/`, `clean/`, `audit/` e `serve.py`
- `uv run python development/get_site_structure.py`
- Smoke em browser com Playwright headless sobre `downloads/don-barber.gr_en/clean/serve.py`
  - `GET /` servindo a homepage correta
  - `console` sem erros de runtime
  - `pageErrors`: 0
  - `requestFailed`: 0
  - `badResponses`: 0
  - Hero inicial voltou a renderizar com as duas colunas lado a lado (`#video-holder` em `left=0` e `#intro-right-box` em `left=720` no viewport desktop 1440x900)
  - `jQuery`, `TweenMax`, `skrollr` e `Modernizr` confirmados ativos no browser após o clean
- Smoke adicional em browser com Playwright headless sobre `downloads/don-barber.gr_en/raw/serve.py`
  - `preloadWarnings`: 0 para o caso de `blankshield.min.js` e demais scripts desativados
  - `console`: sem warnings/erros
- Rodadas extras de `clean_site('downloads/don-barber.gr_en')` após correções no rewrite final
  - Validação interna caiu de `16 refs quebradas` para `OK` (`338 refs verificadas — 0 quebradas`)

**Estado desta entrada:** registro técnico. Confirmação final depende de teste manual do usuário.

### Changed - Separação final entre `single_page`, `core` e deploy web oficial

**Objetivo:** fechar a refatoração arquitetural deixando o `single_page` como app web oficial do projeto e o `core`.

- `README.md`
  - Documentação principal simplificada para refletir o estado real atual
  - O fluxo oficial de uso/deploy agora aponta explicitamente para `single_page`

- `Dockerfile`
  - Mantido como imagem do app web oficial, isto é, do `single_page`
  - O deploy containerizado do repositório permanece focado somente na interface web single-page

- `compose.dev.yml`
  - Compose preservado como stack do app web single-page

- `entrypoint.sh`
  - Continua iniciando `gunicorn single_page.app:app` como entrypoint oficial de deploy

- `FUTURE.md`
  - Registrados os blocos necessários para uma futura versão web multiusuário com cookies, login manual e browser remoto por sessão

- `app.py`
  - Fachada compatível da raiz removida
  - **Decisão:** evitar um segundo entrypoint ambíguo agora que o app web real mora em `single_page/app.py`

**Estado desta entrada:** refletido em documentação, entrypoints e artefatos de deploy.

### Fixed - Tela Preta em Sites WebGL com Renderer Customizado (Active Theory / HYDRA)

**Objetivo:** corrigir a tela preta persistente no `activetheory.net` onde o site carregava os scripts mas o canvas WebGL nunca ficava visível.

- `website_downloader/post_process/runtime_cleanup.py`
  - `_remove_canvas_snapshots` estendido para detectar também canvases WebGL de renderers customizados que **não** usam Three.js e portanto não recebem o atributo `data-engine`
  - Nova heurística: canvas com `width` + `height` HTML attributes **e** `pointer-events: none` no inline style é tratado como snapshot renderizado e removido do DOM salvo
  - **Causa raiz:** o Playwright captura a DOM após hidratação completa, incluindo o `<canvas>` WebGL que o runtime Active Theory (HYDRA, não Three.js) insere dentro de `<div class="Container">`. Quando o app re-executa offline, `Container.instance()` cria um **novo** elemento via `Stage.add($this)` e o acrescenta ao `#Stage`. O antigo `<div class="Container">` (com o canvas capturado de 1920×1080 px) permanecia no DOM — não existia em `data-engine` para o filtro anterior detectar. Como `#Stage` tem `overflow: hidden`, o novo canvas era empurrado para além do viewport e ficava completamente oculto atrás do canvas estático preto.
  - A nova condição captura esse padrão: `pointer-events: none` é o sinal universal que renderers WebGL aplicam ao canvas para deixar eventos de mouse passarem para a DOM subjacente, independente do engine usado.

- `downloads/activetheory.net/raw/index.html`
  - Canvas capturado removido diretamente da versão salva atual para validação imediata sem re-download

**Validação:** confirmado pelo usuário após aplicar o fix manual no HTML salvo — o site carregou a cena WebGL normalmente.

**Estado desta entrada:** ✅ Confirmado pelo usuário.

### Changed - Suporte a Range Requests e Servidor Concorrente no serve.py

**Objetivo:** corrigir vídeos que falhavam com `ERR_ABORTED` ao carregar sites com `<video>` offline, e evitar que o servidor fique bloqueado ao servir múltiplas conexões simultâneas.

- `templates/serve_template.py` (e `downloads/activetheory.net/raw/serve.py`)
  - Adicionado método `_serve_range(fs_path, range_header)` que responde com HTTP 206 Partial Content para requests com header `Range: bytes=N-M`
  - `do_GET` refatorado para extrair resolução de caminho em `_resolve_and_set_path()` e redirecionar Range requests antes de chamar `super().do_GET()`
  - `end_headers` agora envia `Accept-Ranges: bytes` em todas as respostas, sinalizando suporte ao browser
  - Servidor trocado de `socketserver.TCPServer` (single-threaded) para `socketserver.ThreadingTCPServer` com `daemon_threads = True`
  - **Causa raiz:** `SimpleHTTPRequestHandler` não suporta Range requests. Chrome envia `Range: bytes=0-` para elementos `<video>` para obter o tamanho do arquivo antes de reproduzir. Sem resposta 206, o browser retentava várias vezes e abortava com `ERR_ABORTED`. O `TCPServer` single-threaded bloqueava novas conexões enquanto servia arquivos grandes (ex: `reel.mp4` 18MB), impedindo inclusive que o Playwright se conectasse.

**Validação:** com o novo serve.py, `reel.mp4` passa a ser servido como `206 Partial Content` imediatamente (visível nos logs do servidor).

**Estado desta entrada:** registro técnico. Confirmação final depende de teste manual do usuário.

### Changed - Fix de Scrollbar Incorreto em Sites com Container de Scroll Customizado

**Objetivo:** eliminar a barra de scroll visível que aparecia no `activetheory.net` (e outros sites com `FXScroll`/container scroll customizado) que não existe no site original.

- `website_downloader/post_process/runtime_cleanup.py`
  - O CSS injetado pela `_fix_scroll_blocking` quando `uses_runtime_scroll=True` agora inclui regras para ocultar o scrollbar nativo em elementos com `overflow` + `scroll` inline
  - Regras adicionadas: `[style*="overflow"][style*="scroll"]::-webkit-scrollbar { display: none !important }` + `scrollbar-width: none !important` (Firefox)
  - **Causa raiz:** o `FXScroll` tem `overflow: hidden scroll` que força um scrollbar de 8px. No site original o scrollbar era invisível graças ao CSS `--baropacity: 0.0`. No Linux com Chrome, a track do scrollbar pode apresentar alguma renderização visual mesmo com `background: 0 0`, tornando o scrollbar perceptível em modo offline. Ocultar o scrollbar nativo não afeta o scroll por JS (`element.scrollTop` continua funcional).

- `downloads/activetheory.net/raw/index.html`
  - Mesma correção aplicada diretamente na tag `<style data-scroll-fix="true">` existente

**Estado desta entrada:** registro técnico. Confirmação final depende de teste manual do usuário.

### Changed - Fix de Scroll para Sites com Viewport WebGL/Canvas Custom

**Objetivo:** corrigir scrollbars incorretos e HERO invisível no `activetheory.net` causados pela injeção de `overflow: auto !important; height: auto !important` em sites que usam container de scroll customizado em vez do scroll nativo do browser.

- `post_process/runtime_cleanup.py`
  - `_uses_runtime_scroll_container` ganhou detecção de elementos `position: fixed; width: 100%; height: 100%` com `overflow: scroll` em inline style
  - **Causa raiz:** `activetheory.net` usa `<div class="FXScroll" style="position: fixed; ... overflow: hidden scroll">` como container de scroll customizado para o runtime WebGL; a função não detectava esse padrão proprietário e retornava `False`, fazendo a `_fix_scroll_blocking` injetar `html, body { overflow: auto !important; height: auto !important }` que sobrescrevia a arquitetura intencional do site e exibia scrollbars do browser onde não deveria

- `clean/clean_html.py`
  - A extração de `<style>` para CSS externo agora pula tags com `data-scroll-fix="true"` (injetadas pelo DeepMirror WebSites, não conteúdo original)
  - **Causa raiz:** o CSS do scroll-fix era extraído como `index_style_N.css` e depois mesclado no `important.css` pelo consolidator, persistindo `overflow: auto !important; height: auto !important` no `clean/` mesmo após o fix no `PostProcessor`

**Validação técnica (Playwright headless):**
- `html_overflow: hidden` ✓ — preservado como o site espera
- `body_overflow: hidden` ✓
- `fxscroll_overflow: hidden scroll` ✓ — container de scroll customizado funcionando
- `scroll_fix_injected: False` ✓ — CSS problemático não injetado

**Estado desta entrada:**
- Registro técnico apenas
- Nenhum item foi marcado como resolvido aqui; a confirmação final continua dependente do teste manual do usuário

### Changed - Fix de "Asset timed out undefined" no Fetch Interceptor

**Objetivo:** eliminar o aviso `Asset timed out undefined` que aparecia no console ao carregar `activetheory.net` offline.

- `website_downloader/fetch_interceptor.js`
  - `neutralizeDuplicateNode` agora usa exclusivamente `node.dispatchEvent(new Event('load'))` para notificar o app que o asset duplicado foi processado
  - **Causa raiz:** a implementação anterior chamava `node.onload(loadEvent)` manualmente, onde `loadEvent` era criado com `new Event('load')` sem contexto de dispatch — assim `event.target` era `null`. A callback do app lia `event.target.src` para obter a URL do asset e recebia `undefined`, que era passado para `timedOut(undefined)`. O `dispatchEvent` define `event.target = node` automaticamente antes de invocar os listeners, resolvendo o problema.

**Validação Playwright (2 minutos, headless):**
- `Asset timed out` → 0 ocorrências ✓
- Warnings residuais esperados: `reel.mp4` (soft 404 remoto), `UnsupportedRedirect bypass`, `font missing char /`, `CookieNotice timing`

**Estado desta entrada:**
- Registro técnico apenas
- Nenhum item foi marcado como resolvido aqui; a confirmação final continua dependente do teste manual do usuário

### Changed - Fix de CSS Aliases Duplicados e Modo Headless

**Objetivo:** corrigir CSS files do `clean/` que apareciam fora de `assets/css/` e restaurar o modo headless como padrão.

- `website_downloader/__init__.py`
  - Default de `BROWSER_HEADLESS` alterado para `True`; o browser agora roda headless por padrão sem abrir janela
  - Adicionado `--disable-blink-features=AutomationControlled` em `DEFAULT_BROWSER_ARGS` para remover o marker `navigator.webdriver=true` que sites usam para detectar automação

- `website_downloader/browser.py`
  - Adicionado `add_init_script` no context que sobrescreve `navigator.webdriver → undefined` e spoofa o vendor/renderer WebGL de "SwiftShader" para "Intel Iris OpenGL Engine"
  - **Causa raiz da falha headless:** `activetheory.net` detectava `navigator.webdriver=true` e/ou o renderer "SwiftShader" e abortava a inicialização WebGL sem criar canvas nem requestar assets; com stealth o WebGL inicializa normalmente e 765 recursos são capturados idêntico ao modo headful

- `website_downloader/fetch_interceptor.js`
  - Removido `node.removeAttribute('src')` da neutralização de scripts duplicados; o `src` agora é mantido intacto enquanto apenas o `type` é alterado para `application/json`
  - **Causa raiz:** ao remover o `src`, a callback interna do app (`onload` / timeout handler) recebia `undefined` como URL do asset, gerando o log `Asset timed out undefined` no console web
  - O browser não executa `<script type="application/json" src="...">`, então re-execução dupla continua prevenida

- `website_downloader/clean/finalizer.py`
  - Removido `.css` de `_RUNTIME_ALIAS_EXTENSIONS`
  - **Causa raiz:** `materialize_runtime_aliases` processava entradas em ordem alfabética; a entrada `assets/css/index_style_1.css → assets/css/styles.css` criava o alias antes da entrada `index_style_1.css → assets/css/index_style_1.css` ser avaliada, fazendo com que `new_path` passasse a existir e o alias do root fosse criado incorretamente
  - CSS é sempre referenciado de forma estática — `path_corrector` e `repair_css_references` já tratam todas as referências; aliases de runtime não são necessários para CSS

**Validação técnica:**
- `find downloads/activetheory.net/clean -name "*.css" -not -path "*/assets/css/*" -not -path "*/audit/*"` retornou vazio após reprocessamento
- `BROWSER_HEADLESS` confirmado como `True` por default

**Estado desta entrada:**
- Registro técnico apenas
- Nenhum item foi marcado como resolvido aqui; a confirmação final continua dependente do teste manual do usuário

### Changed - Follow-up de Runtime Capture, Clean Relinking e Validação Manual Assistida

**Objetivo:** consolidar a rodada de manutenção focada em `terrabites.eu`, `revolut.com/pt-BR`, `palmer-dinnerware.com` e `activetheory.net`, sem marcar nada como resolvido antes da validação manual final.

- `browser.py`
- Scroll de captura ganhou settle adicional no fundo da página com ida, leve subida e nova descida antes do retorno ao topo
- O launch do browser passou a respeitar `DM_BROWSER_HEADLESS`, permitindo capturas headful para sites com bloqueio/feature-detection agressivo

- `post_process/transformers.py`
- Contêineres ricos em `<div>` passaram a ser restauráveis mesmo quando o runtime deixa apenas wrappers vazios, cobrindo casos como `#contact-home`

- `clean/path_corrector.py`
- Reescrita de literais locais em HTML/JS ficou mais agressiva e mais segura para caminhos reorganizados
- Passou a corrigir literais inline em `<script>` e a resolver aliases implícitos de `assets/` para requests root-relative
- O parser de `srcset` foi endurecido para não quebrar candidatos com espaços ou nomes mais sensíveis

- `clean/clean_html.py`
- Preserva `importmap`, `__NEXT_DATA__` e scripts internos críticos do bootstrap offline

- `clean/clean_js.py`
- Evita limpeza destrutiva em bundles minificados/vendor, reduzindo corrupção de runtime em sites React/Next

- `clean/css_consolidator.py`
- Deixou de colapsar `@import` locais necessários durante a consolidação

- `clean/js_consolidator.py`
- Agrupamento passou a respeitar ordem/contiguidade real dos scripts no HTML, reduzindo quebra por dependência de carregamento

- `templates/serve_template.py`
- Ganhou fallback global para assets reorganizados com basename compatível, cobrindo requests gerados em runtime que não preservam exatamente a árvore original

- `website_downloader/__init__.py`
- Perfil compartilhado de browser foi centralizado para runtime/extractors, incluindo modo headful quando configurado e sem `--disable-gpu`

**Validação manual assistida nesta rodada:**
- `terrabites.eu`: o pacote validado abriu sem `pageerror`, o `#contact-home` apareceu no final da página, e o servidor local respondeu `200` para os CSS/JS/imagens principais do `clean/`
- `revolut.com/pt-BR`: não reapareceram os erros reportados de `textContent === null` e `Invalid regular expression`; os assets locais verificados (`img_047.png`, `media_005.mp4`) responderam `200`, embora ainda restem erros React minificados para investigação futura
- `palmer-dinnerware.com`: `gsap is not defined` e os erros de parse de `srcset` não reapareceram; no browser local restou apenas um `403` externo
- `activetheory.net`: o `clean/` abriu na home real e `UnsupportedRedirect.unsupported()` retornou `false`; permaneceu apenas o aviso/runtime de mídia não suportada para `reel.mp4`
- `uv run python development/get_site_structure.py` executado novamente após regenerar os artefatos

**Estado desta entrada:**
- Registro técnico apenas
- Nenhum item foi marcado como resolvido aqui; a confirmação final continua dependente do teste manual do usuário

### Changed - Activetheory Runtime Retry, Clean Alias Compatibility and Extension Diff

**Objetivo:** remover quebras offline restantes do `activetheory.net` sem voltar para parse estático, reforçando captura por runtime, relink do `clean/` e comparação `raw` vs `clean` em estruturas divergentes.

- `network.py`
- Assets descobertos dentro de arquivos salvos passaram a incluir `.json` e `.webmanifest`, além de JS
- A varredura textual foi ampliada para mais extensões de imagem, mídia, fontes e dados, incluindo referências em formato de basename
- Falhas transitórias de captura do Playwright agora são tratadas como retryables no fallback, em vez de bloquear permanentemente o download daquela URL
- Sucessos posteriores limpam o estado de falha da mesma URL para evitar falso negativo acumulado entre captura e fallback

- `downloader.py`
- A fila final de fallback deixou de excluir URLs com falha retryable, permitindo recuperar assets que o runtime requisitou mas o `Network.loadNetworkResource` não conseguiu salvar na primeira passada

- `browser.py`
- A coleta de assets dinâmicos no DOM passou a inspecionar também `<script>` inline e `<style>`, capturando literais locais usados por runtimes que montam paths sem deixá-los em atributos HTML tradicionais

- `clean/path_corrector.py`
- Reescrita de caminhos passou a cobrir `.json` e `.webmanifest`, preservando o blind mapping também nesses artefatos de dados

- `clean/finalizer.py`
- O `clean/` agora pode materializar aliases locais de compatibilidade para JS/CSS/JSON/fonts reorganizados, cobrindo requests montados em runtime que continuam apontando para o path antigo

- `clean/manager.py`
- A materialização de aliases foi encaixada no pipeline final antes da poda de referências faltantes, reduzindo `404` falsos após reorganização e rebundle

- `development/diff_raw_clean_extensions.py`
- Nova variante do diff `raw` vs `clean` por extensão agregada, comparando total de arquivos, linhas, bytes e tokens por tipo em vez de depender de matching arquivo a arquivo
- Suporta saída `text/json`, filtro por extensões e contagem de tokens via `tiktoken`

- `pyproject.toml`
- `tiktoken` foi adicionado para habilitar a comparação de tokens no novo diff agregado

**Validação manual assistida nesta rodada:**
- `activetheory.net`: fontes atlas, texturas e mídias críticas que antes ficavam faltando passaram a existir em disco no `raw/` e no `clean/`
- `activetheory.net`: o `clean/` deixou de quebrar por ausência de bundle reorganizado referenciado em runtime, após materialização dos aliases locais
- `activetheory.net`: `unsupported.html` e `unsupported-bg.jpg` foram restaurados no pacote atual para eliminar a queda incorreta na tela de fallback por falta desses arquivos
- `activetheory.net`: no estado atual, `raw/` e `clean/` convergiram para o mesmo comportamento residual, restando `TypeError: Failed to fetch` no app e o aviso/pageerror de mídia não suportada
- `uv run python development/diff_raw_clean_extensions.py --raw-dir downloads/activetheory.net/raw --clean-dir downloads/activetheory.net/clean --tokens --sort impact` executado com sucesso
- `uv run python development/get_site_structure.py` executado novamente após os ajustes

**Estado desta entrada:**
- Registro técnico apenas
- Nenhum item foi marcado como resolvido aqui; a confirmação final continua dependente do teste manual do usuário

### Changed - Runtime Fallback por Família de Extensão e Diff Semântico de Tokens

**Objetivo:** cobrir requests tardios cujo basename permanece o mesmo mas a extensão diverge no pacote offline, além de medir melhor o ganho real de leitura entre `raw/` minificado e `clean/` organizado.

- `fetch_interceptor.js`
- Lookup por basename ganhou fallback adicional por stem + família de extensão, cobrindo casos como `lab.gif -> lab.jpg` e `damaged_road_normal.jpg -> damaged_road_normal.png` quando o match é inequívoco
- A mesma lógica foi aplicada também à resolução de imports/paths relativos antes de o request sair para a rede local

- `templates/serve_template.py`
- O fallback global do servidor local deixou de exigir extensão idêntica e passou a aceitar famílias compatíveis para imagens, mídia e fontes, preservando o match único por basename/prefixo
- Quando há mais de um candidato compatível, o servidor agora desempata pelo caminho mais próximo da árvore requisitada, cobrindo casos como `assets/images/pbr/damaged_road_normal.jpg`

- `development/diff_raw_clean_extensions.py`
- Ganhou `--view semantic`, separando `markup_style`, `data_structured`, `js_app_readable`, `js_app_minified`, `js_vendor_readable` e `js_vendor_minified`
- O resumo agora destaca `Leitura prioritária para AI` vs `Suporte / runtime / ruído`, ajudando a medir ganho de tokens úteis mesmo quando o `raw/` está minificado e o `clean/` replica aliases de compatibilidade

**Validação manual assistida nesta rodada:**
- `activetheory.net/clean`: o handler do servidor local respondeu `200` para `/assets/images/lab.gif` e `/assets/images/pbr/damaged_road_normal.jpg`, entregando respectivamente `image/jpeg` e `image/png` via fallback compatível
- `activetheory.net/raw`: com espera longa no Playwright, os `404` tardios dessas duas imagens não reapareceram; o comportamento residual observado ficou concentrado em `reel.mp4` abortado no browser e em `TypeError: Failed to fetch` após navegação para `unsupported.html` em ambiente headless
- `uv run python development/diff_raw_clean_extensions.py --raw-dir downloads/activetheory.net/raw --clean-dir downloads/activetheory.net/clean --view semantic --tokens --sort impact` executado com sucesso

**Estado desta entrada:**
- Registro técnico apenas
- Nenhum item foi marcado como resolvido aqui; a confirmação final continua dependente do teste manual do usuário

### Changed - Bypass Local de Unsupported Redirect e Prefix Matching de Runtime

**Objetivo:** impedir que runtimes locais caiam em `unsupported.html` por feature-detection agressivo em browsers modernos, mantendo a correção genérica e focada no comportamento do `raw/`.

- `post_process/injectors.py`
- Novo `runtime compat shim` injetado antes do bootstrap da app
- O shim bloqueia redirects locais para `unsupported.html` apenas em hosts locais e apenas quando o browser oferece um conjunto moderno mínimo de capacidades
- A mesma camada também intercepta `UnsupportedRedirect.unsupported()` quando o runtime classifica incorretamente um browser moderno/local como não suportado

- `post_process/core.py`
- O shim passou a ser injetado junto do import map e do fetch interceptor, antes da inicialização efetiva do bundle principal

- `fetch_interceptor.js`
- Matching por stem foi ampliado para aceitar também prefixos separados por `.` e `-`, cobrindo requests como `uil.1746999829739.json -> uil_<hash>.json`
- Neutralização de `<link>` duplicado deixou de apagar `href`, reduzindo warnings de `preload` inválido no console

**Validação manual assistida nesta rodada:**
- No `raw` restaurado do `activetheory.net`, a navegação principal permaneceu em `/` e não voltou a redirecionar para `unsupported.html`
- O console registrou `"[Runtime Compat] bypassed UnsupportedRedirect.unsupported() on local modern browser"` durante a validação headless
- Após restaurar `assets/data/uil.1746999829739.json`, `assets/data/uil.json` e os atlas `NBArchitektStd-*.png`, os `404` locais desses arquivos desapareceram na validação do `raw`
- No estado atual do pacote restaurado, o residual principal ficou concentrado em `reel.mp4` abortado no browser e em algumas mídias externas do `storage.googleapis.com`, enquanto `unsupported.html` deixou de ser o fluxo dominante

**Estado desta entrada:**
- Registro técnico apenas
- Nenhum item foi marcado como resolvido aqui; a confirmação final continua dependente do teste manual do usuário

### Changed - Offline Fidelity for Runtime Assets and Dynamic DOM Recovery

**Objetivo:** corrigir falhas genéricas de fidelidade offline em sites com `srcset` dinâmico, CSS com assets relativos, seções esvaziadas pelo runtime e runtimes de scroll/SPA sensíveis ao estado salvo no DOM.

- `url_rewrite.py`
- Passa a reescrever `url(...)` de CSS para caminhos browser-safe preservando estrutura local completa em vez de reduzir para basename
- Corrige lookup de assets com fragmento (`#iefix`, `#Flaticon`) e mantém o fragmento no path final
- Reescreve CSS salvo em disco usando também a URL original do próprio arquivo CSS, cobrindo referências relativas como fontes e imagens de temas Drupal/WordPress/Next

- `network.py`
- Normaliza URLs com fragmento antes de consultar cache/capturas/fallback, evitando perder assets cujo request real foi salvo sem hash fragment
- Quando encontra a versão sem fragmento, cria alias para a URL original e mantém o mapping consistente no `resource_map`

- `post_process/processors.py`
- `srcset` local agora é percent-encoded antes de ir para o HTML, evitando quebra de candidatos quando o nome do arquivo contém vírgulas ou espaços
- O cleanup de scripts de tracking passou a preservar scripts de dados/bootstraps críticos como `__NEXT_DATA__`, `importmap` e o fetch interceptor
- CSS pós-processado agora pode sobrescrever o arquivo salvo originalmente, para que rewrites de `url(...)` realmente cheguem ao disco

- `fetch_interceptor.js`
- Reescrita de `srcset` em runtime agora codifica URLs locais com segurança, cobrindo também alterações feitas pelo browser depois do download inicial

- `post_process/runtime_cleanup.py`
- Detecta sites com container de scroll dedicado e reduz a injeção de CSS global para não quebrar runtimes como `fullpage.js`, `scrolloverflow`, `locomotive` e similares
- Remove classes e atributos transitórios de runtimes de layout quando eles não existiam no HTML original, permitindo reinicialização limpa offline

- `post_process/baseline.py` e `post_process/transformers.py`
- Baseline ganhou heurística adicional para detectar perda real de conteúdo entre HTML original e DOM capturado
- Contêineres ricos do HTML original que foram deixados ocos pelo runtime passam a ser restaurados automaticamente antes da serialização final

**Validação manual nesta rodada:**
- `terrabites.eu`: sem `pageerror` no Playwright após restaurar seções de produto, corrigir CSS relativo e limpar estado transitório do `fullpage.js`
- `revolut.com/pt-BR`: sem `TypeError` de `__NEXT_DATA__`; validação correta via `raw/serve.py` entregou `200` para a árvore `/_next/static/...`
- `palmer-dinnerware.com`: sem `pageerror`; a correção de `srcset` com vírgula eliminou a quebra local dos candidatos de imagem
- `uv run python development/get_site_structure.py` executado novamente após os redownloads finais

### Changed - Clean Pipeline: CSS/JS Rebundle + AI Context Compaction

**Objetivo:** reduzir ruído estrutural no `clean/` sem quebrar a genericidade do pipeline, deixando o material mais navegável para IA e mais fácil de auditar.

**Etapa 7a — Asset Reorganizer (mantida e consolidada):**
- Strip de hash trailing (`.a3f2c1b2`) e prefixos Webflow/CDN (`67b5a02d_`) nos nomes
- Renomeação sequencial por tipo quando o stem continua aleatório ou longo: `img_001.webp`, `font_001.woff2`, `script_001.js`
- Arquivos HTML e metadados `_*.json`/`.md` continuam fixos na raiz do `clean/`

**Etapa 7b — CSS Consolidator (`clean/css_consolidator.py`) refeito:**
- Agora processa **todo** o CSS em `assets/css/`, não só `*_style_N.css`
- Separa regras globais de tags/universais em `globals.css`
- Separa listas densas de seletores com poucas declarações em `selectors.css`
- Separa `@font-face` e regras tipográficas simples em `fonts.css`
- Mantém `:root`, `html` e `body` em `base.css`
- Extrai todos os `@keyframes` para `keyframes.css`
- Separa declarações `!important` em `important.css`, preservando no arquivo original apenas o que não é `!important`
- Agrupa blocos `@media` em `assets/css/medias/base_medias.css` e cria `media_XXX.css` para blocos grandes
- Deduplica regras por assinatura de declarações, mesmo quando a ordem das propriedades muda
- Mescla o restante em chunks `styles.css`, `styles_002.css`, ... com alvo de ~1000 linhas por arquivo
- Mantém o reparo de links como etapa separada para aparecer explicitamente no `audit/`

**Etapa 7c — JS Consolidator (`clean/js_consolidator.py`) ajustado:**
- Agora escolhe candidatos a partir das referências reais do HTML, não só do nome do arquivo
- Mescla scripts pequenos em `utils.js`, `utils_002.js`, ... quando necessário
- Preserva atributos compatíveis da tag `<script>` ao reinserir os bundles no HTML
- Remove os originais mesclados ainda na etapa de redução
- A troca de referências HTML agora ocorre em etapa dedicada, separada da redução de arquivos
- Isso torna visível no `audit/` a diferença entre “rebundle” e “reparo de links”

**SVG inline agora vira asset real:**
- SVGs grandes são exportados como `inline_svg_<hash>.svg`
- O HTML limpo passa a apontar para esses arquivos com `<img src=\"...\">`
- Os paths seguem pela reorganização normal e entram no `audit/`

**Nova finalização genérica (`clean/finalizer.py`):**
- Remove refs locais quebradas em HTML depois do rebundle
- Remove arquivos órfãos de `assets/data` quando não são referenciados e não são Lottie
- Normaliza tabs de indentação para espaços
- Corrige terminadores de linha incomuns (`CR`, `LS`, `PS`) no final do pipeline
- Remove sidecars de contexto já absorvidos em `_ai_context.md`

**Audit expandido para 11 estágios:**
- `07_after_file_reduction` mostra a redução real de CSS/JS
- `08_after_bundle_reference_repair` mostra o reparo das referências
- `09_after_data_pruning` registra a remoção de `assets/data` inútil
- `10_after_text_normalization` registra a normalização final de texto
- `11_final` passa a refletir o `clean/` efetivamente validado

**Validação manual após reprocessamento a partir de `raw/`:**
- `landonorris.com`: validação final `OK`, `595` refs verificadas, `30 -> 16` arquivos CSS e `13 -> 7` arquivos JS no `clean/`
- `pocketchangethe.world`: validação final `OK`, `341` refs verificadas, `6 -> 11` arquivos CSS e `98 -> 27` arquivos JS no `clean/`
- Ambos abriram localmente sem erros de console via Playwright do ambiente isolado do projeto
- O MCP Playwright continuou indisponível neste ambiente porque tenta usar um Chrome de sistema ausente e a instalação pede `sudo`

**Correções de HTML:**
- `path_corrector.py` reescrito para usar `prettify()` + conversão 2-space (antes usava `str(soup)` que minificava)
- Todos os HTMLs em `clean/` agora têm indentação consistente de 2 espaços

**Arquivos removidos do output final:**
- `_clean_summary.json`, `_code_coverage.json`, `_file_inventory.json`
- `_structure.json`, `_validation_report.json`, `_resets.css`, `_path_mapping.json`
- `_scroll_physics.json` → substituído por `_scroll_physics.md`
- `_site_classification.json`, `_computed_styles.json`, `_site_tokens.md`, `_scroll_physics.md` → absorvidos por `_ai_context.md`

**Estrutura atual de saída (`clean/`):**
```
downloads/site.com/
├── raw/                          # Backup fiel
└── clean/                        # Otimizado para IA
    ├── index.html                # 2-space indent, limpo
    ├── assets/
    │   ├── css/
    │   │   ├── globals.css       # Regras globais de tags/universais
    │   │   ├── selectors.css     # Muitos seletores, poucas declarações
    │   │   ├── fonts.css         # @font-face + tipografia simples
    │   │   ├── base.css          # :root, html, body e base estrutural
    │   │   ├── styles.css        # Chunk principal de componentes
    │   │   ├── styles_002.css    # Chunks adicionais quando necessário
    │   │   ├── important.css     # Apenas declarações !important
    │   │   ├── keyframes.css     # Todos os @keyframes
    │   │   └── medias/
    │   │       ├── base_medias.css
    │   │       └── media_001.css
    │   ├── js/
    │   │   ├── utils.js          # Scripts inline pequenos consolidados
    │   │   ├── utils_002.js      # Segundo grupo de atributos, se existir
    │   │   └── script_001.js     # Bibliotecas (nome encurtado, sem hash)
    │   ├── fonts/font_001.woff2
    │   ├── images/img_001.webp
    │   ├── icons/icon_001.svg
    │   ├── models/model_001.glb
    │   └── animations/anim_001.riv
    ├── _shaders/                 # GLSL extraídos (WebGL)
    ├── _ai_context.md            # Contexto consolidado para IA
    └── serve.py                  # Servidor local da versão clean/raw
```

---

### Changed - Pipeline Refactoring: Zero-Config, Fully Automated Design System Generation

**Objetivo:**
- Transformar o pipeline de processamento para 100% automático e genérico
- Eliminar configurações hardcoded (`SiteConfig`)
- Automatizar extração de runtime (computed styles, scroll physics, shaders)
- Gerar contexto AI-ready consolidado

**Arquitetura do Pipeline:**
Ordem canônica: CAPTURAR → CLASSIFICAR → PROCESSAR → DESTILAR → INSTRUIR → EMPACOTAR

**Etapa 1 - Site Classifier:**
- Novo módulo `website_downloader/classifier.py` para detecção automática
- Detecta tipo de site: static, spa, webgl, rive, lottie, scroll-jacking
- Identifica framework: next, nuxt, gatsby, react-router, webflow, framer, vanilla
- Salva resultado em `clean/_site_classification.json`

**Etapa 2 - Extractors Integration:**
- Integrados no pipeline principal (`clean/manager.py`)
- Executam automaticamente após limpeza:
  - `computed_styles` → `clean/_computed_styles.json`
  - `scroll_physics` → `clean/_scroll_physics.md` (se scroll-jacking detectado)
  - `shader_extractor` → `clean/_shaders/` (se WebGL detectado)
- Graceful failure: pipeline continua se extractor falhar

**Etapa 5 - AI-Ready Context:**
- Novo módulo `website_downloader/ai_context.py`
- Gera `clean/_ai_context.md` consolidado para IA
- Consolida: classificação, tokens CSS, computed styles, scroll physics, assets

## [1.0.0] - 2024-Q4

### Changed - Modularização Completa do Downloader

**Mudança:** Refatorado `downloader.py` monolítico (~920 linhas) para arquitetura modular em 3 módulos:
- `browser.py`: Controle do Playwright (launch, scroll, iframes, cookies)
- `network.py`: Interceptação de rede, salvamento, retry logic
- `post_process.py`: Processamento HTML/CSS, limpezas, SPA frameworks

**Interface pública preservada 100%:** Nenhuma mudança nos imports ou comportamento externo.

### Added - Captura e Processamento Robusto de Assets

**Interações com Elementos:**
- Simulação automática de mouse hover para trigger de lazy loading
- Detecção e interação com canvases WebGL (hover em 5 pontos + múltiplos passes)
- Wait adaptativo para network idle (5-8s) capturando XHRs tardios

**Processamento de Recursos:**
- Classificação automática por tipo: image, script, css, font, media, other
- Retry com 2 tentativas e backoff exponencial
- Limite de 100MB por recurso individual
- Timeout de 15s por recurso
- Remoção de tracking domains (Google Analytics, GTM, Facebook Pixel, etc.)

**Relatório Detalhado:**
- Total de recursos por tipo com percentuais
- Lista de falhas (máx 20) com motivos
- Recursos ignorados agrupados por razão
- Tempo total de download

### Fixed - URL Rewriting e Asset Resolution

**Implementações:**
- **Blind Mapping:** Substituição literal de URLs em HTML, CSS, JS, JSON, SVG, XML
- **Rewrite Recursivo:** Processa arquivos em todas subpastas (não só raiz)
- **Substituição de CDN:** Substitui base URLs de CDNs externos por paths locais
- **Fetch Interceptor:** Injetado como primeiro `<script>` do `<head>`
  - Sobrescreve `window.fetch` e `XMLHttpRequest.prototype.open`
  - Redireciona requisições para arquivos locais
  - Serializa resource_map inline ou JSON externo

**Problemas Resolvidos:**
- CSS não carregava por atributo `integrity` → Removido com `post_process.py`
- Basenames em CSS inline faltavam `assets/` → Reescrita de conteúdo implementada
- URL encoding em filenames não resolviam → Decodificação com `urllib.parse.unquote()`
- Cache de módulos Flask causava downloads incorretos → Desabilitado `use_reloader`

**Validação WebGL:**
- landonorris.com: 264 assets capturados (+146 vs versão anterior), 189 texturas .webp
- Tempo: +76s aceitável para sites WebGL
- CSS carrega sem erros, basenames substituídos, layout funcional

### Changed - CSS Processing Seguro

**Filosofia:** "Não quebrar scroll" em vez de "mostrar tudo forçadamente"

**Escopo Mínimo:**
- CSS fix reduzido a: html/body, scroll containers, loaders
- Removidas forças de `opacity: 1 !important` em elementos genéricos
- Removidas forças de `transform: none !important`
- Removidas forças de `visibility: visible !important`

**Resultado:** Sites ficam "congelados no estado de load" (esperado e aceitável para animações).

### Added - Limpeza de Meta-Tags e Otimização

**Processamentos Implementados:**
- Remoção de `<link rel="preconnect">` e `<link rel="dns-prefetch">` (inúteis offline)
- Reescrita de `<link rel="preload|prefetch|modulepreload">` com href corrigido
- Remoção de `sourceMappingURL` em arquivos JS
- Remoção de `integrity`, `crossorigin`, `nonce` de tags CSS

## [0.1.0] - Initial Release

### Added - Website Downloader Base

- Captura de sites com Playwright
- Network interception via CDP
- Salvamento de recursos offline
- Suporte para SPA frameworks (React, Vue, Angular)
- Processamento de HTML/CSS básico
- Geração de design system showcase
