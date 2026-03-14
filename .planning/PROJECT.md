# Proxmox VM Automation Tool

## What This Is

A tool for quickly deploying VMs on a Proxmox instance using Terraform and Packer, optimized for developers. The tool simplifies creating developer-ready VM instances with secure configurations and bootstrapped tools like WireGuard and AdGuard.

## Core Value

Developers can easily deploy secure, minimally configured VM instances with required tools, saving significant time in launching dev environments.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Enable deployment of VMs on Proxmox with Packer and Terraform.
- [ ] Inject authorized SSH keys into VMs during provisioning, sourced securely.
- [ ] Enforce public key authentication only (disable password logins).
- [ ] Configure WireGuard for private networking inside the VMs.
- [ ] Set up AdGuard for DNS-level ad blocking/security.
- [ ] Provide easy-to-follow documentation for home-server deployments.

### Out of Scope

- Dynamic inventory management beyond Terraform state.
- Support for non-Proxmox hypervisors.

## Context

- Proxmox instance available on a local network for iterative testing.
- Toolchain includes Packer for creating consistent and reusable VM images, and Terraform for managing infrastructure deployments. Packer is used to pre-configure VMs with:
  - SSH key injection (public key authentication only).
  - Pre-installed networking tools like WireGuard and AdGuard.
  - Baseline configurations to meet developer workflows.

This ensures all deployed VMs share the same secure and functional base image.
- Goal is to save time for developers by automating tedious setup tasks.

## Constraints

- **Authentication**: Only public key authentication for SSH — no password logins.
- **Security**: Authorized SSH keys must be securely stored and propagated during provisioning.
- **Infrastructure**: Target environment is a Proxmox server running locally.

## Key Decisions

| Decision            | Rationale                          | Outcome       |
|---------------------|------------------------------------|---------------|
| Use Packer & Terraform | Well-supported by Proxmox API     | ✓ Good        |
| Public key auth only | Enhances VM security               | — Pending     |

---
*Last updated: March 14, 2026 after initialization*