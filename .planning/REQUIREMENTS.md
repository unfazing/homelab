# Requirements: Proxmox VM Automation Tool

**Defined:** March 14, 2026
**Core Value:** Developers can easily deploy secure, minimally configured VM instances with required tools, saving significant time.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### VM Provisioning

- [ ] **VM-01**: Deploy VMs on Proxmox using Terraform and Packer templates. Packer-built images must include baseline configurations:
  - SSH key injection (secure source).
  - Public key authentication as the only allowed login method.
  - Pre-installed WireGuard and AdGuard setup scripts.
- [ ] **VM-02**: Inject authorized SSH keys into the VMs from a secure source.
- [ ] **VM-03**: Enforce public key authentication only for SSH.

### Networking Tools

- [ ] **NET-01**: Configure WireGuard for private networking.
- [ ] **NET-02**: Deploy AdGuard for DNS-level ad blocking and security.

### Documentation

- [ ] **DOC-01**: Provide clear instructions to set up Packer templates.
- [ ] **DOC-02**: Document Terraform configurations for VM creation.
- [ ] **DOC-03**: Write end-to-end deployment steps tailored for home server usage.

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Dynamic Features

- **DYN-01**: Enable dynamic inventory management.
- **DYN-02**: Add support for non-local Proxmox environments.

## Out of Scope

| Feature                             | Reason                     |
|-------------------------------------|----------------------------|
| Non-Proxmox hypervisors             | Focused on Proxmox support |
| Password-based SSH authentication   | Security risk              |
| Advanced inventory management       | Future scope               |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase      | Status       |
|-------------|------------|--------------|
| VM-01       | Phase 1    | Pending      |
| VM-02       | Phase 1    | Pending      |
| VM-03       | Phase 1    | Pending      |
| NET-01      | Phase 2    | Pending      |
| NET-02      | Phase 2    | Pending      |
| DOC-01      | Phase 3    | Pending      |
| DOC-02      | Phase 3    | Pending      |
| DOC-03      | Phase 3    | Pending      |

**Coverage:**
- v1 requirements: 8 total
- Mapped to phases: 8
- Unmapped: 0 ✓

---
*Requirements defined: March 14, 2026*