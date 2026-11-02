#!/usr/bin/python3
"""Replace our table atomically; WireGuard/Docker tables are not ours."""
import pathlib
import subprocess

rule = pathlib.Path('/etc/homelab/storage/firewall.nft').read_text()
present = subprocess.run(['nft', 'list', 'table', 'inet', 'homelab_storage'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
transaction = ('delete table inet homelab_storage\n' if present else '') + rule
subprocess.run(['nft', '--check', '-f', '-'], input=transaction, text=True, check=True)
subprocess.run(['nft', '-f', '-'], input=transaction, text=True, check=True)
