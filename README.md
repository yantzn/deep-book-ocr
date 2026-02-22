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

## ✅ ローカル実行方針（実GCS）

ローカル実行時も Storage は実GCSを利用します。

- `ocr_trigger`: 実GCS上の PDF を入力
- `md_generator`: 実GCS上の Document AI JSON を入力

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

確認用（Document AIサービスエージェント）:

```bash
terraform output documentai_service_agent_email
```

---

## infra（本体）

```bash
cd ../infra
terraform init -reconfigure
terraform apply -auto-approve -var-file=../terraform.tfvars
```

`infra` ではデフォルトで Document AI SA に次の IAM を同時付与します。

- input バケット: `roles/storage.objectViewer`
- temp バケット: `roles/storage.objectCreator`

確認:

```bash
terraform output -raw input_bucket
terraform output -raw temp_bucket
terraform output documentai_service_agent_emails_effective
```

実行主体を手動指定したい場合:

```bash
terraform apply -auto-approve -var-file=../terraform.tfvars \
   -var="documentai_service_agent_email_override=service-<PROJECT_NUMBER>@gcp-sa-prod-dai-core.iam.gserviceaccount.com"
```

実行順は次の 3 段階です。

1. `bootstrap`（API有効化）
2. `infra`（input/temp/output バケット作成 + Document AI バケットIAM付与）
3. 必要時のみ `infra` を override 指定で再適用（手動指定）

通常運用では `bootstrap` を再実行する必要はありません。

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

前提:

- ADCログイン済み
- 実GCSに入力ファイルが配置済み

## ocr_trigger

```bash
cd functions/ocr_trigger
cp .env.example .env
make install
python local_runner.py
```

`.env` の最低限設定例:

```dotenv
APP_ENV=local
GCP_PROJECT_ID=deep-book-ocr
PROCESSOR_LOCATION=us
PROCESSOR_ID=<DocumentAI Processor ID>
TEMP_BUCKET=gs://deep-book-ocr-temp-2538d0
LOCAL_INPUT_BUCKET=deep-book-ocr-input-2538d0
LOCAL_INPUT_OBJECT=uploads/test.pdf
```

ローカルPDFは事前に実GCSへアップロード:

```bash
gcloud storage cp /path/to/test.pdf gs://deep-book-ocr-input-2538d0/uploads/test.pdf
```

`LOCAL_INPUT_OBJECT` はローカルパスではなく、バケット内オブジェクト名を指定してください。

---

## md_generator

```bash
cd functions/md_generator
cp .env.example .env
make install
python local_runner.py
```

`.env` の最低限設定例:

```dotenv
APP_ENV=local
GCP_PROJECT_ID=deep-book-ocr
GCP_LOCATION=us-central1
OUTPUT_BUCKET=deep-book-ocr-output-2538d0
LOCAL_INPUT_BUCKET=deep-book-ocr-temp-2538d0
LOCAL_INPUT_OBJECT=processed/sample_pdf/0.json
MODEL_NAME=gemini-1.5-flash
CHUNK_SIZE=10
```

`LOCAL_INPUT_OBJECT` は Document AI 出力JSONのオブジェクト名を指定してください。

推奨実行順:

1. `ocr_trigger` を実行して Document AI ジョブを起動
2. `TEMP_BUCKET` に生成された JSON パスを確認
3. その JSON パスを `md_generator` の `LOCAL_INPUT_OBJECT` に設定して実行

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

## GCSオブジェクトが見つからない

→ `LOCAL_INPUT_BUCKET` / `LOCAL_INPUT_OBJECT` と、実バケット上の配置を確認

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
