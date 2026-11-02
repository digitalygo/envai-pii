from __future__ import annotations

import base64
import hashlib
import io
import json
import stat
from pathlib import Path
import zipfile
import zlib
from typing import Any

from . import gpu_monitor, runtime
from .fixture import fixture_integrity

PACKAGE_ROOT = Path(__file__).parents[2]
ARCHIVE_LIMIT_BYTES = 32 * 1024
COMMAND_LIMIT_BYTES = 32 * 1024
MAX_COMMAND_ARGUMENT_BYTES = 253
MAX_COMMAND_ARGUMENTS = 64
PAYLOAD_LIMIT_BYTES = 32 * 1024
PAYLOAD_CHUNK_BYTES = MAX_COMMAND_ARGUMENT_BYTES
VERIFIER_CHUNK_BYTES = MAX_COMMAND_ARGUMENT_BYTES
SIGNED_PAYLOAD_VERIFIER = (
    "import sys as s,base64 as b,zlib as z,hashlib as h\n"
    "try:d,*c=s.argv;o=z.decompressobj();p=o.decompress(b.b64decode(''.join(c),validate=True),32768);o.eof and not o.unused_data and h.sha256(p).hexdigest()==d or s.exit(70)\n"
    "except:s.exit(70)\n"
    "exec(p)"
)
SIGNED_PAYLOAD_VERIFIER_SHA256 = (
    "8998eede3a53aa5edf26492d1ff725ab092e0d36"
    "b394ca02a51827d79787b968"
)
SIGNED_PAYLOAD_VERIFIER_CHUNKS = tuple(
    SIGNED_PAYLOAD_VERIFIER[index:index + VERIFIER_CHUNK_BYTES]
    for index in range(0, len(SIGNED_PAYLOAD_VERIFIER), VERIFIER_CHUNK_BYTES)
)
SIGNED_PAYLOAD_LOADER = (
    "import sys as s,hashlib as h;v=''.join(s.argv[1:"
    f"{len(SIGNED_PAYLOAD_VERIFIER_CHUNKS) + 1}]);"
    f"h.sha256(v.encode()).hexdigest()=={SIGNED_PAYLOAD_VERIFIER_SHA256!r} or s.exit(70);"
    f"s.argv=s.argv[{len(SIGNED_PAYLOAD_VERIFIER_CHUNKS) + 1}:];"
    "exec(compile(v,'<signed-verifier>','exec'))"
)
PAYLOAD_CHUNK_START = len(SIGNED_PAYLOAD_VERIFIER_CHUNKS) + 2
RUNTIME_DESTINATION = "/tmp/envai-pii-verda-runtime"
GUNICORN_PATH = "/usr/local/bin/gunicorn"
PYTHON_PATH = "/usr/local/bin/python"
APP_PATH = "/app/src/app"
PRIVATE_CONFIG_PATH = f"{RUNTIME_DESTINATION}/gunicorn_config.py"
ARCHIVE_FILES = (
    "tools/__init__.py",
    "tools/verda_model_experiment/__init__.py",
    "tools/verda_model_experiment/fixture.py",
    "tools/verda_model_experiment/runtime.py",
)
ENVIRONMENT = tuple(runtime.EXPECTED_ENV.items())


def _archive_sources(package_root: Path = PACKAGE_ROOT) -> dict[str, bytes]:
    files = {}
    for name in ARCHIVE_FILES:
        path = package_root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("packaging source is not a regular file")
        files[name] = path.read_bytes()
    return files


def build_archive(package_root: Path = PACKAGE_ROOT) -> tuple[bytes, dict[str, str]]:
    files = _archive_sources(package_root)
    output = io.BytesIO()
    hashes = {name: hashlib.sha256(contents).hexdigest()
              for name, contents in files.items()}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_LZMA) as archive:
        for name in ARCHIVE_FILES:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_LZMA
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, files[name])
    payload = output.getvalue()
    if len(payload) > ARCHIVE_LIMIT_BYTES:
        raise ValueError("runtime archive exceeds size limit")
    return payload, hashes


