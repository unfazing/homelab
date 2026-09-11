# Ansible configuration

Ansible configures the Proxmox host and the guests created by Terraform. VM lifecycle remains in Terraform; generic image construction remains in Packer.

## Layout

- `playbooks/site.yml` composes guest roles.
- `roles/common` applies shared guest configuration.
- `roles/wireguard` and `roles/adguard` configure `lab-access-01`.
- The remaining application roles are explicit placeholders until their implementation plans are approved.
- `inventories/homelab/hosts.yml.example` documents the expected generated inventory shape.
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
- The AdGuard Home install script and release version must be pinned before production deployment.
- The example access variables are documentation, not deployable secrets.
