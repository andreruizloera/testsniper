"""Allow running as `python -m testsniper`."""

import sys

from testsniper.cli import main

if __name__ == "__main__":
    sys.exit(main())
