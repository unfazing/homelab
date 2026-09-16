# Hermes role

Planned Docker Compose configuration for `lab-agents-01` using the mounted ZFS dataset at `/srv/homelab/hermes`; container UID ownership remains open. The role will grant only the Gitea ports published by `lab-services-01`, not access to Nextcloud, Vaultwarden, or Proxmox management.