def _bootstrap_script(archive: bytes, file_hashes: dict[str, str],
                      workers: int, run_id: str) -> str:
    if type(workers) is not int or workers not in runtime.SUPPORTED_WORKERS:
        raise ValueError("invalid worker count")
    runtime.validate_run_id(run_id)
    if len(archive) > ARCHIVE_LIMIT_BYTES:
        raise ValueError("runtime archive exceeds size limit")
    archive_hash = hashlib.sha256(archive).hexdigest()
    encoded_archive = base64.b64encode(archive).decode("ascii")
    if len(encoded_archive.encode("ascii")) > COMMAND_LIMIT_BYTES:
        raise ValueError("encoded runtime archive exceeds size limit")
    encoded_hashes = json.dumps(file_hashes, sort_keys=True, separators=(",", ":"))
    script = f'''import base64,hashlib,io,ipaddress,json,os,re,shutil,stat,sys,zipfile
root={RUNTIME_DESTINATION!r}
archive_limit={ARCHIVE_LIMIT_BYTES}
archive_hash={archive_hash!r}
archive_data=base64.b64decode({encoded_archive!r},validate=True)
expected_files=json.loads({encoded_hashes!r})
if len(archive_data)>archive_limit or hashlib.sha256(archive_data).hexdigest()!=archive_hash: raise SystemExit(70)
allowed={ARCHIVE_FILES!r}
if set(expected_files)!=set(allowed): raise SystemExit(70)
host=os.environ.get('PII_HOST','0.0.0.0')
port=os.environ.get('PII_PORT','5005')
if not isinstance(host,str) or not isinstance(port,str) or not re.fullmatch(r'[0-9]{{1,5}}',port) or not 1<=int(port)<=65535: raise SystemExit(72)
try:
 address=ipaddress.ip_address(host[1:-1] if host.startswith('[') and host.endswith(']') else host)
 host='['+str(address)+']' if address.version==6 else str(address)
except ValueError:
 labels=host.split('.') if isinstance(host,str) else []
 if not 1<=len(host)<=253 or ':' in host or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{{0,61}}[A-Za-z0-9])?',label) for label in labels): raise SystemExit(72)
contents={{}}
try:
 with zipfile.ZipFile(io.BytesIO(archive_data)) as bundle:
  entries=bundle.infolist()
  if len(entries)!=len(allowed) or sum(entry.file_size for entry in entries)>128*1024: raise SystemExit(70)
  for entry in entries:
   name=entry.filename
   mode=(entry.external_attr>>16)&0xffff
   if name not in allowed or entry.is_dir() or stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or entry.flag_bits&1: raise SystemExit(70)
   data=bundle.read(entry)
   if hashlib.sha256(data).hexdigest()!=expected_files[name]: raise SystemExit(70)
   contents[name]=data
except (OSError,ValueError,zipfile.BadZipFile,RuntimeError):
 raise SystemExit(70) from None
if set(contents)!=set(allowed): raise SystemExit(70)
try:
 info=os.lstat(root)
 if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
     or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700): raise SystemExit(71)
 shutil.rmtree(root)
except FileNotFoundError:
 pass
except OSError:
 raise SystemExit(71) from None
try:
 os.mkdir(root,0o700)
 os.chmod(root,0o700)
 for name in allowed:
  target=os.path.join(root,*name.split('/'))
  parent=os.path.dirname(target)
  os.makedirs(parent,mode=0o700,exist_ok=True)
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
  with os.fdopen(fd,'wb') as output:
   output.write(contents[name])
   output.flush()
   os.fsync(output.fileno())
  os.chmod(target,0o600)
 config_path=os.path.join(root,'gunicorn_config.py')
 config=b'from tools.verda_model_experiment.runtime import load_gunicorn_config\\nglobals().update(load_gunicorn_config())\\n'
 fd=os.open(config_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
 with os.fdopen(fd,'wb') as output:
  output.write(config)
  output.flush()
  os.fsync(output.fileno())
 os.chmod(config_path,0o600)
except (OSError,ValueError):
 raise SystemExit(71) from None
sys.path.insert(0,root)
os.environ['PYTHONPATH']=root
os.environ[{runtime.PROFILE_WORKERS_ENV!r}]={str(workers)!r}
os.environ[{runtime.PROFILE_RUN_ID_ENV!r}]={run_id!r}
arguments=[{GUNICORN_PATH!r}]
for argument in sys.argv[1:]:
 arguments.append(host+':'+port if argument=='__VERDA_BIND__' else argument)
os.execv({GUNICORN_PATH!r},arguments)
'''
    if len(script.encode("utf-8")) > COMMAND_LIMIT_BYTES:
        raise ValueError("runtime bootstrap exceeds size limit")
    return script


