# DeepMirror WebSites

Download de sites com alta fidelidade via Runtime Network Recording.

Hoje o projeto tem dois fluxos separados que compartilham o mesmo `core/`:

- `single_page/`: app web oficial do projeto, pronto para uso local e deploy

O deploy atual aponta apenas para o `single_page`.

## Estado atual

- A interface web oficial está em [single_page/app.py](/single_page/app.py)
- O contrato programático legado continua em [downloader.py](/downloader.py)
- O runtime compartilhado está em [core/](/core)

## Uso rápido

### Single-page web

```bash
cp .env.example .env
bash setup.sh
uv run python -m single_page.app
```

Acesse `http://localhost:5001`.

Guia completo: [single_page/USAGE.md](/single_page/USAGE.md)

### Single-page programático

```python
from downloader import WebsiteDownloader

WebsiteDownloader(
    'https://example.com',
    'downloads/example',
    print,
).process()
```

## Deploy

O container e o compose deste repositório sobem apenas o `single_page`.

- `Dockerfile`: build do projeto com entrypoint web do `single_page`
- `entrypoint.sh`: inicia `gunicorn single_page.app:app`
- `compose.dev.yml`: expõe o serviço web do `single_page`

## Estrutura

```text
./
├── core/
├── single_page/
├── downloader.py
├── development/
├── downloads/
├── Dockerfile
├── compose.dev.yml
└── pyproject.toml
```

## Documentação

- Uso do single-page: [single_page/USAGE.md](/single_page/USAGE.md)
- Roadmap futuro: [FUTURE.md](/FUTURE.md)
- Histórico técnico: [development/CHANGELOG.md](/development/CHANGELOG.md)
- **Nuxt**: SSR assets capturados, `__NUXT__` state mantido
- **Gatsby**: Build estático funciona perfeitamente
- **React Router**: Rotas client-side requerem servidor (limitação conhecida)
- **WebGL/Three.js**: Texturas, modelos, shaders, WASM (Draco) capturados
- **Rive**: Arquivos `.riv` e canvas interativos funcionam

### Limitações Conhecidas

- **Rotas client-side**: SPAs com router precisam de servidor local (não funciona abrindo `index.html` direto)
- **WebSockets**: Não funcionam offline (esperado)
- **Autenticação**: Sites com login não podem ser baixados (sem cookies)
- **Infinite scroll**: Captura até `MAX_SCROLL_ITERATIONS` (padrão: 20)

## 🚀 Deploy em Produção

Veja [DEPLOY.md](DEPLOY.md) para instruções de deploy em:
- Render
- Railway
- Docker
- Heroku

## 📄 Changelog

Veja [CHANGELOG.md](development/CHANGELOG.md) para histórico detalhado de mudanças.

## 🔮 Roadmap

Veja [FUTURE.md](FUTURE.md) para features planejadas e bugs conhecidos.

## 📄 Licença

Uso pessoal e educacional. Este projeto é uma ferramenta de pesquisa e análise de design.

**Nota ética**: Respeite direitos autorais. Use apenas para:
- Análise de design pessoal
- Backup de seus próprios sites
- Pesquisa educacional
- Sites com permissão explícita

## 🤝 Contribuindo

Contribuições são bem-vindas! Por favor:

1. Fork o projeto
2. Crie uma branch para sua feature (`git checkout -b feature/AmazingFeature`)
3. Commit suas mudanças (`git commit -m 'Add some AmazingFeature'`)
4. Push para a branch (`git push origin feature/AmazingFeature`)
5. Abra um Pull Request

**Desenvolvido com ❤️ para AI Design & Style Transfer**
