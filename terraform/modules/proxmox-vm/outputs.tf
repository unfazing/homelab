output "id" {
  description = "Proxmox VM ID."
  value       = proxmox_vm_qemu.this.id
}

output "name" {
  description = "Proxmox VM name."
  value       = proxmox_vm_qemu.this.name
}

output "default_ipv4_address" {
  description = "IPv4 address reported by the QEMU guest agent."
  value       = proxmox_vm_qemu.this.default_ipv4_address
}
