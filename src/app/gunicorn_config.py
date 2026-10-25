import os
import sys


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from request_admission import resolve_admission_config


admission_config = resolve_admission_config()
workers = 1
worker_class = "gthread"
threads = (
    admission_config.max_concurrent_analyses
    + admission_config.max_queued_analyses
    + 2
)
preload_app = False
