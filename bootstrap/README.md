# bootstrap Terraform Runbook

`bootstrap` は `infra` を安全に運用するための土台を作るモジュールです。  
主目的は **Terraform state 管理** と **GitHub Actions の鍵レス認証（OIDC/WIF）** です。

---

## 1. このREADMEの目的

- 初回bootstrap構築の標準手順
- 変更時の安全な運用手順
- `infra` 連携に必要な outputs/Secrets の対応
- 失敗時の切り分け

---

## 2. 作成されるリソース

### 共通基盤

- Terraform backend 用 GCS bucket（versioning有効）
- GitHub Actions デプロイ用 Service Account
- Cloud Functions Runtime 用 Service Account
- Workflows Runner 用 Service Account

### 認証基盤（GitHub Actions向け）

- Workload Identity Pool
- Workload Identity Provider
- `roles/iam.workloadIdentityUser` バインディング

### オプション

- Firestore Native database（`enable_firestore=true` 時のみ）

---

## 3. 前提条件

- Terraform `>= 1.5.0`
- GCPプロジェクトへの十分なIAM権限
- `terraform.tfvars` に以下を設定
   - `project_id`
   - `github_repository`（`owner/repo`）
   - `github_repository_owner`

---

## 4. 初回セットアップ

```bash
cd bootstrap
terraform init
terraform validate
terraform plan -lock-timeout=5m -var-file=terraform.tfvars -out=tfplan
terraform apply -lock-timeout=5m tfplan
```

---

## 5. 重要変数（運用で触る項目）

- `tfstate_location`  
   state bucket のロケーション。運用中の変更は避ける。

- `rotation_key`  
   変更すると suffix が再生成され、SA/WIF/tfstate bucket 名が切り替わる。  
   **通常運用で変更しない**。

- `enable_firestore` / `firestore_location`  
   Firestoreをbootstrapで管理する場合に利用。  
   Firestoreリージョンは作成後に変更不可。

---

## 6. outputs と連携先

apply 後に以下を取得します。

```bash
terraform output tfstate_bucket_name
terraform output workload_identity_provider_name
terraform output github_actions_service_account_email
terraform output functions_runtime_service_account_email
terraform output workflow_runner_service_account_email
```

### `infra` 連携

- `tfstate_bucket_name` → `infra` の `terraform init -backend-config="bucket=..."`
- `functions_runtime_service_account_email` → `infra/terraform.tfvars`
- `workflow_runner_service_account_email` → `infra/terraform.tfvars`

### GitHub Actions Secrets 連携

- `workload_identity_provider_name` → `WIF_PROVIDER`
- `github_actions_service_account_email` → `WIF_SERVICE_ACCOUNT`
- `tfstate_bucket_name` → `TFSTATE_BUCKET`

---

## 7. 標準運用フロー

1. `bootstrap` は初回に実施
2. outputs を GitHub Secrets / `infra` に反映
3. 以後の本体変更は `infra` 側の GitHub Actions で運用

`bootstrap` の再applyは、WIFやSA構成を更新する必要がある場合に限定してください。

---

## 8. 安全運用ルール

- `plan` を確認せずに `apply` しない
- `rotation_key` を無計画に変更しない
- `terraform destroy` は原則禁止（要明示承認）
- 手動IAM変更を行った場合は次回 `plan` でドリフト確認

---

## 9. 次の手順（infraへ）

1. `infra/terraform.tfvars` に SA email を設定
2. `infra` を backend 指定付きで初期化
3. `infra` の `plan/apply` を実行

例:

```bash
cd ../infra
terraform init -reconfigure \
   -backend-config="bucket=<tfstate_bucket_name>" \
   -backend-config="prefix=terraform/state/infra"
terraform plan -lock-timeout=5m -var-file=terraform.tfvars -out=tfplan
terraform apply -lock-timeout=5m tfplan
```
