# bootstrap

`bootstrap` は、`deep-book-ocr` の本体 `infra` を apply する前に必要な基盤を作成するための Terraform です。

## 作成するもの

- Terraform backend 用 GCS bucket
- GitHub Actions 用 Service Account
- Cloud Functions Runtime 用 Service Account
- Workflows Runner 用 Service Account
- GitHub OIDC 用 Workload Identity Pool / Provider
- Firestore Native database（任意だが推奨）

## 使い方

```bash
cd bootstrap
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
````

## 主な outputs

* `tfstate_bucket_name`
* `github_actions_service_account_email`
* `functions_runtime_service_account_email`
* `workflow_runner_service_account_email`
* `workload_identity_provider_name`

## 次の手順

1. `outputs.tf` の値を控える
2. `infra/backend.tf` または `terraform init -backend-config=...` に tfstate bucket を設定
3. GitHub Actions 側に以下を設定

   * Workload Identity Provider
   * GitHub Actions SA email
4. `infra` を apply
