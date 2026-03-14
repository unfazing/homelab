# Codebase Structure

**Analysis Date:** 2026-03-14

## Directory Layout

```
[project-root]/
├── terraform/          # Terraform configurations for IaC
│   ├── main.tf         # Resource definitions
│   ├── variables.tf    # Variable definitions
│   ├── providers.tf    # Provider configurations
│   ├── homelab.tfvars.json   # Variable values (user-specified)
│   └── terraform.tfstate     # State file (tracks deployed resources)
├── packer/             # Packer configurations for image building
│   └── images/         # Packer templates
├── .env                # Environment variables (e.g., Proxmox API tokens)
├── .gitignore          # Git exclusions
├── README.md           # Project documentation
└── .terraform/         # Terraform metadata directory (auto-generated)
```

## Directory Purposes

**terraform/:**
- Purpose: Infrastructure as Code (IaC) configuration for resource provisioning.
- Contains: Resource declarations, variable definitions, and provider configurations.
- Key files: `main.tf`, `variables.tf`, `providers.tf`

**packer/:**
- Purpose: Build machine images through Packer.
- Contains: HCL templates for describing images.
- Key files: `images/image.pkr.hcl`

**.terraform/:**
- Purpose: Metadata for Terraform state management.
- Contains: Provider versions and state locking mechanisms.
- Key files: `.terraform.lock.hcl`

## Key File Locations

**Entry Points:**
- `terraform/main.tf`: Defines virtual infrastructure resources.

**Configuration:**
- `terraform/variables.tf`: Centralized variable management.
- `.env`: Proxmox authentication details (API URL, token ID, etc.).

**Core Logic:**
- `terraform/main.tf`: Resource provisioning configurations.

**Testing:**
- Not applicable (no explicit testing setup identified).

## Naming Conventions

**Files:**
- CamelCase or lowercase with extensions related to usage, e.g., `main.tf`, `variables.tf`.

**Directories:**
- Lowercase, descriptive names (e.g., `terraform`, `packer`).

## Where to Add New Code

**New Feature:**
- Primary code: `terraform/main.tf`
- Tests: Not applicable (no testing patterns identified).

**New Component/Module:**
- Implementation: `terraform/`.

**Utilities:**
- Shared helpers: `terraform/variables.tf` (for centralizing new values).

## Special Directories

**.terraform/:**
- Purpose: Metadata and state for Terraform operations.
- Generated: Yes (by Terraform CLI).
- Committed: No (ensure `.gitignore` excludes it).

---

*Structure analysis: 2026-03-14*