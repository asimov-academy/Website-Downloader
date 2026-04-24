# Single Page

O `single_page` é o app web oficial do DeepMirror WebSites.

Ele usa o runtime compartilhado de [core/](/core) para capturar uma URL principal de forma automática e gerar:

- `raw/`
- `clean/`
- `audit/`
- `serve.py`

## Quando usar

Use o `single_page` quando:

- você quer baixar uma URL inicial com o mínimo de intervenção manual
- o site funciona bem com captura automática
- você quer usar a interface web atual
- você quer continuar usando o contrato público `WebsiteDownloader(...).process()`

## Entry points

- App web: [single_page/app.py](/single_page/app.py)
- Serviço interno: [single_page/service.py](/single_page/service.py)
- Fachada pública programática: [downloader.py](/downloader.py)

## Interface web

Suba o app:

```bash
uv run python -m single_page.app
```

URL padrão:

```text
http://localhost:5001
```

Arquivos da UI:

- [templates/index.html](/single_page/templates/index.html)
- [templates/login.html](/single_page/templates/login.html)
- [static/css/style.css](/single_page/static/css/style.css)
- [static/js/main.js](/single_page/static/js/main.js)

## Uso programático

```python
from downloader import WebsiteDownloader

WebsiteDownloader(
    "https://example.com",
    "downloads/example",
    print,
).process()
```

## Fluxo técnico

O `single_page` faz:

1. abrir o browser em modo headless
2. navegar para a URL
3. estimular scroll, lazy loading e interações relevantes
4. gravar os recursos de rede em tempo de execução
5. fazer fallback de assets faltantes
6. pós-processar o HTML
7. salvar a página principal como `index.html`
8. rodar o pipeline de `clean`
9. gerar `serve.py`

## Saída

Exemplo:

```text
downloads/exemplo/
  raw/
  clean/
  audit/
  serve.py
```

- `raw/`: backup fiel do download
- `clean/`: versão otimizada para leitura por IA
- `audit/`: snapshots por etapa do clean
- `serve.py`: servidor local do site baixado

## Pipeline clean

O `single_page` usa o `SiteCleaner` compartilhado do `core`.

Etapas principais:

| # | Etapa | Módulo |
|---|---|---|
| 1 | Snapshot raw para auditoria | `core/clean/manager.py` |
| 2 | Limpeza de HTML | `core/clean/clean_html.py` |
| 3 | Limpeza de CSS | `core/clean/clean_css.py` |
| 4 | Limpeza de JS | `core/clean/clean_js.py` |
| 5 | Inventário de arquivos | `core/clean/file_inventory.py` |
| 6 | Reorganização de assets | `core/clean/reorganizer.py` |
| 7 | Correção de paths | `core/clean/path_corrector.py` |
| 7b | Consolidação de CSS | `core/clean/css_consolidator.py` |
| 7c | Consolidação de JS | `core/clean/js_consolidator.py` |
| 7d | Reparo final de referências | `core/clean/finalizer.py` |
| 7e | Poda de órfãos | `core/clean/finalizer.py` |
| 8 | Classificação + extractors | `core/classifier.py` + `core/extractors/` |
| 8d | Geração de `_ai_context.md` | `core/ai_context.py` |
| 8e | Normalização de texto | `core/clean/finalizer.py` |
| 9 | Validação final | `core/clean/validator.py` |

## Deploy

O deploy web oficial do projeto aponta para este fluxo.

- Container: [Dockerfile](/Dockerfile)
- Entrypoint: [entrypoint.sh](/entrypoint.sh)
- Compose: [compose.dev.yml](/compose.dev.yml)

Todos eles sobem `gunicorn single_page.app:app`.

## Configuração

As variáveis compartilhadas vêm de `core/__init__.py` e do `.env`.

Exemplos úteis:

```dotenv
DM_BROWSER_TIMEOUT_MS=60000
DM_RESOURCE_TIMEOUT_S=15
DM_MAX_RESOURCE_SIZE_MB=100
DM_MAX_SCROLL_ITERATIONS=20
DM_CLEAN_MODE=full
DM_SKIP_DOMAINS=google-analytics.com,googletagmanager.com
```

## Validação mínima

Teste web:

```bash
uv run python -m single_page.app
```

Teste programático:

```bash
uv run python -c "from downloader import WebsiteDownloader; WebsiteDownloader('https://example.com', 'downloads/example', print).process()"
```

## Leitura complementar

- Guia de uso: [USAGE.md](/single_page/USAGE.md)
- Runtime compartilhado: [core/](/core)
