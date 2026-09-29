"""Make tests/fakes.py importable from every test directory, including tests/measure/.

pytest's default import mode puts only the test file's own directory on sys.path, so
`from fakes import ...` resolves in tests/ but not in tests/measure/ without this.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
