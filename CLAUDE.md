# CLAUDE.md

Guida per Claude Code (claude.ai/code) quando lavora in questa repo. Panoramica e struttura
delle cartelle in **[README.md](README.md)**. Documenti di dettaglio:
**[docs/TASSONOMIA_TAG.md](docs/TASSONOMIA_TAG.md)** (i 22 tag),
**[docs/DATASET.md](docs/DATASET.md)** (composizione completa di train/validation) e
**[docs/TRAINING.md](docs/TRAINING.md)** (unione dei due dataset HF, accortezze sui tag,
iperparametri).

## Cos'è questo progetto

Pipeline per addestrare un modello **mmBERT** (`jhu-clsp/mmBERT-base`) a fare **token
classification di PII**, con focus su **testi legali italiani** (atti, contratti, sentenze)
ma con training **multilingue**. Obiettivo finale: anonimizzare documenti **in locale**
prima di mandarli a LLM closed (anonymize → placeholder + dizionario reversibile locale →
API → ricostruzione), per studi legali / compliance GDPR.

Scelta di mmBERT (encoder multilingue, architettura ModernBERT, context nativa 8192) e non
ModernBERT vanilla perché quest'ultimo è quasi solo inglese.

## Ambiente: vincoli critici e non ovvi

GPU **RTX 5060 Ti (Blackwell, sm_120)** su Windows; Python in `D:\programmi\python`.
Questi punti fanno fallire tutto se ignorati:

- **torch DEVE essere build cu128**: `torch 2.11.0+cu128` (da `https://download.pytorch.org/whl/cu128`).
  Le build cpu/cu121 non supportano sm_120 → `torch.cuda.is_available()` False o crash.
- **torchvision/torchaudio vanno disinstallati** se a versioni vecchie: rompono l'import di
  transformers con `operator torchvision::nms does not exist`. Non servono qui.
- **accelerate ≥ 1.14** (transformers 4.57 chiama `unwrap_model(keep_torch_compile=...)`).
- Windows: nel Trainer **`dataloader_num_workers=0`** (altrimenti `RuntimeError ... bootstrapping`).
- **seqeval non si compila** (bug setuptools_scm) → metriche entity-level (P/R/F1) calcolate
  a mano dentro gli script, nessuna dipendenza.
- Dipendenze extra installate: **`wandb`** (tracking) e **`python-dotenv`** (legge `.env`).
- **Log da PowerShell**: redirezioni `>` e `Tee-Object` scrivono **UTF-16** → leggerli con
  `Get-Content`/`python`, NON con lo strumento Read. Gli script forzano `sys.stdout` UTF-8.

## Mappa della repo

Questo fork di digitalygo mantiene training, pipeline dati, servizio Flask solo API con workflow
PDF, oltre alla guardrail API v1. La UI browser è stata rimossa: `app.py` non serve più pagine
HTML, solo endpoint. Il packaging desktop Tauri, gli installer nativi e
`src/app/desktop_app.py` sono stati rimossi. Gli entry point mantenuti sono `app.py` e `serve.py`;
il container usa `Dockerfile`.

Struttura completa in [README.md](README.md). In breve: codice in `src/`, dati in `dataset/`,
modelli in `models/<versione>/`, artefatti dei run in `experiments/<run>/`, doc in `docs/`.
**I path negli script sono assoluti (risolti da `__file__`): girano da qualsiasi CWD.**

**Pipeline dati: `src/data_pipeline/` (ordine di esecuzione):**

- `llm_template_bank.py`: Gemini scrive documenti legali con soli segnaposto `{SLOT}` →
  `dataset/synthetic/legal_templates.json` (72 template). Guard scarta i template con nomi inline.
- `generate_synthetic_pii.py`: inietta nei template dati con **checksum validi** (CF/PIVA/IBAN)
  → `dataset/synthetic/synthetic_pii_it_200k.jsonl` (`tokens` + `bio_labels`).
- `augment_real_pii.py`: inietta entità sintetiche in **frasi reali** Ai4Privacy (it) in posizioni
  variabili → `dataset/synthetic/synthetic_pii_it_realaug.jsonl`. Spezza il legame template/posizione.
