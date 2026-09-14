# Packer image pipeline

Packer builds one reusable operating-system template. It does **not** create the three long-lived homelab VMs or install their applications:

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
6. Packer packages the seed as a tiny ISO labelled `cidata`, attaches it as a second virtual CD, creates VM `9000`, and boots the Ubuntu ISO.
7. Ubuntu installs itself, enables key-only SSH, and installs `qemu-guest-agent`.
8. Packer connects with the one-use private key, waits for first-boot cloud-init to finish, then removes installer networking, omits the `dyn-netconf` and `systemd-networkd` early-network modules from the local-disk initramfs, regenerates every initramfs, and cleans cloud-init state, machine identity, the temporary sudo rule, and the `packer` account. Any Dracut error or remaining default network profile fails the build before templating.
9. Packer converts VM `9000` into `ubuntu-26.04-template` and writes the non-secret `.generated/packer/manifest.json` build record.
10. Packer removes the seed CD, and the script deletes the rendered seed and key even if validation or the build fails.

`task image:verify` uses one isolated local Terraform state to create a linked clone on reserved VM ID `9900`. It verifies cloud-init and hostname, guest addressing, key-only SSH, removal of build-time networking and the build account, non-empty machine and SSH identities, and QEMU guest-agent access. It then destroys the clone and retains a non-secret report at `.generated/packer/verification.json` after a pass. Multi-clone identity and networking verification remains deferred until DHCP moves away from the current ZTE router or excluded static test addresses are assigned.

## What is a NoCloud seed?

Cloud-init normally obtains machine configuration from a cloud provider's metadata service. **NoCloud** is a cloud-init data source for machines that have no such provider. A *seed* is the small configuration bundle supplied to NoCloud.

This build uses two seed files:

- `meta-data` identifies the temporary installation instance.
- `user-data` tells Ubuntu's autoinstaller how to install the OS, configure DHCP, install required packages, and authorize Packer's temporary public key.

Packer packages those files at the root of an ISO9660 filesystem labelled `cidata`. The temporary VM therefore sees two virtual CDs:

- the checksum-pinned Ubuntu installer ISO;
- the generated `cidata` seed ISO.

The boot command enables `autoinstall` and selects the local NoCloud data source. Cloud-init discovers the `cidata` volume and reads `/meta-data` and `/user-data` without contacting the operator machine. “NoCloud” means that it does not require AWS, Azure, or another cloud metadata service.

The build-time seed is distinct from the Proxmox cloud-init drive attached to the finished template. Terraform later populates that drive with each cloned VM's hostname, address, and administrator SSH key.

## Security boundaries

- The seed CD contains a public key, never the private key or a reusable password.
- Seed delivery does not open a listening port on the operator machine or depend on guest networking.
- The `packer` account has passwordless sudo only during image construction and is removed before templating.
- Generated keys and rendered seed files are ignored by Git and deleted on exit.
- The image contains no application, workload identity, persistent application data, or application secret.

See `images/ubuntu-26.04/README.md` for the concrete image definition and `../implementation.html` for progress and acceptance criteria.
