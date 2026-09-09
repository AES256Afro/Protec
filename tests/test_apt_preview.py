import unittest
from unittest.mock import patch
from protec.apt_preview import command,parse_simulation,preview,validate_request,validate_plan,verify_selections
from protec.jobs import inventory_digest

INSTALL='''Reading package lists...
0 upgraded, 1 newly installed, 0 to remove and 0 not upgraded.
Inst fixture (1.0 local [all])
Conf fixture (1.0 local [all])
'''

class AptPreviewTests(unittest.TestCase):
    def request(self):return {'action':'install','packages':[{'name':'fixture','version':'1.0'}]}

    def test_command_is_always_simulation_and_pinned_without_shell(self):
        args=command(self.request())
        self.assertIn('--simulate',args);self.assertIn('--no-download',args)
        self.assertEqual(args[-3:],['install','--','fixture=1.0'])
        args=command({'action':'remove','packages':[{'name':'fixture:amd64'}]})
        self.assertEqual(args[-3:],['remove','--','fixture:amd64'])

    def test_rejects_options_patterns_paths_and_unpinned_installs(self):
        for name in ['-o','./fixture.deb','fixture*','fixture;id','fixture\n','fixture/edge','fixture=2','fixture+','x']:
            with self.assertRaises(ValueError):command({'action':'install','packages':[{'name':name,'version':'1'}]})
        for request in [{'action':'upgrade','packages':[{'name':'fixture'}]}, {'action':'install','packages':[{'name':'fixture'}]}, {'action':'remove','packages':[]}, {'action':'install','packages':[{'name':'fixture','version':'1;id'}]}]:
            with self.assertRaises(ValueError):validate_request(request)

    def test_parses_new_upgrade_remove_and_noop(self):
        self.assertEqual(parse_simulation(INSTALL),[{'name':'fixture','before':None,'after':'1.0','action':'install'}])
        upgrade=INSTALL.replace('0 upgraded, 1 newly','1 upgraded, 0 newly').replace('Inst fixture (','Inst fixture [0.9] (')
        self.assertEqual(parse_simulation(upgrade)[0]['before'],'0.9')
        self.assertEqual(parse_simulation('0 upgraded, 0 newly installed, 1 to remove and 0 not upgraded.\nRemv fixture [1.0]')[0]['action'],'remove')
        self.assertEqual(parse_simulation('0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.'),[])

    def test_refuses_truncation_inconsistent_summary_and_configure_only(self):
        for output in [INSTALL.replace('Conf fixture (1.0 local [all])',''),INSTALL.replace('1 newly','2 newly'),INSTALL+'Remv fixture [1.0]\n',INSTALL+'Conf fixture (1.0 local [all])\n',INSTALL+'W: Problem\n',INSTALL+'1 not fully installed or removed.\n','Conf fixture (1.0 local [all])\n',INSTALL.replace('Inst fixture (','Inst ?fixture (')]:
            with self.assertRaises(ValueError):parse_simulation(output)

    def test_preview_digest_binds_device_request_changes_and_state(self):
        with patch('protec.apt_preview.platform.system',return_value='Linux'),patch('protec.apt_preview.Path.is_file',return_value=True),patch('protec.apt_preview.status_digest',return_value='a'*64),patch('protec.apt_preview.run_query',side_effect=['Package: fixture\nVersion: 1.0\nArchitecture: all\n','2.7.14',INSTALL]) as query:
            result=preview(self.request(),'b'*24)
        digest=result.pop('plan_sha256');self.assertEqual(digest,inventory_digest(result))
        self.assertTrue(result['requires_revalidation']);self.assertEqual(result['expires']-result['created'],900)
        self.assertNotIn('APT_CONFIG',query.call_args.kwargs['env'])

    def test_concurrent_dpkg_change_refuses_plan(self):
        with patch('protec.apt_preview.platform.system',return_value='Linux'),patch('protec.apt_preview.Path.is_file',return_value=True),patch('protec.apt_preview.status_digest',side_effect=['a'*64,'b'*64]),patch('protec.apt_preview.run_query',side_effect=['Package: fixture\nVersion: 1.0\nArchitecture: all\n','2.7.14',INSTALL]):
            with self.assertRaisesRegex(ValueError,'changed during'):preview(self.request(),'b'*24)

    def test_mac_never_invokes_apt(self):
        with patch('protec.apt_preview.platform.system',return_value='Darwin'),patch('protec.apt_preview.run_query') as query:
            with self.assertRaises(ValueError):preview(self.request(),'b'*24)
            query.assert_not_called()

    def test_exact_metadata_gate_rejects_pattern_fallback(self):
        with patch('protec.apt_preview.run_query',return_value='Package: fixture-other\nVersion: 1.0\nArchitecture: all\n'):
            with self.assertRaises(ValueError):verify_selections(self.request(),{})
        with patch('protec.apt_preview.run_query',return_value='fixture-other\tall\tinstalled\n'):
            with self.assertRaises(ValueError):verify_selections({'action':'remove','packages':[{'name':'fixture'}]}, {})

    def test_plan_validation_rejects_tampering_expiry_and_wrong_device(self):
        with patch('protec.apt_preview.platform.system',return_value='Linux'),patch('protec.apt_preview.Path.is_file',return_value=True),patch('protec.apt_preview.status_digest',return_value='a'*64),patch('protec.apt_preview.run_query',side_effect=['Package: fixture\nVersion: 1.0\nArchitecture: all\n','2.7.14',INSTALL]):
            plan=preview(self.request(),'b'*24)
        self.assertEqual(validate_plan(plan,'b'*24),plan)
        for changed in [{**plan,'device':'c'*24},{**plan,'changes':[]},{**plan,'created':True},{**plan,'requires_revalidation':False}]:
            with self.assertRaises(ValueError):validate_plan(changed,'b'*24)
        with self.assertRaises(ValueError):validate_plan(plan,'b'*24,now=plan['expires'])
        copy=validate_plan(plan,'b'*24);copy['changes'].clear();self.assertEqual(len(plan['changes']),1)
