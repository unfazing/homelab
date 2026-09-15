resource "proxmox_virtual_environment_vm" "this" {
  vm_id       = var.vmid
  name        = var.name
  node_name   = var.target_node
  description = "Managed by Terraform."

  clone {
    vm_id = var.clone_id
    full  = var.full_clone
  }

  agent {
    enabled = true
    timeout = "${var.agent_timeout}s"

    wait_for_ip {
      ipv4 = true
    }
  }

  started = true
  on_boot = var.start_at_node_boot

  cpu {
    cores   = var.cpu_cores
    sockets = 1
    numa    = true
    type    = "host"
  }

  memory {
    dedicated = var.memory_mb
  }

  disk {
    datastore_id = var.disk_storage
    file_format  = "raw"
    interface    = "scsi0"
    replicate    = false
    size         = var.disk_gb
  }

  network_device {
    bridge      = var.bridge
    mac_address = var.mac_address
    model       = "virtio"
    vlan_id     = var.vlan_tag
  }

  scsi_hardware = "virtio-scsi-pci"
  boot_order    = ["scsi0"]
  bios          = "ovmf"
  machine       = "q35"

  initialization {
    datastore_id = var.disk_storage
    interface    = "ide2"

    ip_config {
      ipv4 {
        address = var.ipv4_address
        gateway = var.ipv4_gateway
      }
    }

    user_account {
      keys     = [var.ssh_public_key]
      password = var.debug_password
      username = var.cloud_init_user
    }
  }

  operating_system {
    type = "l26"
  }

  efi_disk {
    datastore_id      = var.disk_storage
    file_format       = "raw"
    pre_enrolled_keys = false
    type              = "4m"
  }

  lifecycle {
    ignore_changes = [
      clone,
      started,
    ]
  }
}