- `prepare_deepmount.py`: rimappa `DeepMount00/pii-masking-ita` (56 tipi Faker IT) sui 22 tag →
  `dataset/processed/deepmount_pii_it_{train,test}.jsonl`.
- `build_validation.py`: **unica validation reale** → `dataset/validation/validation_real.jsonl`.
- `build_subset.py`: subset stratificati (multilingua + tag) per smoke test →
  `dataset/subsets/{train_subset_10k,val_subset_5k}.jsonl`.

**Training: `src/training/`:**

- `train_pii.py`: fonde tutte le fonti, addestra, salva il modello, plotta la loss, stampa
  metriche train/val, logga su **W&B** (run `rizzo-pii:0.3B-v{VERSION}`). **Modello versionato**:
  ogni run grande salva in `models/rizzo-pii-0.3B-v{VERSION}/` (storico, niente sovrascrittura;
  `MODEL_VERSION` in cima al file o `--version`; storia in `models/registry.json`). Vedi "Parametri".
- `test_pii.py`: inferenza CLI sul modello salvato (entità + testo anonimizzato). Risolve in automatico
  l'**ultima** versione `rizzo-pii-0.3B-v*` (fallback al vecchio non versionato → legacy; override `PII_MODEL_DIR`).

**Utility / ispezione (read-only): `src/inspect/`:**

- `validate_checksums.py`: ricalcola i checksum CF/IBAN/PIVA; **blueprint della rete regex+checksum**
  da affiancare al modello in produzione.
- `inspect_ai4privacy.py` (conteggi lingue/tag), `inspect_lengths.py` (lunghezze), `inspect_no_iban.py`.

**App di anonimizzazione locale: `src/app/`:**

