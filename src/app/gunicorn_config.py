import os
import sys


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from request_admission import resolve_admission_config
from gpu_worker_startup import post_worker_init as verify_worker_startup
from gpu_worker_startup import resolve_gunicorn_workers


admission_config = resolve_admission_config()
workers = resolve_gunicorn_workers()
worker_class = "gthread"
threads = (
    admission_config.max_concurrent_analyses
    + admission_config.max_queued_analyses
    + 2
)
preload_app = False
post_worker_init = verify_worker_startup
