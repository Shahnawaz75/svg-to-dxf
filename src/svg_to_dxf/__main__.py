"""Allow ``python -m svg_to_dxf``."""

import sys

from .cli import main

sys.exit(main())
