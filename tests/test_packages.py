import json
import sys
import time
import unittest
from unittest.mock import patch
from protec.packages import collect,parse_output,run_query,validate_report
from protec.agent import cycle
from protec.server import inventory_input
from protec.agent import inventory

class PackageTests(unittest.TestCase):
    def report(self):
        return {'status':'complete','manager':'dpkg','scope':'Installed Debian packages','message':'Read-only inventory','collected_at':time.time(),'items':[{'name':'curl','version':'1.0'}],'total':1,'truncated':False}
    def test_native_parsers_filter_uninstalled_packages(self):
        self.assertEqual(parse_output('dpkg','curl\t1.0\tinstalled\nremoved\t2\tconfig-files\n'),[{'name':'curl','version':'1.0'}])
        self.assertEqual(parse_output('homebrew','zlib 1.2 1.3\n'),[{'name':'zlib','version':'1.2 1.3'}])
        with self.assertRaises(ValueError):
            parse_output('dpkg','bad output')
    def test_collector_reports_truncation_and_failure(self):
        output=''.join(f'pkg{i}\t1\tinstalled\n' for i in range(501))
        with patch('protec.packages.platform.system',return_value='Linux'),patch('protec.packages.Path.is_file',return_value=True),patch('protec.packages.run_query',return_value=output):
            report=collect()
        self.assertEqual(report['total'],501)
        self.assertEqual(len(report['items']),500)
        self.assertTrue(report['truncated'])
        with patch('protec.packages.platform.system',return_value='Linux'),patch('protec.packages.Path.is_file',return_value=True),patch('protec.packages.run_query',side_effect=ValueError('secret stderr')):
            report=collect()
        self.assertEqual(report['status'],'error')
        self.assertNotIn('secret stderr',json.dumps(report))
        with patch('protec.packages.platform.system',return_value='Windows'):
            self.assertEqual(collect()['status'],'unsupported')
    def test_report_validation_and_request_size(self):
        report=self.report()
        self.assertEqual(inventory_input({'inventory':{**inventory(),'packages':report}})['packages']['total'],1)
        for changed in ({'collected_at':float('nan')},{'total':0},{'items':[{'name':'x\n','version':'1'}]},{'truncated':True},{'status':'error'}):
            with self.assertRaises(ValueError):
                validate_report({**report,**changed})
        report['items']=[{'name':'n'*128,'version':'v'*128}]*500
        report['total']=500
        self.assertLess(len(json.dumps({'inventory':{**inventory(),'packages':validate_report(report)}}).encode()),262144)
    def test_query_timeout_and_output_limit(self):
        self.assertEqual(run_query([sys.executable,'-c',"print('ok')"]),'ok\n')
        with patch('protec.packages.MAX_OUTPUT',100),self.assertRaises(ValueError):
            run_query([sys.executable,'-c',"print('x'*1000)"])
        with patch('protec.packages.TIMEOUT',0.05),self.assertRaises(ValueError):
            run_query([sys.executable,'-c','import time; time.sleep(5)'])
    def test_agent_cache_and_forced_refresh(self):
        state={'server':'http://127.0.0.1','credential':'test'}
        with patch('protec.agent.collect_packages',return_value=self.report()) as collector,patch('protec.agent.request',return_value={'jobs':[]}) as request:
            cycle(state)
            cycle(state)
            self.assertEqual(collector.call_count,1)
            request.side_effect=[{'jobs':[{'id':'a'*24,'kind':'refresh_inventory'}]},{'jobs':[]},{'ok':True}]
            cycle(state)
            self.assertEqual(collector.call_count,2)
            self.assertEqual(request.call_args.args[1],'/api/complete')

if __name__=='__main__':
    unittest.main()
