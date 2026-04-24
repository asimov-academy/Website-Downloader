# DeepMirror WebSites — Processamento e Extração (Sistema)

## Técnica impecável para captura e processamento de sites reais

Este documento cobre tudo que o **DeepMirror WebSites faz internamente via programação** — desde a captura de rede até a entrega de uma pasta `/clean` pronta para consumo por um agente de IA. Nenhuma etapa descrita aqui envolve IA generativa; é engenharia de software pura.

## Captura: Como Extrair o DNA Visual de Qualquer Site

### 3.0 - Runtime Network Recording

A técnica mais poderosa é o **Runtime Network Recording**: em vez de parsear HTML estático, você executa o site real (via Playwright), intercepta **todas** as requisições de rede e salva o que foi realmente carregado.

Por que isso é superior a qualquer parser estático:

1. Captura recursos que não estão no HTML (dinâmicos via fetch/XHR)
2. Captura o estado **após a hidratação** de SPAs (Next.js, Nuxt, etc.)
3. Captura assets de CDNs externos
4. Garante que apenas recursos que realmente foram usados sejam baixados

### 3.1 - A dualidade raw/clean: Nunca confunda as camadas

Uma das descobertas práticas mais valiosas é manter **duas versões** do site capturado:

- **`raw/`**: Backup fiel. Nunca modificar. Fonte de verdade para assets, animações, comportamentos.
- **`clean/`**: Otimizado para leitura por IA. Desminifica, remove tracking, normaliza JS, comenta SVGs, tira comentários dos códigos e seções desnecessárias.

**Regra de ouro:** Sempre comece pelo `clean/`. Recorra ao `raw/` apenas quando algo visual estiver faltando — uma animação perdida, um asset específico, um comportamento de canvas.

### 3.1.1 - Estrutura e organização do `raw/`

O `raw/` é um **espelho fiel** do que o navegador baixou. Sua estrutura deve reproduzir a hierarquia original de URLs e caminhos do site capturado, sem qualquer reorganização.

**Princípios do `raw/`:**

- Manter a estrutura de diretórios original tal como veio da rede (ex: `/assets/js/`, `/static/css/`, `/images/hero/`)
- Arquivos ficam exatamente como foram baixados — minificados, obfuscados, com tracking, com comentários
- Nomes de arquivo preservados (inclusive hashes de bundlers como `main.a3f2c1.js`)
- Assets de CDNs externos são salvos numa subpasta que reflete o domínio de origem (ex: `raw/_cdn/fonts.googleapis.com/...`)
- Nenhuma modificação, renomeação ou exclusão é permitida após a captura
- Servir como ponto de recuperação: se algo der errado no clean, o raw é a fonte de verdade

**Exemplo de estrutura `raw/`:**
```
raw/
  index.html
  about.html
  assets/
    js/
      main.a3f2c1.js          # Minificado, original
      vendor.8b2e4d.js
      analytics.js             # Tracking — mantido
    css/
      styles.min.css           # Minificado
      critical.inline.css
    images/
      hero/
        hero-desktop.webp
        hero-mobile.webp
    icons/
      sprite.svg
      og-image.png
  fonts/
    Inter-Regular.woff2
    Inter-Bold.woff2
  _cdn/
    fonts.googleapis.com/
      css2-family-Inter.css
    cdn.jsdelivr.net/
      lottie-player@2.0.js
```

### 3.1.2 - Estrutura e organização do `clean/`

O `clean/` é uma **versão reorganizada e otimizada** para leitura por IA. Aqui, a estrutura original é descartada em favor de uma organização lógica por tipo de arquivo dentro de uma pasta `assets/`.

**Princípios do `clean/`:**

- Todos os assets são reorganizados dentro de `assets/`, separados por tipo de arquivo
- Arquivos HTML são desminificados, limpos e colocados na raiz do `clean/`
- CSS é desminificado, separado do HTML inline, e consolidado
- JS é desminificado, tracking/analytics removido, e apenas código relevante mantido
- SVGs inline gigantes são substituídos por placeholders com referência ao arquivo extraído
- Todas as referências de path dentro de HTML, CSS e JS são **corrigidas** para apontar para as novas localizações em `assets/`
- Comentários de código são removidos (exceto comentários curtos que ajudam no contexto)
- Seções irrelevantes (banners de cookies, popups de newsletter, tracking pixels) são removidas

**Exemplo de estrutura `clean/`:**
```
clean/
  index.html                        # Desminificado, paths corrigidos
  outras-paginas-ou-elementos.html  # Desminificado, paths corrigidos
  assets/
    css/
      styles.css                # Desminificado, consolidado
      critical.css              # Inline CSS extraído
    js/
      main.js                   # Desminificado, sem tracking
      vendor.js                 # Apenas dependências visuais
    fonts/
      Inter-Regular.woff2
      Inter-Bold.woff2
    images/
      hero-desktop.webp
      hero-mobile.webp
      og-image.png
    icons/
      logo.svg                  # SVGs extraídos do inline
      arrow-right.svg
      sprite.svg
    animations/
      hero-lottie.json          # Lottie JSONs identificados
      loading.json
    models/
      product.glb               # Modelos 3D (se houver)
      environment.hdr
```

