# Prontezza della repository per l'esecuzione su RunPod

## Ambito e contesto

Questa nota raccoglie i risultati dell'analisi in sola lettura della repository e della documentazione ufficiale di RunPod in
risposta alla domanda: "Vorremmo provare l'esecuzione su un provider come runpod, cosa dobbiamo fare per impostare la repo?".
L'analisi è stata svolta il `2026-10-21` sul branch `feature/teams-pii-integration` al commit
`0fd115c5dbee905882ef6651dfb3c77a92cb3739` (albero di lavoro pulito e allineato al remoto verificato via `git ls-remote`).

Poiché l'obiettivo operativo non specifica ancora se la prova riguardi il servizio API di anonimizzazione (`POST /api/v1/analyses`)
oppure il training del modello (`src/training/train_pii.py`), il documento copre entrambi gli scenari. Questa nota riporta fatti
verificati e raccomandazioni preliminari, non un piano di implementazione approvato; nessuna build o esecuzione è stata lanciata su
RunPod e nessun dato reale è stato inviato.

## Riepilogo esecutivo

La repository può essere provata su un Pod RunPod senza riscrivere il motore applicativo e senza introdurre l'SDK di RunPod, ma
l'immagine container attuale è costruita solo per CPU e il servizio Flask espone route legacy prive di autenticazione. Per
l'inferenza API su GPU serve un'immagine separata con wheel CUDA compatibili e un canale di accesso protetto (tunnel SSH reale o
reverse proxy autenticato), mentre per il training serve operare su un volume persistente `/workspace` con dataset caricati fuori da
Git e attenzione ai flag di pubblicazione Hugging Face.

## Fonti ispezionate

- Container e configurazione locale in [`Dockerfile`](../../../Dockerfile), [`.dockerignore`](../../../.dockerignore) e
  [`docker-compose.yml`](../../../docker-compose.yml).
- Runtime API, guardrail e contratto di deploy in [`src/app/app.py`](../../../src/app/app.py),
  [`src/app/guardrail_api.py`](../../../src/app/guardrail_api.py) e [`docs/GUARDRAIL_API.md`](../../../docs/GUARDRAIL_API.md).
- Pipeline di addestramento e documentazione operativa in [`src/training/train_pii.py`](../../../src/training/train_pii.py),
  [`CLAUDE.md`](../../../CLAUDE.md) e [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).
- Traccia storica di isolamento proxy su CPU in
  [`substrate/traces/operations/2026-10-07-envai-pii-vpn-test-environment.md`](../operations/2026-10-07-envai-pii-vpn-test-environment.md).
- Documentazione RunPod verificata il `2026-10-21` su template, credenziali registry, porte, SSH, secret, storage e Serverless.

## Fatti verificati nel codice

### Immagine container, modello e runtime GPU per l'API

- [`Dockerfile`](../../../Dockerfile) (righe 15, 35-36) parte da `python:3.11-slim` e installa `torch==2.13.0` dall'indice CPU
  (`https://download.pytorch.org/whl/cpu`) insieme a `transformers==5.14.1`. L'immagine esistente può girare invariata su un Pod
  RunPod solo in modalità CPU, senza usare la GPU.
- [`Dockerfile`](../../../Dockerfile) (righe 41-46) scarica il modello `rizzoaiacademy/rizzo-pii-0.3B` (`v1.5.0`) durante la build in
  `/app/models/rizzo-pii-0.3B-v1.5.0` e imposta `HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1` (righe 62-65). Per servire l'API non è
  quindi obbligatorio montare un volume a runtime per il modello.
- [`src/app/app.py`](../../../src/app/app.py) (righe 176, 183-184) fissa `APP_MODEL_VERSION = "1.5.0"` e accetta l'override
  `PII_MODEL_DIR`. Poiché [`Dockerfile`](../../../Dockerfile) (riga 45) scrive sempre nel path `/app/models/rizzo-pii-0.3B-v1.5.0`,
  cambiare il build arg `MODEL_REVISION` senza allineare la cartella o impostare `PII_MODEL_DIR` lascia il riferimento a `v1.5.0`.
- [`src/app/app.py`](../../../src/app/app.py) (riga 225) seleziona la GPU se `torch.cuda.is_available()` è vero (`device = 0`),
  altrimenti ripiega su CPU (`-1`). L'endpoint `GET /health` (righe 733-751) riporta `"device": "cuda"` o `"cpu"` senza eseguire
  inferenza; su GPU la verifica richiede sia `/health` con `"device": "cuda"` sia una chiamata reale di inferenza su testo sintetico.

### Concorrenza, timeout, autenticazione e log dell'API

- [`Dockerfile`](../../../Dockerfile) (riga 77) avvia Gunicorn con `--workers 1 --threads 4 --timeout 600` senza `--preload`,
  ascoltando su `0.0.0.0:5005` (righe 62-63). Il vincolo `127.0.0.1:5005:5005` in [`docker-compose.yml`](../../../docker-compose.yml)
  (riga 27) vale solo sul daemon Docker locale e non si trasferisce a RunPod.
