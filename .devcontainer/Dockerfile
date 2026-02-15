FROM mcr.microsoft.com/devcontainers/python:3.10

# パッケージリストの更新と基本ツールのインストール
RUN apt-get update && apt-get install -y gnupg curl lsb-release

# 1. Terraform のインストール
RUN curl -fsSL https://apt.releases.hashicorp.com/gpg \
    | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg \
  && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
    | tee /etc/apt/sources.list.d/hashicorp.list \
  && apt-get update \
  && apt-get install -y terraform

# 2. Google Cloud SDK (gcloud CLI) のインストール
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list \
  && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
  && apt-get update \
  && apt-get install -y google-cloud-cli

# 3. Functions Framework と Google Cloud 各種クライアントライブラリのインストール
RUN pip install --no-cache-dir \
  functions-framework \
  google-cloud-documentai \
  google-cloud-storage \
  google-cloud-aiplatform \
  google-cloud-resource-manager \
  pytest \
  black

WORKDIR /workspace
