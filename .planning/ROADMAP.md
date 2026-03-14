# Roadmap: Proxmox VM Automation Tool

**Defined:** March 14, 2026

## Phases

| #   | Phase Name        | Goal                                   | Requirements       | Success Criteria                         |
|-----|-------------------|-----------------------------------------|--------------------|------------------------------------------|
| 1   | VM Provisioning   | Deploy secure VMs on Proxmox           | VM-01, VM-02, VM-03 | VMs deployable with pre-configured Packer images, SSH keys, and auth-only |
| 2   | Networking Tools  | Enable WireGuard & AdGuard setup       | NET-01, NET-02    | VMs connect securely via WireGuard       |
| 3   | Documentation     | Provide user-friendly setup guides     | DOC-01, DOC-02, DOC-03 | Complete deployment tested locally       |

---

### Phase 1: VM Provisioning
Goal: Deploy secure VMs on Proxmox that meet baseline requirements.

Requirements:
- **VM-01**: Deploy VMs on Proxmox using Terraform and Packer templates.
- **VM-02**: Inject authorized SSH keys into the VMs from a secure source.
- **VM-03**: Enforce public key authentication only for SSH.

Success Criteria:
1. VMs are deployable via Terraform using Packer-built images with secure and consistent baseline configurations.
2. SSH keys are correctly propagated from a secure source.
3. SSH only accepts key-based authentication.

---

### Phase 2: Networking Tools
Goal: Configure WireGuard and AdGuard for bootstrapped VMs.

Requirements:
- **NET-01**: Configure WireGuard for private networking.
- **NET-02**: Deploy AdGuard for DNS-level ad blocking and security.

Success Criteria:
1. WireGuard supports secure private networking between VMs.
2. AdGuard is installed and operational within the VMs.

---

### Phase 3: Documentation
Goal: Provide user-friendly documentation for deploying infrastructure.

Requirements:
- **DOC-01**: Provide clear instructions to set up Packer templates.
- **DOC-02**: Document Terraform configurations for VM creation.
- **DOC-03**: Write end-to-end deployment steps tailored for home server usage.

Success Criteria:
1. Documentation enables a first-time user to deploy VMs successfully.
2. Instructions verified through test deployments.
3. Feedback loop established for improving documentation.

---
*Roadmap created: March 14, 2026*