def build_signed_command(payload: str) -> list[str]:
    try:
        payload_bytes = payload.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        raise ValueError("signed runtime payload must be ASCII") from None
    if not payload_bytes:
        raise ValueError("signed runtime payload must not be empty")
    if len(payload_bytes) > PAYLOAD_LIMIT_BYTES:
        raise ValueError("runtime payload exceeds size limit")
    if (hashlib.sha256(SIGNED_PAYLOAD_VERIFIER.encode("ascii")).hexdigest()
            != SIGNED_PAYLOAD_VERIFIER_SHA256):
        raise ValueError("signed runtime verifier integrity mismatch")
    encoded_payload = base64.b64encode(
        zlib.compress(payload_bytes, level=9)).decode("ascii")
    chunks = [encoded_payload[index:index + PAYLOAD_CHUNK_BYTES]
              for index in range(0, len(encoded_payload), PAYLOAD_CHUNK_BYTES)]
    command = [SIGNED_PAYLOAD_LOADER, *SIGNED_PAYLOAD_VERIFIER_CHUNKS,
               hashlib.sha256(payload_bytes).hexdigest(), *chunks]
    if len(command) > MAX_COMMAND_ARGUMENTS:
        raise ValueError("runtime command exceeds argument count limit")
    if any(len(argument.encode("ascii")) > MAX_COMMAND_ARGUMENT_BYTES
           for argument in command):
        raise ValueError("runtime command argument exceeds provider limit")
    if len(json.dumps(command, separators=(",", ":")).encode("utf-8")) > COMMAND_LIMIT_BYTES:
        raise ValueError("runtime command exceeds size limit")
    return command


def reconstruct_signed_payload(command: list[str]) -> str:
    if (not isinstance(command, list) or len(command) > MAX_COMMAND_ARGUMENTS
            or len(command) <= PAYLOAD_CHUNK_START
            or command[0] != SIGNED_PAYLOAD_LOADER):
        raise ValueError("invalid signed runtime command")
    verifier_chunks = command[1:PAYLOAD_CHUNK_START - 1]
    digest = command[PAYLOAD_CHUNK_START - 1]
    chunks = command[PAYLOAD_CHUNK_START:]
    if (verifier_chunks != list(SIGNED_PAYLOAD_VERIFIER_CHUNKS)
            or not isinstance(digest, str) or len(digest) != 64
            or not digest.isascii()
            or any(not isinstance(chunk, str) or not chunk or not chunk.isascii()
                   or len(chunk.encode("ascii")) > PAYLOAD_CHUNK_BYTES
                   for chunk in chunks)):
        raise ValueError("invalid signed runtime command")
    serialized_size = len(json.dumps(
        command, separators=(",", ":")).encode("utf-8"))
    if serialized_size > COMMAND_LIMIT_BYTES:
        raise ValueError("runtime command exceeds size limit")
    try:
        compressed = base64.b64decode("".join(chunks), validate=True)
        decoder = zlib.decompressobj()
        payload_bytes = decoder.decompress(compressed, PAYLOAD_LIMIT_BYTES)
        if (decoder.unconsumed_tail or not decoder.eof or decoder.unused_data):
            raise ValueError("invalid compressed payload")
        payload = payload_bytes.decode("ascii")
    except (ValueError, zlib.error):
        raise ValueError("invalid signed runtime command") from None
    if hashlib.sha256(payload_bytes).hexdigest() != digest:
        raise ValueError("signed runtime payload hash mismatch")
    return payload


def _environment_entries() -> list[dict[str, str]]:
    return [{
        "name": name,
        "type": "plain",
        "value_or_reference_to_secret": value,
    } for name, value in ENVIRONMENT]


