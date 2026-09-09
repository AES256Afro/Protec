"""Compliance distinguishes confirmed absence from missing or stale evidence."""
from copy import deepcopy
import unittest
from protec.policies import evaluate,validate_rule
from protec.jobs import inventory_digest

class PackagePolicyTests(unittest.TestCase):
    def setUp(self):
        self.now=1000000
        self.rule={'kind':'package_present','manager':'dpkg','package':'git','max_age_seconds':900}
        self.device={'id':'a'*24,'revoked':0,'seen':self.now,'inventory':{'packages':{
            'status':'complete','manager':'dpkg','scope':'Installed Debian packages','message':'Read-only inventory',
            'collected_at':self.now,'items':[{'name':'git','version':'1.2'}],'total':1,'truncated':False}}}
    def check(self):return evaluate(self.rule,self.device,now=self.now)
    def test_present_reports_version_digest_and_does_not_mutate_inputs(self):
        before=deepcopy((self.rule,self.device));result=self.check()
        self.assertEqual(result['status'],'compliant');self.assertEqual(result['observed_versions'],['1.2'])
        self.assertEqual(result['inventory_sha256'],inventory_digest(self.device['inventory']))
        self.assertEqual((self.rule,self.device),before)
        result['rule']['package']='changed';self.assertEqual(self.rule['package'],'git')
    def test_absence_requires_complete_untruncated_report(self):
        report=self.device['inventory']['packages'];report['items']=[];report['total']=0
        self.assertEqual(self.check()['status'],'noncompliant')
        report.update(total=1000,truncated=True)
        self.assertEqual(self.check()['status'],'unknown');self.assertIn('truncated',self.check()['reason'])
    def test_present_in_truncated_report_is_positive_evidence(self):
        self.device['inventory']['packages'].update(total=1000,truncated=True)
        self.assertEqual(self.check()['status'],'compliant')
    def test_fresh_heartbeat_does_not_make_old_packages_fresh(self):
        self.device['inventory']['packages']['collected_at']=self.now-901
        self.assertEqual(self.check()['status'],'unknown');self.assertIn('Package inventory',self.check()['reason'])
    def test_old_heartbeat_is_unknown_even_with_recent_package_timestamp(self):
        self.device['seen']=self.now-901
        self.assertEqual(self.check()['status'],'unknown');self.assertIn('check-in',self.check()['reason'])
    def test_exact_freshness_limit_is_inclusive(self):
        self.device['seen']=self.now-900;self.device['inventory']['packages']['collected_at']=self.now-900
        self.assertEqual(self.check()['status'],'compliant');self.now+=0.01
        self.assertEqual(self.check()['status'],'unknown')
    def test_revocation_missing_inventory_and_missing_report_are_unknown(self):
        for change in ({'revoked':1},{'inventory':None},{'inventory':{}}):
            with self.subTest(change=change):self.assertEqual(evaluate(self.rule,{**self.device,**change},now=self.now)['status'],'unknown')
    def test_wrong_adapter_is_unknown_even_when_package_name_matches(self):
        self.device['inventory']['packages']['manager']='homebrew'
        self.assertEqual(self.check()['status'],'unknown')
        self.rule['manager']='homebrew';self.assertEqual(self.check()['status'],'compliant')
    def test_exact_package_identity_is_not_a_substring_match(self):
        self.device['inventory']['packages']['items'][0]['name']='git-lfs'
        self.assertEqual(self.check()['status'],'noncompliant')
    def test_failed_or_unsupported_collection_never_means_absent(self):
        for status in ('error','unsupported'):
            self.device['inventory']['packages'].update(status=status,items=[],total=0)
            self.assertEqual(self.check()['status'],'unknown')
    def test_malformed_and_inconsistent_reports_are_unknown(self):
        for change in ({'items':'git'},{'items':[{'name':'git'}]},{'total':True},{'truncated':True},{'status':'ok'},{'items':[{'name':'git','version':'bad\nvalue'}]}):
            device=deepcopy(self.device);device['inventory']['packages'].update(change)
            with self.subTest(change=change):self.assertEqual(evaluate(self.rule,device,now=self.now)['status'],'unknown')
    def test_future_nonfinite_boolean_and_missing_times_are_unknown(self):
        for value in (None,True,float('nan'),float('inf'),10**1000,0,self.now+301):
            for target in ('seen','collected_at'):
                device=deepcopy(self.device)
                if target=='seen':device['seen']=value
                else:device['inventory']['packages'][target]=value
                with self.subTest(value=value,target=target):self.assertEqual(evaluate(self.rule,device,now=self.now)['status'],'unknown')
    def test_multiple_versions_are_deduplicated_and_sorted(self):
        self.device['inventory']['packages'].update(items=[{'name':'git','version':v} for v in ('2','1','2')],total=3)
        self.assertEqual(self.check()['observed_versions'],['1','2'])
    def test_rules_reject_unknown_executable_kinds_and_unbounded_inputs(self):
        for change in ({'kind':'install_package'},{'manager':'shell'},{'package':'git; reboot'},{'package':''},{'max_age_seconds':True},{'max_age_seconds':59},{'max_age_seconds':86401},{'command':'anything'}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_rule({**self.rule,**change})
        for value in (None,[],{},True):
            with self.assertRaises(ValueError):validate_rule(value)
