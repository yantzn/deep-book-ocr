# 📚 Deep Book OCR (GCP Edition)

このプロジェクトは、Google Cloud Platform (GCP) を活用して、スキャンされた技術書のPDFを自動で解析し、Gemini 1.5 Proによって構造化された高品質なMarkdownファイルに変換するサーバーレス・パイプラインです。

## 📁 フォルダ構成と役割

Windowsローカル環境およびGitHubリポジトリ内は以下の構成にしてください。

```text
C:\deep-book-ocr\
├── .github/
│   └── workflows/
│       └── terraform.yml      # GitHub Actionsの設定（自動デプロイ用）
├── functions/                 # Cloud Functionsのソースコード
│   ├── ocr_trigger/           # PDF検知・Document AI起動用
│   │   ├── main.py            # 実行ロジック
│   │   └── requirements.txt   # 依存ライブラリ
│   └── md_generator/          # JSON分割・Gemini連携用
│       ├── main.py            # 実行ロジック
│       └── requirements.txt   # 依存ライブラリ
├── files/                     # (自動生成) TerraformがZIP化した一時ファイル用
├── main.tf                    # GCPインフラのメイン定義ファイル
├── variables.tf               # 変数の定義（プロジェクト名、リージョン等）
├── terraform.tfvars           # 変数に代入する実際の値（秘密情報は除く）
└── README.md                  # このドキュメント

```

### 構成要素の説明

- **`functions/`**: 各関数の本体です。`main.py`を修正して`git push`すると、Terraformが変更を検知して自動的にGCP上の関数を更新します。
- **`main.tf`**: インフラの設計図です。ストレージ、OCRプロセッサ、関数の連携、認証設定がすべて記述されています。
- **`.github/workflows/`**: GitHub Actionsの設定です。ここに記載された手順に従って、GitHubが自動的にTerraformを実行します。

---

## 🏗 システム構成図

1. **Cloud Storage (Input)**: PDFをアップロード。
2. **Cloud Functions (OCR Trigger)**: ファイルを検知し、Document AIを起動。
3. **Document AI**: 非同期処理でOCRを実行し、結果をJSONとして一時バケットへ出力。
4. **Cloud Functions (Markdown Generator)**: JSON出力を検知し、内容を5ページ単位で分割。
5. **Vertex AI (Gemini 1.5 Pro)**: 分割されたテキストを技術的な文脈でMarkdownへ整形。
6. **Cloud Storage (Output)**: 結合された最終的な `.md` ファイルを保存。

---

## 🚀 構築ステップ

### 1. GCPの初期設定（手動）

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクト `deep-book-ocr` を作成。
2. 以下のAPIを有効化：

- Document AI API / Cloud Functions API / Vertex AI API / Cloud Build API

3. Terraformの状態管理用バケットを手動作成：

- 名前: `deep-book-ocr-tfstate` （※一意の名前にする必要があります）

### 2. インフラの初回構築（IaC）

WindowsのPowerShellで以下を実行します。

```powershell
# ログイン
gcloud auth application-default login

# 初期化
terraform init

# 構築実行
terraform apply

```

※完了後、出力される `wif_provider_name` をメモしてください。

### 3. CI/CDの設定（GitHub Actions）

GitHubリポジトリの **Settings > Secrets and variables > Actions** に以下を登録：

- `WIF_PROVIDER`: 手順2でメモしたプロバイダー名
- `WIF_SERVICE_ACCOUNT`: `github-actions-sa@deep-book-ocr.iam.gserviceaccount.com`

---

## 🛠 運用と更新

### コードの修正

`functions/` 内の Python ファイルや `main.tf` を修正し、`main` ブランチへ Push してください。
GitHub Actions が自動で差分を検知し、**数分以内に GCP 上の関数やインフラが最新状態に更新**されます。

### 実行

`deep-book-ocr-input` バケットにPDFを投入するだけで処理が開始されます。進捗は Cloud Functions のログから確認可能です。

---

## ⚠️ 注意事項

- **コスト**: ページ数が多い書籍を大量に処理する場合、Document AIとGeminiの利用料金に注意してください。
- **タイムアウト**: 非常に巨大なPDFの場合、Cloud Functionsの実行時間上限（デフォルト設定）を調整する必要がある場合があります。
