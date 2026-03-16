# infra Terraform ガイド

このディレクトリは、Deep Book OCR の**本体インフラ**を作成します。

- GCS バケット（input/temp/output/source）
- Cloud Functions Gen2（`ocr-trigger` / `md-generator`）
- Document AI Processor
- Artifact Registry（Functions ビルド用）
- Workflows（Document AI 監視 + md-generator 起動）
- Firestore（任意作成）
- 実行SA向け IAM（Runtime/Workflow/Document AI）
- 必須 API 有効化

## 前提

先に `bootstrap` を適用し、以下を取得しておきます。

- `github_actions_service_account_email`
- `functions_runtime_service_account_email`
- `workflow_runner_service_account_email`
- `tfstate_bucket_name`

`bootstrap` 未実施だと、SAメールや backend バケットが不足します。

## 初期化手順

`backend "gcs" {}` は空定義なので、`init` 時に bucket/prefix を渡します。

```bash
cd infra
terraform init -reconfigure \
  -backend-config="bucket=<bootstrap の tfstate_bucket_name>" \
  -backend-config="prefix=terraform/state/infra"
```

## 変数設定

`terraform.tfvars.example` をベースに `terraform.tfvars` を作成します。

```bash
cp terraform.tfvars.example terraform.tfvars
```

最低限、次を実値に更新してください。

- `project_id`
- `github_actions_service_account_email`
- `functions_runtime_service_account_email`
- `workflow_runner_service_account_email`

## 適用

```bash
terraform plan -var-file=terraform.tfvars -out=tfplan
terraform apply tfplan
```

## 主な動作

### 1) API 有効化
`apis.tf` で以下を有効化します（抜粋）。

- `cloudfunctions.googleapis.com`
- `run.googleapis.com`
- `documentai.googleapis.com`
- `aiplatform.googleapis.com`
- `firestore.googleapis.com`
- `workflows.googleapis.com`

### 2) バケット作成
`main.tf` の `random_id.bucket_suffix` で suffix を作り、以下を生成します。

- `<project>-input-<suffix>`
- `<project>-temp-<suffix>`
- `<project>-output-<suffix>`
- `<project>-source-<suffix>`（`source_bucket_name` 未指定時）

### 3) Functions
- `ocr-trigger`（GCS input finalize イベント）
- `md-generator`（HTTP 専用、Workflows から OIDC 呼び出し）

### 4) Workflows
`workflows/docai_monitor.yaml` で以下を実行します。

1. Firestore ジョブを `DOC_AI_RUNNING` に更新
2. Document AI operation をポーリング
3. 成功/失敗を Firestore に反映
4. 成功時に `md-generator` を HTTP POST で起動
5. ステータスを `MD_TRIGGERED` に更新

## 主要変数

- `documentai_location` : Document AI のリージョン（例: `us`）
- `gcp_location` : Gemini のリージョン（例: `us-central1`）
- `gemini_model_name` : 生成モデル名（既定: `gemini-1.5-pro`）
- `docai_submit_timeout_sec` : OCR submit タイムアウト秒
- `ocr_firestore_timeout_sec` : ocr-trigger の Firestore timeout 秒
- `workflow_execute_timeout_sec` : ocr-trigger の Workflows create_execution timeout 秒
- `md_firestore_timeout_sec` : md-generator の Firestore timeout 秒
- `gemini_timeout_sec` : Gemini リクエスト timeout 秒
- `gcs_download_timeout_sec` / `gcs_upload_timeout_sec` / `gcs_exists_timeout_sec` : md-generator の GCS I/O timeout 秒
- `gcs_download_max_attempts` / `gcs_download_base_sleep_sec` : md-generator の JSON ダウンロード再試行設定
- `create_firestore_database` : infra 側で Firestore を作るか（既定 `false`）

## 出力

適用後、以下を利用します。

- `input_bucket_name`
- `temp_bucket_name`
- `output_bucket_name`
- `source_bucket_name`
- `documentai_processor_name`
- `documentai_processor_id`
- `ocr_trigger_function_uri`
- `md_generator_function_uri`
- `workflow_name`
- `bucket_suffix`

## 運用上の注意

- `google_storage_bucket_object.*_source` は**プレースホルダ**です。実コード zip は CI/CD で上書きする想定です。
- `create_firestore_database=true` は、既存 Firestore があるプロジェクトでは失敗しやすいため通常 `false` 推奨です。
- `source_bucket_name` を既存バケットにしたい場合のみ明示指定してください。
- `md-generator` は Workflow 経由の HTTP 起動が前提です（直接イベントトリガーではありません）。

## トラブルシュート

- **`SERVICE_DISABLED firestore.googleapis.com`**
  - API が未有効。`bootstrap` / `infra` の API有効化適用後、数分待って再実行。

- **`Policy update access denied`（project IAM更新）**
  - 実行主体に `setIamPolicy` 権限が不足。高権限側（通常 bootstrap 実行主体）で IAM 付与を先に反映。

- **state bucket not found**
  - `terraform init -reconfigure` の `bucket` が古い可能性。`bootstrap` の最新 `tfstate_bucket_name` を使って再初期化。
