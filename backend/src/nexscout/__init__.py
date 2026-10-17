"""NexScout backend: evidence-grounded career and academic opportunity platform."""

import os

# Release builds set NEXSCOUT_VERSION (the Docker image's build argument, see release.yml).
__version__ = os.environ.get("NEXSCOUT_VERSION") or "0.1.0"