- [`src/app/guardrail_api.py`](../../../src/app/guardrail_api.py) (righe 473, 553) e
  [`docs/GUARDRAIL_API.md`](../../../docs/GUARDRAIL_API.md) (righe 169-171) impongono un lock non bloccante per processo su
  `POST /api/v1/analyses`: una seconda richiesta simultanea riceve `429` (`busy`). I 4 thread di Gunicorn non moltiplicano il
  throughput della guardrail, e aumentare i worker su GPU duplica il modello per ogni worker e aumenta l'uso di memoria GPU.
- Il secret `PII_API_TOKEN` protegge solo `POST /api/v1/analyses` ([`src/app/guardrail_api.py`](../../../src/app/guardrail_api.py),
  righe 22-24). Le route legacy in [`src/app/app.py`](../../../src/app/app.py) (`/analyze`, `/pdf`, `/preview`, `/pdf/preview`,
  `/doc/<id>/...`, `/settings`, `/tags`, `/config`, `/port-check`) non hanno autenticazione globale.
  [`docs/GUARDRAIL_API.md`](../../../docs/GUARDRAIL_API.md) (righe 173-185) richiede rete privata o un proxy autenticato con TLS
  davanti al servizio.
- Il budget cooperativo `PII_ANALYSIS_TIMEOUT_SECONDS` (default `60.0` s in
  [`src/app/guardrail_api.py`](../../../src/app/guardrail_api.py), righe 57-58) viene controllato solo ai confini di fase e non può
  interrompere una forward pass del modello o il parser nativo PyMuPDF; ogni proxy a monte deve avere un margine superiore al budget.
- [`Dockerfile`](../../../Dockerfile) (riga 77) abilita `--access-logfile - --error-logfile -`. Per requisito di sicurezza i log non
  devono mai contenere token, corpi richiesta/risposta o dizionari, e i test storici di isolamento locale non sostituiscono una
  verifica sui log effettivi di RunPod; i log di accesso su stdout finiscono nei log gestiti dal provider cloud e vanno ridotti o
  disattivati dietro proxy.

### Vincoli del codice per il training

- [`Dockerfile`](../../../Dockerfile) (riga 52) copia solo `src/app/` e [`.dockerignore`](../../../.dockerignore) (righe 6-7) esclude
  il resto della repository (`*`, `!src/app/`). L'immagine API non contiene gli script di training né la data pipeline; i dataset
  sotto `dataset/` sono gitignorati.
- [`src/training/train_pii.py`](../../../src/training/train_pii.py) richiede CUDA (`assert torch.cuda.is_available()`, riga 156) e
  usa `bf16=True` (riga 501). Alla riga 69 calcola `ROOT = Path(__file__).resolve().parents[2]` e risolve `dataset/`, `models/` ed
  `experiments/` sotto `ROOT`.
- I parametri effettivi in [`src/training/train_pii.py`](../../../src/training/train_pii.py) (righe 80-86, 108) sono `EPOCHS = 2`,
  `BATCH = 14`, `GRAD_ACCUM = 2` e `MODEL_VERSION = "1.3.0"`, diversi dal riepilogo storico in [`CLAUDE.md`](../../../CLAUDE.md)
  (`EPOCHS = 1`, `BATCH = 16`). Poiché l'API usa `v1.5.0`, un run completo richiede `--version` con un numero non ancora usato.
- [`src/training/train_pii.py`](../../../src/training/train_pii.py) offre `--type subset` (righe 125-147) per smoke test rapidi su
  `dataset/subsets/`. In modalità `--type full`, se `HF_TOKEN` è presente nell'ambiente, lo script carica automaticamente il modello
  su Hugging Face a fine run salvo passaggio di `--no-hf-push` (righe 113-131).
- Alla riga 539 `trainer.train()` è invocato senza `resume_from_checkpoint` e manca un'opzione CLI dedicata: anche salvando
  checkpoint intermedi su disco (`save_steps=EVAL_EVERY`, righe 511-513), un run interrotto non riparte da solo.

## Fatti verificati sulla piattaforma RunPod