- `server_config.py`: **configurazione host/porta** (+ `prefs.json` con tag esclusi e stato del
  dizionario) condivisa tra tutti gli entry point.
  Catena di precedenza: **CLI `--host`/`--port` > env `PII_HOST`/`PII_PORT` > `config.json` > default
  `127.0.0.1:5005`**. Il config.json è in `%LOCALAPPDATA%\rizzo-pii\` (Windows) /
  `~/.local/share/rizzo-pii/` (Linux) / `~/Library/Application Support/rizzo-pii/` (macOS).
  Include `port_available()` (pre-bind check) e il codice di uscita `EXIT_PORT_CONFLICT = 76`.
  `serve.py` controlla la porta prima di importare `app.py` e caricare il modello. `app.py` importa
  e carica il modello prima di controllare la porta nel blocco CLI. Entrambi usano il codice 76 se
  il controllo o il bind finale rileva un conflitto.
- `app.py`: server Flask **solo API/HTTP** (nessuna pagina HTML). L'input arriva come testo JSON o
  come file caricato (`.pdf`/`.md`/`.txt`), chunking con overlap, offset
  globali + dedup. Anonimizzazione **reversibile** (ogni PII → `[FULLNAME_1]`/`[IBAN_1]`… +
  dizionario `mapping` nella risposta; il ripristino è **a carico del chiamante**). Affianca al
  modello una **rete regex/checksum** (EMAIL/
  TELEFONO/IBAN/CF/PIVA/carta/importo/targa/**URL**/**IPADDR**; IBAN/CF/PIVA/carta validati con
  checksum, che ha priorità sul modello). `URL` e `IPADDR` sono i **due tag solo-regex** (23° e 24°):
  il modello non li conosce; `URL` matcha schema, `www.` e domini nudi solo su una **lista chiusa di
  TLD** (senza, `p.iva`/`S.r.l.` diventerebbero domini), `IPADDR` quattro ottetti 0-255 incluse le
  forme CIDR e range. Le richieste a `/` o a percorsi sconosciuti rispondono **404 JSON**; gli
  errori framework (404/405/413/500) escono come JSON generico con status e header invariati
  (405 conserva `Allow`, corpo senza URL né dettagli dell'eccezione). `APP_VERSION`. Endpoint:
  `GET /health` (readiness senza inference, 200/503),
  `POST /analyze`, `POST /pdf`, `POST /preview`, `POST /pdf/preview`, `GET /doc/<id>/page/<n>.png`,
  `GET /doc/<id>/file.pdf`, `GET/POST /settings` (alias storico `/tags`), `GET/POST /config`,
  `GET /port-check`, `POST /api/v1/analyses` (guardrail v1, vedi sotto); CLI
  `--host`/`--port`/`--exclude-tags`/`--no-mapping`.
- `pii_dictionary.py` + `guardrail_api.py` + `guardrail_inputs.py`: **guardrail API v1**
  (ENVAS-23): endpoint additivo `POST /api/v1/analyses` con due arm implementati. Il ramo a
  **un solo testo JSON** mantiene il contratto 0.1.0 e accetta in piu' il campo opzionale
  `categories` (schema 0.3.0). Il ramo
  **multifile** (schema 0.2.0, esteso a 0.3.0 dal campo `categories`) e' implementato: stessa
  route, media type `multipart/form-data`
  con fino a 10 file opzionali (`.pdf`/`.txt`/`.text`/`.md`/`.markdown`, estensione
  case-insensitive e whitelist controllata prima del contenuto), `text` singolo opzionale,
  `dictionary` come stringa form con JSON severo (chiavi placeholder canoniche come `[ORG_6]`,
  mai arbitrarie), `categories` come stringa form con JSON severo e un solo `dictionary_delta`
  aggregato, per un massimo di 13 parti (10 file piu' i campi valore `text`, `dictionary` e
  `categories`); `files`, `text`, `dictionary` e `categories` sono
  facoltativi singolarmente ma serve almeno un file o un `text` non vuoto (il campo
  `categories` seleziona soltanto e non conta come input), quindi una richiesta
  solo-testo senza file e' valida e il campo si chiama `files`, mai `files[]`. L'intake usa il
  `MultipartDecoder` nativo di Werkzeug alimentato in RAM (mai `request.files`, niente spool o
  file temporanei); il testo mantiene la policy di codifica legacy e un contenuto `%PDF-` su nome
  `.txt`/`.md` segue lo stesso percorso PDF strict e bounded dei `.pdf` (200 pagine, budget
  aggregato 100000 caratteri, annots/widgets/TOC strict, deadline cooperativa server-side).
  Niente OCR, redazione raster, PDF binario/ZIP, array JSON, UI, training o modifiche AAAS.
  Bearer `PII_API_TOKEN` configurato nell'ambiente del server. La deadline e' un budget
  cooperativo interno, globale su entrambi i rami, letto una volta per richiesta da
  `PII_ANALYSIS_TIMEOUT_SECONDS` (float positivo e finito; assente, vuoto o invalido: fallback
  sicuro a 60 s), non e' un campo della richiesta e non interrompe PDF nativo o model call; il
  timeout di worker/proxy esterno va tenuto piu' lungo del budget piu' margine per upload e
  lavoro nativo. La variabile e' non-segreta e indipendente dal segreto `PII_API_TOKEN`.
  Motore senza dipendenze in `pii_dictionary.py`, guscio HTTP in
  `guardrail_api.py`, intake multipart in `guardrail_inputs.py`, adapter registrato da `app.py`;
  stateless, non legge `prefs.json` e non ha fallback da env/CLI/impostazioni. Il campo
  **solo-richiesta `categories`** e' la whitelist delle etichette da anonimizzare: nello JSON un
  array di nomi canonici (`["FULLNAME","EMAIL"]`), nel multipart un singolo campo valore con
  JSON severo; assente, `null`, `[]`, stringa vuota o di soli spazi = tutte le 24 categorie
  (default storico), valori o voci non validi = `400 invalid_request`, massimo 24 voci grezze
  (oltre il tetto -> `400 invalid_request`) con duplicati deduplicati. La selezione filtra
  modello e regex prima del merge e vale su ogni file e sul `text`: le categorie non selezionate
  restano in chiaro per scelta esplicita del
  chiamante, quindi un sottoinsieme non e' una garanzia di anonimizzazione completa. Il seed
  resta validato e copiato su tutte le 24 categorie anche inattive (stessi conflitti e tetti,
  ID riservati, nessun match ne' delta per le inattive), `dictionary_delta` contiene solo le
  coppie nuove selezionate e `statistics.placeholder_count` conta tutti i token canonici.
  **Capability PDF
  nativa**: all'avvio, una volta per processo, le diagnostiche di MuPDF (errori/warning) vengono
  spente con readback delle flag e reset del buffer verificati; il buffer viene svuotato dopo
  ogni tentativo di estrazione PDF della guardrail che arriva al parser nativo e, se il controllo
  nativo manca o si rompe, solo il ramo PDF risponde 503 (JSON e testo continuano a funzionare)
  fino al riavvio del processo. Contratto:
  `docs/GUARDRAIL_API.md` + `docs/guardrail-openapi.yaml`; test: `tests/test_guardrail_api.py`,
  `tests/test_pii_dictionary.py` (JSON), `tests/test_guardrail_multifiles.py` (multipart e
  cablaggio), `tests/test_guardrail_pdf_privacy.py` (privacy nativa), `tests/test_pdf_text_limits.py`
  (collector strict/bounded), `tests/test_guardrail_timeout.py` (budget e file opzionali),
  `tests/test_guardrail_categories.py` (selezione delle categorie su entrambi gli arm).
- **Anteprima e download del PDF via API**: `POST /preview` tiene il PDF in memoria e ritorna
  testo + numero di pagine; `GET /doc/<id>/page/<n>.png` rende le pagine **server-side con
  PyMuPDF** (`page.get_pixmap` → PNG per pagina), per una resa coerente senza dipendere da pdf.js
  o da una CDN.
  Le pagine sono messe in cache: un PDF di 200 pagine non costa 200 render.
  I documenti stanno in una **LRU in memoria** (`_DOCS`, `MAX_DOCS=6`) e **mai su disco**: valgono
  quanto il documento stesso e muoiono col processo.
  `POST /pdf/preview` fa lo stesso lavoro di `/pdf` ma lascia il binario nello store e ritorna
  `{doc_id, n_pages, residual, skipped}`: anteprima e download (`GET /doc/<id>/file.pdf`) usano
  **la stessa copia**, quindi guardare il PDF e poi scaricarlo costa **una sola** anonimizzazione.
  `/pdf` resta invariato per chi usa l'API.
- **Preferenze di anonimizzazione** → `prefs.json` nella config dir (`EXCLUDED_TAGS`,
  `MAPPING_ENABLED`). File **separato da `config.json`** perché quest'ultimo viene riscritto per
  intero quando si cambia porta. Precedenza: campo nella richiesta > CLI > env > file.
- **Tag disattivabili**: i tag esclusi vengono rilevati ma **non** sostituiti (restano in
  chiaro), utile per confrontare gli importi o tenere età/sesso in un caso clinico. Env
  `PII_EXCLUDE_TAGS`, campo `exclude_tags` nella richiesta, preferenza in `prefs.json`. I 24 tag
  applicativi (22 del modello + `URL`/`IPADDR`) con descrizioni IT/EN ed esempi vivono in `TAGS`
  in cima a `app.py` e sono esposti da `GET /settings`.
- **Dizionario reversibile on/off** (`MAPPING_ENABLED`, default **on**; env `PII_MAPPING=0`, campo
  `include_mapping`): con off l'anonimizzazione è **definitiva**. `analyze()` restituisce comunque
  `mapping: {}`, senza valori originali, e i segmenti-entità **perdono il campo `t`** (altrimenti il
  dizionario si ricostruirebbe dal payload). La route `/analyze` omette `source_text` quando il
  mapping è disattivato; con il mapping attivo lo restituisce, così il chiamante può conservare
  testo originale e dizionario. Il ripristino è **a carico del chiamante**: il backend non espone
  un endpoint di restore e non conserva la mappa. La **numerazione resta**
  (`[FULLNAME_1]` due volte = stesso soggetto): da sola non riporta al valore.
- `pdf_export.py` + endpoint **`POST /pdf`**: **download del PDF anonimizzato** (issue #7, punto 1).
  Due modalità: se l'input era un **PDF**
  si fa **redazione vera** del documento originale (`apply_redactions()`: il testo esce dal content
  stream, non ci si disegna sopra un rettangolo) con i placeholder al posto delle PII e il layout
  intatto; altrimenti (testo incollato, `.md`/`.txt`) si **ricostruisce** un PDF impaginando da zero
  il solo testo anonimizzato.
  **Il dizionario non viaggia sulla rete in nessuna direzione**: `/pdf` prende lo stesso input di
  `/analyze`, richiama `analyze(..., mapping_enabled=True)` internamente e la mappa muore con la
  richiesta. Per questo la redazione funziona identica anche con il **dizionario reversibile
  disattivato**, dove il chiamante non ne ha nessuno (il costo è una seconda inferenza).
  Matching **char-preciso** con confini di parola (indice per carattere da `rawdict` + regex ancorate
  `(?<!\w)…(?!\w)`), tollerante alla **sillabazione a fine riga** e agli spazi tra token: "DE" non
  viene redatto dentro "CORDELLA". Unica eccezione alle ancore: se il valore ha **punteggiatura ai
  bordi** il modello ha tagliato a metà una parola spezzata a fine riga (su "Fran-\ncesco Cordella"
  etichetta `-\ncesco Cordella`), dove il confine di parola impedirebbe di trovarlo,
  quindi si toglie, ma **solo** se il resto ha ≥ 4 caratteri alfanumerici (altrimenti `.it`
  matcherebbe "it" dentro ogni parola).
  Oltre al testo di pagina ripulisce ciò che `apply_redactions()` **non** tocca e in cui la PII
  sopravviverebbe: metadati + XMP, contenuto delle **annotazioni**, valore dei **campi modulo**,
  titoli dei **segnalibri**; gli **allegati incorporati** vengono rimossi in blocco.
  **Due casi in cui un valore resta in chiaro, entrambi segnalati negli header della risposta**
  (`X-PII-Residual` e `X-PII-Skipped`): (a) *residui* = valore ancora leggibile nell'output alla
  verifica finale; (b) *saltati* = valori con < 2 caratteri alfanumerici o di 2 sole cifre (es. "45"),
  non cercabili senza devastare il documento. Se in tutto il PDF non si trova **nessuna** occorrenza
  → `422`, non un PDF "anonimizzato" che non lo è (caso tipico: scansione, serve OCR → punti 2-4
  della issue). Nessuna dipendenza dal modello: `pdf_export.py` è testabile in isolamento.
- `serve.py`: entry **headless** adatto a un process manager. `app.py` e `serve.py` servono la
  stessa API HTTP; nessuno dei due apre una finestra nativa, un browser o pagine statiche.
  `app.py` scrive su stdout/stderr e controlla la porta dopo aver caricato il modello.
  `serve.py` scrive in `%LOCALAPPDATA%\rizzo-pii\backend.log` su Windows o `~/rizzo-pii/backend.log`
  altrove, e controlla la porta prima di importare `app.py`. Entrambi escono con codice 76 se il
  controllo o il bind finale rileva un conflitto. Restano `smoke_app.py` e `make_test_pdf.py`.

**Config:** `.env` (segreti W&B, **gitignorato**) e `.gitignore` (protegge credenziali, vecchi
output di build e snapshot di stato locali).
**Artefatti non versionati** (gitignored): `dataset/`, `models/`, `experiments/`, `wandb/`,
`build_env/`, `dist/`, `build/`.

## Idea architetturale chiave: "LLM autore, codice etichettatore"

Il cuore della generazione sintetica: **l'LLM scrive solo la prosa con segnaposto, il codice
inietta i dati**. Risolve insieme tre problemi: label BIO esatte (sappiamo dove iniettiamo),
checksum matematicamente validi, nessuna PII reale rigurgitata dall'LLM. **Non far mai scrivere
all'LLM i dati sensibili veri.**

## Tassonomia: 22 tag (dettaglio in TASSONOMIA_TAG.md)

`TAG_MAP` + `DROP_TYPES` + `normalize_labels()` in `train_pii.py` rimappano **al caricamento**
(file grezzi intatti). Per cambiare la tassonomia si edita **solo** `TAG_MAP`/`DROP_TYPES`.

Fusioni: nomi+ruoli legali → `FULLNAME`; `SEX`→`GENDER`; `TAXNUM`→`PIVA`; `PEC`→`EMAIL`;
`RG`→`DOCID`; `IDCARDNUM`/`PASSPORTNUM`/`DRIVERLICENSENUM`/`SOCIALNUM`→`ID_DOC`; `CONTO`→`IBAN`.
Rimossi (→`O`): `TITLE` (appellativo), `TRIBUNAL` (ente pubblico, non PII).
Tag aggiunti via sintetico: `ORG`, `DOCID`, `CATASTO`, `CONTO`(→IBAN), `PROVINCE`.

I 5 tag legali IT-specifici (`CF`, `PIVA`, `CATASTO`, `DOCID`, `PROVINCE`) non esistono come
dato reale da nessuna parte → vengono solo dai sintetici.

## Fonti dati (dettaglio in DATASET.md)

Quattro fonti, tutte ricondotte ai 22 tag al caricamento:

1. **Ai4Privacy** `open-pii-masking-500k`, reale, **8 lingue**, ~464k righe train (it ~55k).
   `hf download ai4privacy/open-pii-masking-500k-ai4privacy`. Ha `mbert_tokens`+`mbert_token_classes`.
2. **Sintetico da template**: `generate_synthetic_pii.py`, 200k righe, copre i tag legali IT.
3. **Augment**: `augment_real_pii.py`, 40k, entità sintetiche in frasi reali it.
4. **DeepMount** `DeepMount00/pii-masking-ita`, Faker IT, 41k; dà contesto reale a IBAN/ORG/AMOUNT/TARGA.

Train pool ≈ **745k righe** (multilingue; italiano rinforzato al ~45%). ~38% sintetico.

## Validation: una validation reale unificata

`validation_real.jsonl` (7k righe, **solo italiano**, da `build_validation.py`):

- base reale held-out = Ai4Privacy val (it) + DeepMount test;
- i 5 tag senza dato reale sono **iniettati in frasi reali held-out** (frasi della validation
  Ai4, non nel training) → contesto reale, niente leakage.

Tutti i sintetici e il DeepMount **train** stanno nel pool di training; il DeepMount **test**
è consumato solo nella validation. Scelta: validation italiana perché l'uso reale è il dominio
legale IT (il training resta multilingue; le altre lingue non sono validate).

## Parametri di training importanti (`src/training/train_pii.py`)

- `LANG = None` → **multilingue** (8 lingue Ai4Privacy); `"it"` = solo italiano. Synth/DeepMount
  sempre inclusi (già italiani, rinforzo).
- `MAX_LEN = 768` → copre i sintetici (max 771 subword) e DeepMount (660); con 512 si troncava il
  **33% dei sintetici**. Padding dinamico.
- `BATCH = 16` + `GRAD_ACCUM = 2` (batch **effettivo 32**) → a MAX_LEN 768 su una 16 GB **condivisa
  col desktop**, batch più grandi saturano la VRAM e causano **thrashing** (allocatore CUDA che
  libera/ri-alloca ad ogni batch lungo → 24-37 s/step). Con 16 il picco di attivazioni resta ~8-9 GB.
  Altre mitigazioni: `group_by_length=True` (`LengthGroupedTrainer` usa lunghezze precalcolate per
  non ri-tokenizzare il dataset lazy) e `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
  Chiudere le app che usano la GPU (Chrome/WhatsApp/…) libera 1-2 GB.
