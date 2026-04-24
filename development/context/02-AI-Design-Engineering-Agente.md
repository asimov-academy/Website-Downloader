# AI Design Engineering — Agente de IA para Design System

## Técnica impecável para geração de Design System com IA a partir de uma pasta `/clean`

Este documento cobre tudo que o **agente de IA faz** — desde receber a pasta `/clean` já processada pelo DeepMirror WebSites até gerar uma pasta `design_system/` autônoma e de alta fidelidade. Aqui não há captura de rede nem processamento de arquivos brutos; o input já está pronto.
   
## O Problema Fundamental: Por que a IA é Péssima em HTML/CSS Puro

Antes de qualquer coisa é essencial compreender **o problema de raiz**. Sem isso, qualquer workflow será construído sobre uma base errada.

### 1.0 - A IA não tem olhos: Ela processa texto

A IA prevê tokens baseada em padrões estatísticos. Quando você pede para ela gerar um layout Flexbox, ela não "visualiza" o resultado. Isso significa:

- **CSS é espacial, a IA é sequencial.** Fluxos de empilhamento e posicionamento 2D exigem raciocínio que a IA não possui. O código pode fazer sentido linha a linha e ainda assim quebrar completamente na tela.

- **O Cascade é global, a IA é local.** A IA prevê o próximo token com base no contexto imediato. O CSS é global por natureza — uma regra em `styles.css` pode destruir o layout de um elemento aninhado 6 níveis abaixo, numa estrutura que a IA nunca "viu" ao mesmo tempo.

### 1.1 - O viés dos dados de treinamento

O código front-end de alta qualidade disponível publicamente está majoritariamente em React, Vue e similares. O HTML/CSS puro disponível para treino frequentemente remete a épocas mais antigas da web, com padrões desatualizados e soluções de fóruns. Resultado: a IA é melhor no ecossistema moderno por ter aprendido padrões melhores nele.

### 1.2 - Equifinalidade: O problema da múltipla resposta correta

Diferente do código algorítmico (onde poucas soluções são corretas), HTML/CSS tem **equifinalidade**: existem dezenas de formas igualmente válidas de centralizar uma `div`, colorir um botão ou criar um card. Isso faz com que a IA alterne aleatoriamente entre abordagens diferentes ao longo de uma sessão, gerando inconsistência.

### 1.3 - Por que JSX/React funciona melhor

React, JSX e outros frameworks resolvem estruturalmente os três problemas acima:

| Problema | CSS Puro | React/JSX |
| :- | :-: | :-: |
| Escopo | Global (Cascade) | Local (componente isolado) |
| Padrão de treino | Fragmentado, antigo | Rico, moderno, consistente |
| Equifinalidade | Alta | Baixa (padrões estabelecidos) |
| Legibilidade estrutural | Baixa | Alta |

**Conclusão prática:** Para geração de interfaces completas, vá direto para JSX/React com Tailwind. A fricção de debugar CSS puro gerado por IA raramente compensa.

### 1.4 - Por que JSX é o formato ideal para o agente de IA

Indo além da tabela acima, existem razões técnicas profundas pelas quais o agente deve gerar JSX e não HTML/CSS puro:

**Componentização natural:** Cada seção do design system (Hero, Typography, Colors, Components) vira um componente React isolado. A IA raciocina melhor sobre um escopo fechado de 50-100 linhas do que sobre um HTML monolítico de 2.000 linhas. Isso reduz alucinações e inconsistências drasticamente.

**Tailwind como ponte semântica:** Quando a IA escreve `className="bg-[#FF006E] text-white px-6 py-3 rounded-lg"`, ela está declarando a intenção visual diretamente no elemento — não precisa reconciliar um seletor CSS com um elemento HTML distante. A correspondência é 1:1, token visual → classe no elemento.

**Co-localização de estado e estilo:** Em JSX, a lógica de interação (hover, active, expanded) vive ao lado do markup. A IA não precisa navegar entre arquivos para entender o que acontece quando um botão é clicado — está tudo no mesmo componente.

**Ecossistema de motion design:** Framer Motion e GSAP (com wrapper React) são os padrões de facto para animação em React. A IA tem excelente fluência nessas libs por conta do volume de treinamento. Pedir `useTransform` + `useScroll` gera resultados muito mais fiéis do que pedir CSS `@keyframes` complexos.
   
