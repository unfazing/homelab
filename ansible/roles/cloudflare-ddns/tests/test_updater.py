"""Exercise the actual shell updater against a local fake curl, never live DNS."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'files/cloudflare-ddns.sh'
FAKE_CURL = r'''
import json,os,sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
args=sys.argv[1:]
assert 'fake-test-token-never-in-argv' not in ' '.join(args)
if '--config' in args: sys.stdin.read()
statefile=Path(os.environ['FAKE_STATE']);state=json.loads(statefile.read_text())
url=args[-1]
if url=='https://trace.invalid/':
 print('ip=203.0.113.25');raise SystemExit(0)
method=args[args.index('--request')+1]
path=urlsplit(url).path
if path.endswith('/zones'):
 result=[{'id':'zone1','name':'test.invalid'}]*state.get('zones',1)
elif method=='GET':
 name=parse_qs(urlsplit(url).query)['name'][0]
 result=[r for r in state['records'] if r['name']==name]
else:
 record=json.loads(args[args.index('--data')+1])
 state['writes'].append([method,record['name']])
 if method=='PATCH':
  old=next(r for r in state['records'] if r['id']==path.rsplit('/',1)[1])
  old.update(record);result=old
 else:
  record['id']='created'+str(len(state['records']));state['records'].append(record);result=record
 statefile.write_text(json.dumps(state))
print(json.dumps({'success':True,'result':result}))
'''


def record(name, content='203.0.113.25', **changes):
    return {'id':name, 'type':'A', 'name':name, 'content':content, 'ttl':300, 'proxied':False, **changes}


class UpdaterTests(unittest.TestCase):
    def run_updater(self, records, labels='@ vpn', zones=1):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            curl=root/'curl';curl.write_text('#!'+sys.executable+'\n'+FAKE_CURL);curl.chmod(0o700)
            state=root/'state.json';state.write_text(json.dumps({'records':records,'writes':[],'zones':zones}))
            env={**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'FAKE_STATE':str(state),
                 'CLOUDFLARE_ACCOUNT_ID':'a'*32,'CLOUDFLARE_DDNS_API_TOKEN':'fake-test-token-never-in-argv',
                 'CLOUDFLARE_DDNS_RECORD_LABELS':labels,'CLOUDFLARE_DDNS_TTL':'300',
                 'CLOUDFLARE_DDNS_IPV4_SOURCE_URL':'https://trace.invalid/'}
            result=subprocess.run(['/bin/sh',str(SCRIPT)],env=env,capture_output=True,text=True)
            self.assertNotIn(env['CLOUDFLARE_DDNS_API_TOKEN'],result.stdout+result.stderr)
            return result,json.loads(state.read_text())

    def test_stale_apex_updated_while_vpn_and_other_records_are_preserved(self):
        records=[record('test.invalid','192.0.2.1'),record('vpn.test.invalid'),record('other.test.invalid','192.0.2.2'),
                 {'id':'txt','name':'test.invalid','type':'TXT','content':'keep-me'}]
        result,state=self.run_updater(records)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(state['writes'],[['PATCH','test.invalid']])
        self.assertEqual(state['records'][2]['content'],'192.0.2.2')
        self.assertEqual(state['records'][3]['content'],'keep-me')
        again,second=self.run_updater(state['records'])
        self.assertEqual(again.returncode,0,again.stderr)
        self.assertEqual(second['writes'],[])

    def test_both_addresses_follow_a_changed_public_ip(self):
        result,state=self.run_updater([record('test.invalid','192.0.2.1'),record('vpn.test.invalid','192.0.2.1')])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(state['writes']),2)
        self.assertTrue(all(r['content']=='203.0.113.25' for r in state['records']))

    def test_create_both_missing_records(self):
        result,state=self.run_updater([])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(state['writes'],[['POST','test.invalid'],['POST','vpn.test.invalid']])

    def test_second_record_ambiguity_prevents_even_first_mutation(self):
        result,state=self.run_updater([record('test.invalid','192.0.2.1'),record('vpn.test.invalid'),record('vpn.test.invalid',id='duplicate')])
        self.assertNotEqual(result.returncode,0)
        self.assertIn('multiple A records',result.stderr)
        self.assertEqual(state['writes'],[])

    def test_cname_conflict_fails_before_any_write(self):
        result,state=self.run_updater([record('test.invalid','192.0.2.1'),record('vpn.test.invalid',type='CNAME')])
        self.assertNotEqual(result.returncode,0)
        self.assertIn('CNAME conflicts',result.stderr)
        self.assertEqual(state['writes'],[])

    def test_unsafe_or_duplicate_labels_are_rejected(self):
        for labels in ('', '@ @', '@ bad.name', '@ *', '@ -bad', '@ bad-', '@ '+'a'*64):
            with self.subTest(labels=labels):
                result,state=self.run_updater([],labels=labels)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(state['writes'],[])

    def test_multiple_zones_fail_without_changes(self):
        result,state=self.run_updater([],zones=2)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(state['writes'],[])

    def test_ttl_and_proxy_state_are_reconciled(self):
        result,state=self.run_updater([record('test.invalid',ttl=1,proxied=True),record('vpn.test.invalid')])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(state['writes'],[['PATCH','test.invalid']])
        self.assertEqual(state['records'][0]['ttl'],300)
        self.assertFalse(state['records'][0]['proxied'])


if __name__=='__main__': unittest.main()
