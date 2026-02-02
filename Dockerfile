# Use Python image with Playwright dependencies
FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create downloads directory
RUN mkdir -p downloads

# Expose port (Render will set $PORT)
EXPOSE 8080

# Start gunicorn
CMD gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 300 --access-logfile - --error-logfile -