## A Virada de Paradigma

Este é o insight central que diferencia uma abordagem amadora de uma profissional.

### 2.0 - O erro conceitual padrão

A maioria das pessoas tenta fazer a IA **ler e entender** o código de um site para depois reproduzi-lo. Isso falha por razões previsíveis:

- Sites modernos de alto nível têm código minificado, obfuscado ou gerado por bundlers;
- O HTML frequentemente é apenas um "palco vazio" — a mágica acontece na GPU e na memória JS;
- Jogar um arquivo CSS gigante no contexto resulta em alucinação e perda de detalhes;

#### 2.1 - A mudança de paradigma correta

Em vez de "como faço a IA entender esse espaguete minificado?", a pergunta certa é:

> **"Como eu entrego para a IA apenas os ingredientes essenciais — assets, shaders, dados de estado — para ela cozinhar um prato novo?"**

A IA não precisa ler o código do Lottie Player para reproduzir uma animação. Ela precisa do **arquivo JSON de configuração** da animação.

A IA não precisa entender o JS minificado de scroll-jacking da Apple. Ela precisa dos **keyframes matemáticos** mapeados por um script externo.

#### 2.2 - O modelo mental correto: pipeline em três camadas

| MUNDO REAL | PROCESSAMENTO | IA |
| :- | :-: | :-: |
| Site de referência | Scripts + Ferramentas | Geração |
| HTML/CSS/JS minificado | Extração cirúrgica | Prompt rico |
| Assets na rede | Download seletivo | Assets disponíveis |
| Animações na GPU | Mapeamento comportamental | Especificação clara |
| Shaders GLSL | Captura via Spector.js | Tradução para React |

## Geração: Como o Agente Instrui a IA para Resultados de Alta Fidelidade

### 3.0 - Separar estrutura (html) e estilos (css)

Esta é a regra mais simples e mais poderosa:

**Errado:**
> "Crie um card HTML/CSS com sombra e tipografia moderna."

**Correto:**
> **Turno 1:** "Aqui está o JSON de estilos computados do elemento `.card` do site X. Crie a estrutura semântica em HTML para este componente, usando as classes evidenciadas."
> **Turno 2:** "Agora escreva o CSS para este HTML, usando **apenas** estas variáveis CSS extraídas: `[lista de tokens]`. Não invente valores."

A separação elimina a equifinalidade: a IA toma uma decisão estrutural de cada vez, sem precisar reconciliar duas camadas conflitantes simultaneamente.

### 3.1 - Design System como âncora de contexto

Nunca inicie uma geração sem ancorar o contexto. O formato mais eficaz:

```
CONTEXTO DO PROJETO:
- Framework: React + Tailwind v4
- Tokens CSS disponíveis: [lista extraída por script]
- Fontes carregadas: [lista extraída por script]
- Paleta aprovada: [lista extraída por script]

REGRA HARD: Não use valores de cor, espaçamento ou tipografia que não estejam nesta lista.
REGRA HARD: Não normalize ou simplifique o visual. O objetivo é máxima fidelidade à referência.
```

### 3.2 - Forçar BEM quando CSS puro for inevitável

Se o projeto exige CSS puro, imponha BEM explicitamente no prompt:

```
Gere o HTML e CSS usando estritamente a convenção BEM:
- Block: .card
- Element: .card__title, .card__image, .card__body
- Modifier: .card--featured, .card--compact

Não use seletores aninhados além de 2 níveis. Não use !important.
```

Isso força a IA a simular isolamento de componente dentro do CSS global.

### 3.3 - Tailwind como lingua franca da IA

A IA ama Tailwind porque ele resolve estruturalmente o problema do escopo: os estilos são aplicados localmente via classes no próprio HTML, semelhante à mentalidade do JSX. A IA consegue mapear o token de texto diretamente para o resultado visual sem se preocupar com especificidade.

**Quando detectar Tailwind em um site:** não tente converter para CSS puro. Preserve as classes utilitárias no design system e apenas liste as cores/fontes customizadas no `style.css`.
   
## Tecnologias e Stack do Agente

### 4.0 - Python + `uv`: Setup mínimo e rápido

O agente é implementado em Python e usa `uv` como gerenciador de pacotes e ambiente virtual. `uv` é ordens de magnitude mais rápido que `pip` e `venv` tradicionais, o que importa quando o agente precisa ser bootstrappado rapidamente.

