variable "name" {
  type        = string
  description = "Proxmox VM name."
}

variable "target_node" {
  type        = string
  description = "Proxmox node that hosts the VM."
}

variable "clone" {
  type        = string
  description = "Packer-built template name to clone."
}

variable "cpu_cores" {
  type        = number
  description = "Virtual CPU core count."
}

variable "memory_mb" {
  type        = number
  description = "Guest memory in MiB."
}

variable "disk_gb" {
  type        = number
  description = "Rebuildable root-disk size in GiB."
}

variable "disk_storage" {
  type        = string
  description = "Proxmox storage ID for rebuildable VM disks."
}

variable "bridge" {
  type        = string
  description = "Proxmox bridge attached to the VM NIC."
}

variable "vlan_tag" {
  type        = number
  description = "Optional VLAN tag applied by Proxmox."
  default     = null
}

variable "mac_address" {
  type        = string
  description = "Optional stable NIC MAC address."
  default     = null
}

variable "ipconfig0" {
  type        = string
  description = "Cloud-init network configuration for the primary NIC."
}

variable "cloud_init_user" {
  type        = string
  description = "Administrative cloud-init user."
}

variable "debug_password" {
  type        = string
  description = "Optional temporary cloud-init password."
  default     = null
  sensitive   = true
}

variable "ssh_public_key" {
  type        = string
  description = "SSH public key injected by cloud-init."
}
