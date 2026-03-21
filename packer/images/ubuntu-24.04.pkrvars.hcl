name             = "ubuntu-24.04-template"
iso_file         = "ubuntu-24.04.3-live-server-amd64.iso"
iso_url          = ""
iso_storage_pool = "local"
iso_download_pve = false
iso_download     = false
iso_checksum     = "file:https://releases.ubuntu.com/noble/SHA256SUMS"

disk_storage_pool = "local-lvm"


http_directory = "../http/ubuntu"
boot_wait      = "5s"
disk_size      = "100G"

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
  "cloud-init clean",
  "rm /etc/cloud/cloud.cfg.d/*",
  "userdel --remove --force packer"
]
