# Servizio API su GPU con RunPod

Questa guida descrive come costruire l'immagine container GPU dal file `Dockerfile.gpu`, pubblicarla manualmente su GitHub Container Registry (GHCR) ed eseguire il **servizio HTTP API** di `envai-pii` su un GPU Pod di RunPod tramite `src/app/cloud_service.py`. Il flusso riguarda esclusivamente il servizio di inferenza (un normale Pod HTTP, non il training e non un handler RunPod Serverless).

> [!note]
> Build locale completata il 2026-10-22, incluso il salvataggio finale dell'immagine `linux/amd64`: circa 6,14 GiB non compressi. I 575 test nel container passano senza skip; il modello incluso e' stato caricato offline e provato con un'analisi sintetica su CPU, separatamente dall'entry point cloud che richiede CUDA. Il comando Gunicorn predefinito termina con codice `3` senza token o senza GPU, come previsto.

> [!warning]
> Storico verificato al 2026-10-25, prima dello stop dell'utente: il Pod esistente `2glj7taobhnhvg` e' stato aggiornato sul posto all'immagine `v1.0.0-dev.3` (digest `sha256:2b0324fe6e15...`) con un solo `PATCH` nativo dell'immagine e un solo riavvio del container, senza stop/start e senza nuove risorse. Sul Pod reale il forward su GPU ora **funziona per i casi sintetici verificati**. Lo storico resta valido: l'immagine `v1.0.0-dev.2` (digest `a0b25f412c3b...`) non aveva il compilatore C e la prima richiesta autenticata rispondeva `500` (`RuntimeError: Failed to find C compiler`, driver C di Triton, `bmm_outer_product` nel matmul rotary di ModernBERT) pur con `/health` a `200`.
>
> Misure storiche del 2026-10-25, prima dello stop successivo dell'utente: Pod `RUNNING`, A40 x1, 50 GB di memoria, 9 vCPU, EU-SE-1, `0.59` USD/h da lettura fresca, avviato alle `2026-10-24T23:43:56Z`. Confronto completo con lo stato precedente: variabili d'ambiente, argomenti, cloud, costo, data center, disco 20 GB, mount, GPU, registry, rete globale, nome, porta `5005/http` e template invariati. Nessuna rotazione di credenziali e nessuna copia della chiave PII. Il container e' ripartito alle 23:46:23Z; i log mostrano `Listening at: http://0.0.0.0:5005` (gthread), il caricamento del modello su GPU e `Modello pronto.` alle 23:46:30Z. Nessun fallback su CPU, pin ML invariati.
>
> Risultati sul proxy `https://2glj7taobhnhvg-5005.proxy.runpod.net` con `src/app/smoke_cloud.py` completo (chiave letta dalla collezione Postman privata in memoria, mai stampata ne' passata da argv): 6 su 6 superati in 2,52 s totali (misura, non benchmark): `/health` caricato su `cuda`; `POST /api/v1/analyses` senza token `401`; `GET` legacy `/settings` senza token `401`; JSON con email `200` e delta di segnaposto validato; riuso del seed `200` con delta `{}`; multipart TXT con aggregati `200`. Casi aggiuntivi, tutti con dati sintetici: JSON con email e IBAN, categorie predefinite (tutte), `200` in 0,51 s con entrambi mascherati; PDF sintetico reale su `POST /api/v1/analyses` (campo `files`, tipo File) `200` in 0,32 s con estrazione e maschere validate; `POST /pdf` legacy (campo `file`) `200` in 0,34 s, PDF valido aperto in locale, email e IBAN originali assenti. Il vecchio `500` e' risolto per questi casi sintetici verificati su GPU reale; non e' una garanzia di accuratezza, ne' di copertura di tutti i PDF o del GDPR.
>
> Stato corrente dell'artefatto: la concorrenza limitata (4 analisi attive, coda FIFO di 4 richieste, attesa massima 5 s) e' ora **pubblicata** nell'immagine `v1.0.0-dev.4` (commit sorgente `0f161021b03b630ecf03556b6bf3cfe2f074cf75`, digest `sha256:c71a392411ab...`), con build, scansione Trivy e tag verificati da CI: vedi [`v1.0.0-dev.4`](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.4) e il [publisher docker-publish](https://github.com/digitalygo/envai-pii/actions/runs/40194544097). **Distribuzione e concorrenza su hardware reale restano in sospeso**: `v1.0.0-dev.4` non e' stata applicata al Pod di test, che resta fermo secondo quanto riferito dall'utente, e la nuova concorrenza non e' stata provata su GPU. I 6 test funzionali e i casi PDF su GPU reale con `v1.0.0-dev.3` restano **solo storici**. Il sorgente ammette 4 analisi attive e 4 in coda FIFO per un massimo di 5 s; due thread proprietari separati gestiscono modello e PDF. I forward del modello restano serializzati: non sono quattro forward GPU paralleli ne' una promessa di throughput quadruplicato. Thread Gunicorn predefiniti: 10. Nessun nuovo benchmark di carico e' stato eseguito.
>
> Stato del Pod: l'utente ha riferito in seguito di averlo fermato (`STOPPED`). Durante questa fase sorgente lo stato del control plane non e' stato interrogato e nessun riavvio e' stato eseguito, quindi lo stato attuale non e' verificato qui. Il valore `0.59` USD/h e' solo un'osservazione storica di quella lettura, non indica fatturazione o prezzo attuali. I parametri di test (senza segreti) sono in un file privato fuori dal repository: il file riferito a `v1.0.0-dev.3` descrive l'impostazione storica e resta invariato finche' `v1.0.0-dev.4` non viene distribuita. Nessuna lettura, aggiornamento, riavvio o avvio del Pod e' stato eseguito in questa fase.
>
> La build non richiede una GPU. La release `v1.0.0-dev.4` ha completato build, scansione e tag ed e' l'immagine candidata corrente. Inferenza NVIDIA e proxy RunPod sono stati verificati con la precedente `v1.0.0-dev.3`, non ancora con `v1.0.0-dev.4`. Il gate Trivy di v4 ha riportato `0 blocker(s), 247 unfixed ignored`: restano vulnerabilita' residue note, non zero, senza segreti ne' `HIGH`/`CRITICAL` correggibili, con policy invariata. Digest e dettagli sono in [automazione CI e GHCR](ci-release.md). Le immagini locali di test vengono rimosse dopo la verifica. Evidenze e limiti sono nel [registro della verifica](../substrate/traces/operations/2026-10-21-runpod-service.md#update-2026-10-22-local-image-build-and-packaging-verification).

## Immagine GPU e requisiti host

- **Immagine base fissata per digest**: `python:3.11.17-slim-bookworm@sha256:8fb0b110b022c70cbe09d3ff1fb313654f31f9c814abb0d48180af56d906a199` (manifest `linux/amd64`).
- **Dipendenze ML pinnate**: `src/app/requirements-gpu.txt` mantiene le stesse versioni ML dell'immagine CPU (`torch==2.13.0+cu126` dall'indice ufficiale PyTorch `cu126` per la ricetta corrente; le immagini pubblicate `dev.3`, `dev.4` e `dev.6` restano `cu130`, come le loro misure storiche, e `transformers==5.14.1`), insieme a `tokenizers==0.22.2`, `safetensors==0.8.0`, `numpy==2.4.6`, `huggingface-hub==1.33.0`, `flask==3.1.3`, `pymupdf==1.28.2` e `gunicorn==26.2.0`. La toolchain di build e' fissata a `setuptools==80.10.2`, che vendorizza `jaraco.context 6.1.0` e `wheel 0.46.3` e ha ruolo di sicurezza: sostituisce la base `79.0.1`, i cui vendor vulnerabili hanno bloccato il gate. Il riferimento a `cu128` presente in `CLAUDE.md` e `requirements.txt` riguarda il training locale su Windows (RTX 5060 Ti), non questa immagine container.
- **Driver NVIDIA sull'host e dipendenze CUDA userspace**: le dipendenze di PyTorch `cu126` installano nell'immagine i pacchetti userspace CUDA, ma non installano alcun driver del kernel NVIDIA sull'host. Per la ricetta corrente (sorgente `cu126`, non ancora pubblicata come nuova immagine) l'host RunPod deve esporre un driver NVIDIA compatibile con **CUDA 12.6**; le immagini gia' pubblicate `dev.3`, `dev.4` e `dev.6` e i Pod esistenti sono `cu130` e richiedono ancora CUDA 13. Nessuna azione RunPod e' stata eseguita per questo cambio; selezionare il filtro CUDA appropriato nella scelta del Pod. Non e' stato eseguito un benchmark di VRAM per questa immagine: misurare e dimensionare l'occupazione di memoria direttamente sulla GPU scelta per il Pod.
- **Modello integrato e flag offline Hugging Face**: durante la build viene scaricato lo snapshot `rizzoaiacademy/rizzo-pii-0.3B` alla revisione `v1.5.0` in `/app/models/rizzo-pii-0.3B-v1.5.0` (`PII_MODEL_DIR`). A runtime sono attive `HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1`: queste variabili disabilitano i download di rete delle librerie Hugging Face e Transformers all'avvio (i pesi vengono letti solo dalla directory locale), ma non costituiscono un firewall di egress a livello di container o di rete. L'immagine non richiede un volume per il modello e non include strumenti di training o l'SDK RunPod.

## Pubblicazione su GHCR (automatica e manuale)

### Pubblicazione automatica tramite GitHub Actions (percorso principale)

Il repository include i workflow `.github/workflows/release.yml`, `.github/workflows/docker-publish.yml` e `.github/workflows/trigger-build.yml`: ad ogni release pubblicata sui rami `dev`, `alpha`, `beta` o `main`, GitHub Actions costruisce `Dockerfile.gpu` per `linux/amd64` sull'esatto commit della release, carica l'immagine su `ghcr.io/digitalygo/envai-pii` solo per digest, esegue la scansione remota Trivy (`vuln,secret`) sul digest e promuove i tag di versione e canale solo se il gate di sicurezza passa. Consultare la [guida all'automazione CI, release e GHCR](ci-release.md) per la configurazione di `RELEASE_TOKEN`, la regola di bootstrap con `[skip ci]` e i permessi del pacchetto GHCR.

### Build e pubblicazione manuale (alternativa operativa)

Questi comandi non applicano il gate Trivy della pipeline automatica: usarli solo per immagini di prova, senza creare o spostare i tag di release o di canale. Per distribuire una release verificata usare la catena GitHub Actions descritta sopra.

Eseguire la build dalla root del repository (cosi' `.dockerignore` limita il contesto a `src/app`). La build non richiede una GPU locale, ma richiede spazio disco sufficiente per il commit finale dei layer di PyTorch e di `model.safetensors`. Il valore di circa 6,14 GiB per l'immagine locale non compressa e' una misura storica dell'immagine `cu130`, non la dimensione della nuova ricetta `cu126`, che non e' stata misurata.

Usare Podman come runtime predefinito passando `--format docker`: Podman 5.4.2 genera per default immagini in formato OCI e scarta l'istruzione `HEALTHCHECK` con un avviso, mentre `--format docker` produce un manifest Docker v2 che conserva `HEALTHCHECK` nei metadati dell'immagine. Se Podman non e' installato e si usa Docker come fallback, omettere `--format docker` perche' `docker build` non accetta quell'opzione e preserva `HEALTHCHECK` in modo nativo (`docker build --platform linux/amd64 -f Dockerfile.gpu -t "$IMAGE" .`). La pubblicazione manuale su GHCR richiede un token con permesso `write:packages`:

```bash
IMAGE_TAG="runpod-20261022-01"
IMAGE="ghcr.io/digitalygo/envai-pii:${IMAGE_TAG}"

podman build --format docker --platform linux/amd64 -f Dockerfile.gpu -t "$IMAGE" .
podman login ghcr.io -u "$GHCR_USER"
DIGEST_FILE=$(mktemp)
podman push --digestfile "$DIGEST_FILE" "$IMAGE"
read -r IMAGE_DIGEST < "$DIGEST_FILE"
rm -f "$DIGEST_FILE"
printf '%s@%s\n' "ghcr.io/digitalygo/envai-pii" "$IMAGE_DIGEST"
```

- Alternativa manuale: usare un tag esplicito e univoco nella forma `ghcr.io/digitalygo/envai-pii:runpod-<unique-tag>` solo se non si usa una versione di release approvata. L'univocita' del tag e' una convenzione operativa e non un vincolo di immutabilita' applicato automaticamente dal registro, quindi per il deploy del Pod preferire il riferimento fissato per digest `ghcr.io/digitalygo/envai-pii@sha256:...`.
- Ricavare il digest dal file scritto da `podman push --digestfile` e non da `podman inspect` sull'immagine locale, perche' l'ispezione locale puo' restituire un valore vuoto o calcolato su una serializzazione diversa rispetto al manifest pubblicato sul registro.
- Non passare mai il token GHCR negli argomenti della riga di comando: `podman login` richiede la password o il token in modo interattivo sul prompt.
- Se l'immagine su GHCR e' privata, registrare le credenziali di pull nella sezione Container Registry Auth di RunPod prima di creare il Pod.

## Configurazione del Pod RunPod

Configurare un normale **GPU Pod** (non un worker Serverless) su un host con driver compatibile con la CUDA richiesta dall'immagine scelta (CUDA 13 per il digest `dev.4` dell'esempio, CUDA 12.6 per le nuove immagini `cu126` una volta pubblicate):

1. **Template e immagine**: indicare preferibilmente il riferimento per digest candidato `ghcr.io/digitalygo/envai-pii@sha256:c71a392411ab14aed2d4b28bb8e84e5e727f32df6e24e5238b11715d3fbaf9ef` (build `v1.0.0-dev.4`, tag `1.0.0-dev.4`, `dev`, `1.0.0-dev.4-0f161021b03b`), e selezionare le credenziali del registro se il pacchetto GHCR e' privato. I tag non aggiornano da soli un Pod o un template esistente: serve un'applicazione esplicita e autorizzata del nuovo riferimento. Il digest storico `v1.0.0-dev.3` (`sha256:2b0324fe6e154eadc270b1accf157519abb5cac1663453579d5f76e1cf2f2f13`) e' quello provato su GPU reale.
2. **Secret e variabili d'ambiente**: nella sezione Secrets di RunPod creare un segreto con nome `pii_api_token`. Nel template del Pod mappare la variabile `PII_API_TOKEN` al segreto usando la sintassi `{{ RUNPOD_SECRET_pii_api_token }}`. Le variabili `PII_HOST=0.0.0.0` e `PII_PORT=5005` sono gia' impostate nell'immagine; per il budget cooperativo dell'endpoint guardrail e' consigliato mantenere o esplicitare `PII_ANALYSIS_TIMEOUT_SECONDS=60`.
3. **Esposizione della porta**: esporre la porta HTTP `5005` esclusivamente tramite il proxy HTTPS di RunPod (`https://<pod-id>-5005.proxy.runpod.net`). Non esporre mai la porta `5005` come porta TCP pubblica diretta in chiaro. L'immagine non installa `openssh-server`: l'accesso SSH al container e i tunnel SSH automatici non sono disponibili a meno di usare un template esterno abilitato a SSH o un proxy dedicato.
4. **Volumi opzionali**: non serve alcun volume per i pesi del modello e non bisogna mai montare un volume su `/app/models`, perche' oscurerebbe i pesi integrati nell'immagine. Il mount predefinito di un Network Volume su RunPod (`/workspace`) **non** persiste `/home/app` (dove le route legacy salvano `~/.local/share/rizzo-pii/prefs.json` e `config.json`): senza un mount o una mappatura personalizzata verso `/home/app`, le preferenze legacy restano effimere nel filesystem del container (l'endpoint `/api/v1/analyses` e' invece stateless e non usa `prefs.json`).

## Architettura runtime, autenticazione e limiti operativi

- **Fail-closed all'avvio e nessun fallback CPU**: la factory `cloud_service:create_app()` verifica che `PII_API_TOKEN` sia configurato e non vuoto, poi esegue e sincronizza un piccolo kernel su `cuda` prima di importare `app.py`. Dopo l'import controlla che la pipeline sia caricata sulla GPU (`device == 0`). Se il token manca, CUDA non risponde o il modello non e' su GPU, il worker termina immediatamente senza ripiegare sulla CPU. Gli entry point locali (`src/app/app.py`, `src/app/serve.py` e il `Dockerfile` CPU) non subiscono modifiche.
- **Modalita' di autenticazione**: il comportamento predefinito qui descritto, con `PII_API_TOKEN` e Bearer locale, resta invariato. L'opt-in `PII_AUTH_MODE=upstream` (valore esatto, solo da ambiente del server) esiste per provider che autenticano a monte, vedi [guida Verda](verda-service.md), ma e' **non sicuro** sul proxy pubblico di RunPod, che non autentica i chiamanti: non impostarlo su un Pod RunPod.
- **Autenticazione globale sul proxy pubblico**: l'URL `https://<pod-id>-5005.proxy.runpod.net` e' raggiungibile pubblicamente su internet. Il middleware WSGI `CloudService` protegge quindi **ogni route** (incluse `/api/v1/analyses` e tutte le route legacy `/analyze`, `/pdf`, `/pdf/preview`, `/preview`, `/settings`, `/config`, `/port-check` e `/doc/...`) richiedendo `Authorization: Bearer <PII_API_TOKEN>` prima che Flask legga la richiesta. Tutte le risposte ricevono `Cache-Control: no-store` e i record di errore del logger Flask vengono sanificati.
- **Probe di salute pubbliche**: solo `GET` e `HEAD` su `/health` e `/healthz` sono accessibili senza Bearer token e restituiscono un JSON minimale (`{"status":"ok","model_loaded":true,"device":"cuda"}` con codice `200` quando token, modello e GPU sono pronti, altrimenti `503` con `"status":"loading"`).
- **Modello single-tenant**: tutte le chiamate autenticate condividono lo stesso `PII_API_TOKEN`. Il servizio e' pensato per un singolo chiamante o backend fidato, non per l'isolamento multi-utente: le preferenze legacy (`/settings`, `/config`) e la cache LRU in memoria dei PDF (`_DOCS`) sono condivise nell'unico processo.
- **Gunicorn, ammissione guardrail e timeout di rete**: il comando carica `--config src/app/gunicorn_config.py` (un solo worker `gthread`, senza `--preload`, thread = analisi attive + coda + 2, predefinito 10) e mantiene `--timeout 600 --graceful-timeout 30`, con una sola copia del modello in VRAM. `POST /api/v1/analyses` ammette per processo fino a `PII_MAX_CONCURRENT_ANALYSES` analisi attive (predefinito 4, da 1 a 16) e una coda FIFO di `PII_MAX_QUEUED_ANALYSES` richieste (predefinito 4, da 0 a 32, 0 la disabilita) che attendono al piu' `PII_QUEUE_TIMEOUT_SECONDS` (predefinito 5, massimo 30). Valori non validi tornano al predefinito, quelli sopra il massimo sono ridotti, e nessun campo client li modifica. Coda piena o disabilitata e attesa scaduta rispondono `429 busy` senza leggere il body; l'attesa in coda non riduce il budget di analisi da 60 s, che parte dopo la lettura del body. Le chiamate native PDF e modello usano due thread dedicati con un solo proprietario: il forward del modello resta serializzato di proposito, quindi 4 analisi attive non sono 4 forward GPU paralleli ne' 4 volte il throughput. Il parametro `--timeout 600` e' l'heartbeat di liveness del worker Gunicorn, non una scadenza hard per singola richiesta nei worker `gthread`. Inoltre il proxy HTTPS di RunPod (Cloudflare) impone un timeout di circa 100 secondi per richiesta HTTP: anche con `PII_ANALYSIS_TIMEOUT_SECONDS=60`, il tempo di upload sommato al parsing PDF nativo o a un'inferenza lunga puo' superare i 100 secondi e produrre un errore `524` dal proxy. Il proxy ha un limite fisso che ne' il timeout del client ne' l'heartbeat 600 possono alzare: contano coda, upload, budget e margine nativo. Aumentare il timeout del client non modifica ne' il budget cooperativo del server ne' il limite del proxy RunPod.

## Verifica con lo smoke test sintetico

Quando il Pod risulta pronto, eseguire da locale `src/app/smoke_cloud.py` caricando il token nella shell senza inserirlo in chiaro nei comandi o nella cronologia:

```bash
set +o history
read -rsp "PII_API_TOKEN: " PII_API_TOKEN && echo
export PII_API_TOKEN
set -o history

RUNPOD_POD_ID="inserisci-id-pod"
python src/app/smoke_cloud.py --url "https://${RUNPOD_POD_ID}-5005.proxy.runpod.net"
```

Lo script usa solo la libreria standard, non effettua retry, non segue redirect e non stampa mai token, URL o payload nei messaggi di errore. Esegue in ordine sei verifiche:

1. `GET /health` senza token: attende `200`, `status == "ok"`, `model_loaded == true` e `device == "cuda"` (`PASS health`).
2. `POST /api/v1/analyses` senza header Bearer: attende `401` (`PASS unauthenticated analyses`).
3. `GET /settings` senza header Bearer: attende `401` (`PASS unauthenticated settings`).
4. `POST /api/v1/analyses` JSON con testo sintetico e `categories: ["EMAIL"]`: verifica placeholder `[EMAIL_1]` e `dictionary_delta` (`PASS json email`).
5. `POST /api/v1/analyses` JSON con seed `{"[EMAIL_1]": "runpod-smoke@example.com"}`: verifica il riuso di `[EMAIL_1]` e il delta vuoto (`PASS json seed reuse`).
6. `POST /api/v1/analyses` `multipart/form-data` con un file `.txt` sintetico, campo `text` e `categories`: verifica `file_1`, `text` e il delta aggregato (`PASS multipart aggregate`), chiudendo con `PASS remote synthetic smoke`.

Lo smoke test non invia PDF binari e non e' un benchmark di accuratezza del modello. Il test sul Pod GPU reale del 2026-10-25 ha integrato PDF sintetici su `/api/v1/analyses` e `/pdf` con esito positivo (vedi nota iniziale).

## Risoluzione dei problemi

- **`401 unauthorized` sulle route legacy (`/analyze`, `/pdf`, `/settings`, `/config`)**: comportamento previsto sul servizio cloud; aggiungere l'header `Authorization: Bearer <PII_API_TOKEN>`.
- **`503 unavailable` su `/health` rispetto a `503` sui PDF della guardrail**: se `/health` risponde `503` (o il container si riavvia in loop), `PII_API_TOKEN` non e' valorizzato oppure il modello non e' caricato su GPU. Se invece `/health` risponde `200` ma `POST /api/v1/analyses` restituisce `503` solo quando riceve un PDF, sono falliti i controlli nativi di privacy di MuPDF (le richieste JSON, `.txt` e `.md` continuano a funzionare perche' `/health` non controlla il sottosistema PDF).
- **`RuntimeError: CUDA is unavailable.` nei log di avvio**: l'host RunPod ha un driver NVIDIA incompatibile con la CUDA dell'immagine (CUDA 12.6 per la ricetta `cu126` corrente, CUDA 13 per le immagini pubblicate `cu130` come `dev.4` e `dev.6`) o il runtime GPU non e' attivo; terminare il Pod e crearne uno su un host compatibile.
- **`500 internal_error` sulla prima richiesta autenticata con `/health` a `200` e `RuntimeError: Failed to find C compiler` (Triton)**: l'immagine non contiene un compilatore C, necessario a Triton per compilare a runtime il kernel `bmm_outer_product` nel matmul rotary di ModernBERT. La correzione, verificata su GPU reale con `v1.0.0-dev.3`, e' una nuova immagine costruita da `Dockerfile.gpu` con `gcc` e `libc6-dev`: la base Python ufficiale ha gia' gli header, quindi non serve `python3-dev` di Debian. Non installare il compilatore a runtime con l'utente non privilegiato `app`, non impostare `CC` verso un finto compilatore e non disabilitare Triton: `CC` non sostituisce il compilatore. Per riprodurre l'errore sul Pod usare il [comando diagnostico](runpod-diagnostic-command.md).
- **Errore di caricamento del modello o pesi non trovati**: con `HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1` il servizio non scarica nulla da Hugging Face a runtime. Verificare di non aver sovrascritto `PII_MODEL_DIR` e di non aver montato volumi su `/app/models`.

## Privacy, licenza e controllo dei costi

- **Dati personali verso infrastruttura cloud**: inviare documenti reali a RunPod comporta il transito di PII non ancora mascherata verso un provider cloud esterno prima che avvenga l'anonimizzazione. Utilizzare **esclusivamente dati sintetici** finche' non sono formalmente approvati DPA, regione geografica del Pod e policy di conservazione. Il container disabilita gli access log di Gunicorn (`--access-logfile /dev/null`) e filtra i log applicativi, ma eventuali log di accesso, telemetria e metadati del proxy o dell'infrastruttura RunPod restano sotto il controllo del provider.
- Il filtro applicativo copre il logger Flask, non il parser HTTP di Gunicorn: richieste malformate possono ancora far comparire il percorso e la query negli error log del server, prima che intervenga il middleware. Non inserire token o dati personali negli URL; usare il body per i documenti e l'header `Authorization` per il token. Non viene garantita l'assenza totale di log dell'infrastruttura HTTP.
- **Obblighi AGPL-3.0 per PyMuPDF**: il container include PyMuPDF per la gestione dei PDF. Quando il servizio e' accessibile in rete da altri utenti, la clausola di rete della licenza AGPL-3.0 richiede di offrire il codice sorgente corrispondente; consultare [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md) e la sezione [licenza del README](../README.md#license-and-attribution).
- **Arresto e terminazione del Pod**: RunPod non arresta ne' elimina automaticamente i Pod dopo una prova. La fatturazione del calcolo GPU e quella dello storage seguono regole distinte: verificare nella console e nella documentazione del provider quali costi restano attivi quando un Pod viene fermato (`Stop`) rispetto a quando viene terminato (`Terminate`). Eventuali Network Volume continuano a essere addebitati finche' non vengono eliminati esplicitamente dopo il backup dei dati necessari.

## Riferimenti esterni

- [Documentazione RunPod sull'esposizione delle porte HTTP](https://docs.runpod.io/pods/configuration/expose-ports)
- [Documentazione RunPod sulla gestione dei Secrets](https://docs.runpod.io/pods/templates/secrets)
- [Documentazione RunPod sulle credenziali dei container registry](https://docs.runpod.io/get-started/credentials)
- [Documentazione RunPod sui Network Volumes](https://docs.runpod.io/storage/network-volumes)
- [Indice e versioni ufficiali di PyTorch per CUDA](https://pytorch.org/get-started/previous-versions/)
