"""Bounded opt-in package for the Verda batch diagnostic profile.

The archive carries the unchanged diagnostic runtime plus a generated overlay:
the current ``model_batching`` module, the AST-extracted current
``_guardrail_detect`` source, and a manifest binding their hashes to the
unchanged base image files. The default ``package`` archives and profiles are
not rebuilt or modified here.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import lzma
import marshal
from pathlib import Path
import struct
from typing import Any

from . import batch_runtime, package, runtime
from .fixture import FIXTURE_TEXT, FIXTURE_TEXT_SHA256, TEXT_PARAGRAPHS, fixture_integrity

BATCH_PROFILE_WORKERS = batch_runtime.BATCH_PROFILE_WORKERS
BATCH_PROFILE_WORKER_CHOICES = batch_runtime.BATCH_PROFILE_WORKER_CHOICES
SUPPORTED_BATCH_SIZES = batch_runtime.SUPPORTED_BATCH_SIZES
BATCH_SIZE_ENV = batch_runtime.BATCH_SIZE_ENV
BATCH_ARCHIVE_ENV_PREFIX = "ENVAIPI_VERDA_BATCH_ARCHIVE_"
BATCH_ARCHIVE_ENV_LIMIT_BYTES = 4 * ((package.ARCHIVE_LIMIT_BYTES + 2) // 3)
BATCH_CARRIER_CHUNK_BYTES = package.MAX_COMMAND_ARGUMENT_BYTES
BATCH_MAX_ENVIRONMENT_ENTRIES = package.GPU_MAX_ENVIRONMENT_ENTRIES
BATCH_TRANSPORT_HEADROOM = package.GPU_TRANSPORT_HEADROOM
BATCH_CARRIER_COUNT = 56
BATCH_EXTRACTED_LIMIT_BYTES = batch_runtime.EXTRACTED_LIMIT_BYTES
BATCH_BUNDLE_MAGIC = b"ENVAIPIBATCH1\n"
BATCH_BUNDLE_FORMAT = "lzma-bundle-1"
BATCH_ENVIRONMENT_COUNT = 0
BATCH_BOOTSTRAP_ENV = tuple(
    name for name, _value in package.ENVIRONMENT) + (BATCH_SIZE_ENV,)
BATCH_MANIFEST_FORMAT = batch_runtime.MANIFEST_FORMAT
BATCH_ARCHIVE_FILES = (
    "tools/verda_model_experiment/runtime.py",
    "tools/verda_model_experiment/fixture.py",
    "tools/verda_model_experiment/gpu_runtime.py",
    "tools/verda_model_experiment/gpu_monitor.py",
    "tools/verda_model_experiment/batch_runtime.py",
    "tools/verda_model_experiment/batch_overlay/model_batching.py",
    "tools/verda_model_experiment/batch_overlay/guardrail_detect.py",
    "tools/verda_model_experiment/batch_overlay/manifest.json",
)
BATCH_MANIFEST_ASSET = (
    "tools/verda_model_experiment/batch_overlay/manifest.json")
BATCH_HELPER_ASSET = batch_runtime.HELPER_ASSET
BATCH_DETECTOR_ASSET = batch_runtime.DETECTOR_ASSET
BATCH_APPROOT = package.PACKAGE_ROOT / "src" / "app"
BATCH_APP_SOURCE = BATCH_APPROOT / "app.py"
BATCH_HELPER_SOURCE = BATCH_APPROOT / "model_batching.py"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_source(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("packaging source is not a regular file")
    return path.read_bytes()


def _extract_detector(app_source: bytes) -> tuple[bytes, str]:
    try:
        tree = ast.parse(app_source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError, ValueError):
        raise ValueError("application source is invalid") from None
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == batch_runtime.TARGET_FUNCTION
    ]
    if len(matches) != 1:
        raise ValueError("application detector is unavailable")
    source = ast.get_source_segment(app_source.decode("utf-8"), matches[0])
    invalid_fragment = (
        matches[0].decorator_list
        or not isinstance(source, str)
        or not source.startswith(
            f"def {batch_runtime.TARGET_FUNCTION}(")
    )
    if invalid_fragment:
        raise ValueError("application detector fragment is invalid")
    fragment = source.encode("utf-8")
    batch_runtime.compile_detector(fragment)
    return fragment, _sha256(fragment)


def _fixture_source() -> bytes:
    source = (
        "import hashlib\n"
        f"TEXT_PARAGRAPHS = {TEXT_PARAGRAPHS!r}\n"
        "def _fixture_text():\n"
        "    email = 'req42@example.com'\n"
        "    pieces = [email, ' ']\n"
        "    remaining = 45000 - len(email) - 1\n"
        "    index = 42 % len(TEXT_PARAGRAPHS)\n"
        "    while remaining:\n"
        "        paragraph = TEXT_PARAGRAPHS[index]\n"
        "        index = (index + 3) % len(TEXT_PARAGRAPHS)\n"
        "        segment = paragraph + ' '\n"
        "        pieces.append(segment[:remaining])\n"
        "        remaining -= min(remaining, len(segment))\n"
        "    return ''.join(pieces)\n"
        "FIXTURE_TEXT = _fixture_text()\n"
        f"if len(FIXTURE_TEXT) != 45000 or hashlib.sha256(FIXTURE_TEXT.encode('utf-8')).hexdigest() != {FIXTURE_TEXT_SHA256!r}:\n"
        "    raise RuntimeError\n"
    ).encode("utf-8")
    namespace = {}
    exec(compile(source, "<generated-fixture>", "exec"), namespace)
    if namespace.get("FIXTURE_TEXT") != FIXTURE_TEXT:
        raise ValueError("generated fixture text mismatch")
    return source


def _bundle(files: dict[str, bytes]) -> bytes:
    blob = bytearray(BATCH_BUNDLE_MAGIC)
    for name in BATCH_ARCHIVE_FILES:
        name_bytes = name.encode("ascii")
        data = files[name]
        blob += struct.pack(">H", len(name_bytes))
        blob += name_bytes
        blob += struct.pack(">I", len(data))
        blob += data
    return bytes(blob)


def _manifest(files: dict[str, bytes], base_app_sha256: str) -> dict[str, Any]:
    helper_sha256 = _sha256(files[BATCH_HELPER_ASSET])
    detector_sha256 = _sha256(files[BATCH_DETECTOR_ASSET])
    detector = batch_runtime.compile_detector(
        files[BATCH_DETECTOR_ASSET], source_sha256=detector_sha256)
    return {
        "format": BATCH_MANIFEST_FORMAT,
        "base_app_sha256": base_app_sha256,
        "helper_sha256": helper_sha256,
        "detector_source_sha256": detector_sha256,
        "detector_code_sha256": _sha256(
            marshal.dumps(detector.__code__)),
    }


def build_batch_archive() -> tuple[bytes, dict[str, str], dict[str, Any], bytes]:
    sources: dict[str, bytes] = {}
    for name in BATCH_ARCHIVE_FILES:
        if name == BATCH_MANIFEST_ASSET:
            continue
        if name == "tools/verda_model_experiment/fixture.py":
            sources[name] = _fixture_source()
        elif name == BATCH_HELPER_ASSET:
            sources[name] = _read_source(BATCH_HELPER_SOURCE)
        elif name == BATCH_DETECTOR_ASSET:
            sources[name], _digest = _extract_detector(
                _read_source(BATCH_APP_SOURCE))
        elif name == "tools/verda_model_experiment/batch_runtime.py":
            sources[name] = _read_source(Path(batch_runtime.__file__))
        else:
            sources[name] = _read_source(package.PACKAGE_ROOT / name)
    manifest = _manifest(sources, runtime.SOURCE_HASHES["app.py"])
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode("ascii")
    sources[BATCH_MANIFEST_ASSET] = manifest_bytes
    bundle = _bundle(sources)
    if len(bundle) > BATCH_EXTRACTED_LIMIT_BYTES:
        raise ValueError("batch runtime archive exceeds extracted size limit")
    archive = lzma.compress(
        bundle, format=lzma.FORMAT_XZ,
        filters=[{"id": lzma.FILTER_LZMA2, "preset": 9, "lc": 3, "lp": 0,
                  "pb": 0}])
    if len(archive) > package.ARCHIVE_LIMIT_BYTES:
        raise ValueError("batch runtime archive exceeds size limit")
    hashes = {name: _sha256(data) for name, data in sources.items()}
    return archive, hashes, manifest, manifest_bytes


def _encoded_archive(archive: bytes) -> str:
    if len(archive) > package.ARCHIVE_LIMIT_BYTES:
        raise ValueError("batch runtime archive exceeds size limit")
    encoded = base64.b64encode(archive).decode("ascii")
    if len(encoded) > BATCH_ARCHIVE_ENV_LIMIT_BYTES:
        raise ValueError("batch runtime carrier exceeds size limit")
    return encoded


def _carrier_names(count: int) -> tuple[str, ...]:
    return tuple(
        f"{BATCH_ARCHIVE_ENV_PREFIX}{index:02d}" for index in range(count))


def _carrier_parts(encoded: str, inline_chars: int) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    if type(inline_chars) is not int or not 0 < inline_chars < len(encoded):
        raise ValueError("invalid batch runtime carrier split")
    inline = encoded[:inline_chars]
    remainder = encoded[inline_chars:]
    values = tuple(
        remainder[index:index + BATCH_CARRIER_CHUNK_BYTES]
        for index in range(0, len(remainder), BATCH_CARRIER_CHUNK_BYTES))
    max_chunks = (BATCH_MAX_ENVIRONMENT_ENTRIES - BATCH_TRANSPORT_HEADROOM
                  - BATCH_ENVIRONMENT_COUNT)
    if not values or len(values) > max_chunks:
        raise ValueError("batch runtime carrier exceeds environment limit")
    names = _carrier_names(len(values))
    if any(len(value.encode("ascii")) > package.MAX_COMMAND_ARGUMENT_BYTES
           for value in values) or any(
               len(name.encode("ascii")) > package.MAX_COMMAND_ARGUMENT_BYTES
               for name in names):
        raise ValueError("batch runtime carrier exceeds provider limit")
    return inline, names, values


def _bootstrap_script(archive: bytes, manifest_sha256: str, run_id: str,
                      inline_chars: int, carrier_names: tuple[str, ...],
                      batch_size: int, workers: int) -> str:
    runtime.validate_run_id(run_id)
    if type(batch_size) is not int or batch_size not in SUPPORTED_BATCH_SIZES:
        raise ValueError("invalid batch size")
    if type(workers) is not int or workers not in BATCH_PROFILE_WORKER_CHOICES:
        raise ValueError("invalid worker count")
    encoded = _encoded_archive(archive)
    _, expected_names, _ = _carrier_parts(encoded, inline_chars)
    if carrier_names != expected_names:
        raise ValueError("batch runtime carrier names mismatch")
    inline = encoded[:inline_chars]
    archive_hash = _sha256(archive)
    script = f'''import base64,hashlib,ipaddress,json,lzma,os,re,shutil,stat,sys
root={package.RUNTIME_DESTINATION!r}
archive_limit={package.ARCHIVE_LIMIT_BYTES}
extracted_limit={BATCH_EXTRACTED_LIMIT_BYTES}
archive_bytes={len(archive)}
archive_hash={archive_hash!r}
manifest_sha={manifest_sha256!r}
expected_encoded_length={len(encoded)}
carrier_limit={BATCH_ARCHIVE_ENV_LIMIT_BYTES}
carrier_chunk_limit={BATCH_CARRIER_CHUNK_BYTES}
inline_carrier={inline!r}
carrier_names={carrier_names!r}
allowed={BATCH_ARCHIVE_FILES!r}
manifest_name={BATCH_MANIFEST_ASSET!r}
bundle_magic={BATCH_BUNDLE_MAGIC!r}
carrier_chunks=[]
carrier_prefix={BATCH_ARCHIVE_ENV_PREFIX!r}
if {{name for name in os.environ if name.startswith(carrier_prefix)}}!=set(carrier_names): raise SystemExit(70)
for name in carrier_names:
 chunk=os.environ.pop(name,None)
 if not isinstance(chunk,str) or not 0<len(chunk)<=carrier_chunk_limit or not chunk.isascii(): raise SystemExit(70)
 carrier_chunks.append(chunk)
carrier=inline_carrier+''.join(carrier_chunks)
if not carrier.isascii() or len(carrier)!=expected_encoded_length or len(carrier)>carrier_limit: raise SystemExit(70)
try:
 archive_data=base64.b64decode(carrier,validate=True)
except (ValueError,TypeError):
 raise SystemExit(70)
if len(archive_data)!=archive_bytes or len(archive_data)>archive_limit or hashlib.sha256(archive_data).hexdigest()!=archive_hash: raise SystemExit(70)
try:
 decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
 bundle=decoder.decompress(archive_data,extracted_limit+1)
 if len(bundle)>extracted_limit or not decoder.eof or decoder.unused_data: raise SystemExit(70)
except (lzma.LZMAError,ValueError):
 raise SystemExit(70)
if not bundle.startswith(bundle_magic): raise SystemExit(70)
contents={{}}
position=len(bundle_magic)
try:
 for name in allowed:
  if position+2>len(bundle): raise SystemExit(70)
  size=int.from_bytes(bundle[position:position+2],'big'); position+=2
  if size<1 or size>253 or position+size>len(bundle): raise SystemExit(70)
  if bundle[position:position+size].decode('ascii')!=name: raise SystemExit(70)
  position+=size
  if position+4>len(bundle): raise SystemExit(70)
  length=int.from_bytes(bundle[position:position+4],'big'); position+=4
  if length<0 or length>extracted_limit or position+length>len(bundle): raise SystemExit(70)
  contents[name]=bundle[position:position+length]; position+=length
except (UnicodeDecodeError,ValueError,OverflowError):
 raise SystemExit(70)
if position!=len(bundle) or set(contents)!=set(allowed): raise SystemExit(70)
if hashlib.sha256(contents[manifest_name]).hexdigest()!=manifest_sha: raise SystemExit(70)
def unique_pairs(pairs):
 result={{}}
 for key,value in pairs:
  if key in result: raise ValueError
  result[key]=value
 return result
try:
 manifest=json.loads(contents[manifest_name],object_pairs_hook=unique_pairs)
except (TypeError,ValueError):
 raise SystemExit(70)
manifest_fields={{'format','base_app_sha256','helper_sha256','detector_source_sha256','detector_code_sha256'}}
if not isinstance(manifest,dict) or set(manifest)!=manifest_fields or manifest.get('format')!={BATCH_MANIFEST_FORMAT!r}: raise SystemExit(70)
hashes=(manifest['base_app_sha256'],manifest['helper_sha256'],manifest['detector_source_sha256'],manifest['detector_code_sha256'])
if any(not isinstance(value,str) or len(value)!=64 or any(char not in '0123456789abcdef' for char in value) for value in hashes): raise SystemExit(70)
if (manifest['base_app_sha256']!={runtime.SOURCE_HASHES['app.py']!r}
    or hashlib.sha256(contents[{BATCH_HELPER_ASSET!r}]).hexdigest()!=manifest['helper_sha256']
    or hashlib.sha256(contents[{BATCH_DETECTOR_ASSET!r}]).hexdigest()!=manifest['detector_source_sha256']): raise SystemExit(70)
host=os.environ.get('PII_HOST','0.0.0.0')
port=os.environ.get('PII_PORT','5005')
if (not isinstance(host,str) or not 1<=len(host)<=253
    or not isinstance(port,str) or not 1<=len(port)<=5
    or not re.fullmatch(r'[0-9]{{1,5}}',port) or not 1<=int(port)<=65535): raise SystemExit(72)
try:
 address=ipaddress.ip_address(host[1:-1] if host.startswith('[') and host.endswith(']') else host)
 host='['+str(address)+']' if address.version==6 else str(address)
except ValueError:
 labels=host.split('.') if isinstance(host,str) else []
 if not 1<=len(host)<=253 or ':' in host or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{{0,61}}[A-Za-z0-9])?',label) for label in labels): raise SystemExit(72)
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
 config=b'from tools.verda_model_experiment.batch_runtime import load_gunicorn_config\\nglobals().update(load_gunicorn_config())\\n'
 fd=os.open(config_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
 with os.fdopen(fd,'wb') as output:
  output.write(config)
  output.flush()
  os.fsync(output.fileno())
 os.chmod(config_path,0o600)
except (OSError,ValueError):
 raise SystemExit(71) from None
sys.path.insert(0,root)
try:
 from tools.verda_model_experiment.batch_runtime import compile_detector
 compile_detector(contents[{BATCH_DETECTOR_ASSET!r}],source_sha256=manifest['detector_source_sha256'],code_sha256=manifest['detector_code_sha256'])
except Exception:
 shutil.rmtree(root)
 raise SystemExit(70) from None
os.environ['PYTHONPATH']=root
os.environ[{runtime.PROFILE_WORKERS_ENV!r}]={str(workers)!r}
os.environ[{runtime.PROFILE_RUN_ID_ENV!r}]={run_id!r}
os.environ.update({dict((*package.ENVIRONMENT, (BATCH_SIZE_ENV, str(batch_size))))!r})
arguments=[{package.GUNICORN_PATH!r}]
for argument in sys.argv[1:]:
 arguments.append(host+':'+port if argument=='__VERDA_BIND__' else argument)
os.execv({package.GUNICORN_PATH!r},arguments)
'''
    if len(script.encode("utf-8")) > package.COMMAND_LIMIT_BYTES:
        raise ValueError("batch runtime bootstrap exceeds size limit")
    return script


def _gunicorn_arguments(workers: int) -> list[str]:
    return [
        "--config", package.PRIVATE_CONFIG_PATH,
        "--chdir", package.APP_PATH,
        "--bind", "__VERDA_BIND__",
        "--worker-class", "gthread",
        "--workers", str(workers),
        "--timeout", "600",
        "--graceful-timeout", "30",
        "--access-logfile", "/dev/null",
        "--error-logfile", "-",
        "cloud_service:create_app()",
    ]


def _build_command(archive: bytes, manifest_bytes: bytes, run_id: str,
                   *, inline_chars: int, batch_size: int,
                   workers: int) -> list[str]:
    manifest_sha256 = _sha256(manifest_bytes)
    encoded = _encoded_archive(archive)
    _, carrier_names, _ = _carrier_parts(encoded, inline_chars)
    bootstrap = _bootstrap_script(
        archive, manifest_sha256, run_id, inline_chars, carrier_names,
        batch_size, workers)
    gunicorn_arguments = _gunicorn_arguments(workers)
    payload = (
        f"import sys;sys.argv={['-c', *gunicorn_arguments]!r}\n{bootstrap}")
    command = package.build_signed_command(payload)
    entrypoint = [package.PYTHON_PATH, "-c"]
    max_arguments = package.MAX_COMMAND_ARGUMENTS - BATCH_TRANSPORT_HEADROOM
    if len(command) > max_arguments:
        raise ValueError("batch runtime command exceeds argument count limit")
    if any(len(argument.encode("ascii")) > package.MAX_COMMAND_ARGUMENT_BYTES
           for argument in [*entrypoint, *command]):
        raise ValueError("batch runtime command argument exceeds provider limit")
    if len(json.dumps(command, separators=(",", ":")).encode("utf-8")) > package.COMMAND_LIMIT_BYTES:
        raise ValueError("batch runtime command exceeds size limit")
    return command


def _command_plan(archive: bytes, manifest_bytes: bytes,
                  run_id: str, batch_size: int,
                  workers: int) -> tuple[int, int, list[str]]:
    encoded = _encoded_archive(archive)
    encoded_length = len(encoded)
    max_chunks = (BATCH_MAX_ENVIRONMENT_ENTRIES - BATCH_TRANSPORT_HEADROOM
                  - BATCH_ENVIRONMENT_COUNT)
    first_inline = max(1, encoded_length - max_chunks * BATCH_CARRIER_CHUNK_BYTES)
    for inline_chars in range(
            first_inline, min(encoded_length, first_inline + 8)):
        try:
            _, names, _ = _carrier_parts(encoded, inline_chars)
        except ValueError:
            continue
        if BATCH_ENVIRONMENT_COUNT + len(names) > (
                BATCH_MAX_ENVIRONMENT_ENTRIES - BATCH_TRANSPORT_HEADROOM):
            continue
        if len(names) != BATCH_CARRIER_COUNT:
            continue
        try:
            command = _build_command(
                archive, manifest_bytes, run_id, inline_chars=inline_chars,
                batch_size=batch_size, workers=workers)
        except ValueError:
            continue
        return inline_chars, len(names), command
    raise ValueError("batch runtime transport exceeds provider limits")


def build_batch_gpu_profile(run_id: str, batch_size: int, *,
                            workers: int = BATCH_PROFILE_WORKERS) -> dict[str, Any]:
    runtime.validate_run_id(run_id)
    if type(batch_size) is not int or batch_size not in SUPPORTED_BATCH_SIZES:
        raise ValueError("batch size must be one of 1, 4, 8, 16")
    if type(workers) is not int or workers not in BATCH_PROFILE_WORKER_CHOICES:
        raise ValueError("workers must be one of 8, 12, 16")
    archive, archive_hashes, manifest, manifest_bytes = build_batch_archive()
    inline_chars, chunk_count, command = _command_plan(
        archive, manifest_bytes, run_id, batch_size, workers)
    encoded = _encoded_archive(archive)
    _, carrier_names, carrier_values = _carrier_parts(encoded, inline_chars)
    environment = []
    environment.extend({
        "name": name,
        "type": "plain",
        "value_or_reference_to_secret": value,
    } for name, value in zip(carrier_names, carrier_values))
    if len(environment) > (BATCH_MAX_ENVIRONMENT_ENTRIES
                           - BATCH_TRANSPORT_HEADROOM):
        raise ValueError("batch runtime environment exceeds provider limit")
    if any(len(entry["name"].encode("ascii")) > package.MAX_COMMAND_ARGUMENT_BYTES
           or len(entry["value_or_reference_to_secret"].encode("ascii"))
           > package.MAX_COMMAND_ARGUMENT_BYTES
           for entry in environment):
        raise ValueError("batch runtime environment value exceeds provider limit")
    if len(environment) != BATCH_CARRIER_COUNT:
        raise ValueError("batch runtime carrier count mismatch")
    overlay = {
        "base_app_sha256": manifest["base_app_sha256"],
        "detector_source_sha256": manifest["detector_source_sha256"],
        "detector_code_sha256": manifest["detector_code_sha256"],
        "helper_sha256": manifest["helper_sha256"],
        "manifest_sha256": _sha256(manifest_bytes),
        "function": batch_runtime.TARGET_FUNCTION,
        "application": "base+overlay",
    }
    deployment_patch = {
        "containers": [{
            "name": "envai-pii-test-0",
            "entrypoint_overrides": {
                "enabled": True,
                "entrypoint": [package.PYTHON_PATH, "-c"],
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
        "runtime_destination": package.RUNTIME_DESTINATION,
        "runtime_archive_bytes": len(archive),
        "runtime_archive_sha256": _sha256(archive),
        "batch_profile": True,
        "batch_size": batch_size,
        "batch_environment": "bootstrap",
        "batch_environment_moved": list(BATCH_BOOTSTRAP_ENV),
        "batch_archive_transport": "hybrid",
        "batch_archive_env": BATCH_ARCHIVE_ENV_PREFIX,
        "batch_archive_env_chunks": chunk_count,
        "batch_archive_inline_chars": inline_chars,
        "batch_archive_format": BATCH_BUNDLE_FORMAT,
        "batch_python_version": ".".join(map(
            str, batch_runtime.CODE_HASH_PYTHON_VERSION)),
        "batch_overlay": overlay,
        "fixture": fixture_integrity(),
    }
    return {
        "workers": workers,
        "run_id": run_id,
        "batch_size": batch_size,
        "deployment_patch": deployment_patch,
        "scaling_patch": scaling_patch,
        "overrides": overrides,
        "source_hashes": dict(runtime.SOURCE_HASHES),
        "archive_file_hashes": archive_hashes,
    }