### 3.1.3 - O processo de transformação raw → clean

A transformação de `raw/` para `clean/` é um pipeline de etapas sequenciais. Cada etapa é um script ou processor dedicado:

**Etapa 1 — Inventário e classificação de arquivos:**
Varrer todo o `raw/` e classificar cada arquivo por tipo (HTML, CSS, JS, fonte, imagem, SVG, animação, modelo 3D, outros). Gerar um manifesto `file_inventory.json`.

**Etapa 2 — Reorganização em `assets/`:**
Copiar cada arquivo para sua subpasta correspondente em `clean/assets/`, renomeando para nomes legíveis quando possível (remover hashes de bundler). Gerar um `path_mapping.json` que mapeia cada path original para o novo path.

**Etapa 3 — Desminificação:**
- HTML: Usar um formatter (ex: `js-beautify` ou equivalente) para indentar corretamente
- CSS: Desminificar e separar em arquivos lógicos
- JS: Desminificar com `js-beautify`, preservar estrutura semântica

**Etapa 4 — Limpeza de HTML:**
- Remover scripts de tracking/analytics (Google Analytics, Facebook Pixel, Hotjar, etc.)
- Remover meta tags irrelevantes (og:tags excessivas, SEO markup desnecessário)
- Remover banners de cookies, modais de newsletter, popups
- Substituir SVGs inline gigantes por `<img src="assets/icons/nome.svg" data-original-inline="true">`
- Extrair `<style>` inline para arquivos CSS separados
- Extrair `<script>` inline para arquivos JS separados

**Etapa 5 — Limpeza de CSS:**
- Remover blocos de tracking/analytics
- Remover regras de print (a menos que relevantes)
- Consolidar múltiplos arquivos CSS em um ou poucos arquivos lógicos
- Remover comentários gigantes (licenças extensas, blocos de documentação), manter comentários curtos úteis

**Etapa 6 — Limpeza de JS:**
- Remover scripts de tracking/analytics por completo
- Remover polyfills desnecessários
- Manter apenas JS relacionado a interação visual, animação e comportamento de UI

**Etapa 7 — Correção de paths (crítico):**
Percorrer todos os arquivos HTML, CSS e JS do `clean/` e atualizar referências usando o `path_mapping.json`:
- Em HTML: `src`, `href`, `srcset`, `data-src`, `poster`, `url()` inline
- Em CSS: `url()`, `@import`, `src` dentro de `@font-face`
- Em JS: strings que referenciam assets (detecção heurística + mapa de paths)

**Etapa 8 — Extração de tokens e metadados:**
- Extrair variáveis CSS (`--*`) para `extracted_tokens.json`
- Extrair paleta de cores (HEX, RGB, HSL) via Regex
- Extrair `@font-face` declarations
- Extrair `@keyframes`
- Rodar `getComputedStyle` nos elementos-chave via Playwright e salvar em `computed_styles.json`

**Etapa 9 — Validação:**
- Verificar que todos os paths referenciados em HTML/CSS/JS existem em `clean/assets/`
- Verificar que nenhum arquivo de `raw/` ficou órfão sem ser copiado (ou foi intencionalmente descartado)
- Gerar relatório de diferenças entre `raw/` e `clean/`

### 3.2 - Estratégia de captura por tipo de site

| Tipo de site | Estratégia primária | Assets-alvo |
| :- | :-: | :-: |
| Site estático simples | HTML/CSS direto | `.css`, `.woff2`, imagens |
| SPA (Next.js, Nuxt) | Runtime Recording + DOM hidratado | JS chunks, API responses visuais |
| Site com Three.js/WebGL | Network Recording focado em binários | `.glb`, `.gltf`, `.hdr`, `.wasm` |
| Site com Rive | Network Recording + canvas | `.riv` |
| Animações Lottie | Interceptar XHR/fetch | JSONs Bodymovin |
| Scroll-jacking (Apple-style) | Playwright Profiler + CDP | Mapeamento de keyframes matemáticos |

## Processamento: Como Preparar o Material para a IA

Esta é a camada mais determinante para a qualidade do resultado final. O processamento correto pode transformar um arquivo de 10.000 linhas em um contexto rico e denso de apenas 2.000 linhas.

### 4.0 - Nunca use Regex para estrutura HTML: Use AST

Regex é inadequado para HTML hierárquico. Para limpar e fatiá-lo, use ferramentas de AST:

- **Python:** BeautifulSoup
- **Node.js:** Cheerio ou unified/rehype

