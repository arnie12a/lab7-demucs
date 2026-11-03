
# Python environment for the Demucs worker
FROM python:3.10-slim-bookworm

# Avoid interactive installation prompts
ENV DEBIAN_FRONTEND=noninteractive

# Make Python logs appear immediately
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Limit CPU thread usage
ENV OMP_NUM_THREADS=2
ENV MKL_NUM_THREADS=2

# Install system dependencies for audio processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        git \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Upgrade Python packaging tools
RUN python -m pip install --no-cache-dir \
    pip setuptools wheel

# Install CPU-only PyTorch and Torchaudio
# Use PyPI for normal dependencies and PyTorch for CPU wheels
RUN python -m pip install --no-cache-dir \
    "numpy<2" \
    "flit_core>=3.11,<4" \
    && python -m pip install --no-cache-dir \
    torch==2.2.2+cpu \
    torchaudio==2.2.2+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu

# Install worker dependencies
COPY requirements.txt .

RUN python -m pip install --no-cache-dir \
    -r requirements.txt

# Verify required modules are installed
RUN python -c "import demucs, torch, torchaudio, redis, boto3, requests; print('Worker dependencies installed')"

# Copy the worker code into the image
COPY worker-server.py /app/worker-server.py

# Run the worker when the container starts
CMD ["python", "-u", "/app/worker-server.py"]

