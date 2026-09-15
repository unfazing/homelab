provider "proxmox" {
  endpoint  = trimsuffix(trimsuffix(var.pm_api_url, "/"), "/api2/json")
  api_token = "${var.pm_api_token_id}=${var.pm_api_token_secret}"
  insecure  = true
}
