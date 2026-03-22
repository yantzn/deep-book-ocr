# infra Terraform Runbook

このディレクトリは Deep Book OCR の本体インフラを管理します。  
対象は **GCS / Cloud Functions Gen2 / Workflows / Document AI / IAM / Artifact Registry / Firestore(任意)** です。

---

## 1. このREADMEの目的

このREADMEは以下を対象にした **運用手順書** です。

- 初回構築（init/plan/apply）
- 継続運用（安全な変更反映）
- 障害時対応（よくある失敗の切り分け）
- ドリフト検知（実環境との差分管理）

---

## 2. 前提条件

### 必須

- Terraform `>= 1.6.0`
- Google provider `~> 5.0`（`versions.tf`）
- `bootstrap` の適用完了

### bootstrapから引き継ぐ値

`bootstrap` の `terraform output` から次を取得し、`infra/terraform.tfvars` に設定します。

- `github_actions_service_account_email`
- `functions_runtime_service_account_email`
- `workflow_runner_service_account_email`

`backend` 初期化には以下も必要です。

- `tfstate_bucket_name`

---

## 3. 何が作成されるか

このモジュールは主に以下を作成・管理します。

- GCSバケット: `input` / `temp` / `output` / `source`
- Cloud Functions Gen2: `ocr-trigger` / `md-generator`
- Document AI Processor（OCR）
- Workflows: `docai-monitor`
- Artifact Registry（Functions build artifact）
- 必須API有効化（`apis.tf`）
- 実行SAに対するバケット・SecretアクセスIAM
- Firestore database（`create_firestore_database=true` の場合のみ）

補足:
- `md-generator` は **Pub/Subトリガー関数** として作成され、`docai-monitor` からトピック publish で非同期起動されます。
- `ocr-trigger` は input バケット finalize イベントで起動されます。

---

## 4. 初回セットアップ（手動）

### 4-1. backend初期化

`backend "gcs" {}` は空定義です。`init` 時に bucket/prefix を渡します。

```bash
cd infra
terraform init -reconfigure \
  -backend-config="bucket=<bootstrapのtfstate_bucket_name>" \
  -backend-config="prefix=terraform/state/infra"
```

### 4-2. tfvars作成

```bash
cp terraform.tfvars.example terraform.tfvars
```

最低限の更新項目:

- `project_id`
- `github_actions_service_account_email`
- `functions_runtime_service_account_email`
- `workflow_runner_service_account_email`

### 4-3. 反映

```bash
terraform validate
terraform plan -lock-timeout=5m -var-file=terraform.tfvars -out=tfplan
terraform apply -lock-timeout=5m tfplan
```

---

## 5. 推奨運用フロー（本番）

本番反映は GitHub Actions（`.github/workflows/terraform-infra.yml`）を正とする

### 標準フロー

1. ブランチで変更
2. PRで `plan` を確認
3. `main` マージ後に `apply`

---

## 6. 主要変数（運用で触る項目）

### パフォーマンス/安定性

- `gemini_max_input_chars`（チャンクサイズ）
- `gemini_read_timeout_sec`（Gemini read timeout）
- `gemini_request_max_attempts`（Gemini retry回数）
- `md_generator_timeout_seconds`（Function実行上限）

### スケーリング

- `ocr_trigger_max_instance_count`
- `md_generator_max_instance_count`
- `*_max_instance_request_concurrency`

### タイムアウト（外部I/O）

- `docai_submit_timeout_sec`
- `workflow_execute_timeout_sec`
- `gcs_download_timeout_sec` / `gcs_upload_timeout_sec`
- `md_firestore_timeout_sec` / `ocr_firestore_timeout_sec`

---

## 7. Outputs（運用で使う値）

```bash
terraform output input_bucket_name
terraform output output_bucket_name
terraform output workflow_name
```

主な用途:

- `input_bucket_name`: OCR入力ファイル投入先
- `output_bucket_name`: Markdown出力確認先
- `workflow_name`: 実行状態追跡

補足:
- MD成功時の input PDF / temp JSON 削除は `md-generator` 実装側で実施します（Workflow側では削除しません）。

---

## 8. 安全に変更するための原則

- `terraform apply` は必ず `plan` の結果を確認してから実行
- `-target` は緊急時以外使わない（依存関係崩壊の原因）
- 手動でGCPリソースを編集した場合は、必ず次回 `plan` でドリフト確認
- Secret値（`GEMINI_API_KEY`）は tfvars に入れない（Secret Manager経由）

---

## 9. 変更失敗時の復旧方針

### apply失敗時

1. 同じ state/backend で `terraform plan` を再実行
2. 失敗原因（権限/API未有効/依存順）を解消
3. 再度 `apply`

### 関数デプロイ不整合時

- `source` バケットのZIP更新状態
- Artifact Registry / Cloud Build API有効化
- 実行SAへの権限

を優先確認してください。

---

## 10. 参考ファイル

- `infra/main.tf`（主要リソース）
- `infra/apis.tf`（必須API）
- `infra/variables.tf`（入力変数）
- `infra/outputs.tf`（運用出力）
- `infra/workflows/docai_monitor.yaml`（OCR監視ワークフロー）
