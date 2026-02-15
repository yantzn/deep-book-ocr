以下は、これまで整理した **bootstrap / infra 分離構成・Terraformのみで完結・DevContainer対応・GitHub Actions(WIF)対応** をすべて反映した
`deep-book-ocr` 用 **README.md 完全版** です。
そのままリポジトリに置き換えて使えます。

---

# 📚 Deep Book OCR (GCP Edition)

Google Cloud Platform を活用し、
**スキャンPDF → OCR → テキスト構造化 → Markdown生成** を行う
サーバーレス自動パイプラインです。

* Document AI：OCR
* Cloud Functions Gen2：処理制御
* Vertex AI（Gemini）：Markdown整形
* Cloud Storage：ファイル管理
* Terraform：完全IaC
* GitHub Actions：CI/CD（WIF認証）

---

# 🏗 システム構成

```
PDF Upload
   ↓
Cloud Storage (input)
   ↓
Cloud Functions (ocr-trigger)
   ↓
Document AI
   ↓
Cloud Storage (temp JSON)
   ↓
Cloud Functions (md-generator)
   ↓
Vertex AI (Gemini)
   ↓
Cloud Storage (output Markdown)
```

---

# 📁 リポジトリ構成

```
deep-book-ocr/
├── .devcontainer/                 # VSCode + Docker 開発環境
├── .github/workflows/terraform.yml
├── bootstrap/                     # API有効化専用 (state分離)
│   ├── main.tf
│   ├── variables.tf
│   └── versions.tf
├── infra/                         # 本体インフラ
│   ├── main.tf
│   ├── variables.tf
│   └── versions.tf
├── functions/
│   ├── ocr_trigger/
│   └── md_generator/
├── files/                         # ZIP生成物（git管理しない）
├── terraform.tfvars               # 環境変数（git管理しない）
├── .gitignore
└── README.md
```

---

# 🎯 この構成の設計思想

## Terraformのみで完結

* API有効化もTerraform
* IAMもTerraform
* WIFもTerraform
* FunctionsもTerraform

## bootstrap / infra 分離（ベストプラクティス）

| ディレクトリ    | 役割           |
| --------- | ------------ |
| bootstrap | API enableのみ |
| infra     | 本体リソース       |

理由：

* API未有効状態だとIAM取得が403で落ちる
* bootstrapで先にAPI有効化
* infraで通常構築

---

# 🚀 初回セットアップ

## ① 必須前提（手動）

Terraformで唯一自動化できない部分：

* GCPプロジェクト作成
* Billing有効化
* tfstate用GCSバケット作成

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

# 🧱 ローカル構築手順

## DevContainer利用（推奨）

VSCodeで：

```
Reopen in Container
```

Terraform / gcloud / Python が自動セットアップされます。

---

## bootstrap 実行（API有効化）

```bash
cd bootstrap
terraform init -reconfigure
terraform apply -auto-approve -var-file=../terraform.tfvars
```

有効化される主なAPI：

* cloudresourcemanager
* iam
* serviceusage
* storage
* pubsub
* cloudfunctions
* artifactregistry
* documentai
* aiplatform
* run
* eventarc

---

## infra 実行（本体構築）

```bash
cd ../infra
terraform init -reconfigure
terraform plan  -var-file=../terraform.tfvars -out=tfplan
terraform apply -auto-approve tfplan
```

---

# 🔐 GitHub Actions (WIF)

infra apply 後、Outputs を取得：

```bash
terraform output -raw wif_provider_name
terraform output -raw github_actions_service_account
```

GitHub Secrets に設定：

| Name                | Value   |
| ------------------- | ------- |
| WIF_PROVIDER        | output値 |
| WIF_SERVICE_ACCOUNT | output値 |

---

# 🤖 CI/CD 自動デプロイ

push すると：

1. bootstrap
2. infra
3. Functions再デプロイ

が自動実行されます。

---

# 📦 PDF処理方法

```
deep-book-ocr-input
```

バケットへPDFアップロードするだけ。

自動で：

* OCR
* JSON生成
* Markdown変換
* outputバケットへ保存

---

# 🧩 よくあるエラーと解決

## ① Cloud Resource Manager 403

原因：
API未有効

解決：
bootstrap を実行

---

## ② WorkloadIdentityPool update 403

原因：
display_name変更で update 発生

対策済：

```
ignore_changes = [display_name]
```

---

## ③ terraform provider permission denied

原因：
DevContainerのnoexecマウント

対策済：

```
TF_PLUGIN_CACHE_DIR=/tmp
```

---

# 🔒 セキュリティ

現在：

```
roles/editor
```

安定優先

後で最小権限へ縮小可能：

* storage.admin
* artifactregistry.admin
* cloudfunctions.admin
* iam.serviceAccountUser
* iam.workloadIdentityPoolAdmin

---

# 💰 コスト注意

主に課金対象：

* Document AI
* Vertex AI (Gemini)
* Cloud Functions

テスト時は小さいPDF推奨。

---

# 🧪 ローカル関数テスト

```bash
cd functions/ocr_trigger
functions-framework --target=start_ocr
```

---

# 🧠 将来拡張

* OCR結果の自動要約
* 知識ベース化
* RAG検索
* Notion連携
* Kindle統合

---

# 👨‍💻 開発者向けメモ

## ZIP再生成トリガ

Functionsは md5 変更で自動更新。

---

## state構成

```
bootstrap state
infra state
```

分離により安全。

---

# 📄 ライセンス

Private project

---

# ✨ 最終まとめ

このリポジトリは：

* Terraform完全自動化
* GCPサーバーレス
* OCR + AIパイプライン
* GitHub Actions自動デプロイ
* WIFによる鍵レス認証

までを **本番レベル構成** で実現しています。
