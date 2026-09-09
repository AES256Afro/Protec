"""Release identity shared by the source agent and packaged control plane."""
from pathlib import Path
import re

VERSION = (Path(__file__).resolve().parent.parent/'VERSION').read_text().strip()
if not re.fullmatch(r'\d+\.\d+\.\d+', VERSION):
    raise ValueError('Invalid Protec release VERSION')
