import ssl
import unittest
from unittest.mock import patch, MagicMock
from protec.agent import tls_context, validate_server


class AgentTrustTests(unittest.TestCase):
    def context(self,ca_count,system='Darwin',environment=None):
        context=MagicMock()
        context.cert_store_stats.return_value={'x509_ca':ca_count}
        with patch('protec.agent.ssl.create_default_context',return_value=context), patch('protec.agent.platform.system',return_value=system), patch('protec.agent.os.environ',environment or {}), patch('protec.agent.Path.is_file',return_value=True):
            self.assertIs(tls_context(),context)
        return context

    def test_missing_mac_default_ca_uses_system_bundle(self):
        self.context(0).load_verify_locations.assert_called_once_with(cafile='/etc/ssl/cert.pem')

    def test_existing_custom_and_linux_trust_are_preserved(self):
        for context in [self.context(12),self.context(0,'Linux'),self.context(0,environment={'SSL_CERT_FILE':'/private/ca.pem'}),self.context(0,environment={'SSL_CERT_DIR':'/private/ca'})]:
            context.load_verify_locations.assert_not_called()

    def test_certificate_and_hostname_verification_remain_required(self):
        context=tls_context()
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_malformed_remote_origin_is_rejected_before_enrollment(self):
        for url in ['https://','https://host:bad','https://host:99999','http://remote.example']:
            with self.assertRaises(ValueError): validate_server(url)
