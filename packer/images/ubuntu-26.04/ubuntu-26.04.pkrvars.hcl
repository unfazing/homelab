vmid             = 9000
name             = "ubuntu-26.04-template"
description      = "Generic Ubuntu Server 26.04.1 LTS template built by Packer"
iso_file         = "ubuntu-26.04.1-live-server-amd64.iso"
iso_url          = "https://releases.ubuntu.com/26.04/ubuntu-26.04.1-live-server-amd64.iso"
iso_storage_pool = "local"
iso_download_pve = true
iso_download     = true
iso_checksum     = "sha256:cc8a95cde20f6ced61a322420de00f10cc3c90ced545daa46cb9c1a117f1d927"

disk_storage_pool       = "local-lvm"
cloud_init_storage_pool = "local-lvm"
cpu_cores               = 2
memory                  = 4096

packer_http_port = 8800
boot_wait        = "5s"
disk_size        = "16G"

boot_command = [
  "<wait5>",
  "c<wait5>",
  "linux /casper/vmlinuz autoinstall ds='nocloud-net;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/' ---",
  "<enter><wait5>",
  "initrd /casper/initrd",
  "<enter><wait5>",
  "boot",
  "<enter>"
]

provisioner = [
  "cloud-init clean --logs --seed",
  "rm -f /etc/cloud/cloud.cfg.d/99-installer.cfg",
  "rm -f /etc/cloud/cloud.cfg.d/subiquity-disable-cloudinit-networking.cfg",
  "rm -f /etc/netplan/00-installer-config*.yaml",
  "truncate -s 0 /etc/machine-id",
  "rm -f /var/lib/dbus/machine-id",
  "rm -f /etc/sudoers.d/packer",
  "userdel --remove --force packer"
]
