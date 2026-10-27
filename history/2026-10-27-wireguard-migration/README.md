# Historical WireGuard migration · 27 October 2026

Archived reference only. These utilities moved the four existing native/PiVPN
peers from red `.9` into staged wg-easy on `.100`, preserving server/client keys,
PSKs and client routes. The operator selected `donk.live:27272` and DNS `.100`.
Three inactive saved profiles were excluded. Public router cutover was separate.

`controller/`, `guest/` and `tests/` preserve the former migration helpers and
tests, with their original path assumptions. They are not maintained entry
points and must not be run against production as-is. No active Taskfile or
Ansible role imports them. The historical notes mention Task commands that
have since been removed. No credentials or generated client profiles belong here.

Current installs use the ordinary wg-easy role, generate a new server identity
on empty durable storage, and create no clients. Existing clients and per-client
firewall settings are runtime data in the durable volume. Restore that data
separately when preserving identities is required; rerunning an install is not
a replacement for a data restore. Protected legacy exports remain ignored
recovery artifacts, not installation inputs or files to move into this archive.
