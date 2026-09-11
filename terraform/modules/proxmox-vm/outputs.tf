output "id" {
  description = "Proxmox VM ID."
  value       = proxmox_vm_qemu.this.id
}

output "name" {
  description = "Proxmox VM name."
  value       = proxmox_vm_qemu.this.name
}