- `EPOCHS = 1`. L'eval **non** gira durante il training: train loss a ogni step, **metriche P/R/F1
  ALLA FINE** su validation e su un campione di train (`TRAIN_EVAL_N`).
- **Modalità del run** (`--type {full,subset}`, default `full`; anche `PII_SUBSET=1` forza subset):
  `subset` = smoke test / tuning sui subset `dataset/subsets/` (10k/5k), MAX_LEN 256, BATCH 32,
  ~3 min → `experiments/subset_smoke/`. `full` = run grande.
- Output run grande: `models/rizzo-pii-0.3B-v{VERSION}/` (+ tokenizer) e `experiments/full_run_v{VERSION}/`
  (loss + out/) + append a `models/registry.json`. La versione viene da `MODEL_VERSION` o `--version`.

## Weights & Biases

`train_pii.py` carica `.env` con `load_dotenv()`; se c'è `WANDB_API_KEY` attiva
`report_to=["wandb"]` (progetto da `WANDB_PROJECT`, default impostato a `pii-mmbert-it`).
Logga la **train loss live a ogni step** e le **metriche finali** (`final/train_*`, `final/val_*`).
Il `.env` è **gitignorato**: non committarlo. Senza chiave, W&B si disattiva da solo.

## Comandi

Tutti gli script forzano UTF-8 e risolvono i path da soli (girano da qualsiasi CWD; i comandi
sotto si lanciano dalla root per comodità).

