#!/usr/bin/env bash
# Build script for Docker/Deploy environments
# For local development, use setup.sh instead

set -e

# Set Docker environment flag
export DOCKER_CONTAINER=1

# Run unified setup
./setup.sh