def build_profile(workers: int, run_id: str) -> dict[str, Any]:
    if type(workers) is not int or workers not in runtime.SUPPORTED_WORKERS:
        raise ValueError("workers must be one of 1, 2, 4, 8, 12, 16")
    runtime.validate_run_id(run_id)
    archive, archive_hashes = build_archive()
    bootstrap = _bootstrap_script(archive, archive_hashes, workers, run_id)
    gunicorn_arguments = [
        "--config", PRIVATE_CONFIG_PATH,
        "--chdir", APP_PATH,
        "--bind", "__VERDA_BIND__",
        "--worker-class", "gthread",
        "--workers", str(workers),
        "--timeout", "600",
        "--graceful-timeout", "30",
        "--access-logfile", "/dev/null",
        "--error-logfile", "-",
        "cloud_service:create_app()",
    ]
    payload = f"import sys;sys.argv={['-c', *gunicorn_arguments]!r}\n{bootstrap}"
    command = build_signed_command(payload)
    entrypoint = [PYTHON_PATH, "-c"]
    if len(command) > MAX_COMMAND_ARGUMENTS:
        raise ValueError("runtime command exceeds argument count limit")
    if any(len(argument.encode("ascii")) > MAX_COMMAND_ARGUMENT_BYTES
           for argument in [*entrypoint, *command]):
        raise ValueError("runtime command argument exceeds provider limit")
    command_bytes = len(json.dumps(
        command, separators=(",", ":")).encode("utf-8"))
    if command_bytes > COMMAND_LIMIT_BYTES:
        raise ValueError("runtime command exceeds size limit")
    deployment_patch = {
        "containers": [{
            "name": "envai-pii-test-0",
            "entrypoint_overrides": {
                "enabled": True,
                "entrypoint": entrypoint,
                "cmd": command,
            },
            "env": _environment_entries(),
        }],
    }
    scaling_patch = {
        "min_replica_count": 0,
        "max_replica_count": 1,
        "concurrent_requests_per_replica": 32,
    }
    overrides = {
        "workers": workers,
        "worker_class": "gthread",
        "preload_app": False,
        "timeout_seconds": 600,
        "graceful_timeout_seconds": 30,
        "access_logs": False,
        "error_log": "stderr",
        "gunicorn_factory": "cloud_service:create_app()",
        "runtime_destination": RUNTIME_DESTINATION,
        "runtime_archive_bytes": len(archive),
        "runtime_archive_sha256": hashlib.sha256(archive).hexdigest(),
        "fixture": fixture_integrity(),
    }
    return {
        "workers": workers,
        "run_id": run_id,
        "deployment_patch": deployment_patch,
        "scaling_patch": scaling_patch,
        "overrides": overrides,
        "source_hashes": dict(runtime.SOURCE_HASHES),
        "archive_file_hashes": archive_hashes,
    }


GPU_ARCHIVE_FILES = (
    *ARCHIVE_FILES,
    "tools/verda_model_experiment/gpu_monitor.py",
    "tools/verda_model_experiment/gpu_runtime.py",
)
GPU_ARCHIVE_ENV = "ENVAIPI_VERDA_GPU_ARCHIVE"
GPU_ARCHIVE_ENV_PREFIX = f"{GPU_ARCHIVE_ENV}_"
GPU_ARCHIVE_ENV_LIMIT_BYTES = 4 * ((ARCHIVE_LIMIT_BYTES + 2) // 3)
GPU_EXTRACTED_LIMIT_BYTES = 128 * 1024
GPU_PROFILE_WORKERS = gpu_monitor.PROFILE_WORKERS
GPU_PROFILE_WORKER_CHOICES = gpu_monitor.PROFILE_WORKER_CHOICES
GPU_CARRIER_CHUNK_BYTES = MAX_COMMAND_ARGUMENT_BYTES
GPU_MAX_ENVIRONMENT_ENTRIES = 64
GPU_TRANSPORT_HEADROOM = 8


def _gpu_archive_sources(package_root: Path = PACKAGE_ROOT) -> dict[str, bytes]:
    files = {}
    for name in GPU_ARCHIVE_FILES:
        path = package_root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("packaging source is not a regular file")
        files[name] = path.read_bytes()
    return files


def build_gpu_archive(package_root: Path = PACKAGE_ROOT) -> tuple[bytes, dict[str, str]]:
    files = _gpu_archive_sources(package_root)
    if sum(len(content) for content in files.values()) > GPU_EXTRACTED_LIMIT_BYTES:
        raise ValueError("gpu runtime archive exceeds extracted size limit")
    output = io.BytesIO()
    hashes = {name: hashlib.sha256(contents).hexdigest()
              for name, contents in files.items()}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_LZMA) as archive:
        for name in GPU_ARCHIVE_FILES:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_LZMA
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, files[name])
    payload = output.getvalue()
    if len(payload) > ARCHIVE_LIMIT_BYTES:
        raise ValueError("gpu runtime archive exceeds size limit")
    return payload, hashes


