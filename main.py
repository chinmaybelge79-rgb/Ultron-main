"""Ultron top-level entry point.

Delegates execution to ``ultron.app.main()``.
"""

import sys

from ultron.app import main

if __name__ == "__main__":
    sys.exit(main())
