import importlib.util
from pathlib import Path
import unittest

FILES=Path(__file__).parents[1]/'files'
spec=importlib.util.spec_from_file_location('verify',FILES/'verify.py')
verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)


class GuardTests(unittest.TestCase):
    def rules(self):
        return '\n'.join(['-P FORWARD DROP','-A FORWARD -i wg0 -j WG_CLIENTS_wg0',
            '-A FORWARD -i wg0 -j DROP',
            '-A FORWARD -o wg0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT','-A FORWARD -o wg0 -j DROP',
            '-A FORWARD -i wg0 -j ACCEPT','-A FORWARD -o wg0 -j ACCEPT'])
    def check(self,rules):
        verify.verify_forward_guard(rules,'-A WG_CLIENTS_wg0 -j DROP','-A INPUT -i wg0 -j DROP')
    def test_native_jump_precedes_fallback_and_broad_accepts(self):self.check(self.rules())
    def test_accept_before_drop_is_rejected(self):
        with self.assertRaises(AssertionError):self.check(self.rules().replace('-A FORWARD -i wg0 -j DROP','-A FORWARD -i wg0 -j ACCEPT\n-A FORWARD -i wg0 -j DROP',1))
    def test_missing_native_chain_is_rejected(self):
        with self.assertRaises(AssertionError):self.check(self.rules().replace('-A FORWARD -i wg0 -j WG_CLIENTS_wg0',''))
    def test_return_allowance_cannot_bypass_peer_fallback_drop(self):
        rule='-A FORWARD -o wg0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT'
        with self.assertRaises(AssertionError):self.check(rule+'\n'+self.rules().replace(rule,''))
    def test_guard_has_no_client_identity_or_migration_input(self):
        text=(FILES/'start.sh').read_text()+(FILES/'configure.py').read_text()
        for forbidden in ('gareth','legacy.json','preshared_key','client_profiles','10.115.145.7'):
            self.assertNotIn(forbidden,text)


if __name__=='__main__':unittest.main()
