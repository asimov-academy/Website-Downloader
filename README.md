# 🌐 Website Downloader

Uma ferramenta web para baixar réplicas completas de sites, incluindo conteúdo renderizado por JavaScript.

## ✨ Funcionalidades

- 📥 Download completo de sites (HTML, CSS, JS, imagens, fontes)
- 🎭 Renderização de JavaScript usando Playwright/Chromium
- 🖼️ Captura de imagens lazy-loaded
- 📦 Exportação em arquivo ZIP
- 🔄 Interface em tempo real com logs de progresso
- 🧹 Limpeza automática de arquivos temporários
- 🛡️ Correção automática de problemas de scroll para visualização offline
- ⚡ Suporte para sites modernos (Next.js, Gatsby, Nuxt, etc.)

## 🚀 Deploy em Produção

Veja o arquivo [DEPLOY.md](DEPLOY.md) para instruções completas de deploy no Render, Railway, ou outros serviços.

**Deploy rápido no Render**:
1. Faça push do código para GitHub
2. Conecte o repositório no [render.com](https://render.com)
3. Configure domínio customizado
4. Deploy automático a cada push!

## 🛠️ Desenvolvimento Local

### Requisitos
- Python 3.11+
- uv (gerenciador de pacotes Python)

### Instalação

```bash
# Instalar dependências
uv sync

# Instalar Playwright browsers
uv run playwright install chromium

# Rodar aplicação
uv run python app.py
```

Acesse: `http://localhost:5001`

## 📁 Estrutura do Projeto

```
.
├── app.py              # Aplicação Flask (API + SSE)
├── downloader.py       # Lógica de download e processamento
├── templates/
│   └── index.html      # Interface do usuário
├── downloads/          # Arquivos temporários (auto-limpa)
└── requirements.txt    # Dependências Python
```

## 🔧 Como Funciona

1. **Captura**: Usa Playwright para renderizar a página e capturar recursos de rede
2. **Processamento**: BeautifulSoup processa HTML e reescreve URLs para assets locais
3. **Otimização**: Remove scripts de framework que não funcionam offline
4. **Correção**: Injeta CSS para corrigir problemas de scroll e visibilidade
5. **Empacotamento**: Cria um arquivo ZIP com tudo

## 📝 Notas Técnicas

- **Smooth Scroll Libraries**: Detecta e remove Lenis, Locomotive Scroll, etc.
- **SPAs**: Remove scripts de hydration de Next.js, Gatsby, Nuxt
- **Iframes**: Extrai conteúdo de iframes (comum em site builders como Aura)
- **Lazy Loading**: Rola a página para carregar imagens lazy-loaded

## 📄 Licença

Uso pessoal e educacional.

## 🤝 Contribuições

Sugestões e melhorias são bem-vindas!
