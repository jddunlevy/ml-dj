"""Entry point for `python -m mldj`, which is how the README invokes capture."""

import sys

from mldj.cli import main

if __name__ == "__main__":
    sys.exit(main())
