output "ipv4_addresses" {
  description = "Verification-clone IPv4 address reported by QEMU guest agent."
  value       = { for key, vm in module.verification_vm : key => vm.default_ipv4_address }
}

output "vm_ids" {
  description = "Reserved Proxmox VM ID used by the verification clone."
  value       = { for key, vm in module.verification_vm : key => vm.id }
}
