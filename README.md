# envai-pii

`envai-pii` is the [digitalygo fork](https://github.com/digitalygo/envai-pii) of [`rizzo-pii`](https://github.com/Rizzo-AI-Academy/rizzo-pii), the Italian legal PII anonymizer created upstream by Simone Rizzo and Rizzo AI Academy. This fork keeps training, the HTTP API service with its PDF workflows, and guardrail API v1. It removes desktop packaging and release targets, and the service no longer ships a browser UI. Supported deployments are Python from source and the container built from `Dockerfile`.

The upstream [rizzo-pii:0.3B model](https://huggingface.co/rizzoaiacademy/rizzo-pii-0.3B) uses the multilingual [mmBERT-base backbone](https://huggingface.co/jhu-clsp/mmBERT-base). It predicts 22 categories; the application adds two regex-only categories. See the [tag taxonomy](docs/TASSONOMIA_TAG.md) for the complete list and mapping decisions.

## Fork scope

This fork maintains multilingual training, data preparation, evaluation, inspection, the HTTP API service, reversible dictionary, tag filters, PDF preview and export, guardrail API v1, tests, and the upstream technical report. The browser UI has been removed; the service is API-only. The Tauri shell, native launcher, PyInstaller targets, build scripts, installers, and desktop release workflows are no longer maintained or built. The upstream model and community dataset retain their Rizzo AI Academy names and attribution.

## Run the app

### Run in a container

Podman is preferred when available; Docker uses equivalent commands. The CPU-only image includes the Flask app and downloads upstream model revision v1.5.0 during the image build.

```bash
git clone https://github.com/digitalygo/envai-pii
cd envai-pii
podman build -t envai-pii .
podman run -d --name envai-pii -p 127.0.0.1:5005:5005 envai-pii
podman logs -f envai-pii
podman rm -f envai-pii
```

Replace `podman` with `docker` when using Docker. Bind the published port to loopback as shown: the service listens on `0.0.0.0` inside the container, so publishing `5005:5005` can expose it to the LAN. The image build needs network access to download dependencies and model weights. `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are set at runtime. The checked-in `docker-compose.yml` is a legacy service deployment and does not pass `PII_API_TOKEN`.

### Run from source

`APP_MODEL_VERSION` in `src/app/app.py` selects the default model directory. Download revision v1.5.0 there before starting the app:

```bash
git clone https://github.com/digitalygo/envai-pii
cd envai-pii
python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
hf download rizzoaiacademy/rizzo-pii-0.3B --revision v1.5.0 \
  --local-dir models/rizzo-pii-0.3B-v1.5.0
python src/app/app.py
```

Both `app.py` and `serve.py` serve the same HTTP API only; there is no browser UI and no HTML page at `GET /`, and neither entry point opens a browser or native window. Use `GET /health` as the readiness probe while the model loads; unknown paths return a JSON `404`. `app.py` checks the port after loading the model; `serve.py` checks before importing `app.py`. `serve.py` logs to `%LOCALAPPDATA%\\rizzo-pii\\backend.log` on Windows or `~/rizzo-pii/backend.log` on Linux and macOS. Both use exit code 76 for a detected port conflict; `app.py` writes logs to stdout/stderr.

`PII_MODEL_DIR` overrides the model directory. Source setup does not enable Hugging Face offline mode by default, so model downloads and other environment-level network activity are separate from local inference. Host and port precedence is CLI `--host`/`--port`, `PII_HOST`/`PII_PORT`, `config.json`, then `127.0.0.1:5005`. Legacy API preferences (excluded tags and reversible mapping) live in `prefs.json`, exposed by `GET /settings`; `PII_EXCLUDE_TAGS` sets excluded tags and `PII_MAPPING` controls reversible mapping. See the [environment notes](CLAUDE.md) and [`requirements.txt`](requirements.txt), including Blackwell GPU training constraints.

### Command-line inference

```bash
PII_MODEL_DIR=models/rizzo-pii-0.3B-v1.5.0 \
  python src/training/test_pii.py "Mi chiamo Mario Rossi, IBAN IT60X0542811101000000123456"
```

Inference runs locally after the model is available. The model and regex network can miss personal data, so review output before sharing it.

## PDF support

The PDF endpoints are API-only. `POST /preview` keeps an uploaded PDF in memory and returns extracted text and the page count; `GET /doc/<id>/page/<n>.png` renders one page on the server with PyMuPDF, with pages cached so a 200-page PDF does not cost 200 renders. Documents live in a small in-memory cache and are never written to disk.

`POST /pdf` returns the anonymized PDF: it redacts the original document when the upload was a PDF, or lays out a new PDF from anonymized text otherwise. It reports residual and skipped values when it cannot safely redact every detected span. Scans with no extractable text need OCR first. `POST /pdf/preview` redacts once and keeps the PDF in memory so preview and download (`GET /doc/<id>/file.pdf`) reuse the same copy. Regex and checksum detectors supplement model predictions for structured values; neither guarantees complete coverage.

## HTTP API

The legacy routes are the service's own API surface and have no authentication of their own. Keep the service on loopback or protect it with network controls. Do not expose them directly to untrusted networks.

Unknown paths and framework errors (`404`, `405`, `413`, `500`) return a generic JSON body that keeps the HTTP status and headers and contains no URL or exception detail; a `405` keeps its `Allow` header. A framework `OPTIONS` answers an empty `200`. Successful PDF and PNG responses remain binary.

| Route | Purpose |
|---|---|
| `GET /health` | Readiness for startup checks, without inference |
| `POST /analyze` | Analyze JSON text or PDF, Markdown, or text upload |
| `POST /preview` | Extract text and prepare a PDF for preview |
| `POST /pdf` | Return a redacted PDF or a newly laid out PDF for text input |
| `POST /pdf/preview` | Redact and keep a PDF for preview and download |
| `GET /doc/<id>/page/<n>.png` | Return a rendered page from in-memory storage |
| `GET /doc/<id>/file.pdf` | Download a redacted PDF from in-memory storage |
| `GET/POST /settings` | Read or update preferences; `/tags` is a historical alias |
| `GET/POST /config` | Read or update host and port |
| `GET /port-check` | Check whether a host and port can be bound |

Legacy `/analyze` returns the request-local `mapping`. When mapping is disabled, it returns an empty `mapping` object, omits `source_text`, and omits original entity text from segments. Restore is caller-side: the service provides no restore endpoint, so store and protect the dictionary returned by `/analyze` yourself. Legacy routes and preferences do not apply to guardrail API v1.

### Guardrail API v1

`POST /api/v1/analyses` accepts one JSON `text` and an optional `dictionary` seed. It returns anonymized text and `dictionary_delta`, containing only new placeholder-to-original pairs. The seed and full mapping are not returned. The endpoint is stateless, enables all 24 categories, ignores the legacy preferences, and does not accept batches, files, multipart input, PDFs, or OCR.

The server process needs a non-empty `PII_API_TOKEN`; clients send the same token in `Authorization: Bearer <token>`. An unset token returns 503; missing or incorrect client credentials return 401. The 30-second processing deadline is cooperative, not a hard HTTP timeout. Use a worker or proxy timeout that also covers slow body reads and in-flight inference. See the [guardrail API contract](docs/GUARDRAIL_API.md) and [OpenAPI schema](docs/guardrail-openapi.yaml) for request limits, errors, concurrency, and dictionary rules.

For a source deployment, set the token securely in the shell or secret manager before starting the server process:

```bash
# PII_API_TOKEN must already be set securely in this shell.
export PII_API_TOKEN
python src/app/app.py
```

A container does not inherit host environment variables automatically. Set the host variable securely, then pass it explicitly with `-e PII_API_TOKEN`:

```bash
podman run -d --name envai-pii \
  -p 127.0.0.1:5005:5005 \
  -e PII_API_TOKEN envai-pii
```

Use `docker run` with the same `-e PII_API_TOKEN` option for Docker. The checked-in Compose file does not pass this token; configure an override before using the endpoint through Compose. The guardrail token does not authenticate legacy routes. For access beyond loopback, place an authenticated internal proxy and TLS in front of the service, as described in the [API deployment notes](docs/GUARDRAIL_API.md#deployment).

```bash
curl -X POST http://127.0.0.1:5005/api/v1/analyses \
  -H "Authorization: Bearer $PII_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dictionary": {"[FULLNAME_7]": "Mario Rossi"}, "text": "Mario Rossi, scrivi a mario@example.com"}'
```

## Quickstart

This workflow regenerates training data and trains a model. To use the app without training, see [Run the app](#run-the-app). Training requirements and environment constraints are in [CLAUDE.md](CLAUDE.md). Raw corpora come from Hugging Face; scripts resolve paths from `__file__` and run from any working directory.

### Install and prepare data

On Windows, use PowerShell. For RTX 50-series training, install CUDA 12.8 PyTorch first with `pip install torch --index-url https://download.pytorch.org/whl/cu128`; CPU PyTorch is sufficient for inference. DeepMount preparation requires Hugging Face authentication. Gemini-authored templates are optional.

```powershell
git clone https://github.com/digitalygo/envai-pii
cd envai-pii
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env                    # optional: W&B and Gemini keys
python src/data_pipeline/llm_template_bank.py --per-type 5 --append
python src/data_pipeline/generate_synthetic_pii.py -n 200000 --out dataset/synthetic/synthetic_pii_it_200k.jsonl
python src/data_pipeline/augment_real_pii.py -n 40000 --out dataset/synthetic/synthetic_pii_it_realaug.jsonl
python src/data_pipeline/prepare_deepmount.py
python src/data_pipeline/build_validation.py
python src/data_pipeline/build_subset.py
```

The pool combines Ai4Privacy, generated examples, augmented Ai4Privacy sentences, and DeepMount. It contains about 745,000 rows across eight languages, with Italian reinforced. The 7,000-row validation set is Italian and includes legal identifiers injected into held-out real sentences. See [dataset composition](docs/DATASET.md) and the [training guide](docs/TRAINING.md) for source, split, and preprocessing details.

### Train and evaluate

```powershell
python src/training/train_pii.py --type subset
python src/training/train_pii.py --type full
python src/training/train_pii.py --type full --version 1.2.0
python src/training/test_pii.py "Mi chiamo Mario Rossi, IBAN IT60X0542811101000000123456"
python src/app/app.py --port 8080 --exclude-tags AGE,GENDER --no-mapping
```

Full runs write models to `models/rizzo-pii-0.3B-v{VERSION}/`, artifacts to `experiments/full_run_v{VERSION}/`, and update `models/registry.json`. Generated data, models, and run artifacts are not included in the repository. The app default remains model v1.5.0; set `PII_MODEL_DIR` to use a model produced by training.

### Run tests

```bash
python -m unittest discover -v tests
```

GitHub Actions runs discovery on Python 3.11, 3.13, and 3.14 without installing torch or model weights. Tests that need optional Flask or PyMuPDF are skipped when unavailable. CI tests logic and contracts, not model accuracy.

## Historical upstream results

These measurements belong to upstream Rizzo AI Academy checkpoints. This fork has not rerun
them, and CI does not measure model accuracy. The v1.2.0 checkpoint reported micro-F1 0.989 on
the 7,000-row held-out Italian `validation_real` set. The v1.5.0 release reports micro-F1 0.9999
on `validation_clean`, 0.9886 on `validation_real`, and 99.89% masking coverage on that neutral
benchmark. See the [upstream v2.0.0 release notes](docs/releases/v2.0.0.md), the
[technical report](report/rizzo-pii-report.pdf) and its [Typst source](report/rizzo-pii.typ),
and the [upstream v1.5.0 evaluation](https://huggingface.co/rizzoaiacademy/rizzo-pii-0.3B/blob/v1.5.0/EVAL_v1.5.0_vs_main.md)
for benchmark definitions, provenance, and per-tag results.

## Limitations

- The model and regex network can miss spans, especially in scans, unusual layouts, and short values. Review output before sharing.
- Scanned PDFs need OCR. If the PDF endpoint finds no redaction target, it returns an error instead of a successful-looking file.
- Training is multilingual, but the published `validation_real` benchmark is Italian-only. Five Italian legal identifiers are injected into real validation sentences because public labeled examples are unavailable.
- Some tags are under-represented, and DeepMount includes values outside Italian usage. See the [dataset](docs/DATASET.md) and [taxonomy](docs/TASSONOMIA_TAG.md) documentation.
- This project is not a GDPR certification or legal advice. Compliance depends on deployment and use.

## Repository layout

```text
envai-pii/
├── README.md, LICENSE, THIRD_PARTY_LICENSES.md, CONTRIBUTING.md
├── requirements.txt, Dockerfile, docker-compose.yml, CLAUDE.md
├── src/                     app/, data_pipeline/, inspect/, training/
├── tests/                   standard-library test suite
├── docs/                    API, data, training and taxonomy guides
├── report/                  upstream technical report and evaluation artifacts
└── reports/                 TARGA stress-test baseline
```

Generated `dataset/`, `models/`, `experiments/`, and `wandb/` directories are ignored by Git.

## Documentation

- [Dataset composition](docs/DATASET.md)
- [Training guide](docs/TRAINING.md)
- [Tag taxonomy](docs/TASSONOMIA_TAG.md)
- [Dataset contribution format](docs/FORMATO_DATI.md)
- [Guardrail API contract](docs/GUARDRAIL_API.md) and [OpenAPI schema](docs/guardrail-openapi.yaml)
- [TARGA generation notes](docs/targa_generation_notes.md)
- [Change log](docs/CHANGELOG.md)
- [Historical upstream v2.0.0 notes](docs/releases/v2.0.0.md)
- [Contributor guide](CONTRIBUTING.md)
- [Developer environment and architecture notes](CLAUDE.md)
- [Third-party license notices](THIRD_PARTY_LICENSES.md)

## Contributing

Code, documentation, and synthetic data contributions are welcome. Start with
[CONTRIBUTING.md](CONTRIBUTING.md). Never submit real personal data. The upstream technical
report lists contributors to the original community dataset.

## License and attribution

The source code remains under the upstream [MIT License](LICENSE), copyright (c) 2026 Simone
Rizzo, Rizzo AI Academy. This fork adds no separate terms. The upstream model and mmBERT-base are
declared MIT. The Ai4Privacy dataset card declares `license: other` and `license_name: cc-by-4.0`,
with attribution required; DeepMount declares no dataset license. See
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for component details.

PyMuPDF is dual-licensed under AGPL-3.0 or a commercial license and is used for PDF rendering
and redaction. A container built from `Dockerfile` bundles PyMuPDF. Redistributing a combined
work requires the corresponding source under the terms described in
[the third-party notices](THIRD_PARTY_LICENSES.md). For a service reachable by other people,
the AGPL network clause requires an offer of corresponding source. The obligations apply to the
software, not the anonymized documents.
