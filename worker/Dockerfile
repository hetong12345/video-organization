FROM nvidia/cuda:12.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3

WORKDIR /app

# 先复制代码，方便调试
COPY requirements.txt .

# 安装依赖，分步进行便于定位问题
RUN pip install --no-cache-dir --upgrade pip && \
    echo "Installing packages..." && \
    pip install --no-cache-dir requests numpy opencv-python-headless pillow && \
    echo "Installing torch..." && \
    pip install --no-cache-dir torch torchvision && \
    echo "Installing insightface..." && \
    pip install --no-cache-dir insightface onnxruntime-gpu && \
    echo "Installing other packages..." && \
    pip install --no-cache-dir transformers accelerate bitsandbytes hdbscan scikit-learn && \
    echo "Verifying installation..." && \
    python -c "import insightface; print('insightface:', insightface.__version__)" && \
    python -c "import torch; print('torch:', torch.__version__)"

COPY worker.py .

ENV NAS_URL=http://localhost:8000
ENV MAX_CONCURRENT=2
ENV ENABLED_TASKS=feature,cluster,tag

CMD ["python", "worker.py"]
