# Python 3.14+ uses 'forkserver' as default multiprocessing start method,
# which requires pickling. DNF objects contain unpicklable SWIG C objects.
# Set to 'fork' method before any other imports to avoid pickling issues.
# https://docs.python.org/3/whatsnew/3.14.html#concurrent-futures

import multiprocessing

try:
    multiprocessing.set_start_method("fork")
except RuntimeError:
    # Already set, ignore
    pass
