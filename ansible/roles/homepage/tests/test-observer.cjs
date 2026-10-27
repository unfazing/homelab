const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {snapshot} = require('../files/observer.cjs');
test('stopped collection makes VM and TLS data explicitly stale', () => {
  const read = fs.readFileSync;
  fs.readFileSync = () => JSON.stringify({generated_at:1, caddy_checked_at:1,
    collector_status:'ok', routes:[{hostname:'old.home.test',destination:'old:3000',kind:'exact',tls_status:'valid',certificate:'old'}],
    vms:{1000:{checked_at:1,status:'running',cpu:'2%'}}});
  try {
    const data=snapshot();
    assert.match(data.freshness,/STALE/);
    assert.match(data.routes[0].tls_label,/STALE/);
    assert.match(data.vms[1000].status,/unknown/);
    assert.equal(data.vms[1000].cpu,'unknown');
  } finally {fs.readFileSync=read;}
});
test('fresh partial failures remain visible', () => {
  const read = fs.readFileSync;
  const now = Date.now()/1000;
  fs.readFileSync=()=>JSON.stringify({generated_at:now,caddy_checked_at:now,collector_status:'partial failure',
    errors:['VM 1000: URLError'],routes:[],vms:{}});
  try {
    const data=snapshot();
    assert.match(data.freshness,/partial failure/);
    assert.equal(data.errors,'VM 1000: URLError');
  } finally {fs.readFileSync=read;}
});
test('compact card combines routes and deduplicates shared certificate metadata', () => {
  const read=fs.readFileSync;const now=Date.now()/1000;
  const cert={kind:'exact hostname',destination:'backend:3000',tls_status:'valid',issuer:'Test CA',
    expires_at:'2026-12-26T00:00:00+00:00',days_remaining:61,protocol:'TLSv1.3'};
  fs.readFileSync=()=>JSON.stringify({generated_at:now,caddy_checked_at:now,collector_status:'ok',
    routes:[{...cert,hostname:'a.home.test'},{...cert,hostname:'b.home.test'}],vms:{}});
  try {
    const data=snapshot();
    assert.equal(data.caddy_rows.filter(row=>row.name==='Certificate').length,1);
    assert.match(data.caddy_rows[0].summary,/backend:3000 · TLS 61d/);
    assert.equal(data.caddy_rows.at(-1).name,'Snapshot');
  }finally{fs.readFileSync=read;}
});
