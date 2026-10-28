#!/usr/bin/python3
"""Atomically replace only our nftables table; never flush another owner's rules."""
import pathlib
import subprocess

rule = pathlib.Path('/etc/homelab-runner/egress.nft').read_text()
present = subprocess.run(['nft', 'list', 'table', 'inet', 'homelab_ci_egress'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
transaction = ('delete table inet homelab_ci_egress\n' if present else '') + rule
subprocess.run(['nft', '--check', '-f', '-'], input=transaction, text=True, check=True)
subprocess.run(['nft', '-f', '-'], input=transaction, text=True, check=True)
