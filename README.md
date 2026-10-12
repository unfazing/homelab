# homelab

This homelab uses Packer to build Proxmox VM templates and Terraform to deploy VM instances on a 5 year old HP Pavilion running Proxmox VE 9.

Architecture and design decisions: [architecture.html](architecture.html)

Implementation plan and progress: [implementation.html](implementation.html)

Step-by-step deployment commands and code trace: [deployment-guide.html](deployment-guide.html)

## Operator workflow

Copy `.envrc.example` to the ignored `.envrc`, replace its placeholders, and load it with direnv. Task never sources or prints the credential file.

```sh
task doctor
task validate
```

Use `task --list` to see the available root and image tasks.

Deploy the DNS-only WireGuard dynamic record after Cloudflare becomes authoritative:

```sh
task apps:ddns:check
task apps:ddns:deploy
```

Build and test the private Caddy endpoint against Let's Encrypt staging before requesting a production certificate:

```sh
task data:reconcile
task infra:plan
task infra:apply
task apps:caddy:check
task apps:caddy:deploy-staging
HOMELAB_CONFIRM_PRODUCTION_CERTS=yes task apps:caddy:deploy-production
```

## Terraform Providers
### BGP (Selected)

### Telmate

### hashicorp
