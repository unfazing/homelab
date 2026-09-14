# Ansible configuration

Ansible configures the Proxmox host and the guests created by Terraform. VM lifecycle remains in Terraform; generic image construction remains in Packer.

## Layout

- `playbooks/site.yml` composes guest roles.
- `roles/common` applies shared guest configuration.
- `roles/wireguard` configures the native WireGuard service on `lab-access-01`.
- `roles/adguard` will configure an AdGuard Compose project on `lab-access-01` after its deployment contract is approved.
- `roles/nextcloud`, `roles/gitea`, and `roles/password-manager` are Compose placeholders for `lab-services-01`.
- `roles/hermes` is a Compose placeholder for `lab-agents-01`.
- `inventories/homelab/hosts.example.yml` documents the expected generated inventory shape and is used for syntax validation.
- `inventories/homelab/group_vars/access.yml.example` documents non-secret access-service variables beside the inventory that consumes them.

## Inventory contract

Terraform exposes the `ansible_inventory` output. A later Task command will convert that output into `.generated/ansible/hosts.yml`; committed inventory files are examples only.

Until the generator exists, copy the example outside version control and pass it explicitly:

```sh
ansible-playbook \
  -i .generated/ansible/hosts.yml \
  ansible/playbooks/site.yml
```

## Current limitations

- Router, switch, and Proxmox host roles are not implemented.
- WireGuard peer configuration is still generated on `lab-access-01`; encrypted controller-side secret management remains open.
- AdGuard and the application roles remain excluded from `site.yml` until their pinned images, ports, data mounts, and secret handling are approved.
- The shared services VM is one trust and failure boundary; each application still requires a separate Compose project, network, secrets, and ZFS-backed dataset.
- The example access variables are documentation, not deployable secrets.
