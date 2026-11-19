"""Allow ``python -m vpn_monitor``."""

import sys

from vpn_monitor.cli import main

if __name__ == "__main__":
    sys.exit(main())