- Le immagini custom sui Pod devono essere compilate per architettura `linux/amd64` e pubblicate su un container registry; per
  registry privati si configurano credenziali dedicate su RunPod (vedi
  [creazione di template personalizzati RunPod](https://docs.runpod.io/pods/templates/create-custom-template) e
  [credenziali container registry RunPod](https://docs.runpod.io/get-started/credentials)).
- RunPod Serverless distingue due modalità: gli endpoint queue-based richiedono un handler con SDK RunPod, mentre gli endpoint HTTP
  load-balancing inoltrano richieste HTTP direttamente a un server come Flask/Gunicorn senza imporre un handler custom (vedi
  [panoramica load balancing Serverless RunPod](https://docs.runpod.io/serverless/load-balancing/overview)).
- Le porte HTTP esposte tramite il proxy pubblico di RunPod vengono servite in HTTPS, richiedono il bind del processo su `0.0.0.0` e
  applicano un timeout fisso di 100 secondi per richiesta; inoltre, i Pod non supportano UDP sulle porte esposte (vedi
  [configurazione delle porte esposte su RunPod](https://docs.runpod.io/pods/configuration/expose-ports)). Alzare
  `PII_ANALYSIS_TIMEOUT_SECONDS` oltre tale soglia non evita il taglio a 100 s lato proxy.
- La pagina ufficiale di RunPod su SSH distingue la connessione SSH completa (che richiede `sshd` attivo nel container, IP pubblico
  e porta TCP 22 esposta) dalla connessione SSH di base, indicando esplicitamente che la modalità di base non supporta SCP e SFTP senza
  però escludere esplicitamente il port forwarding; per usare `ssh -L` si raccomanda di configurare l'SSH completo con `sshd`, IP
  pubblico e TCP 22, poiché il nostro [`Dockerfile`](../../../Dockerfile) non installa `openssh-server`. Non assumere che la
  connessione SSH di base offra le stesse funzioni; il supporto al forwarding va verificato (vedi
  [uso di SSH sui Pod RunPod](https://docs.runpod.io/pods/configuration/use-ssh)).
- I secret di RunPod sono valori write-only richiamati nei template tramite la sintassi `{{ RUNPOD_SECRET_pii_api_token }}` assegnata
  alla variabile d'ambiente `PII_API_TOKEN`, dove `pii_api_token` è il nome del secret e il prefisso `RUNPOD_SECRET_` fa parte della
  sintassi di riferimento del template (vedi [gestione dei secret nei template RunPod](https://docs.runpod.io/pods/templates/secrets)).
- I Network Volume vengono montati su `/workspace`, sopravvivono alla terminazione del Pod, continuano a generare costi di storage
  finché esistono e la loro cancellazione distrugge definitivamente i dati (vedi
  [network volume RunPod](https://docs.runpod.io/storage/network-volumes) e
  [tipi di storage dei Pod RunPod](https://docs.runpod.io/pods/storage/types)).

## Raccomandazioni non ancora testate per l'impostazione

1. Partire da un singolo Pod RunPod con soli dati sintetici, senza modificare il motore applicativo e rimandando la scelta Serverless
   (queue-based contro HTTP load-balancing) a dopo la validazione su Pod; non formuliamo stime di costi, sizing GPU o throughput
   prima di test empirici.
2. Affiancare un `Dockerfile.gpu` additivo per l'inferenza API su GPU lasciando intatto [`Dockerfile`](../../../Dockerfile) per la
   CPU, dopo aver verificato una combinazione compatibile tra immagine base, driver NVIDIA dell'host RunPod, `transformers` e wheel
   CUDA di PyTorch (senza assumere che esista `torch==2.13.0+cu128`; le wheel GPU includono già le librerie CUDA userspace e non
   vanno installati driver host nel container), fissando digest e dipendenze.
3. Non esporre l'intero server Flask/Gunicorn sul proxy pubblico RunPod: usare un tunnel SSH su TCP 22 (con immagine/template dotato
   di `sshd` e IP pubblico, senza esporre la porta 5005) o un reverse proxy autenticato (come il pattern Caddy in
   [`substrate/traces/operations/2026-10-07-envai-pii-vpn-test-environment.md`](../operations/2026-10-07-envai-pii-vpn-test-environment.md),
   utile come riferimento architetturale per bloccare le route legacy e spegnere gli access log, ma non come verifica su RunPod); una
   VPN nel container richiederebbe verifica poiché RunPod non supporta UDP sulle porte esposte.
4. Mappare `PII_API_TOKEN` a `{{ RUNPOD_SECRET_pii_api_token }}` nel template senza includere `.env` nell'immagine (e impostare
   `HF_TOKEN` solo se necessario); per il training, clonare la repository sotto `/workspace` su Network Volume (o montare/linkare
   `dataset/`, `models/`, `experiments/` e cache Hugging Face), lanciare prima `--type subset`, passare `--no-hf-push` e `--version`
   esplicita nei run completi, e aggiungere il supporto a `resume_from_checkpoint` prima di usare istanze spot/interrompibili.
5. Dopo il primo test manuale, valutare workflow CI per pubblicare l'immagine `linux/amd64` su GHCR o registry privato con tag/digest
   fissati, un template `.env` di deploy e uno script di smoke test remoto; sul piano GDPR, ricordare che l'anonimizzazione in cloud
   invia **PII non ancora anonimizzate, disponibili al processo che gira sul provider** prima del mascheramento (tunnel e TLS
   proteggono solo il transito), quindi vanno usati solo dati sintetici finché non sono verificati regione UE, DPA, accessi e
   retention.

## Domanda aperta per il prossimo passo

Per trasformare questa analisi in un piano operativo mirato, quale carico volete provare per primo su RunPod: il servizio API di
inferenza (`POST /api/v1/analyses`), il training del modello (`src/training/train_pii.py`) o entrambi?
