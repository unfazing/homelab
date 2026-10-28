#!/usr/bin/python3
"""Forced SSH command: promote image digests through an operator-owned contract.

Never accepts Compose files, shell fragments, environment variables or host paths.
Contract files are root-owned and deliberately separate from writable release state.
"""
import fcntl
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

APP = re.compile(r'[a-z][a-z0-9-]{0,39}')
REVISION = re.compile(r'[a-f0-9]{40}')
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')


def validate_release(contract, release):
    if set(release) != {'revision', 'images'} or not REVISION.fullmatch(release['revision']):
        raise ValueError('Expected a commit SHA and an images mapping')
    if not isinstance(release['images'], dict) or set(release['images']) != set(contract['images']):
        raise ValueError('Image names do not match the admitted application')
    for name, image in release['images'].items():
        prefix = contract['images'][name]['repository'] + '@'
        if not isinstance(image, str) or not image.startswith(prefix) or not DIGEST.fullmatch(image[len(prefix):]):
            raise ValueError('Only approved repositories pinned by SHA-256 digest are accepted')
    return release


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f)
            f.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def promote(state, release, run):
    current_file = state / 'current.json'
    previous_file = state / 'previous.json'
    current = json.loads(current_file.read_text()) if current_file.exists() else None
    up = ['up', '--detach', '--wait', '--wait-timeout', '180']
    if release == current:
        run(up, release)
        (state / 'pending.json').unlink(missing_ok=True)
        return False
    run(['pull', '--quiet'], release)
    atomic_json(state / 'pending.json', release)
    try:
        run(up, release)
    except (RuntimeError, subprocess.TimeoutExpired):
        if current:
            try:
                run(up, current)
                (state / 'pending.json').unlink(missing_ok=True)
            except (RuntimeError, subprocess.TimeoutExpired) as e:
                raise RuntimeError('Deployment and rollback failed; operator recovery required') from e
        raise RuntimeError('Deployment failed; previous release restored' if current
                           else 'Initial deployment failed; no previous release exists')
    if current:
        atomic_json(previous_file, current)
    atomic_json(current_file, release)
    (state / 'pending.json').unlink(missing_ok=True)
    return True


def main():
    if len(sys.argv) != 2 or not APP.fullmatch(sys.argv[1]):
        raise ValueError('An admitted application name is required')
    app = sys.argv[1]
    command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
    if command not in ('deploy', 'rollback', 'status'):
        raise ValueError('Only deploy, rollback and status are supported')
    base = pathlib.Path('/etc/homelab-deploy') / app
    contract = json.loads((base / 'contract.json').read_text())
    home = pathlib.Path.home()
    state = home / 'releases' / app
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ['DOCKER_HOST'] = f'unix:///run/user/{os.getuid()}/docker.sock'
    # Explicitly discard job-controlled Compose/Docker settings. The caller only
    # controls SSH_ORIGINAL_COMMAND and the validated JSON on stdin.
    env = {k: v for k, v in os.environ.items()
           if k in ('HOME', 'PATH', 'XDG_RUNTIME_DIR', 'DOCKER_HOST')}
    env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
    env['HOME'] = str(home)
    compose = ['docker', 'compose', '--project-name', 'app-' + app,
               '--project-directory', str(base), '--env-file', str(base / 'runtime.env'),
               '-f', str(base / 'compose.yaml')]

    def run(args, release):
        release_env = dict(env)
        for key, config in contract['images'].items():
            release_env[config['variable']] = release['images'][key]
        # Suppress raw output: application/registry errors may contain secrets.
        r = subprocess.run(compose + args, env=release_env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=1800)
        if r.returncode:
            raise RuntimeError('Compose operation failed; inspect locally without exposing runtime secrets')

    with (state / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current_file = state / 'current.json'
        previous_file = state / 'previous.json'
        current = json.loads(current_file.read_text()) if current_file.exists() else None
        if command == 'status':
            print(json.dumps({'app': app, 'current': current, 'previous_available': previous_file.exists(),
                              'recovery_required': (state / 'pending.json').exists()}))
            return
        if command == 'rollback':
            release = validate_release(contract, json.loads(previous_file.read_text()))
        else:
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise ValueError('Release request is too large')
            release = validate_release(contract, json.loads(raw))
        changed = promote(state, release, run)
        print(json.dumps({'app': app, 'changed': changed, 'revision': release['revision']}))


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired):
        print('Deployment rejected or unsuccessful; inspect the host locally.', file=sys.stderr)
        raise SystemExit(1)
