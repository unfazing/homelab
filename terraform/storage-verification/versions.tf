terraform {
  required_version = ">= 1.5.0, < 2.0.0"

  backend "local" {}

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.112.0"
    }
  }
}
