terraform {
  backend "gcs" {
    bucket = "deep-book-ocr-tfstate"
    prefix = "bootstrap"
  }
}
