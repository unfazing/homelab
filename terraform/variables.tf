variable "pm_api_url" {
  type        = string
  description = "URL to access the Proxmox API. Usually <domain/ip-addr>:8006/api2/json."
}

variable "pm_api_token_id" {
  type        = string
  description = "Name of Proxmox Access Token with permissions for terraform provider."
}

variable "pm_api_token_secret" {
  type        = string
  description = "Proxmox Access Token secret."
  sensitive   = true
}

variable "ssh_public_key_file" {
  type        = string
  description = "Path to the SSH public key file injected into deployed VMs."
  default     = "./keys/keys.pub"
}

variable "debug_password" {
  type        = string
  description = "Optional temporary password for the cloud-init user during debugging."
  default     = null
  sensitive   = true
}

variable "vms" {
  description = "VM definitions keyed by deployed VM name."
  type = map(object({
    target_node  = string
    clone        = string
    cpu_cores    = optional(number, 2)
    memory_mb    = optional(number, 4096)
    disk_gb      = optional(number, 100)
    disk_storage = optional(string, "local-lvm")
    bridge       = optional(string, "vmbr0")
    ipconfig0    = optional(string, "ip=dhcp")
    mac_address  = optional(string)
  }))
}
