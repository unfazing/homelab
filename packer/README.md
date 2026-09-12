# Packer image pipeline

Packer builds one reusable operating-system template. It does **not** create the five long-lived homelab VMs or install their applications:

- Packer creates `ubuntu-26.04-template` as Proxmox template VM `9000`.
- Terraform clones that template and gives each VM its CPU, memory, disks, VLAN, address, and identity.
- Ansible installs and configures the services inside those VMs.

## What happens during a build

Run the pipeline from the repository root:

```sh
task image:validate
task image:build
```

`image:build` changes Proxmox. The flow is:

1. Task initializes the pinned Proxmox plugin and checks Packer formatting.
2. `scripts/packer-image.sh` generates a one-use ED25519 key pair under `.generated/packer`.
3. The script renders a temporary NoCloud seed containing only the public key and unattended-install settings.
4. Packer checks that the definition is valid and refuses to continue if Proxmox VM ID `9000` is occupied.
5. Proxmox downloads the checksum-pinned Ubuntu Server 26.04.1 LTS ISO directly from Ubuntu.
6. Packer creates VM `9000`, boots the ISO, and briefly serves the seed from the operator machine's trusted interface on TCP port `8800`.
7. Ubuntu installs itself, enables key-only SSH, and installs `qemu-guest-agent`.
8. Packer connects with the one-use private key and removes installer networking, cloud-init state, machine identity, the temporary sudo rule, and the `packer` account.
9. Packer converts VM `9000` into `ubuntu-26.04-template` and writes the non-secret `.generated/packer/manifest.json` build record.
10. The script deletes the temporary seed and key even if validation or the build fails.

The next pipeline step will clone the template into a disposable VM and verify that cloud-init, unique host identity, SSH host keys, and the QEMU guest agent behave correctly.

## What is a NoCloud seed?

Cloud-init normally obtains machine configuration from a cloud provider's metadata service. **NoCloud** is a cloud-init data source for machines that have no such provider. A *seed* is the small configuration bundle supplied to NoCloud.

This build serves two seed files:

- `meta-data` identifies the temporary installation instance.
- `user-data` tells Ubuntu's autoinstaller how to install the OS, configure DHCP, install required packages, and authorize Packer's temporary public key.

The boot command includes a URL shaped like this:

```text
ds=nocloud-net;s=http://<operator-ip>:8800/
```

That tells the installer to fetch `/meta-data` and `/user-data` from Packer's temporary HTTP server. Despite the name *NoCloud*, the `nocloud-net` form can retrieve its seed over the network; “NoCloud” means that it does not require AWS, Azure, or another cloud metadata service.

The build-time seed is distinct from the Proxmox cloud-init drive attached to the finished template. Terraform later populates that drive with each cloned VM's hostname, address, and administrator SSH key.

## Security boundaries

- The seed server binds to `PKR_VAR_packer_http_interface`, not every workstation interface. That interface must be reachable by the temporary VM.
- The HTTP endpoint is unauthenticated but exists only during a build. It contains a public key, never the private key or a reusable password.
- The `packer` account has passwordless sudo only during image construction and is removed before templating.
- Generated keys and rendered seed files are ignored by Git and deleted on exit.
- The image contains no application, workload identity, persistent application data, or application secret.

See `images/ubuntu-26.04/README.md` for the concrete image definition and `../implementation.html` for progress and acceptance criteria.
