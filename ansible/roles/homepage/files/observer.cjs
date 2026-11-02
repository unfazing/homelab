// Unprivileged JSON reader: no credentials, Docker access, proxying or writes.
const http = require('node:http');
const fs = require('node:fs');
const fresh = checked => Number.isFinite(checked) && Date.now() / 1000 - checked >= 0 && Date.now() / 1000 - checked < 180;
const ageLabel = checked => `${Math.max(0,Math.floor(Date.now()/1000-checked))}s ago`;
function hostDetails(id, host) {
  const storageTime=id==='blue'?host.storage_checked_at:host.checked_at;
  const activityTime=id==='blue'?host.activity_checked_at:host.checked_at;
  const storageFresh=fresh(storageTime), activityFresh=fresh(activityTime);
  const rows=id==='blue' ? (host.storage_rows || []).map(row=>({name:row.name,summary:storageFresh?row.summary:'STALE / unknown'})) :
    [['root_disk','Root filesystem'],['postgresql_disk','PostgreSQL filesystem'],['garage_disk','Garage filesystem']]
      .map(([field,name])=>({name,summary:storageFresh?host[field] || 'unknown':'STALE / unknown'}));
  if(!rows.length) rows.push({name:'Storage',summary:'Unavailable / unknown'});
  const metric=field=>activityFresh?host[field] || 'unknown':'STALE / unknown';
  rows.push({name:id==='blue'?'Node network ↓ / ↑':'LAN ↓ / ↑',summary:`${metric('network_in')} / ${metric('network_out')}`});
  if(id==='blue') {
    rows.push({name:'I/O wait',summary:metric('io_wait')},{name:'ZFS ARC cache',summary:metric('arc')});
  } else rows.push({name:'Disk read / write',summary:`${metric('disk_read')} / ${metric('disk_write')}`});
  rows.push({name:'Storage sample',summary:!storageFresh?'STALE / unknown':host.storage_error?'Last read failed · '+ageLabel(storageTime):ageLabel(storageTime)},
    {name:'Activity sample',summary:!activityFresh?'STALE / unknown':host.activity_error || host.error?'Last read failed · '+ageLabel(activityTime):ageLabel(activityTime)});
  return rows;
}
function storageSummary(host, filesystem) {
  const current=fresh(host?.checked_at), disk=host?.filesystem_usage?.[filesystem];
  const valid=current && disk?.mounted===true;
  const unknown=current && disk?.mounted===false?'NOT MOUNTED / unknown':'STALE / unknown';
  const service=host?.services?.[filesystem] || {}, serviceFresh=fresh(service.checked_at);
  const fields=filesystem==='garage'?['buckets','objects','object_bytes','requests_per_min','errors_per_min','health']:
    ['databases','tables','database_bytes','connections','transactions_per_sec','blocked'];
  return {used_total:valid?disk.used_total:unknown,
    ...Object.fromEntries(fields.map(field=>[field,serviceFresh?service[field] ?? 'unknown':'STALE / unknown'])),
    status:`disk ${!current?'STALE':host.error?'read failed':'sampled '+ageLabel(host.checked_at)} · service ${!serviceFresh?'STALE':service.error?'read failed · '+ageLabel(service.checked_at):'sampled '+ageLabel(service.checked_at)}`};
}
function snapshot() {
  const data = JSON.parse(fs.readFileSync('/snapshot/snapshot.json', 'utf8'));
  const age = Math.max(0, Math.floor(Date.now() / 1000 - data.generated_at));
  const caddyFresh = fresh(data.caddy_checked_at);
  data.age_seconds = age;
  data.freshness = !fresh(data.generated_at) ? 'STALE — collector has stopped' :
    `${data.collector_status} · ${age}s ago`;
  data.caddy_status = caddyFresh ? `${data.routes?.length || 0} route matchers · ${data.collector_status}` : 'STALE / unknown';
  data.errors = (data.errors || []).join('; ') || 'none';
  data.routes = (data.routes || []).map(row => ({...row,
    route_label: `${row.destination} · ${caddyFresh ? row.kind : 'STALE'}`,
    tls_label: caddyFresh ? `${row.tls_status} · ${row.certificate}` : 'STALE / unknown',
  }));
  const exact = data.routes.filter(row => row.kind === 'exact hostname');
  data.caddy_rows = exact.map(row => ({name:row.hostname,
    summary:`${row.destination} · ${!caddyFresh ? 'STALE' : row.tls_status==='valid' ? `TLS ${row.days_remaining}d` : row.tls_status}`}));
  if (caddyFresh) {
    const certificates=[...new Set(exact.filter(row=>row.tls_status==='valid').map(row=>
      `${row.issuer} · expires ${row.expires_at.slice(0,10)} · ${row.protocol}`))];
    certificates.forEach((summary,i)=>data.caddy_rows.push({name:certificates.length===1?'Certificate':`Certificate ${i+1}`,summary}));
  }
  data.caddy_rows.push({name:'Snapshot',summary:`${data.freshness}${caddyFresh?'':' · Caddy STALE'}${data.errors==='none'?'':' · '+data.errors}${data.routes_truncated?' · TRUNCATED':''}`});
  data.vms = Object.fromEntries(Object.entries(data.vms || {}).map(([id, vm]) => [id,
    fresh(vm.checked_at) ? vm : {...vm, status:'STALE / unknown', cpu:'unknown', memory:'unknown', uptime:'unknown',
      network_in:'unknown', network_out:'unknown', disk_read:'unknown', disk_write:'unknown'}]));
  data.host_details=Object.fromEntries(Object.entries(data.hosts || {}).map(([id,host])=>[id,hostDetails(id,host)]));
  data.storage={garage:storageSummary(data.hosts?.red,'garage'),postgresql:storageSummary(data.hosts?.red,'postgresql')};
  data.hosts = Object.fromEntries(Object.entries(data.hosts || {}).map(([id, host]) => [id,
    fresh(host.checked_at) ? {...host,
      cpu:fresh(host.cpu_checked_at ?? host.checked_at)?host.cpu:'unknown',
      status:host.error ? `Collection failed · ${host.error}` :
        `online · ${ageLabel(host.checked_at)}${id==='blue' ?
          host.storage_error ? ' · storage read failed' : !fresh(host.storage_checked_at) ? ' · storage stale' :
          host.storage_warning ? ' · ATTENTION: '+host.storage_warning : '' : ''}`} :
      {...host, status:'STALE / unknown', cpu:'unknown', load:'unknown', memory:'unknown', swap:'unknown', uptime:'unknown',
       root_disk:'unknown', postgresql_disk:'unknown', garage_disk:'unknown',
       network_in:'unknown', network_out:'unknown', disk_read:'unknown', disk_write:'unknown'}]));
  return data;
}
if (require.main === module) http.createServer((req, res) => {
  if (req.method !== 'GET' || req.url !== '/snapshot') { res.writeHead(404).end(); return; }
  try {
    res.writeHead(200, {'Content-Type':'application/json', 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'});
    res.end(JSON.stringify(snapshot()));
  } catch (_) { res.writeHead(503).end('{"error":"Snapshot unavailable"}'); }
}).listen(8080, '172.30.90.4');
module.exports = {snapshot};
