import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

FILES=Path(__file__).parents[1]/'files'
def module(name):
    spec=importlib.util.spec_from_file_location(name,FILES/(name+'.py'))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
bootstrap=module('bootstrap');export=module('export-legacy')
verify=module('verify')


class MigrationTests(unittest.TestCase):
    def test_kernel_acceptance_rejects_changed_address_or_psk_without_disclosing_values(self):
        bundle={'peers':[{'public_key':'public','address':'10.115.145.3','preshared_key':'sensitive-test-psk'}]}
        for address,psk,passes in [('10.115.145.3/32','sensitive-test-psk',True),
                                   ('10.115.145.4/32','sensitive-test-psk',False),
                                   ('10.115.145.3/32','wrong-sensitive-test-psk',False)]:
            with patch.object(verify.subprocess,'check_output',side_effect=['public\t'+address,'public\t'+psk]):
                if passes:verify.verify_kernel_peers(bundle)
                else:
                    with self.assertRaises(AssertionError) as result:verify.verify_kernel_peers(bundle)
                    self.assertNotIn('sensitive-test-psk',str(result.exception))

    def test_pivpn_names_are_metadata_only(self):
        names=export.peer_names('### begin phone-travel ###\n[Peer]\nPublicKey = phone-key\n### end phone-travel ###\n### begin gareth ###\n[Peer]\nPublicKey = guest-key\n')
        self.assertEqual(names,{'phone-key':'phone-travel','guest-key':'gareth'})

    def test_parse_live_config_preserves_multiple_peers_without_executing_hooks(self):
        interface,peers=export.parse('[Interface]\nPrivateKey = server-secret\nListenPort = 51820\n[Peer]\nPublicKey = first\nPresharedKey = secret\nAllowedIPs = 10.115.145.3/32\n[Peer]\nPublicKey = second\nAllowedIPs = 10.115.145.7/32\n')
        self.assertEqual(interface['PrivateKey'],'server-secret')
        self.assertEqual(len(peers),2)
        self.assertEqual(peers[1]['AllowedIPs'],'10.115.145.7/32')

    def test_adapter_retains_identity_peer_addresses_and_optional_psk(self):
        bundle={'server':{'private_key':'server-secret','public_key':'server-public'},
                'peers':[{'name':'phone','address':'10.115.145.3','public_key':'phone-public','preshared_key':'phone-psk'},
                         {'name':'guest','address':'10.115.145.7','public_key':'guest-public','preshared_key':''}]}
        result=bootstrap.migration(bundle)
        self.assertEqual(result['server']['privateKey'],'server-secret')
        self.assertEqual(result['server']['address'],'10.115.145.1')
        self.assertEqual(result['clients']['1']['address'],'10.115.145.3')
        self.assertEqual(result['clients']['1']['preSharedKey'],'phone-psk')
        self.assertEqual(result['clients']['1']['privateKey'],'')
        self.assertEqual(result['clients']['2']['preSharedKey'],'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')

    def policy_commands(self,fail=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);log=root/'commands'
            mock=root/'iptables'
            mock.write_text('#!'+sys.executable+'\nimport json,os,sys\na=sys.argv[1:]\nwith open(os.environ["POLICY_LOG"],"a") as f:f.write(json.dumps(a)+"\\n")\nif "-C" in a:raise SystemExit(1)\nif os.environ.get("FAIL_POLICY")=="yes" and "-A" in a:raise SystemExit(2)\n')
            mock.chmod(0o700)
            policy=(FILES/'start.sh').read_text().rsplit('exec /usr/bin/dumb-init',1)[0]
            result=subprocess.run(['/bin/sh','-c',policy],env={**os.environ,'PATH':temp+os.pathsep+os.environ['PATH'],
                'POLICY_LOG':str(log),'FAIL_POLICY':'yes' if fail else 'no'},capture_output=True)
            return result,[json.loads(line) for line in log.read_text().splitlines()]

    def test_actual_policy_commands_enforce_exact_guest_grants_and_admin_denial(self):
        result,commands=self.policy_commands();self.assertEqual(result.returncode,0)
        rules=[args for args in commands if '-A' in args]
        def verdict(source,destination,protocol,port):
            for rule in rules:
                if '-s' in rule and ipaddress.ip_address(source) not in ipaddress.ip_network(rule[rule.index('-s')+1]):continue
                if '-d' in rule and ipaddress.ip_address(destination) not in ipaddress.ip_network(rule[rule.index('-d')+1]):continue
                if '-p' in rule and protocol!=rule[rule.index('-p')+1]:continue
                if '--dport' in rule and str(port)!=rule[rule.index('--dport')+1]:continue
                return rule[rule.index('-j')+1]
        for proto in ('tcp','udp'):self.assertEqual(verdict('10.115.145.7','192.168.1.100',proto,53),'RETURN')
        self.assertEqual(verdict('10.115.145.7','192.168.1.9','tcp',3000),'RETURN')
        for dst,proto,port in [('192.168.1.9','tcp',22),('192.168.1.100','tcp',3000),('192.168.1.101','tcp',443),('1.1.1.1','udp',53)]:
            self.assertEqual(verdict('10.115.145.7',dst,proto,port),'DROP')
        self.assertEqual(verdict('10.115.145.3','1.1.1.1','tcp',443),'RETURN')
        self.assertEqual(verdict('10.115.145.3','10.115.145.1','tcp',51821),'DROP')

    def test_policy_failure_aborts_before_application_start(self):
        result,_=self.policy_commands(fail=True)
        self.assertNotEqual(result.returncode,0)


if __name__=='__main__':unittest.main()
