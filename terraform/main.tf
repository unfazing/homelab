resource "proxmox_vm_qemu" "vm" {
  for_each           = local.vms
  name               = each.key
  target_node        = each.value.target_node
  clone              = each.value.clone
  full_clone         = true
  os_type            = "cloud-init"
  agent              = 1
  start_at_node_boot = true

  memory = each.value.memory_mb
  cpu {
    cores   = each.value.cpu_cores
    sockets = 1
    numa    = true
    type    = "host"
  }

  disk {
    slot    = "scsi0"
    size    = each.value.disk_gb
    storage = each.value.disk_storage
  }

  disk {
    type    = "cloudinit"
    slot    = "ide2"
    storage = each.value.disk_storage
  }

  network {
    id      = 0
    model   = "virtio"
    bridge  = each.value.bridge
    macaddr = each.value.mac_address
  }

  scsihw   = "virtio-scsi-pci"
  boot     = "order=scsi0"
  bootdisk = "scsi0"
  bios     = "ovmf"
  machine  = "q35"

  # Cloud-Init configuration
  ciuser     = "user"
  cipassword = var.debug_password
  sshkeys    = local.ssh_public_key
  ipconfig0  = each.value.ipconfig0
  skip_ipv6  = true

  efidisk {
    efitype = "4m"
    storage = each.value.disk_storage
  }
}

output "vm_names" {
  value = { for name, vm in proxmox_vm_qemu.vm : name => vm.name }
}

output "vm_ids" {
  value = { for name, vm in proxmox_vm_qemu.vm : name => vm.id }
}
