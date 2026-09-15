output "id" {
  description = "Proxmox VM ID."
  value       = proxmox_virtual_environment_vm.this.id
}

output "name" {
  description = "Proxmox VM name."
  value       = proxmox_virtual_environment_vm.this.name
}

output "default_ipv4_address" {
  description = "First non-loopback IPv4 address reported by the QEMU guest agent."
  value = try([
    for address in flatten(proxmox_virtual_environment_vm.this.ipv4_addresses) : address
    if !startswith(address, "127.")
  ][0], null)
}
