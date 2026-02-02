#!/bin/bash
set -e

echo "Starting gunicorn on port 8080..."

# Start gunicorn with fixed port 8080
# Railway will automatically proxy external traffic to this port
exec gunicorn app:app \
    --bind "0.0.0.0:8080" \
    --workers 1 \
    --threads 2 \
    --timeout 300 \
    --worker-class gthread \
    --access-logfile - \
    --error-logfile -
