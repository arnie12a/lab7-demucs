
# Lightweight Python image
FROM python:3.11-slim-bookworm

# Python configuration
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Application directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .

RUN python -m pip install --no-cache-dir \
    -r requirements.txt

# Copy REST server code
COPY rest-server.py .

# REST API listens on port 5000
EXPOSE 5000

# Start Flask through Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "rest-server:app"]

