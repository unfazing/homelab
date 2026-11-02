# Garage UI role

Deploys Noooste Garage UI0.14.0 on Garage's dedicated rootless bridge. The release source is pinned to commit `90f56deb99b0b9f737a6af862ffcae1ca3312ec0` and archive SHA256. A pinned Go1.27.3 builder replaces the release's Go1.27.1 backend while retaining its exact digest-pinned static frontend assets. Swag1.16.6 (matching upstream go.mod) generates required embedded API docs; no floating build-tool version is used. `.dockerignore` excludes runtime config/credentials from the image build.

## Authentication and persistence

Only `.9:3909` publishes the internal8080 listener. Parent firewall permits Caddy `.101` and the host. Caddy serves `https://garage.home.DOMAIN`. **Native username/password authentication is enabled**, admin-token login and OIDC are disabled, and metrics require authentication. This is a privileged operator interface: its configured Garage admin token can manage all buckets and keys. Do not share this login with application users or expose it publicly.

The controller generates the admin username/password in ignored `.generated/secrets/storage.json`. Ansible renders these, plus the privileged Garage token, into protected host YAML. Neither is stored in Terraform, Git, image layers, command arguments, or logs. UI's Ed25519 signer auto-generates under `/app/data/jwt-key.pem`, backed by `/srv/homelab/garage/ui`; preserving it allows valid native sessions to survive container recreation. Do not copy signer contents into controller logs.

The container filesystem is read-only, caps are dropped, and UID0 **inside rootless Docker** maps to the unprivileged storage host account so bind ownership remains simple. UI gets no host socket/network or Garage data mount; it reaches Garage's admin API only on the private bridge. Same-host root/storage-runtime compromise remains a shared trust boundary. UI requests are limited to 32 MiB to fit its 256 MiB process budget; use the signed S3 API for larger objects.

## S3 URL behavior

The UI uses `https://s3.home.DOMAIN` for both backend S3 requests and browser presigned downloads. A container-local hostname mapping points that exact hostname at Caddy `.101`; TLS verifies the public certificate and intended hostname. Do not replace it with `http://garage:3900`: that would leak an unreachable Docker endpoint into browser download URLs. Authenticated media previews use short-lived relative UI URLs. The direct admin endpoint remains `http://garage:3903` on the bridge.

Initial startup does not depend on Caddy's new S3 route. Parent creates Caddy/AdGuard routes after services start and then runs `tasks/verify.yml`. The verifier sends credentials through stdin with `no_log`, requires trusted HTTPS, checks native auth/invalid login, uploads/downloads/removes a uniquely named probe object using the scoped app key, denies anonymous S3 access and bucket creation, and exercises browser preview and canonical presigned URLs.

Set `garage_ui_verify_restart=true` during initial acceptance to restart only the UI and prove the **same JWT** still works. Normal verification defaults to no restart. There is no scheduled backup; losing the mount loses the signer as well as development storage data.
