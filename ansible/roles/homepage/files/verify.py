#!/usr/bin/env python3
"""Read-only acceptance checks; stdin carries the edge login, never argv."""
from http.cookiejar import CookieJar
import json
from pathlib import Path
import socket
import subprocess
import sys
from urllib import request, error, parse

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def main():
    config = json.load(sys.stdin)
    domain = config['domain']
    host = 'dashboard.home.' + domain
    real = socket.getaddrinfo
    socket.getaddrinfo = lambda name, *a, **kw: real('192.168.1.101' if name == host else name, *a, **kw)
    cookies = CookieJar()
    client = request.build_opener(request.HTTPCookieProcessor(cookies))
    secrets = [p.read_text().strip().encode() for p in Path('/etc/homelab/homepage').glob('*-token')]
    secrets += [Path('/etc/homelab/homepage/' + name).read_text().strip().encode() for name in ['adguard-password', 'session-secret']]
    secrets += [config['password'].encode()]
    def call(path, authenticated=True, expected=200, form=None, headers=None):
        data = parse.urlencode(form).encode() if form is not None else None
        req = request.Request('https://' + host + path, data=data, headers=headers or {})
        opener = client if authenticated else request.build_opener()
        if expected == 307:
            handlers = [NoRedirect()]
            if authenticated: handlers.append(request.HTTPCookieProcessor(cookies))
            opener = request.build_opener(*handlers)
        try:
            with opener.open(req, timeout=20) as res:
                status, body = res.status, res.read()
        except error.HTTPError as e:
            status, body = e.code, e.read()
        assert status == expected or isinstance(expected, tuple) and status in expected, f'Unexpected HTTP {status} at {path}; expected {expected}'
        assert not any(s and s in body for s in secrets), 'A service credential appeared in a browser response'
        return body
    assert b'password' in call('/', False).lower(), 'Native sign-in page missing'
    call('/api/services', False, 307)
    call('/api/services/proxy?group=Network&service=AdGuard&index=0&endpoint=stats', False, 307)
    csrf = json.loads(call('/api/auth/csrf'))['csrfToken']
    call('/api/auth/callback/credentials', form={'csrfToken': csrf, 'password': config['password'],
         'callbackUrl': 'https://' + host + '/', 'json': 'true'})
    assert json.loads(call('/api/auth/session')).get('user'), 'Native session not established'
    assert any(c.secure and c.name.startswith('__Secure-') for c in cookies), 'Secure session cookie missing'
    call('/')
    services = call('/api/services')
    assert b'wg-easy' in services and ('https://wireguard.home.' + domain).encode() in services, 'wg-easy portal tile missing'
    if config.get('storage_enabled'):
        for label in ['Garage S3', 'PostgreSQL']:
            assert label.encode() in services, 'Storage dashboard tile missing: ' + label
        for prefix in ['https://garage.home.', 'https://s3.home.']:
            assert (prefix + domain).encode() in services, 'Private storage dashboard URL missing'
    if config.get('hosts'):
        assert b'red-server' in services, 'Red infrastructure card missing'
        # The provisioned key must return only the fixed JSON report, even for
        # an attempted shell command. No extra remote command is executed.
        sys_path = str(Path(__file__).parent)
        sys.path.insert(0, sys_path)
        import collect
        targets = json.loads((Path(sys_path) / 'observer.json').read_text())['hosts']
        for target in targets:
            forced = subprocess.run(collect.host_ssh_command(target, 'id -u'),
                                    text=True, capture_output=True, timeout=8, check=True)
            report = json.loads(forced.stdout)
            assert isinstance(report, dict) and report.get('version') == 1, 'Telemetry key allowed an arbitrary command'
    # Test the application's raw Host handling directly; the edge proxy normalizes
    # forwarded headers. Pass the temporary bearer cookie on stdin, never argv.
    host_probe = r"""
      let cookie='';process.stdin.on('data',b=>cookie+=b).on('end',()=>{
        require('http').get('http://127.0.0.1:3000/api/services',
          {headers:{Host:'untrusted.invalid',Cookie:cookie}},r=>{
            r.resume();console.log(r.statusCode);process.exit(r.statusCode===400?0:1);
          }).on('error',()=>process.exit(1));
      });
    """
    host_checked = subprocess.run(['docker','exec','-i','homepage','node','-e',host_probe],
                                  input='; '.join(c.name + '=' + c.value for c in cookies), capture_output=True,text=True)
    assert host_checked.returncode == 0, 'Authenticated raw Host validation failed: ' + host_checked.stdout.strip()
    call('/api/mcp', expected=(404,405))
    probes = [('Network', 'AdGuard', 'stats'), ('Network', 'Caddy', 'upstreams')]
    probes += [('Development & AI', 'Gitea', e) for e in ['repositories', 'notifications', 'issues', 'pulls']]
    for group, service, endpoint in probes:
        query = parse.urlencode({'group': group, 'service': service, 'index': 0, 'endpoint': endpoint})
        value = json.loads(call('/api/services/proxy?' + query))
        assert not isinstance(value, dict) or not value.get('error'), 'Widget failed: ' + service + ' / ' + endpoint
        if service == 'AdGuard': assert 'num_dns_queries' in value, 'AdGuard statistics schema missing'
        if service == 'Caddy': assert isinstance(value, list), 'Caddy upstream statistics missing'
        if service == 'Gitea': assert isinstance(value.get('count'), int), 'Gitea count missing: ' + endpoint
    # Optional destructive-to-process restart check, only when explicitly requested.
    if config.get('restart'):
        subprocess.run(['docker', 'restart', 'homepage'], check=True, stdout=subprocess.DEVNULL)
        import time
        for attempt in range(30):
            try:
                assert json.loads(call('/api/auth/session')).get('user')
                break
            except Exception:
                if attempt == 29: raise
                time.sleep(1)
        call('/api/services')
    csrf = json.loads(call('/api/auth/csrf'))['csrfToken']
    call('/api/auth/signout', form={'csrfToken': csrf, 'callbackUrl': 'https://' + host + '/', 'json': 'true'})
    call('/api/services', expected=307)
    csrf = json.loads(call('/api/auth/csrf'))['csrfToken']
    call('/api/auth/callback/credentials', form={'csrfToken': csrf, 'password': 'intentionally-wrong-test-password',
         'callbackUrl': 'https://' + host + '/', 'json': 'true'}, expected=401)
    assert not json.loads(call('/api/auth/session')).get('user'), 'Wrong password was accepted'
    node = r'''
      (async () => {
        for (const [path, method, expected] of [
          ['/reverse_proxy/upstreams', 'GET', 200], ['/config/', 'GET', 404],
          ['/load', 'GET', 404], ['/stop', 'GET', 404]]) {
          const r = await fetch('http://172.30.90.2:2020' + path, {method});
          if (r.status !== expected) throw Error('Caddy method/path boundary failed');
        }
        try { await fetch('http://172.30.90.2:2019/config/', {signal: AbortSignal.timeout(2000)}); throw Error('Admin API reachable'); }
        catch (e) { if (e.message === 'Admin API reachable') throw e; }
        const r = await fetch('http://127.0.0.1:3000/api/mcp', {headers:{Host:process.env.HOMEPAGE_ALLOWED_HOSTS}});
        if (![307,401,404,405].includes(r.status)) throw Error('MCP unexpectedly available');
        const snapshot = await (await fetch('http://172.30.90.4:8080/snapshot')).json();
        if(snapshot.age_seconds>180 || snapshot.collector_status!=='ok') throw Error('Collector is stale or failed');
        if(Object.keys(snapshot.vms).length!==3) throw Error('VM snapshots missing');
        for(const id of ['blue',...JSON.parse(process.argv[1])]) {
          const host=snapshot.hosts?.[id];
          if(!host || host.error || Date.now()/1000-host.checked_at>180 || !host.status.startsWith('online'))
            throw Error('Host snapshot missing, stale or failed: '+id);
          if(!host.memory || host.memory==='unknown' || !host.root_disk || host.root_disk.includes('unknown'))
            throw Error('Host RAM/root filesystem metrics missing: '+id);
        }
        for(const id of ['garage','postgresql']) {
          const storage=snapshot.storage?.[id];
          if(!storage || !storage.used_total.includes(' / ') || !storage.status.startsWith('disk sampled'))
            throw Error('Storage disk use missing or stale: '+id);
        }
        for(const id of ['garage','postgresql']) {
          const service=snapshot.hosts.red.services?.[id];
          if(service?.checked_at && (service.error || Date.now()/1000-service.checked_at>180))
            throw Error('Installed storage service metrics failed/stale: '+id);
        }
        const blue=snapshot.hosts.blue;
        if(blue.activity_error || blue.storage_error || Date.now()/1000-blue.storage_checked_at>180 ||
           Date.now()/1000-blue.activity_checked_at>180 || !blue.storage_rows?.some(r=>r.name.endsWith(' health')))
          throw Error('Blue storage/activity snapshot missing or stale');
        if(!snapshot.host_details?.blue?.length || !snapshot.host_details?.red?.length)
          throw Error('Infrastructure details missing');
        if(!snapshot.routes.some(r=>r.hostname==='dashboard.home.'+process.env.HOMEPAGE_ALLOWED_HOSTS.split('.').slice(2).join('.'))) throw Error('Dashboard route was not discovered');
        if(snapshot.routes.some(r=>r.kind==='exact hostname' && r.tls_status!=='valid')) throw Error('TLS probe failed');
        const invalid = await new Promise((resolve, reject) => require('http').get('http://127.0.0.1:3000/api/services',
          {headers: {Host:'untrusted.invalid'}}, r => {r.resume(); resolve(r.statusCode)}).on('error', reject));
        if (![307,400].includes(invalid)) throw Error('Unauthenticated Host validation failed');
        if (new (require('follow-redirects').https.Agent)({rejectUnauthorized:false}).options.rejectUnauthorized !== true)
          throw Error('Widget certificate verification is not enforced');
        if (process.version !== 'v24.22.1') throw Error('Unexpected Node runtime');
        if (require('next/package.json').version !== '16.4.1') throw Error('Unexpected Next runtime');
      })().catch((e) => { console.error(e.message); process.exit(1); });
    '''
    result = subprocess.run(['docker', 'exec', 'homepage', 'node', '-e', node, json.dumps(config.get('hosts', []))], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr.strip()
    # Inspect the active route rather than issuing potentially destructive writes.
    running = json.loads(subprocess.check_output(['docker', 'exec', 'caddy', 'wget', '-qO-',
                                                  'http://127.0.0.1:2019/config/apps/http/servers/']))
    metrics = [s for s in running.values() if '172.30.90.2:2020' in s.get('listen', [])]
    assert len(metrics) == 1, 'Statistics listener is not isolated to its dedicated address'
    forwards = []
    def walk(value, matches=()):
        if isinstance(value, dict):
            inherited = matches + tuple(value.get('match', []))
            if value.get('handler') == 'reverse_proxy': forwards.append((inherited, value))
            for key, child in value.items():
                if key != 'match': walk(child, inherited)
        elif isinstance(value, list):
            for child in value: walk(child, matches)
    walk(metrics[0])
    assert len(forwards) == 1, 'Unexpected additional statistics forwarding route'
    matches, forward = forwards[0]
    assert any(m.get('method') == ['GET'] and m.get('path') == ['/reverse_proxy/upstreams'] for m in matches), 'Statistics route is not restricted to the approved GET'
    assert forward.get('upstreams') == [{'dial':'127.0.0.1:2019'}], 'Unexpected statistics backend'
    inspected = json.loads(subprocess.check_output(['docker', 'inspect', 'homepage']))[0]
    assert inspected['Config']['User'] == '10001:10001', 'Homepage is not using its dedicated UID'
    assert not inspected['HostConfig']['Privileged'] and not inspected['HostConfig']['PortBindings'], 'Unexpected privilege or published port'
    assert not any(m['Destination'] == '/var/run/docker.sock' or m['Source'].startswith('/srv/homelab/') for m in inspected['Mounts']), 'Unexpected host/application mount'
    assert not any(m['Source'].startswith('/etc/homelab/homepage-observer') for m in inspected['Mounts']), 'Collector SSH identities mounted into Homepage'
    reader = json.loads(subprocess.check_output(['docker', 'inspect', 'homepage-observer']))[0]
    assert not reader['HostConfig']['PortBindings'] and len(reader['NetworkSettings']['Networks']) == 1, 'Snapshot server exposed beyond internal bridge'
    assert not any(m['Source'].startswith('/etc/homelab') or 'docker.sock' in m['Source'] for m in reader['Mounts']), 'Reader has credentials or Docker access'
    dns = subprocess.check_output(['dig', '+short', '@192.168.1.100', host], text=True).strip()
    assert dns == '192.168.1.101', 'Private DNS did not return Caddy'
    print('Native login/logout, secure sessions, secret redaction, widgets, fresh VM/routes/TLS inventory, DNS and private Caddy boundary passed')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
