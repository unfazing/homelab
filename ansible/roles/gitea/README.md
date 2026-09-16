# Gitea role

Deploys Gitea 1.27.3 by immutable image digest on `lab-services-01`. It uses SQLite in WAL mode for this small installation and stores the entire `/data` tree on `/srv/homelab/gitea` as UID/GID 1000.

HTTP binds only to `192.168.1.101:3000`; Git SSH binds to `192.168.1.101:2222`. Registration, OpenID sign-in/sign-up, and Actions are disabled. The ignored bootstrap administrator is `homelab-admin` with email `admin@gmail.com`; its generated password must be changed on first login. SMTP is not configured, so the email is metadata only and cannot receive password-recovery mail. No Actions runner executes on this VM.
