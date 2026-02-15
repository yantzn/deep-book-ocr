terraform {
  backend "gcs" {
    bucket = "deep-book-ocr-tfstate"
    prefix = "terraform/state"
  }
}
