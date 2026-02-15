# Deep Book OCR (GCP Edition)

GCP上で、技術書PDFを Document AI でOCRし、（後段で）GeminiでMarkdown整形するサーバーレスパイプラインです。

## フォルダ構成

```text
deep-book-ocr/
├── .github/workflows/terraform.yml
├── functions/
│   ├── ocr_trigger/
│   └── md_generator/
├── files/                # Terraform が zip を生成
├── main.tf
├── variables.tf
├── terraform.tfvars      # ※秘密情報を入れない。理想は example 化
└── README.md
````

## 初回セットアップ（重要）

### 1) GCPプロジェクト準備

* プロジェクト作成（例: `deep-book-ocr`）
* Billing を有効化（無効だと API/リソース作成で失敗する場合があります）

### 2) Terraform backend (GCS) 用バケット作成

Terraform state を GCS 管理する場合は、事前にバケット作成が必要です。

例:

* `deep-book-ocr-tfstate`

### 3) 必要APIについて

このリポジトリの Terraform は `google_project_service` で必要APIを有効化します。
ただし、Terraform 実行主体に `serviceusage.services.enable` 相当の権限が無い場合は、
先に手動で有効化してください。

最低限必要:

* cloudresourcemanager.googleapis.com
* iam.googleapis.com
* serviceusage.googleapis.com

## GitHub Actions (WIF)

Terraform apply 後、Outputs を GitHub Secrets に設定します。

* `WIF_PROVIDER`: terraform output `wif_provider_name`
* `WIF_SERVICE_ACCOUNT`: terraform output `github_actions_service_account`

## 実行

Input bucket（`${project_id}-input`）へ PDF をアップロードすると処理が始まります。

````

---

# 反映手順（最短）

1. 上の内容でファイルを差し替え
2. `.terraform/`, `terraform.tfstate*`, `files/*.zip`, `terraform.tfvars` を git 管理から外す（今後の事故防止）

```bash
git rm -r --cached .terraform
git rm --cached terraform.tfstate terraform.tfstate.backup
git rm -r --cached files/*.zip
git rm --cached terraform.tfvars
git add .
git commit -m "Improve Terraform/GHA: enable required APIs, fix WIF, fix provider exec, add .gitignore"
git push
````
