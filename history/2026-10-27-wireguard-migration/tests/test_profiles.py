import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

FILES=Path(__file__).parents[1]/'files'
def load(name):
    spec=importlib.util.spec_from_file_location(name,FILES/(name+'.py'))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
collector=load('export-client-profiles');verify=load('verify')


class ProfileTests(unittest.TestCase):
    def fixture(self,directory,psk='matching-psk'):
        text=f'[Interface]\nPrivateKey = original-client-secret\nAddress = 10.115.145.5/24\nDNS = 192.168.1.9\n[Peer]\nPublicKey = server-public\nPresharedKey = {psk}\nEndpoint = donk.tech:27272\nAllowedIPs = 192.168.1.0/24\n'
        (directory/'active.conf').write_text(text)
        (directory/'revoked.conf').write_text(text.replace('original-client-secret','revoked-secret'))
        return {'server_public_key':'server-public','peers':[{'public_key':'active-public',
            'preshared_key':'matching-psk','address':'10.115.145.5'}]},text

    def test_source_collection_matches_keys_excludes_revoked_and_retains_original_file(self):
        with tempfile.TemporaryDirectory() as temp:
            contract,text=self.fixture(Path(temp))
            with patch.object(collector.subprocess,'check_output',side_effect=['active-public','revoked-public']):
                profiles=collector.collect(contract,Path(temp))
            self.assertEqual(set(profiles),{'active-public'})
            self.assertEqual(profiles['active-public']['original_config'],text)
            self.assertEqual(profiles['active-public']['allowed_ips'],['192.168.1.0/24'])

    def test_mismatched_source_psk_is_rejected_without_disclosure(self):
        with tempfile.TemporaryDirectory() as temp:
            contract,_=self.fixture(Path(temp),psk='wrong-secret')
            with patch.object(collector.subprocess,'check_output',return_value='active-public'):
                with self.assertRaises(AssertionError) as error:collector.collect(contract,Path(temp))
            self.assertNotIn('wrong-secret',str(error.exception))

    def test_download_checks_original_key_and_routes_with_explicit_normalizations(self):
        profile={'private_key':'original-client-secret','allowed_ips':['192.168.1.0/24'],
                 'persistent_keepalive':0,'mtu':None}
        peer={'address':'10.115.145.5','preshared_key':'matching-psk'}
        bundle={'server':{'public_key':'server-public','mtu':1420},
                'client_profiles_policy':{'endpoint':'donk.live:27272','dns':['192.168.1.100']}}
        text='PrivateKey = original-client-secret\nAddress = 10.115.145.5/32\nMTU = 1420\nDNS = 192.168.1.100\nPublicKey = server-public\nPresharedKey = matching-psk\nAllowedIPs = 192.168.1.0/24\nPersistentKeepalive = 0\nEndpoint = donk.live:27272\n'
        verify.verify_download(text,profile,peer,bundle)
        with self.assertRaises(AssertionError):verify.verify_download(text.replace('AllowedIPs = 192.168.1.0/24','AllowedIPs = 0.0.0.0/0'),profile,peer,bundle)
        with self.assertRaises(AssertionError) as error:verify.verify_download(text.replace('original-client-secret','wrong-client-secret'),profile,peer,bundle)
        self.assertNotIn('wrong-client-secret',str(error.exception))


if __name__=='__main__':unittest.main()
