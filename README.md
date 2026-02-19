最高です 👍
今の最新構成（**srcレイアウト統一 / APP_ENV / Cloud Logging / pip-compile / Ruff / DevContainer / Gen2 / GCSイベントトリガー**）に合わせて README をアップデートします。

そのまま置き換え可能な **最新版 README.md 完全版** を出します。

---

# 📚 Deep Book OCR (GCP Serverless Edition)

Google Cloud Platform を活用し、

**PDF → OCR → JSON → Markdown構造化 → AI整形**

を行うサーバーレス自動パイプラインです。

---

## 🚀 使用技術

| サービス                 | 役割         |
| -------------------- | ---------- |
| Document AI          | OCR        |
| Cloud Functions Gen2 | 処理制御       |
| Vertex AI (Gemini)   | Markdown整形 |
| Cloud Storage        | ファイル管理     |
| Terraform            | 完全IaC      |
| GitHub Actions (WIF) | CI/CD      |
| pip-tools            | 依存固定       |
| Ruff                 | Lint       |
| DevContainer         | ローカル開発     |

---

# 🏗 システム構成

```
PDF Upload
   ↓
Cloud Storage (input bucket)
   ↓
Cloud Functions (ocr-trigger)
   ↓
Document AI
   ↓
Cloud Storage (JSON output)
   ↓
Cloud Functions (md-generator)
   ↓
Vertex AI (Gemini)
   ↓
Cloud Storage (Markdown output)
```

---

# 📁 リポジトリ構成

```
deep-book-ocr/
├── .devcontainer/
├── .github/workflows/deploy-functions.yml
├── bootstrap/
├── infra/
├── functions/
│   ├── ocr_trigger/
│   │   ├── src/ocr_trigger/
│   │   │   ├── config.py
│   │   │   ├── entrypoint.py
│   │   │   └── gcp_services.py
│   │   ├── tests/
│   │   ├── local_runner.py
│   │   └── requirements.*
│   │
│   └── md_generator/
│       ├── src/md_generator/
│       │   ├── config.py
│       │   ├── entrypoint.py
│       │   ├── gcp_services.py
│       │   └── markdown_logic.py
│       ├── tests/
│       ├── local_runner.py
│       └── requirements.*
│
├── ruff.toml
├── terraform.tfvars
└── README.md
```

---

# 🎯 設計方針

## ✅ src構成統一（main.pyなし）

Cloud Functions Gen2 では `main.py` は必須ではありません。

すべての関数は：

```
src/<package>/entrypoint.py
```

にエントリポイントを統一。

デプロイ時に：

```
--entry-point=generate_markdown
--entry-point=start_ocr
```

を指定します。

---

## ✅ APP_ENV 切り替え

| 環境   | APP_ENV |
| ---- | ------- |
| ローカル | local   |
| 本番   | gcp     |

### ログ挙動

| APP_ENV | ログ            |
| ------- | ------------- |
| local   | 標準 logging    |
| gcp     | Cloud Logging |

---

## ✅ STORAGE_MODE 切替（md_generator）

| モード      | 説明              |
| -------- | --------------- |
| gcp      | 実GCS            |
| emulator | fake-gcs-server |

Vertex AI は常に実GCP（ADC利用）。

---

# 🚀 初回セットアップ

## ① 前提（手動）

Terraformで自動化できないもの：

* GCPプロジェクト作成
* Billing有効化
* tfstate用GCS作成

例：

```
deep-book-ocr-tfstate
```

---

## ② terraform.tfvars 作成

```hcl
project_id        = "deep-book-ocr"
region            = "asia-northeast1"
github_repository = "yantzn/deep-book-ocr"
tfstate_bucket    = "deep-book-ocr-tfstate"
```

---

# 🧱 インフラ構築

## bootstrap（API有効化）

```bash
cd bootstrap
terraform init -reconfigure
terraform apply -auto-approve -var-file=../terraform.tfvars
```

---

## infra（本体）

```bash
cd ../infra
terraform init -reconfigure
terraform apply -auto-approve -var-file=../terraform.tfvars
```

---

# 🔐 GitHub Actions (WIF)

Terraform apply 後：

```bash
terraform output -raw wif_provider_name
terraform output -raw github_actions_service_account
```

GitHub Secrets に設定：

| Name                | Value      |
| ------------------- | ---------- |
| WIF_PROVIDER        | output値    |
| WIF_SERVICE_ACCOUNT | output値    |
| GCP_PROJECT_ID      | project_id |
| GCP_REGION          | region     |

---

# 🤖 自動デプロイ

push → GitHub Actions → Cloud Functions Gen2 再デプロイ

エントリポイント：

| Function     | entry_point       |
| ------------ | ----------------- |
| ocr-trigger  | start_ocr         |
| md-generator | generate_markdown |

---

# 🧪 ローカル開発

## DevContainer（推奨）

VSCode:

```
Reopen in Container
```

自動セットアップ：

* Python
* Terraform
* gcloud
* pip-tools

---

## ADC認証（Gemini用）

```bash
sudo chown -R vscode:vscode /home/vscode/.config/gcloud
gcloud auth application-default login
```

---

# 🔍 ローカル関数実行

## ocr_trigger

```bash
cd functions/ocr_trigger
cp .env.example .env
make install
python local_runner.py
```

---

## md_generator（Storageエミュ）

```bash
cd functions/md_generator
cp .env.example .env
make install
python local_runner.py
```

---

# 🧪 テスト

```bash
make test
```

---

# 🧹 Lint

```bash
make lint
```

---

# 📦 依存管理

## 依存追加時

```bash
# requirements.in 編集
make compile
make install
```

## 通常開発

```bash
make install
```

---

# 🧩 よくあるエラー

## 403 API未有効

→ bootstrap実行

---

## Cloud Loggingが出ない

→ APP_ENV=gcp が設定されているか確認

---

## emulatorでバケットが無い

→ fake-gcs-server 起動確認

---

# 🔒 セキュリティ

現在：

```
roles/editor
```

将来的に最小権限へ縮小予定。

---

# 💰 コスト注意

主な課金：

* Document AI
* Vertex AI
* Cloud Functions

テストは小さいPDF推奨。

---

# 🧠 将来拡張

* OCR後の自動要約
* RAG化
* Notion連携
* Kindle統合
