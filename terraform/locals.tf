locals {
  ssh_public_key = trimspace(file(var.ssh_public_key_file))

  vms = {
    for name, cfg in var.vms : name => {
      name         = name
      target_node  = cfg.target_node
      clone        = cfg.clone
      cpu_cores    = cfg.cpu_cores
      memory_mb    = cfg.memory_mb
      disk_gb      = cfg.disk_gb
      disk_storage = cfg.disk_storage
      bridge       = cfg.bridge
      ipconfig0    = cfg.ipconfig0
      mac_address  = try(cfg.mac_address, null)
    }
  }
}
