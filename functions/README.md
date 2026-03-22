# Cloud Functions 運用ガイド

`functions/` 配下の2つのCloud Functions Gen2（ocr-trigger / md-generator）の開発・テスト・デプロイ・運用を扱うドキュメントです。

---

## 1. 構成

- `ocr-trigger/`: GCS input イベント起動 → Document AI OCR 投入
- `md-generator/`: Pub/Sub トリガー関数 → OCR JSON 集約 + Markdown 生成 + Gemini 整形

---

## 2. ローカル開発環境

### 2-1. 依存インストール

```bash
cd functions/ocr_trigger
make install

cd functions/md_generator
make install
```

### 2-2. 単体テスト

```bash
cd functions/ocr_trigger
make test

cd functions/md_generator
make test
```

### 2-3. Lint実行

```bash
cd functions/ocr_trigger
make lint

cd functions/md_generator
make lint
```

---

## 3. ローカル実行（検証用）

### 3-1. ocr_trigger ローカル実行

前提:
- `functions/ocr_trigger/.env` を設定（`.env.example` をコピー）
- 実GCS上のPDFファイルを指定

```bash
cd functions/ocr_trigger
make run
```

設定項目:

- `APP_ENV=local`
- `GCP_PROJECT_ID`: GCPプロジェクトID
- `PROCESSOR_LOCATION`: Document AI リージョン（例: `us`）
- `PROCESSOR_ID`: OCR Processor ID
- `TEMP_BUCKET`: OCR JSON出力先
- `FIRESTORE_JOBS_COLLECTION`: ジョブ管理コレクション
- `DOCAI_MONITOR_WORKFLOW_NAME`: 監視Workflow名
- `WORKFLOW_REGION`: Workflow リージョン
- `LOCAL_INPUT_BUCKET`: テスト用入力バケット
- `LOCAL_INPUT_OBJECT`: テスト用PDF（`gs://` なし、オブジェクト名のみ）

### 3-2. md_generator ローカル実行

前提:
- `functions/md_generator/.env` を設定（`.env.example` をコピー）
- Firestore に登録済みのジョブID を指定

```bash
cd functions/md_generator
make run
```

設定項目:

- `APP_ENV=local`
- `GCP_PROJECT_ID`: GCPプロジェクトID
- `TEMP_BUCKET`: JSON入力バケット
- `OUTPUT_BUCKET`: Markdown出力バケット
- `FIRESTORE_JOBS_COLLECTION`: ジョブコレクション
- `GEMINI_MODEL_NAME`: Geminiモデル（例: `gemini-2.5-flash`）
- `GEMINI_API_KEY`: 有効なGemini API キー
- `ENABLE_GEMINI_POLISH`: `true` / `false`
- `GEMINI_MAX_INPUT_CHARS`: チャンク上限文字数
- `GEMINI_READ_TIMEOUT_SEC`: Read Timeout秒
- `LOCAL_JOB_ID`: テスト用ジョブID（既存ジョブ）

---

## 4. デプロイ前チェックリスト

### 4-1. PR/マージ前

- [ ] テスト全パス: `make test FUNCTION=ocr_trigger && make test FUNCTION=md_generator`
- [ ] Lint 無視: `make lint FUNCTION=ocr_trigger && make lint FUNCTION=md_generator`
- [ ] ローカル実行で動作確認済み
- [ ] 依存更新時は `requirements.txt` / `requirements-dev.txt` が整合
- [ ] 新しいenv変数を追加した場合、`.env.example` へ記載
- [ ] Cloud Functions タイムアウト・メモリ増加時は `infra/terraform.tfvars` で確認

### 4-2. Secrets確認

GitHub Actions 実行前に以下が揃っていることを確認:

- [ ] `GCP_PROJECT_ID`
- [ ] `GCP_REGION`
- [ ] `TFSTATE_BUCKET`
- [ ] `WIF_PROVIDER`
- [ ] `WIF_SERVICE_ACCOUNT`
- [ ] `GEMINI_API_KEY`


---

## 5. デプロイ（GitHub Actions）

`.github/workflows/terraform-infra.yml` が自動実行します。

### 5-1. デプロイフロー

```text
Push(main)
  → GitHub Actions 起動
  → OIDC 認証
  → Terraform Plan → Code Review/承認
  → Terraform Apply
  → Source ZIP upload
  → Function redeploy
```

---

## 7. 環境変数と設定管理

### 7-1. .env.example の構成

各関数の `.env.example` には、**デプロイ時に必要な全env変数** を記載してください。

パターン:

```bash
# local | gcp
APP_ENV=local

# GCP
GCP_PROJECT_ID=your-project

# 必須
VAR_NAME=value

# 任意（説明付き）
OPTIONAL_VAR=default# 説明
```

### 7-2. 本番環境（クラウド実行時）

- env変数は `infra/main.tf` の `environment_variables` で指定
- Secret値（`GEMINI_API_KEY`）は `secret_environment_variables` で Secret Manager から注入
- ローカルテストでは `.env` ファイルで上書き可能

---
