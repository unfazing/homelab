resource "proxmox_vm_qemu" "test_vm" {
  count       = 1
  name        = var.vm_name
  target_node = var.pm_target_host
  agent       = 1
  memory      = var.memory_mb
  cpu {
    cores = var.cpu_count
    sockets = 1
    numa = true
    type = "x86-64-v2-AES"
  }
  disk {
    slot    = "virtio0"
    size    = var.disk_gb
    storage = "local-lvm"
  }
  network {
    id     = 0
    model  = "virtio"
    bridge = "vmbr0"
  }
  scsihw      = "virtio-scsi-single" # Use VirtIO SCSI controller
  boot        = "order=scsi0" # has to be the same as the OS disk of the template
  clone       = var.clone # The template to clone from

  # Cloud-Init configuration
  cicustom   = var.cicustom
  ciupgrade  = true # it will upgrade the OS to the latest version
  nameserver = var.nameserver
  ipconfig0  = var.ipconfig0
  skip_ipv6  = true
  ciuser     = "root" # The user to use for the cloud-init script
  cipassword = var.cipassword # Password for the cloud-init user
  sshkeys    = var.ssh-public-key # The SSH public key to be added to the VM

  # Most cloud-init images require a serial device for their display
  serial {
    id = 0
  }

  # EFI disk for UEFI boot
  # This is required for cloud-init images that use UEFI
  # If your template does not use UEFI, you can remove this block
  efidisk {
    efitype = "4m" 
    storage = "hdd-vm-data"
  }
}

output "vm_name" {
  value = proxmox_vm_qemu.test_vm[0].name
}

output "vm_id" {
  value = proxmox_vm_qemu.test_vm[0].id
}
