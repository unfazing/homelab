# Ansible configuration

Ansible configures the Proxmox host and the guests created by Terraform. VM lifecycle remains in Terraform; generic image construction remains in Packer.

## Layout

- `playbooks/common.yml` is the safe first convergence boundary and applies no workload configuration.
- `playbooks/site.yml` imports the common baseline, then composes approved workload roles.
- `roles/common` applies shared guest configuration.
- `roles/persistent-data` mounts only the VirtioFS tags assigned by Terraform; application roles own dataset permissions.
- `roles/docker-engine` installs reviewed Docker CE and Compose versions from Docker's official repository without granting the administrator user root-equivalent Docker-group access.
- `roles/wireguard` configures the native WireGuard service on `lab-access-01`.
- `roles/adguard` will configure an AdGuard Compose project on `lab-access-01` after its deployment contract is approved.
- `roles/gitea` deploys the pinned Gitea Compose project on `lab-services-01`; Nextcloud and password-manager remain placeholders.
- `roles/hermes` is a Compose placeholder for `lab-agents-01`.
- `inventories/homelab/hosts.example.yml` documents the expected generated inventory shape and is used for syntax validation.
- `inventories/homelab/group_vars/access.yml.example` documents non-secret access-service variables beside the inventory that consumes them.

## Inventory contract

Terraform exposes the `ansible_inventory` output. `task config:inventory` converts it into ignored `.generated/ansible/hosts.json`; committed inventory files are examples only. The generated file contains addresses, groups, SSH user, port, assigned VirtioFS tags and mount points, and the generic image's stable `/usr/bin/python3` interpreter path—not credentials.

Use the generated inventory through Task:

```sh
task config:inventory
task config:validate
task config:ping
task config:common-check
task config:common
task apps:gitea:check
task apps:gitea:deploy
task apps:gitea:credentials
```

`config:common` invokes only `playbooks/common.yml`. It does not install WireGuard, Docker, or applications. SSH host-key checking is enabled; trust a changed guest key explicitly before convergence.

## Current limitations

- Router, switch, and Proxmox host roles are not implemented.
- WireGuard peer configuration is still generated on `lab-access-01`; encrypted controller-side secret management remains open.
- AdGuard, Nextcloud, Vaultwarden, and Hermes remain excluded from `site.yml` until their pinned images, ports, data mounts, and secret handling are approved. Gitea uses its dedicated playbook and Task commands.
- The shared services VM is one trust and failure boundary; each application still requires a separate Compose project, network, secrets, and ZFS-backed dataset.
- The example access variables are documentation, not deployable secrets.
