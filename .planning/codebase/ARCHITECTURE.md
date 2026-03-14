# Architecture

**Analysis Date:** 2026-03-14

## Pattern Overview

**Overall:** Infrastructure as Code (IaC)

**Key Characteristics:**
- Declarative configurations for resource provisioning
- Modular variable management
- Provider-centric resource management

## Layers

**Resource Definitions:**
- Purpose: Define virtual infrastructure resources (VMs, networks, etc.)
- Location: `terraform/main.tf`
- Contains: Resource blocks (e.g., `proxmox_vm_qemu`)
- Depends on: Variables and backend configuration
- Used by: Terraform CLI during `plan` and `apply`

**Variable Management:**
- Purpose: Centralize configuration values for reusability and portability
- Location: `terraform/variables.tf`
- Contains: Variables with types, descriptions, and values
- Depends on: Not applicable
- Used by: Resource definitions in `main.tf`

## Data Flow

**Terraform Execution:**

1. User runs `terraform apply`.
2. Terraform reads variable definitions from `terraform/variables.tf`.
3. Terraform processes resource definitions in `terraform/main.tf`.
4. Resources are provisioned on Proxmox hypervisor.

**State Management:**
- Handled via `.terraform` state files.
- Ensures idempotency and tracks deployed resources.

## Key Abstractions

**Proxmox VM Resource (`proxmox_vm_qemu`):**
- Purpose: Represents a virtual machine on the Proxmox hypervisor.
- Examples: `terraform/main.tf:1-5`
- Pattern: Declarative resource definition

**Variables (`variable`):**
- Purpose: Parameterize configurations
- Examples: `terraform/variables.tf:1-21`
- Pattern: Defined using `variable` block

## Entry Points

**Terraform Execution:**
- Location: Command-line execution targeting Terraform files
- Triggers: Commands like `terraform init`, `terraform plan`, `terraform apply`
- Responsibilities: Provision, update, or destroy infrastructure based on IaC definitions

## Error Handling

**Strategy:**
- Eliminate runtime resource conflicts through Terraform's plan-preview mechanism.

**Patterns:**
- Variable validation and error messaging in variable definitions
- Dry-runs before apply to verify configurations

## Cross-Cutting Concerns

**Logging:** Supported by native Terraform CLI logs.
**Validation:** Declarative enforcement via Terraform variable schemas.
**Authentication:** Managed through Proxmox API tokens in `.env`.

---

*Architecture analysis: 2026-03-14*