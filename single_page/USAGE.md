# Guia de Uso — Single Page

## O que é

O `single_page` é o fluxo atual e automático do DeepMirror WebSites.

Ele recebe uma URL, abre o site em modo headless, captura a página principal com o motor compartilhado do `core`, processa os assets e gera:

- `raw/`
- `clean/`
- `audit/`
- `serve.py`

Esse fluxo é o mais indicado quando você quer baixar uma única entrada do site do jeito mais automático possível.

## Quando usar

Use o `single_page` quando:

- você quer baixar uma URL inicial completa sem navegar manualmente
- o site funciona bem com captura automática
- você quer usar a interface web existente
- você quer usar a API pública `WebsiteDownloader(...).process()`

## Formas de uso

### 1. Interface web

Suba a interface do single-page:

```bash
uv run python -m single_page.app
```

A interface ficará disponível em:

```text
http://localhost:5001
```

Esse app web usa:

- [single_page/templates/index.html](/single_page/templates/index.html)
- [single_page/templates/login.html](/single_page/templates/login.html)
- [single_page/static/css/style.css](/single_page/static/css/style.css)
- [single_page/static/js/main.js](/single_page/static/js/main.js)

Compatibilidade:

- o app web real do single-page está em [single_page/app.py](/single_page/app.py)
- os endpoints antigos continuam válidos

### 2. Uso programático

```bash
uv run python -c "from downloader import WebsiteDownloader; WebsiteDownloader('https://example.com', 'downloads/example', print).process()"
```

Ou em Python:

```python
from downloader import WebsiteDownloader

downloader = WebsiteDownloader(
    "https://example.com",
    "downloads/example",
    print,
)
downloader.process()
```

### 3. Serviço interno

O fluxo real do single-page fica em:

- [single_page/service.py](/single_page/service.py)

Normalmente você não precisa chamar esse serviço diretamente, porque `downloader.py` já é a fachada pública estável.

## Saída gerada

Exemplo:

```text
downloads/exemplo/
  raw/
  clean/
  audit/
  serve.py
```

Na prática:

- `raw/` é o backup fiel
- `clean/` é a versão otimizada para leitura por IA
- `audit/` guarda snapshots intermediários
- `serve.py` sobe o site baixado localmente

## Fluxo padrão

O `single_page` faz:

1. abrir browser headless
2. navegar para a URL
3. estimular scroll/interações/WebGL
4. gravar recursos de rede
5. baixar fallbacks faltantes
6. pós-processar o HTML
7. salvar `index.html`
8. rodar o `clean`
9. gerar `serve.py`

## Exemplo real validado

Este fluxo já foi validado no projeto com:

```bash
uv run python -u -c "from downloader import WebsiteDownloader; WebsiteDownloader('https://landonorris.com/', 'downloads/test_landonorris_single', print).process()"
```

## Limitações práticas

- o fluxo é pensado para uma página principal por execução
- proteções anti-bot podem impedir a navegação automática mesmo quando a URL abre normalmente no seu navegador

## Configuração útil

As configurações compartilhadas vêm de `core/__init__.py` e `.env`.

Algumas variáveis úteis:

```dotenv
DM_BROWSER_TIMEOUT_MS=60000
DM_RESOURCE_TIMEOUT_S=15
DM_MAX_RESOURCE_SIZE_MB=100
DM_MAX_SCROLL_ITERATIONS=20
DM_CLEAN_MODE=full
DM_SKIP_DOMAINS=google-analytics.com,googletagmanager.com
```

## Troubleshooting

### A interface abre, mas o download do ZIP falha

O endpoint correto do single-page fica em [single_page/app.py](/single_page/app.py).

O sistema já foi ajustado para salvar e servir ZIPs usando caminho absoluto na raiz do projeto.
