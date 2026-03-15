FROM python:3.11-slim

# Install system dependencies for yt-dlp
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Expose port
EXPOSE 10000

# Start with gunicorn
CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:10000", "--workers", "1", "--threads", "4", "--timeout", "300", "--access-logfile", "-"]
