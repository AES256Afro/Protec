"""The runtime and deployment artifacts must report the same release identity."""
from pathlib import Path
import time
import tempfile
import unittest
from protec.agent import inventory
from protec.history import health
from protec.server import Store
from protec.version import VERSION

class ReleaseVersionTests(unittest.TestCase):
    def test_agent_and_authenticated_health_use_release_file(self):
        self.assertEqual(VERSION,Path('VERSION').read_text().strip())
        self.assertEqual(inventory()['agent_version'],VERSION)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(health(Store(Path(directory)/'test.db'),time.monotonic())['version'],VERSION)

    def test_compose_and_mock_version_match_release(self):
        self.assertIn('ghcr.io/aes256afro/protec:'+VERSION,Path('compose.yaml').read_text())
        self.assertIn("version:'"+VERSION+"',status:'simulated'",Path('website/demo.js').read_text())
