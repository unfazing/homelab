# homelab

This homelab uses Packer to build Proxmox VM templates and Terraform to deploy VM instances on a 5 year old HP Pavilion running Proxmox VE 9.

Architecture and design decisions: [architecture.html](architecture.html)

Implementation plan and progress: [implementation.html](implementation.html)

## Operator workflow

Copy `.envrc.example` to the ignored `.envrc`, replace its placeholders, and load it with direnv. Task never sources or prints the credential file.

```sh
task doctor
task validate
```

Use `task --list` to see the available root and image tasks.

## Terraform Providers
### BGP (Selected)

### Telmate

### hashicorp
