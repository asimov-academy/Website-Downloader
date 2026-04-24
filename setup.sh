#!/usr/bin/env bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}DeepMirror WebSites - Setup${NC}"
echo "========================================"

# Detect environment
if [ -f "/.dockerenv" ] || [ -n "$DOCKER_CONTAINER" ] || [ -n "$RENDER" ]; then
    ENVIRONMENT="docker"
    echo -e "${YELLOW}🐳 Ambiente: Docker/Deploy${NC}"
else
    ENVIRONMENT="local"
    echo -e "${YELLOW}💻 Ambiente: Local${NC}"
fi

echo ""

# Clean Python cache (prevent Flask reloader bug)
echo -e "${GREEN}Limpando cache Python...${NC}"
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo "- Cache limpo"

echo ""

if [ -f ".env" ]; then
    set -a
    . ./.env
    set +a
    echo "- Variáveis carregadas de .env"
    echo ""
fi

if [ "$ENVIRONMENT" = "local" ]; then
    # Local development setup
    echo -e "${GREEN}Setup Local${NC}"
    echo "--------------------------------"

    # Check if uv is installed
    if ! command -v uv &> /dev/null; then
        echo -e "${RED}uv não encontrado!${NC}"
        echo ""
        echo "Por favor, instale o uv primeiro:"
        echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        echo ""
        echo "Ou visite: https://github.com/astral-sh/uv"
        exit 1
    fi

    echo "- uv encontrado: $(uv --version)"
    echo ""

    # Sync dependencies with uv
    echo -e "${GREEN}Instalando dependências com uv...${NC}"
    uv sync --frozen
    echo "- Dependências instaladas"

    echo ""

    # Install Playwright Chromium
    echo -e "${GREEN}Instalando Playwright Chromium...${NC}"
    uv run playwright install chromium
    echo "- Playwright Chromium instalado"

    echo ""
    echo -e "${GREEN}Setup completo!${NC}"
    echo ""
    echo "Para rodar o single-page web app:"
    echo "  uv run python -m single_page.app"
    echo ""
    echo "Para testar o downloader diretamente:"
    echo "  uv run python -c 'from downloader import WebsiteDownloader; print(\"OK\")'"
    echo ""

else
    # Docker/Deploy environment
    echo -e "${GREEN}Setup Docker/Deploy${NC}"
    echo "--------------------------------"

    if ! command -v uv &> /dev/null; then
        echo -e "${RED}uv não encontrado no ambiente de build${NC}"
        exit 1
    fi

    echo "Instalando dependências Python com uv..."
    uv sync --frozen
    echo "- Dependências instaladas"

    echo ""

    echo "Instalando Playwright Chromium..."
    uv run playwright install chromium
    echo "- Playwright Chromium instalado"

    echo ""

    echo "Tentando instalar dependências do sistema (pode falhar)..."
    uv run playwright install-deps chromium || echo " System deps install falhou (continuando)"

    echo ""
    echo -e "${GREEN}Build completo!${NC}"
fi
