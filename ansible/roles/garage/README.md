# Garage storage role

Deploys Garage 2.5.0 pinned by OCI digest on red's dedicated **rootless** storage Docker daemon. The parent `storage-runtime`/mount roles must finish first. This role does not allocate, format, destroy, or migrate disks.

## Inputs and trust boundary

Consume `ansible/vars/storage.yml`, `storage_mounts_verified=true`, `storage_runtime_uid`, `storage_runtime_environment` and protected `storage_secrets.garage`. `storage_runtime_environment` must point at `/run/user/UID/docker.sock`, with the runtime account's HOME and XDG_RUNTIME_DIR. It must never point at rootful Docker.

Only `.9:3900` (S3) is published. RPC3901 and admin3903 remain on the dedicated `homelab-storage` bridge (`172.30.92.0/28`). The parent host firewall allows Caddy `.101` and host-local connections to the published S3 port. Caddy preserves the original Host/path/query for signed requests; do not put Basic Auth in front of S3. Anonymous object reads and website hosting are disabled.

`/srv/homelab/garage` must be an actual ext4 mount. Metadata and objects are separate directories on it, not separate disks. Missing mounts and linked/non-directory state paths fail before startup; long bind mounts have `create_host_path:false`. Existing state is never recursively chowned. Configuration is root-owned, readable by the storage account; file-based RPC/admin/metrics secrets are mode0600. Namespace UID0 maps to that unprivileged host account inside rootless Docker. No host networking, Docker socket, extra capabilities, or writable container root filesystem is granted.

## Bootstrap and permissions

`reconcile.py` uses the native Garage RPC `json-api` CLI. No database edits or published admin API are required; application credentials arrive on stdin under Ansible `no_log`.

On an empty, single-node cluster it applies a replication-factor-one layout with 64GiB advertised capacity inside the 80GiB filesystem. Existing matching layouts are retained; foreign layout/staging changes fail for explicit review. This leaves metadata/headroom but is not a filesystem quota. It creates `colouring-book-dev` only if absent and imports the controller-generated `GK` plus24hex access-key ID and64hex secret only if absent. A conflicting or expired key fails instead of being silently replaced.

The managed application key receives read/write on that bucket only. Repeated convergence removes create-bucket, owner, and unrelated-bucket grants from this managed key, but never deletes unknown keys, buckets, or their data. Garage UI alone receives the privileged admin token; applications, Homepage and Hermes must not receive it.

Replication1 has **no redundancy**. No backup or automatic snapshot schedule is installed. Internal metadata snapshots, if manually requested later, would not replace backups. User explicitly deferred backups; host/disk loss can lose this development data.

## Verification

`tasks/verify.yml` proves native convergence is unchanged. It is read-only and fails on drift; normal convergence performs repairs. The UI final verifier covers authenticated HTTPS/S3 behavior after Caddy routes exist. Unit tests: `python3 -m unittest discover -s ansible/roles/garage/tests -v`.

An isolated real Garage container test has additionally checked fresh bootstrap, a no-change second run, exact key permissions and persistent node/layout state after restart. Disposable test containers/volumes were removed.
