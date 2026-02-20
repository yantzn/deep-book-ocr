FROM mcr.microsoft.com/devcontainers/python:3.10

# ---- OS packages ----
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    gnupg curl lsb-release make \
  && rm -rf /var/lib/apt/lists/*

# ---- Terraform ----
RUN curl -fsSL https://apt.releases.hashicorp.com/gpg \
  | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg \
  && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
  | tee /etc/apt/sources.list.d/hashicorp.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends terraform \
  && rm -rf /var/lib/apt/lists/*

# ---- Google Cloud SDK ----
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | tee /etc/apt/sources.list.d/google-cloud-sdk.list \
  && curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
  && apt-get update \
  && apt-get install -y --no-install-recommends google-cloud-cli \
  && rm -rf /var/lib/apt/lists/*

# ---- Python tooling ----
RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir \
    functions-framework \
    pip-tools \
    ruff \
    pytest

WORKDIR /workspace
