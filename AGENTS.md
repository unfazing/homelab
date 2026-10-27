# Homelab repository instructions

## Sources of truth

- Treat `architecture.html` as the canonical source for design intent, constraints, topology, and accepted decisions.
- Treat `implementation.html` as the canonical source for implementation sequence, acceptance criteria, and progress.
- Read the relevant sections of both documents before planning or changing the repository.
- After making any change to code, configuration, dependencies, documentation, or repository structure, update both HTML documents in the same change set. Record the design effect in `architecture.html` and the implementation status or next action in `implementation.html`.
- When an implementation detail changes the design, amend the architecture decision first. Do not mark work complete while the documents disagree.
- Keep both documents concise. Add or change an SVG diagram only when it materially improves understanding.

## Collaboration

- Challenge ambiguous assumptions and surface security, operability, recovery, and maintenance trade-offs.
- Ask for a decision when different answers would materially change the architecture. Otherwise, state a reasonable assumption and proceed.
- Keep VM names semantic and independent of the product currently assigned to them.

## Tool ownership

- Packer owns the generic, reusable Ubuntu image. Do not add workload identity, applications, or durable data to the image.
- Terraform owns Proxmox VMs, rebuildable disks, NICs, VLAN tags, and machine-readable outputs. Do not configure applications or store application secrets in Terraform.
- Ansible owns guest convergence and application configuration. Do not use it to own VM lifecycle or Terraform state.
- Task is the public operator interface. Keep implementation logic in Packer, Terraform, Ansible, or focused scripts.
- Canonical deployment tasks must support fresh service installs without legacy client exports or one-time migration prerequisites. Keep one-time migration utilities under `history/` without Taskfile hooks or active-role imports; existing clients, keys and per-client policies are runtime data, not install fixtures.
- Keep controller-side Task helpers under `taskfiles/scripts/`. They are private implementation details invoked by Taskfiles, not a second public interface and not Ansible-managed guest scripts. Put scripts installed on a guest inside the owning Ansible role.

## Security and data safety

- Do not expose application services directly to the public internet. The only planned public ingress is the WireGuard UDP port.
- Do not commit credentials, private keys, Terraform state, generated WireGuard profiles, or other secrets.
- Treat VM operating systems as disposable and persistent application data as separately managed state.
- Keep ordinary compute teardown separate from persistent-data destruction. Require explicit user authorization before destructive data operations.

## Verification and Git

- Run formatting and validation appropriate to every changed tool before reporting completion.
- Preserve unrelated working-tree changes and local artifacts.
- When commits are requested, use conventional commit messages and split changes into coherent commits.
- Do not push commits unless the user explicitly requests it.
