FROM mcr.microsoft.com/devcontainers/python:3.10-bookworm

# 基本ツール
RUN apt-get update && apt-get install -y \
    make \
    git \
    curl \
    ca-certificates \
    sudo \
 && rm -rf /var/lib/apt/lists/*

# gcloud CLI
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] http://packages.cloud.google.com/apt cloud-sdk main" \
      | tee /etc/apt/sources.list.d/google-cloud-sdk.list \
 && curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
      | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
 && apt-get update && apt-get install -y google-cloud-cli \
 && rm -rf /var/lib/apt/lists/*

# pip-tools / ruff（開発補助）
RUN pip install --no-cache-dir -U pip pip-tools ruff
