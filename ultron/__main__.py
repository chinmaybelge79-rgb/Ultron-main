"""Module entry point for python -m ultron.

Per the Day 1 architecture, ``python -m ultron`` starts the headless daemon
(single-instance lock, kill-switch check, three concurrent loop threads). The
interactive TUI remains available via ``python main.py``.
"""

import sys

from ultron.daemon import main

if __name__ == "__main__":
    sys.exit(main())
