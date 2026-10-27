// Unprivileged JSON reader: no credentials, Docker access, proxying or writes.
const http = require('node:http');
const fs = require('node:fs');
const fresh = checked => Number.isFinite(checked) && Date.now() / 1000 - checked < 180;
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
