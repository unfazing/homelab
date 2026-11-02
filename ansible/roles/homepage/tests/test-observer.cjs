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
test('host metrics become unknown when their own sample is stale', () => {
  const read=fs.readFileSync, now=Date.now()/1000;
  fs.readFileSync=()=>JSON.stringify({generated_at:now,caddy_checked_at:now,collector_status:'partial failure',
    routes:[],vms:{},hosts:{red:{checked_at:now-181,cpu:'20%',memory:'2 GiB',root_disk:'10 GiB'}}});
  try {
    const data=snapshot();
    assert.match(data.hosts.red.status,/STALE/);
    for(const field of ['cpu','memory','root_disk','network_in']) assert.equal(data.hosts.red[field],'unknown');
  }finally{fs.readFileSync=read;}
});
test('recent failed host collection is visible while retaining last good values', () => {
  const read=fs.readFileSync, now=Date.now()/1000;
  fs.readFileSync=()=>JSON.stringify({generated_at:now,caddy_checked_at:now,collector_status:'partial failure',
    routes:[],vms:{},hosts:{red:{checked_at:now-60,error:'TimeoutExpired',cpu:'20%'}}});
  try {
    const data=snapshot();
    assert.match(data.hosts.red.status,/Collection failed/);
    assert.equal(data.hosts.red.cpu,'20%');
  }finally{fs.readFileSync=read;}
});
test('blue storage and RRD have independent freshness from live host status', () => {
  const read=fs.readFileSync, now=Date.now()/1000;
  fs.readFileSync=()=>JSON.stringify({generated_at:now,caddy_checked_at:now,collector_status:'partial failure',
    routes:[],vms:{},hosts:{blue:{checked_at:now,cpu_checked_at:now-181,cpu:'20%',memory:'8 GiB',
      storage_checked_at:now-181,activity_checked_at:now-181,network_in:'999 KiB/s',
      storage_rows:[{name:'tank health',summary:'ONLINE'}]}}});
  try {
    const data=snapshot();
    assert.equal(data.hosts.blue.memory,'8 GiB');
    assert.equal(data.hosts.blue.cpu,'unknown');
    assert.equal(data.host_details.blue[0].summary,'STALE / unknown');
    assert.match(data.host_details.blue.find(r=>r.name==='Node network ↓ / ↑').summary,/STALE/);
    assert.match(data.hosts.blue.status,/storage stale/);
  }finally{fs.readFileSync=read;}
});
test('pool warnings remain visible when the detailed group is collapsed', () => {
  const read=fs.readFileSync, now=Date.now()/1000;
  fs.readFileSync=()=>JSON.stringify({generated_at:now,caddy_checked_at:now,collector_status:'ok',routes:[],vms:{},
    hosts:{blue:{checked_at:now,storage_checked_at:now,storage_warning:'ZFS DEGRADED',cpu:'1%'}}});
  try {assert.match(snapshot().hosts.blue.status,/ATTENTION: ZFS DEGRADED/);}
  finally{fs.readFileSync=read;}
});
test('storage cards expose current usage and mark absent mounts or stale counters unknown', () => {
  const read=fs.readFileSync, now=Date.now()/1000;
  let host={checked_at:now,filesystem_usage:{garage:{mounted:true,used_total:'1 / 80 GiB',available:'79 GiB',utilisation:'1.3%'},
    postgresql:{mounted:false}}};
  fs.readFileSync=()=>JSON.stringify({generated_at:now,caddy_checked_at:now,collector_status:'ok',routes:[],vms:{},hosts:{red:host}});
  try {
    let data=snapshot();
    assert.equal(data.storage.garage.used_total,'1 / 80 GiB');
    assert.match(data.storage.postgresql.used_total,/NOT MOUNTED/);
    host={...host,checked_at:now-181};
    data=snapshot();
    assert.equal(data.storage.garage.objects,'STALE / unknown');
    assert.equal(data.storage.garage.used_total,'STALE / unknown');
  }finally{fs.readFileSync=read;}
});

test('fresh filesystem cannot disguise stale service counters', () => {
  const read=fs.readFileSync, now=Date.now()/1000;
  fs.readFileSync=()=>JSON.stringify({generated_at:now,routes:[],hosts:{red:{checked_at:now,
    filesystem_usage:{garage:{mounted:true,used_total:'2 / 80 GiB'}},
    services:{garage:{checked_at:now-181,objects:'999',health:'healthy'}}}}});
  try {
    const data=snapshot();
    assert.equal(data.storage.garage.used_total,'2 / 80 GiB');
    assert.equal(data.storage.garage.objects,'STALE / unknown');
    assert.match(data.storage.garage.status,/service STALE/);
  }finally{fs.readFileSync=read;}
});