```powershell
# 1) (opz.) template legali via Gemini   (richiede GEMINI_API_KEY)
python src/data_pipeline/llm_template_bank.py --per-type 5 --append

# 2) sintetico da template (200k)
python src/data_pipeline/generate_synthetic_pii.py -n 200000 --out dataset/synthetic/synthetic_pii_it_200k.jsonl

# 3) augment in testo reale (40k)
python src/data_pipeline/augment_real_pii.py -n 40000 --out dataset/synthetic/synthetic_pii_it_realaug.jsonl

# 4) DeepMount rimappato 56->22 tag  (richiede login HF: hf auth login)
python src/data_pipeline/prepare_deepmount.py

# 5) validation reale unificata (7k)
python src/data_pipeline/build_validation.py

# 6) subset stratificati per smoke test (10k/5k)
python src/data_pipeline/build_subset.py

# 7a) smoke test / tuning sul subset (~3 min)  -> experiments/subset_smoke/
python src/training/train_pii.py --type subset
# 7b) run grande su tutto  -> models/rizzo-pii-0.3B-v{VERSION}/ + experiments/full_run_v{VERSION}/ + W&B
python src/training/train_pii.py --type full                  # usa MODEL_VERSION nel file
python src/training/train_pii.py --type full --version 1.2.0  # oppure versione esplicita

# inferenza / app
python src/training/test_pii.py "Mi chiamo Mario Rossi, IBAN ..."
python src/app/app.py            # API su http://127.0.0.1:5005  (PII_PORT per override; 5000 = AirPlay su macOS)

# ispezione read-only
python src/inspect/inspect_ai4privacy.py
python src/inspect/inspect_lengths.py
```

## Limiti noti / aspettative oneste

- **Overfit strutturale**: i tag che vengono solo dai template rischiano di imparare la
  *struttura* invece dell'entità. Mitigazioni in atto: 72 template (non più ~29), augment in
  testo reale, e il contesto vario di DeepMount per IBAN/ORG/AMOUNT/TARGA.
- **Validation solo italiana**: non misura le 7 lingue non-it (scelta voluta).
- **Tag legali IT-only** (`CF`/`PIVA`/`CATASTO`/`DOCID`/`PROVINCE`): in validation sono entità
  generate in frasi reali → buon proxy, non eval completamente cieco. `PROVINCE` nel train ha
  poca diversità di contesto (quasi solo dai template).
- **Sbilanciamento di classe**: FULLNAME ≫ CREDITCARDNUMBER (~66×) → i tag rari sono più rumorosi.
- **Valori off-domain di DeepMount**: nomi/indirizzi USA; utili per forma/contesto, non come
  valori italiani.
- In produzione affiancare **sempre** la rete regex+checksum (`src/inspect/validate_checksums.py`) al modello.