**Setup do projeto:**
```bash
# Instalar uv (se ainda não tiver)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Criar o projeto do agente
uv init design-system-agent
cd design-system-agent

# Adicionar dependências
uv add anthropic          # SDK da Anthropic para chamadas de IA
uv add jinja2             # Templates para prompts estruturados
uv add rich               # Output bonito no terminal
uv add pyyaml             # Configuração do agente
```

**Por que `uv` e não `pip`?**
- Resolução de dependências 10-100x mais rápida
- Lockfile determinístico (`uv.lock`) — reprodutibilidade garantida
- Cria e gerencia virtualenv automaticamente
- Roda scripts com `uv run` sem ativar venv manualmente

### 4.1 - Estrutura do projeto do agente

```
design-system-agent/
├── pyproject.toml                # Dependências via uv
├── uv.lock                      # Lock determinístico
├── src/
│   ├── agent.py                  # Orquestrador principal
│   ├── context_builder.py        # Monta o contexto a partir de /clean
│   ├── prompt_templates/
│   │   ├── hero.jinja2           # Template de prompt para seção Hero
│   │   ├── typography.jinja2
│   │   ├── colors.jinja2
│   │   ├── components.jinja2
│   │   ├── layout.jinja2
│   │   ├── motion.jinja2
│   │   └── system_prompt.jinja2  # Prompt de sistema base
│   ├── assembler.py              # Monta a pasta design_system/ final
│   └── validators.py             # Valida output (paths, tokens, completude)
└── config.yaml                   # Configurações (modelo, tokens, paths)
```

### 4.2 - O fluxo de execução do agente

```bash
# Rodar o agente apontando para a pasta clean
uv run src/agent.py --input ./clean --output ./design_system
```

**Passo a passo interno:**

1. **Carregar metadados**: Ler `extracted_tokens.json`, `computed_styles.json`, `scroll_physics.json`
2. **Inventariar assets**: Listar tudo em `clean/assets/` para saber o que está disponível
3. **Montar contexto base**: Usar `context_builder.py` para criar o bloco de contexto que vai em todo prompt (tokens, fontes, paleta, assets disponíveis)
4. **Gerar seção por seção**: Para cada seção do design system (Hero, Typography, Colors, etc.), montar o prompt específico usando o template Jinja2 + contexto base + arquivos relevantes do `clean/`
5. **Chamar a API da Anthropic**: Enviar o prompt e receber JSX/React como resposta
6. **Validar output**: Verificar que o JSX não referencia cores/fontes/assets que não existem
7. **Montar pasta final**: Usar `assembler.py` para criar a estrutura `design_system/` com todos os arquivos

### 4.3 - Por que o output é JSX e não HTML puro

O agente gera **JSX/React com Tailwind** como formato primário do design system. As razões estão detalhadas na seção 1.3 e 1.4, mas a consequência prática é:

- O `main.html` do design system final é um showcase que importa componentes React
- Cada seção é um componente isolado, testável e reutilizável
- Tailwind garante que os tokens visuais estão declarados inline, sem cascade
- Framer Motion é usado para reproduzir animações mapeadas no `scroll_physics.json`

**Fallback para HTML puro:** Se o design system precisa ser em HTML/CSS puro (requisito do projeto), o agente aplica as regras BEM da seção 5.2 e gera CSS scoped por componente. A qualidade será inferior, mas aceitável se as regras forem seguidas.

### 4.4 - Multi-turn e gestão de contexto

Para sites complexos, o agente não gera tudo em um único prompt. Ele usa uma estratégia multi-turn:

**Turno 1 — Análise:** Enviar metadados + HTML limpo e pedir um plano de seções com componentes identificados.

**Turno 2 — Tokens:** Enviar o plano aprovado + `extracted_tokens.json` e pedir a configuração do Tailwind com os tokens customizados.

**Turno 3-N — Seções:** Para cada seção do design system, enviar o contexto base + a porção relevante do HTML/CSS do `clean/` + computed styles daqueles elementos.

**Turno final — Revisão:** Enviar o design system completo gerado e pedir uma revisão de consistência (cores, fontes, espaçamentos).

Cada turno recebe apenas o contexto necessário — nunca o `clean/` inteiro de uma vez.
   