**Por que o placeholder de SVG é crítico:** SVGs inline gigantes consomem milhares de tokens sem adicionar nenhuma informação visual para a IA. Substituir por `<svg data-icon="logo">...</svg>` economiza contexto para o que realmente importa.

> Dessa forma, é extremamente importante separar o css e js do html para aplicar as próximas regras em cada um deles e remover comentários dele gigantes dele, mas manter os pequenos que podem ajudar no contexto.

### 4.1 - CSS é onde o Regex brilha: Use-o com precisão

Diferente do HTML, o CSS tem estrutura previsível o suficiente para Regex ser eficaz para:

- Extrair todas as variáveis CSS (Design System de bandeja);
- Extrair paleta de cores bruta (HEX, RGB, HSL);
- Extrair todas as @font-face declarations;
- Extrair todos os @keyframes;
- Separar listas gigantes de classes, ids e elementos para um simples "margem: 0;" e colocar em um arquivo separado;

**O fluxo correto:** Rodar esses scripts, salvar os resultados, e passar **os tokens extraídos** em um arquivo de contexto para o prompt — não o CSS completo. Enquanto o que é ação, pode ser feita na estrutura mesmo.

### 4.2 - Raciocínio visual via `getComputedStyle`

Em vez de pedir para a IA adivinhar qual classe CSS produz qual visual, você usa código para "ler" a tela renderizada:

**Por que isso é revolucionário:** A IA não precisa mais ler o arquivo CSS gigante. Ela recebe um JSON com os valores reais, computados, de cada elemento. Elimina completamente a ambiguidade do Cascade.

### 4.3 - Isolamento por relevância: Descarte o código morto

Para sites complexos (Apple AirPods, por exemplo), mais de 80% do JS baixado é irrelevante: polyfills, rotas não visitadas, lógica de carrinho. Use o Chrome DevTools Protocol (CDP) para mapear apenas o código executado:

```python
# Conceito: usar CDP para tracing de execução
async with page.expect_event('load'):
    await page.goto(url)

# Ativar cobertura de JS
await page.coverage.start_js_coverage()
await scroll_page_fully(page)  # Acionar todas as animações
coverage = await page.coverage.stop_js_coverage()

# Filtrar apenas blocos executados durante a animação
executed_ranges = [
    entry for entry in coverage 
    if entry['url'].endswith('animation.js')
]
```

**Resultado:** Em vez de milhares de funções minificadas, você tem apenas o fluxo das animações. Esse bloco filtrado é o que vai para a IA.

## Sites Complexos: WebGL, Three.js, Rive e Scroll-Jacking

Esta seção trata dos casos onde todas as abordagens convencionais falham — e onde a engenharia reversa de comportamento e assets também deve ser aplicada.

### 6.0 - O diagnóstico crítico: quando o HTML é um palco vazio

Sites como Apple AirPods Pro ou Lando Norris têm um HTML mais simples (ainda com css, mas não é focado nele):
```html
<div id="app"></div>
<canvas id="webgl-canvas"></canvas>
```

Toda a magia — iluminação 3D, física de scroll, interpolação de Rive, Motion — acontece na GPU e na memória JavaScript. Tentar ler o HTML/CSS desses sites para extrair design é útil, mas não é suficiente para replicar os comportamentos e estilos. A estratégia precisa mudar.

### 6.1 - Network Recording focado em binários

Para sites Three.js/WebGL, foque nos binários e depois no html e css:

```python
EXTENSOES_ALVO = [
    '.glb',   # Modelos 3D (Three.js)
    '.gltf',  # Modelos 3D alternativos
    '.riv',   # Animações Rive
    '.hdr',   # Mapas de iluminação ambiente
    '.wasm',  # WebAssembly (Draco, compressão)
    '.json',  # Verificar se tem estrutura Lottie/Bodymovin
]

# Identificar JSONs Lottie
def is_lottie_json(json_data):
    return all(k in json_data for k in ['v', 'fr', 'ip', 'op', 'layers'])
```

### 6.2 - Mapeamento comportamental de scroll-jacking

Para sites que atrelam animações complexas ao scroll (Apple-style), não tente ler o JS minificado. Mapeie a **física** diretamente:

```python
async def map_scroll_physics(page):
    scroll_map = []
    
    # Rolar de 100 em 100 pixels
    for scroll_y in range(0, 5000, 100):
        await page.evaluate(f'window.scrollTo(0, {scroll_y})')
        await asyncio.sleep(0.1)  # Aguardar animação estabilizar
        
        # Capturar estado computado dos elementos de interesse
        state = await page.evaluate('''() => {
            const hero = document.querySelector('.hero-image');
            const title = document.querySelector('h1');
            const style_hero = window.getComputedStyle(hero);
            const style_title = window.getComputedStyle(title);
            
            return {
                scrollY: window.scrollY,
                hero: {
                    opacity: style_hero.opacity,
                    transform: style_hero.transform,
                },
                title: {
                    opacity: style_title.opacity,
                    transform: style_title.transform,
                }
            };
        }''')
        
        scroll_map.append(state)
    
    return scroll_map
```

