variable "pm_api_url" {
  type        = string
  description = "Proxmox API URL."
}

variable "pm_api_token_id" {
  type        = string
  description = "Proxmox API token ID."
}

variable "pm_api_token_secret" {
  type        = string
  description = "Proxmox API token secret."
  sensitive   = true
}

variable "verification_node" {
  type        = string
  description = "Proxmox node on which the verification clone runs."
}

variable "ssh_public_key" {
  type        = string
  description = "Temporary public key injected into the verification clone."
}

variable "template_vmid" {
  type        = number
  description = "Exact Packer template VM ID under test."
  default     = 9000
}
