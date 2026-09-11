resource "proxmox_vm_qemu" "this" {
  name               = var.name
  target_node        = var.target_node
  clone              = var.clone
  full_clone         = true
  os_type            = "cloud-init"
  agent              = 1
  start_at_node_boot = true

  memory = var.memory_mb
  cpu {
    cores   = var.cpu_cores
    sockets = 1
    numa    = true
    type    = "host"
  }

  disk {
    slot    = "scsi0"
    size    = var.disk_gb
    storage = var.disk_storage
  }

  disk {
    type    = "cloudinit"
    slot    = "ide2"
    storage = var.disk_storage
  }

  network {
    id      = 0
    model   = "virtio"
    bridge  = var.bridge
    tag     = var.vlan_tag
    macaddr = var.mac_address
  }

  scsihw   = "virtio-scsi-pci"
  boot     = "order=scsi0"
  bootdisk = "scsi0"
  bios     = "ovmf"
  machine  = "q35"

  ciuser     = var.cloud_init_user
  cipassword = var.debug_password
  sshkeys    = var.ssh_public_key
  ipconfig0  = var.ipconfig0
  skip_ipv6  = true

  efidisk {
    efitype = "4m"
    storage = var.disk_storage
  }
}
