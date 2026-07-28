"""FastAPI service: upload audio, run the pipeline as a background job, poll
for status, fetch the rendered MusicXML.

Importing the package loads ``.env`` first, so configuration is in place before
any submodule reads ``os.environ``.
"""

from . import config as config  # noqa: F401  (import for the side effect)
