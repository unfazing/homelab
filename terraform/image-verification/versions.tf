terraform {
  required_version = ">= 1.5.0, < 2.0.0"

  backend "local" {}

  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "3.0.2-rc10"
    }
  }
}