## O Design System como Produto: Estrutura e Contrato de Saída

### 5.0 - A estrutura mínima viável

Todo Design System extraído deve ter exatamente esta estrutura:

```
design-system/
├── main.html     # Showcase ao vivo, todas as seções
├── style.css     # Apenas CSS necessário + tokens
├── main.js       # Apenas JS de interação e demos
└── assets/       # Apenas assets usados (sem dumps)
```

**Regra crítica:** A pasta final nunca deve depender de `raw/` ou `clean/`. Ela deve funcionar de forma completamente autônoma.

### 5.1 - Ordem canônica das seções do showcase

O `index.html` deve seguir esta ordem invariavelmente:

1. **Hero**: Prova o DNA visual. Deve ser reconhecível como derivado da referência.
2. **Motions**: Uso de todos os motions, animações e modelos 3d.
3. **Typography**: Famílias, pesos, tamanhos, line-height, letter-spacing com exemplos ao vivo.
4. **Colors & Surfaces**: Cores base, texto, backgrounds, borders, glows, gradientes, opacidades.
5. **Components**: Buttons, inputs, cards, navbars, badges, accordions, CTAs, footers.
6. **Layout & Spacing**: Container widths, grids, composição de hero, negative space.
7. **Frames & Transições**: @keyframes, transições, reveals, hover effects, loops decorativos.
8. **Icons & Assets** — Sistema de ícones, logos, texturas, ilustrações.
   
## Armadilhas Clássicas na Geração por IA

### 6.1 - Normalização genérica

**O erro:** Normalizar tudo para um visual "bonitinho porém genérico" — o famoso azul `#007bff`, os 8px de border-radius, as shadows padrão do Bootstrap.

**Por que falha:** O objetivo é extrair o DNA visual do site, não criar uma interpretação. Se o site tem um gradiente de neon específico `#FF006E -> #8338EC`, esse é o token correto — não "algum gradiente roxa".

**A regra:** Nunca invente componentes, estilos ou estados que não estejam evidenciados no download.

### 6.2 - Contexto gigante

**O erro:** Jogar o CSS inteiro único, o HTML completo e todos os assets no contexto da IA de uma vez.

**Por que falha:** Modelos de IA degradam em qualidade quando o contexto excede sua capacidade de atenção efetiva. Isso resulta em alucinação sobre os detalhes das primeiras 2.000 linhas quando a IA está processando as últimas 2.000.

**A regra:** Sempre pré-processar e entregar o mínimo necessário. Tokens de contexto são um recurso escasso.

### 6.5 - Não validar o output contra os tokens de entrada

**O erro:** Aceitar o JSX gerado pela IA sem verificar se ele referencia apenas tokens, cores, fontes e assets que existem no `/clean`.

**Por que falha:** A IA frequentemente "inventa" cores parecidas (`#FF006E` vira `#FF0066`), substitui fontes por similares mais comuns (`Space Grotesk` vira `Inter`), ou referencia assets que não existem. Sem validação, o design system perde fidelidade silenciosamente.

**A regra:** O agente deve rodar um validator automatizado que cruza o output gerado contra `extracted_tokens.json` e a lista de assets disponíveis. Qualquer divergência deve ser corrigida ou flagada antes da montagem final.
   
## Sumário do Pipeline do Agente

```
1. RECEBER      →  Pasta /clean já processada pelo DeepMirror WebSites
2. CARREGAR     →  Metadados (_metadata/*.json) + inventário de assets
3. CONTEXTUAR   →  Montar contexto base (tokens, fontes, paleta, assets)
4. PLANEJAR     →  Analisar estrutura e definir seções do design system
5. GERAR        →  Seção por seção, multi-turn, JSX/React + Tailwind
6. VALIDAR      →  Cruzar output contra tokens e assets de entrada
7. MONTAR       →  Assemblar pasta design_system/ autônoma
8. REVISAR      →  Pedir revisão de consistência à própria IA
```

**Input:** Pasta `clean/` com HTML limpo, assets organizados e metadados extraídos.
**Output:** Pasta `design_system/` autônoma, com showcase visual, componentes React e todos os assets necessários.

> Capture comportamento, não código. Destile evidências, não suposições. Entregue ingredientes, não dumps. E deixe a IA cozinhar.