### 6.3 - Captura de Shaders GLSL

Para efeitos de distorção de imagem fluida em Canvas (sites Awwwards-level), o segredo está nos Fragment e Vertex Shaders:

- **Ferramenta:** Spector.js (extensão Chrome para interceptar chamadas WebGL);
- **O que captura:** Código GLSL exato rodando na GPU naquele frame;
- **O que fazer:** Colar o shader capturado para a IA e pedir tradução para React Three Fiber;

**Insight crítico:** A IA é excepcionalmente boa em ler GLSL. Você cola o shader capturado e pede uma versão manipulável como prop de componente React.

## Armadilhas Clássicas no Processamento

### 8.0 - Desofuscação em massa

**O erro:** Tentar desofuscar cada função minificada de um arquivo JS grande.

**Por que falha:**
- Funções minificadas perdem escopo e closure — sem contexto global, a IA alucina nomes inúteis;
- Uma variável `a` pode ser uma função de animação em um módulo e um contador de loop em outro, substituição global via Regex corrompe o código;
- Um arquivo JS de 200KB pode ter milhares de blocos, o volume inviabiliza o processo;

**A alternativa correta:** Usar CDP para mapear apenas o código que **realmente executa** durante a interação relevante, e passar esse bloco filtrado para um LLM robusto.

### 8.3 - Snapshot DOM em sites WebGL

**O erro:** Usar um MCP simples ou um scraper de DOM para capturar sites como Apple AirPods Pro ou Three.js-heavy.

**Por que falha:** O HTML desses sites é um palco vazio. O design não está no DOM — está na GPU.

**A regra:** Para sites com WebGL/Three.js/Rive, mude a estratégia para Network Recording de binários + mapeamento comportamental.

### 8.4 - Extração de múltiplos sites

**O erro:** Misturar referências de sites diferentes no mesmo design system.

**Por que falha:** Design systems são destilações de uma única identidade visual coesa. Misturar cria inconsistência de DNA.

**A regra:** Um site por extração. Sempre.

## Novas Fronteiras: Extensões do Sistema

### 9.0 - Processor de Shaders Automatizado

Um script que vasculha arquivos JS baixados buscando por strings GLSL (`void main()`, `gl_FragColor`, `gl_Position`) e extrai automaticamente os shaders para arquivos `.glsl` separados. Isso seria adicionado ao `SiteCleaner` como um processor dedicado.

### 9.1 - Design Token Diff: Comparar evoluções

Uma ferramenta que compara dois design systems extraídos do mesmo site em momentos diferentes (v1 vs v2) e gera um diff visual dos tokens alterados. Útil para acompanhar evoluções de identidade de marca.

- `development/diff_raw_clean.py`

### 9.2 - Scroll Physics Recorder como feature nativa

Integrar o mapeamento de física de scroll diretamente no DeepMirror WebSites como uma etapa opcional da pipeline, gerando automaticamente um `scroll_physics.json` para cada elemento animado detectado durante a navegação.

### 9.3 - Multi-pass de extração por intenção

Ao invés de uma única extração, rodar múltiplos passes especializados:

- **Pass 1:** Estrutura e componentes (HTML)
- **Pass 2:** Tokens visuais (CSS)
- **Pass 3:** Comportamento e motion (JS/keyframes)
- **Pass 4:** Assets binários (imagens, fontes, modelos)

Cada pass tem seu próprio script de limpeza e seu próprio prompt otimizado para aquela intenção específica.

## Sumário do Pipeline de Sistema

```
1. CAPTURAR     →  Runtime Network Recording (Playwright + interceptação de rede)
2. SALVAR RAW   →  Estrutura original fiel, sem modificações
3. CLASSIFICAR  →  Inventário de arquivos por tipo
4. REORGANIZAR  →  Copiar para clean/assets/ por tipo, gerar path_mapping.json
5. DESMINIFICAR →  HTML, CSS e JS formatados para leitura
6. LIMPAR       →  Remover tracking, analytics, popups, código morto
7. CORRIGIR     →  Atualizar todos os paths em HTML/CSS/JS
8. EXTRAIR      →  Tokens CSS, paleta, fontes, keyframes, computed styles
9. VALIDAR      →  Verificar integridade de paths e completude de assets
```

**Saída final:** Uma pasta `clean/` com estrutura padronizada, assets organizados por tipo, paths corrigidos, metadados extraídos, desminificada e limpa de ruidos, arquivos html sem scripts, style, com tudo separado — pronta para ser consumida por um agente de IA.
