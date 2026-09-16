output "vm_names" {
  description = "Proxmox VM names keyed by logical machine name."
  value       = { for name, vm in module.vm : name => vm.name }
}

output "vm_ids" {
  description = "Proxmox VM IDs keyed by logical machine name."
  value       = { for name, vm in module.vm : name => vm.id }
}

output "ansible_inventory" {
  description = "Non-secret machine metadata consumed by the inventory generator."
  value = {
    for name, vm in local.vms : name => {
      ansible_host      = vm.ansible_host
      ansible_groups    = sort(tolist(vm.ansible_groups))
      ansible_port      = 22
      ansible_user      = var.cloud_init_user
      virtiofs_mappings = sort(keys(vm.virtiofs_mappings))
    }
  }
}

output "virtiofs_mappings" {
  description = "Persistent directory-mapping tags attached to each VM."
  value = {
    for name, vm in local.vms : name => sort(keys(vm.virtiofs_mappings))
  }
}
