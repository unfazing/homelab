variable "pm_target_host" {
  type        = string
  description = "Name of the Proxmox target host to deploy the resources on."
  default     = "blue"
}

variable "pm_api_url" {
  type        = string
  description = "URL to access the Proxmox API. Usually <domain/ip-addr>::8006/api2/json."
}

variable "pm_api_token_id" {
  type        = string
  description = "Name of Proxmox Access Token with permissions for terraform provider"
}

variable "pm_api_token_secret" {
  type        = string
  description = "Proxmox Access Token secret"
}

variable "vm_name" {
  type        = string
  description = "Name of the virtual machine to create."
  default     = "example-vm"
}

variable "cpu_count" {
  type        = number
  description = "Number of CPU cores for the virtual machine."
  default     = 8
}

variable "memory_mb" {
  type        = number
  description = "Amount of memory (in MB) for the virtual machine."
  default     = 16384
}

variable "disk_gb" {
  type        = number
  description = "Disk size (in GB) for the virtual machine."
  default     = 100
}


variable "nameserver" {
    type        = string
    description = "Nameserver for the VM"
    default     = "1.1.1.1 8.8.8.8"

}

variable "cicustom" {
    type        = string
    description = "Cloud-Init custom configuration"
    default     = "vendor=local:snippets/qemu-guest-agent.yml"
}

variable "cipassword" {
    type        = string
    description = "Cloud-Init password for the VM"
    sensitive = true
}


variable "ssh-public-key" {
    type = string
    description = "SSH public key for the VMs"
    sensitive = true
}


variable "clone" {
  type = string
}

variable "ipconfig0" {
  type = string
  default = "ip=dhcp"
}
