output "ipv4_address" {
  description = "Disposable verification-clone IPv4 address reported by QEMU guest agent."
  value       = module.verification_vm.default_ipv4_address
}

output "mapping_name" {
  description = "VirtioFS mount tag exposed to the verification guest."
  value       = proxmox_hardware_mapping_dir.proof.name
}

output "vm_id" {
  description = "Reserved Proxmox VM ID used by the storage verification clone."
  value       = module.verification_vm.id
}