def _gpu_encoded_archive(archive: bytes) -> str:
    if len(archive) > ARCHIVE_LIMIT_BYTES:
        raise ValueError("gpu runtime archive exceeds size limit")
    encoded = base64.b64encode(archive).decode("ascii")
    if len(encoded) > GPU_ARCHIVE_ENV_LIMIT_BYTES:
        raise ValueError("gpu runtime archive carrier exceeds size limit")
    return encoded


def _gpu_carrier_names(count: int) -> tuple[str, ...]:
    return tuple(
        f"{GPU_ARCHIVE_ENV_PREFIX}{index:02d}" for index in range(count))


def _gpu_carrier_parts(
        encoded: str, inline_chars: int,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    if type(inline_chars) is not int or not 0 < inline_chars < len(encoded):
        raise ValueError("invalid gpu runtime archive split")
    inline = encoded[:inline_chars]
    remainder = encoded[inline_chars:]
    values = tuple(
        remainder[index:index + GPU_CARRIER_CHUNK_BYTES]
        for index in range(0, len(remainder), GPU_CARRIER_CHUNK_BYTES))
    if not values or len(values) > GPU_MAX_ENVIRONMENT_ENTRIES - len(ENVIRONMENT):
        raise ValueError(
            "gpu runtime archive carrier exceeds environment limit")
    names = _gpu_carrier_names(len(values))
    if any(len(value.encode("ascii")) > MAX_COMMAND_ARGUMENT_BYTES
           for value in values) or any(
               len(name.encode("ascii")) > MAX_COMMAND_ARGUMENT_BYTES
               for name in names):
        raise ValueError("gpu runtime archive carrier exceeds provider limit")
    return inline, names, values


def _gpu_split_candidates(encoded_length: int) -> list[int]:
    midpoint = (encoded_length + 1) // 2
    candidates = []
    for step in range(0, encoded_length, GPU_CARRIER_CHUNK_BYTES):
        for candidate in (midpoint - step, midpoint + step):
            if 0 < candidate < encoded_length and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _gpu_bootstrap_script(archive: bytes, file_hashes: dict[str, str], run_id: str,
                          inline_chars: int, workers: int) -> str:
    runtime.validate_run_id(run_id)
    if type(workers) is not int or workers not in GPU_PROFILE_WORKER_CHOICES:
        raise ValueError("invalid worker count")
    encoded_archive = _gpu_encoded_archive(archive)
    if set(file_hashes) != set(GPU_ARCHIVE_FILES):
        raise ValueError("gpu runtime archive file set mismatch")
    inline_carrier, carrier_names, _ = _gpu_carrier_parts(
        encoded_archive, inline_chars)
    archive_hash = hashlib.sha256(archive).hexdigest()
    encoded_hashes = json.dumps(file_hashes, sort_keys=True, separators=(",", ":"))
    script = f'''import base64,hashlib,io,ipaddress,json,os,re,shutil,stat,sys,zipfile
root={RUNTIME_DESTINATION!r}
archive_limit={ARCHIVE_LIMIT_BYTES}
archive_bytes={len(archive)}
carrier_limit={GPU_ARCHIVE_ENV_LIMIT_BYTES}
carrier_chunk_limit={GPU_CARRIER_CHUNK_BYTES}
expected_encoded_length={len(encoded_archive)}
archive_hash={archive_hash!r}
inline_carrier={inline_carrier!r}
carrier_names={carrier_names!r}
carrier_chunks=[]
for name in carrier_names:
 chunk=os.environ.pop(name,None)
 if not isinstance(chunk,str) or not chunk.isascii() or not 0<len(chunk)<=carrier_chunk_limit: raise SystemExit(70)
 carrier_chunks.append(chunk)
carrier=inline_carrier+''.join(carrier_chunks)
if not carrier.isascii() or len(carrier)!=expected_encoded_length or len(carrier)>carrier_limit: raise SystemExit(70)
try:
 archive_data=base64.b64decode(carrier,validate=True)
except (ValueError,TypeError):
 raise SystemExit(70)
expected_files=json.loads({encoded_hashes!r})
if len(archive_data)!=archive_bytes or len(archive_data)>archive_limit or hashlib.sha256(archive_data).hexdigest()!=archive_hash: raise SystemExit(70)
allowed={GPU_ARCHIVE_FILES!r}
if set(expected_files)!=set(allowed): raise SystemExit(70)
host=os.environ.get('PII_HOST','0.0.0.0')
port=os.environ.get('PII_PORT','5005')
if not isinstance(host,str) or not isinstance(port,str) or not re.fullmatch(r'[0-9]{{1,5}}',port) or not 1<=int(port)<=65535: raise SystemExit(72)
try:
 address=ipaddress.ip_address(host[1:-1] if host.startswith('[') and host.endswith(']') else host)
 host='['+str(address)+']' if address.version==6 else str(address)
except ValueError:
 labels=host.split('.') if isinstance(host,str) else []
 if not 1<=len(host)<=253 or ':' in host or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{{0,61}}[A-Za-z0-9])?',label) for label in labels): raise SystemExit(72)
contents={{}}
try:
 with zipfile.ZipFile(io.BytesIO(archive_data)) as bundle:
  entries=bundle.infolist()
  if len(entries)!=len(allowed) or sum(entry.file_size for entry in entries)>{GPU_EXTRACTED_LIMIT_BYTES}: raise SystemExit(70)
  for entry in entries:
   name=entry.filename
   mode=(entry.external_attr>>16)&0xffff
   if name not in allowed or entry.is_dir() or stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or entry.flag_bits&1: raise SystemExit(70)
   data=bundle.read(entry)
   if hashlib.sha256(data).hexdigest()!=expected_files[name]: raise SystemExit(70)
   contents[name]=data
except (OSError,ValueError,zipfile.BadZipFile,RuntimeError):
 raise SystemExit(70) from None
if set(contents)!=set(allowed): raise SystemExit(70)
try:
 info=os.lstat(root)
 if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)
     or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700): raise SystemExit(71)
 shutil.rmtree(root)
except FileNotFoundError:
 pass
except OSError:
 raise SystemExit(71) from None
try:
 os.mkdir(root,0o700)
 os.chmod(root,0o700)
 for name in allowed:
  target=os.path.join(root,*name.split('/'))
  parent=os.path.dirname(target)
  os.makedirs(parent,mode=0o700,exist_ok=True)
  fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
  with os.fdopen(fd,'wb') as output:
   output.write(contents[name])
   output.flush()
   os.fsync(output.fileno())
  os.chmod(target,0o600)
 config_path=os.path.join(root,'gunicorn_config.py')
 config=b'from tools.verda_model_experiment.gpu_runtime import load_gunicorn_config\\nglobals().update(load_gunicorn_config())\\n'
 fd=os.open(config_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
 with os.fdopen(fd,'wb') as output:
  output.write(config)
  output.flush()
  os.fsync(output.fileno())
 os.chmod(config_path,0o600)
except (OSError,ValueError):
 raise SystemExit(71) from None
sys.path.insert(0,root)
os.environ['PYTHONPATH']=root
os.environ[{runtime.PROFILE_WORKERS_ENV!r}]={str(workers)!r}
os.environ[{runtime.PROFILE_RUN_ID_ENV!r}]={run_id!r}
arguments=[{GUNICORN_PATH!r}]
for argument in sys.argv[1:]:
 arguments.append(host+':'+port if argument=='__VERDA_BIND__' else argument)
os.execv({GUNICORN_PATH!r},arguments)
'''
    if len(script.encode("utf-8")) > COMMAND_LIMIT_BYTES:
        raise ValueError("gpu runtime bootstrap exceeds size limit")
    return script


def _gpu_gunicorn_arguments(workers: int) -> list[str]:
    return [
        "--config", PRIVATE_CONFIG_PATH,
        "--chdir", APP_PATH,
        "--bind", "__VERDA_BIND__",
        "--worker-class", "gthread",
        "--workers", str(workers),
        "--timeout", "600",
        "--graceful-timeout", "30",
        "--access-logfile", "/dev/null",
        "--error-logfile", "-",
        "cloud_service:create_app()",
    ]


def _build_gpu_command(archive: bytes, archive_hashes: dict[str, str], run_id: str,
                       *, inline_chars: int, workers: int) -> list[str]:
    bootstrap = _gpu_bootstrap_script(
        archive, archive_hashes, run_id, inline_chars, workers)
    gunicorn_arguments = _gpu_gunicorn_arguments(workers)
    profile_payload = (
        f"import sys;sys.argv={['-c', *gunicorn_arguments]!r}\n{bootstrap}")
    command = build_signed_command(profile_payload)
    entrypoint = [PYTHON_PATH, "-c"]
    if len(command) > MAX_COMMAND_ARGUMENTS:
        raise ValueError("runtime command exceeds argument count limit")
    if any(len(argument.encode("ascii")) > MAX_COMMAND_ARGUMENT_BYTES
           for argument in [*entrypoint, *command]):
        raise ValueError("runtime command argument exceeds provider limit")
    command_bytes = len(json.dumps(
        command, separators=(",", ":")).encode("utf-8"))
    if command_bytes > COMMAND_LIMIT_BYTES:
        raise ValueError("runtime command exceeds size limit")
    return command


def _gpu_command_plan(
        archive: bytes, archive_hashes: dict[str, str], run_id: str,
        workers: int,
) -> tuple[int, int, list[str]]:
    encoded_length = len(_gpu_encoded_archive(archive))
    for inline_chars in _gpu_split_candidates(encoded_length):
        remaining = encoded_length - inline_chars
        chunk_count = (
            (remaining + GPU_CARRIER_CHUNK_BYTES - 1)
            // GPU_CARRIER_CHUNK_BYTES)
        if chunk_count > GPU_MAX_ENVIRONMENT_ENTRIES - len(ENVIRONMENT):
            continue
        try:
            command = _build_gpu_command(
                archive, archive_hashes, run_id, inline_chars=inline_chars,
                workers=workers)
        except ValueError:
            continue
        if (len(command) <= MAX_COMMAND_ARGUMENTS - GPU_TRANSPORT_HEADROOM
                and len(ENVIRONMENT) + chunk_count
                <= GPU_MAX_ENVIRONMENT_ENTRIES - GPU_TRANSPORT_HEADROOM):
            return inline_chars, chunk_count, command
    raise ValueError("gpu runtime transport exceeds provider limits")


def build_gpu_profile(run_id: str, *, workers: int = GPU_PROFILE_WORKERS) -> dict[str, Any]:
    runtime.validate_run_id(run_id)
    if type(workers) is not int or workers not in GPU_PROFILE_WORKER_CHOICES:
        raise ValueError("workers must be one of 8, 12, 16")
    archive, archive_hashes = build_gpu_archive()
    inline_chars, chunk_count, command = _gpu_command_plan(
        archive, archive_hashes, run_id, workers)
    encoded_archive = _gpu_encoded_archive(archive)
    _, carrier_names, carrier_values = _gpu_carrier_parts(
        encoded_archive, inline_chars)
    environment = _environment_entries()
    environment.extend({
        "name": name,
        "type": "plain",
        "value_or_reference_to_secret": value,
    } for name, value in zip(carrier_names, carrier_values))
    if len(environment) > GPU_MAX_ENVIRONMENT_ENTRIES:
        raise ValueError("gpu runtime environment exceeds provider limit")
    if any(len(entry["name"].encode("ascii")) > MAX_COMMAND_ARGUMENT_BYTES
           or len(entry["value_or_reference_to_secret"].encode("ascii"))
           > MAX_COMMAND_ARGUMENT_BYTES
           for entry in environment):
        raise ValueError("gpu runtime environment value exceeds provider limit")
    deployment_patch = {
        "containers": [{
            "name": "envai-pii-test-0",
            "entrypoint_overrides": {
                "enabled": True,
                "entrypoint": [PYTHON_PATH, "-c"],
                "cmd": command,
            },
            "env": environment,
        }],
    }
    scaling_patch = {
        "min_replica_count": 0,
        "max_replica_count": 1,
        "concurrent_requests_per_replica": 32,
    }
    overrides = {
        "workers": workers,
        "worker_class": "gthread",
        "preload_app": False,
        "timeout_seconds": 600,
        "graceful_timeout_seconds": 30,
        "access_logs": False,
        "error_log": "stderr",
        "gunicorn_factory": "cloud_service:create_app()",
        "runtime_destination": RUNTIME_DESTINATION,
        "runtime_archive_bytes": len(archive),
        "runtime_archive_sha256": hashlib.sha256(archive).hexdigest(),
        "gpu_profile": True,
        "gpu_archive_transport": "hybrid",
        "gpu_archive_env": GPU_ARCHIVE_ENV_PREFIX,
        "gpu_archive_env_chunks": chunk_count,
        "gpu_archive_inline_chars": inline_chars,
        "fixture": fixture_integrity(),
    }
    return {
        "workers": workers,
        "run_id": run_id,
        "deployment_patch": deployment_patch,
        "scaling_patch": scaling_patch,
        "overrides": overrides,
        "source_hashes": dict(runtime.SOURCE_HASHES),
        "archive_file_hashes": archive_hashes,
    }
