terraform {
  required_version = ">= 1.5.0, < 2.0.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.112.0"
    }
  }
}


provider "proxmox" {
  endpoint  = trimsuffix(trimsuffix(var.pm_api_url, "/"), "/api2/json")
  api_token = "${var.pm_api_token_id}=${var.pm_api_token_secret}"
  insecure  = true
}
