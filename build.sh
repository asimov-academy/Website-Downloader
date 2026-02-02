#!/usr/bin/env bash
set -e

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Installing Playwright Chromium..."
playwright install chromium

echo "Attempting to install system dependencies (may fail, that's ok)..."
playwright install-deps chromium || echo "System deps install failed, continuing..."

echo "Build completed successfully!"
