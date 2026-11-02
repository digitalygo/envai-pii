# Avvio dei worker GPU e batching lato server

Questa guida descrive la configurazione di avvio dei processi Gunicorn, il batching dei chunk lato server e la verifica opzionale di warmup per ciascun worker nel sorgente ordinario dell'immagine GPU (`Dockerfile.gpu`, `src/app/gunicorn_config.py`, `src/app/gpu_worker_startup.py`, `src/app/model_batching.py` e `src/app/cloud_service.py`). I contratti HTTP e il formato delle risposte restano quelli descritti in [GUARDRAIL_API.md](GUARDRAIL_API.md).

**Stato operativo (`2026-11-02`, tentativo 5):** otto worker CUDA/float32 a B8 verificati sul percorso ordinario, salute/auth e 72/72 richieste valide. Il servizio resta healthy e abilitato; zero repliche per inattivita' e scale-to-zero naturale provato. Sorgente, default e immagine `v1.0.0-dev.8` invariati. Vedi il [report della messa online](../substrate/traces/reports/2026-11-02-verda-n8-b8-online.md).

## Architettura dei processi nell'immagine GPU

L'immagine GPU avvia Gunicorn con la factory `cloud_service:create_app()` e la configurazione `src/app/gunicorn_config.py`:

- Ogni processo worker richiede un dispositivo CUDA attivo (`cuda:0`) e carica in modo indipendente una propria copia in memoria GPU dei pesi `rizzo-pii-0.3B` `v1.5.0` in `float32`.
- `preload_app` è impostato a `False` (nessun `--preload`), quindi l'inizializzazione di PyTorch, il controllo del token o della modalità di autenticazione e il caricamento del modello avvengono dentro ciascun worker prima che il processo accetti connessioni.
- Ogni worker usa la classe `gthread` con un numero di thread derivato dalla configurazione di ammissione (`resolve_admission_config()`): `max_concurrent_analyses + max_queued_analyses + 2`.
- Il flag CLI `--workers 1` è stato rimosso solo dal `CMD` di `Dockerfile.gpu` per consentire a `gunicorn_config.py` di risolvere il numero di worker dall'ambiente.
- In `Dockerfile` (immagine CPU) il `CMD` mantiene `--workers 1` esplicito da riga di comando, che ha precedenza su `gunicorn_config.py`; `PII_GUNICORN_WORKERS` non governa quindi il numero di processi dell'immagine CPU.
- I pin delle dipendenze, i pesi `v1.5.0`, la precisione `float32`, il formato wire dell'API e i valori predefiniti (`1` worker e batch size `1`) restano invariati. Non viene introdotto alcun motore asincrono.

## Variabili d'ambiente di avvio e batching

| Variabile | Valori ammessi | Predefinito e fallback | Comportamento |
| --- | --- | --- | --- |
| `PII_GUNICORN_WORKERS` | Stringhe canoniche da `"1"` a `"8"` (spazi iniziali e finali ignorati tramite trim) | `1` se assente, vuota o fuori dall'insieme `1..8` | Imposta il numero di processi worker Gunicorn quando il comando di avvio non forza `--workers` via CLI (come avviene in `Dockerfile.gpu`). |
| `PII_MODEL_BATCH_SIZE` | Stringhe canoniche `"1"`, `"4"`, `"8"`, `"16"` (con trim degli spazi) | `1` se assente, booleana, malformata o non supportata | Risolve una sola volta all'avvio del server la dimensione dei gruppi di chunk passati alla pipeline token-classification in v1. Il raggruppamento resta locale alla singola invocazione del rilevatore e non attraversa mai richieste diverse, file diversi o intervalli protetti. |
| `PII_VERIFY_MODEL_STARTUP` | Stringa esatta `"1"` per attivare la verifica | Disattivata se assente o diversa da `"1"` | Esegue in `post_worker_init` una prova di inferenza reale e la validazione dei tensori sul worker corrente prima che quel processo entri nel proprio ciclo `accept()`. |

### Semantica del batching lato server

All'avvio del worker, `src/app/app.py` risolve una sola volta `MODEL_BATCH_SIZE` dall'ambiente del server tramite l'helper `model_batching.resolve_model_batch_size()` (`src/app/model_batching.py` fornisce la funzione di risoluzione e gli helper di raggruppamento e normalizzazione senza congelare stato in proprio):

- Quando `PII_MODEL_BATCH_SIZE` vale `1`, il rilevatore invoca la pipeline un chunk alla volta senza passare un argomento `batch_size` esplicito.
- Quando `PII_MODEL_BATCH_SIZE` vale `4`, `8` o `16`, i chunk consecutivi di una singola chiamata a `_guardrail_detect` vengono suddivisi in gruppi di dimensione massima pari a `batch_size` e passati alla pipeline con `batch_size` esplicito.
- `normalize_batch_results` valida che la pipeline restituisca esattamente una riga di entità per ciascun chunk di input e che ogni span ricada entro i limiti del chunk corrispondente, fallendo chiuso (`ModelBatchResultError`) in caso di risultati piatti, mancanti o malformati.
- Nessun batch unisce chunk appartenenti a richieste HTTP distinte, documenti diversi di una richiesta multi-file o segmenti separati da intervalli protetti.

## Verifica di avvio per singolo worker e limiti di `/health`

Quando `PII_VERIFY_MODEL_STARTUP=1` è attivo, l'hook `post_worker_init` (`src/app/gpu_worker_startup.py`) esegue un controllo sul singolo processo worker prima che inizi a servire traffico:

1. Verifica che `module.device == 0` e ispeziona tutti i parametri (`require_floating=True`) e i buffer del modello, confermando che risiedano su `cuda:0` e che ogni tensore in virgola mobile abbia dtype `torch.float32`.
2. Costruisce un testo sintetico fisso composto da 6252 ripetizioni della parola `"neutral"`, che il chunker ordinario suddivide esattamente in 63 chunk.
3. Invoca il percorso reale del rilevatore ordinario (`module._guardrail_detect`, che esegue l'inferenza su `MODEL_LANE` sia per gli input di testo sia per il testo estratto dai PDF) avvolgendo temporaneamente `module.nlp` in un contatore e ripristinando sempre la pipeline originale nel blocco `finally`.
4. Sincronizza CUDA (`torch.cuda.synchronize()`) entro una scadenza monotona di 60 secondi e controlla le dimensioni dei batch osservati. Con `PII_MODEL_BATCH_SIZE=8`, i 63 chunk producono esattamente 8 chiamate alla pipeline, somma degli input pari a 63, dimensione massima del batch pari a 8 e batch di coda finale pari a 7.
5. In caso di successo emette sul log del worker una riga `PII_WORKER_READY` con metadati JSON strutturati (`event`, `pid`, `workers`, `model_device`, `model_dtype`, `parameter_bytes`, `buffer_bytes`, `model_batch_size`, `warmup_chunk_count`, `warmup_call_count`, `warmup_input_count`, `warmup_max_batch_size`, `warmup_tail_batch_size`).
6. Se qualsiasi controllo fallisce o supera la scadenza, emette `PII_WORKER_STARTUP_FAILED` e solleva `RuntimeError("worker startup proof failed")`, terminando il worker con errore generico senza esporre dettagli interni.

I metadati di log contengono esclusivamente contatori, dimensioni in byte, PID e parametri numerici di configurazione. Non includono mai testi di input, output del modello, entità estratte, header HTTP, UUID di richiesta o valori segreti.

La verifica avviene per singolo worker e non costituisce una barriera globale sull'intero pool di Gunicorn: ogni worker esegue il warmup prima del proprio ciclo di accettazione, ma una risposta `200 OK` di `/health` o `/healthz` proviene da un singolo worker già pronto e non dimostra che tutti gli 8 processi abbiano completato l'avvio. Per verificare dall'esterno che un pool a 8 worker sia interamente inizializzato, occorre contare 8 righe `PII_WORKER_READY` con `pid` distinti nei log del container.

## Autenticazione e configurazione runtime di esempio

L'immagine GPU non incorpora mai `PII_API_TOKEN` né `PII_AUTH_MODE`. L'autenticazione locale tramite header `Authorization: Bearer <token>` rimane attiva per impostazione predefinita e richiede `PII_API_TOKEN` a runtime. Il valore esatto `PII_AUTH_MODE=upstream` disattiva il controllo locale del token solo negli ambienti in cui il proxy o il provider a monte autentica già ogni singola rotta esposta.

Esempio delle sole variabili non segrete per avviare 8 worker GPU con batch size 8 e verifica di avvio per worker:

```bash
export PII_GUNICORN_WORKERS=8
export PII_MODEL_BATCH_SIZE=8
export PII_VERIFY_MODEL_STARTUP=1
```

## Requisiti dell'immagine container e stato del rollout del 2026-11-01

Il supporto a `PII_GUNICORN_WORKERS`, `PII_MODEL_BATCH_SIZE` e `PII_VERIFY_MODEL_STARTUP` richiede un'immagine GPU costruita a partire dal sorgente che include `src/app/gpu_worker_startup.py`, `src/app/model_batching.py` e il `CMD` aggiornato in `Dockerfile.gpu`. Impostare queste variabili d'ambiente su un'immagine precedente (ad esempio `1.0.0-dev.7`, distinta dalla versione `v1.5.0` dei pesi del modello) non attiva il batching né il pool multi-worker, perché quell'immagine non contiene i moduli corrispondenti e forza `--workers 1` nella riga di comando di Gunicorn. Entrambe le immagini `1.0.0-dev.7` e `1.0.0-dev.8` usano `torch==2.13.0+cu126`.

Il 2026-11-01 il sorgente ordinario è stato rilasciato su `dev` (commit `8773c86895577c6040c2cbc6fd2438bfea7d7ef8`, pacchetto sorgente di 12 file `7dc956b761e4b27100249be3bf9e10053d96286d5809b5b9127167a67a6162eb`, 950 test superati senza skip in 43,816 s e 1246 test nel worktree completo, copertura delta di produzione `217/235` pari al `92,34%` e test `680/691` pari al `98,41%`). La catena GitHub Actions ([Release 41342246921](https://github.com/digitalygo/envai-pii/actions/runs/41342246921) e [docker-publish 41342296083](https://github.com/digitalygo/envai-pii/actions/runs/41342296083)) ha pubblicato la prerelease `v1.0.0-dev.8` con digest `ghcr.io/digitalygo/envai-pii@sha256:9d7a579b45513a0ae6de01298e7312e3f849fdef98c84ccc6238541a345c6f53` (configurazione `sha256:9d7ffed2d5008d745321f7740feb6476a16e9261f0340f9620744e908a37aab4`, scansione Trivy `0 blocker(s), 239 unfixed ignored`, non zero vulnerabilità).

Sul deployment di test Verda `envai-pii-test` (`envai-pii-test-0`, una GPU L40S) sono stati rimossi l'overlay diagnostico e le 97 variabili carrier `ENVAIPI_VERDA_*_ARCHIVE_*`, impostando l'immagine `1.0.0-dev.8`, `entrypoint_overrides.enabled=false`, le 11 variabili d'ambiente ordinarie in chiaro (`PII_AUTH_MODE=upstream`, `PII_ANALYSIS_TIMEOUT_SECONDS=60`, `PII_GUNICORN_WORKERS=8`, `PII_MODEL_BATCH_SIZE=8`, `PII_VERIFY_MODEL_STARTUP=1`, `PII_MAX_CONCURRENT_ANALYSES=16`, `PII_MAX_QUEUED_ANALYSES=32`, `PII_QUEUE_TIMEOUT_SECONDS=30`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `TOKENIZERS_PARALLELISM=false`) e lo scaling `min_replica_count=0`, `max_replica_count=1`, `concurrent_requests_per_replica=16`, `queue_message_ttl_seconds=600`.

**Stato parziale e bloccato della validazione live:**

- Nella seconda e ultima attivazione GPU autorizzata (`2026-11-01T22:54:02.648537Z`, pod `envai-pii-test-5c77d7d87d-fc5n6`), tutti gli 8 worker (`PID 202..209`) hanno completato il warmup di 63 chunk in 8 chiamate (`cuda:0`, `float32`, `parameter_bytes=1230259380`, `buffer_bytes=512` come conteggi osservati e confrontati dal collector, non verificati dall'hook, coda 7) ed emesso `PII_WORKER_READY` in `11,128448 s` da `Listening at` (`34,837916 s` dal resume accettato), e la richiesta `POST /api/v1/analyses` a freddo (`35,746288 s`) ha restituito `HTTP 200` (`45746` byte wire, SHA-256 wire `b9b5b91fe4a2731a6b6a7cf70382f5b3ffa30af7ecc6a5ac8169fa9f01500651`) con SHA-256 JSON canonico `ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40` identico all'oracolo atteso (la revisione del modello e' fissata a `v1.5.0`, ma i soli conteggi di byte non dimostrano pesi bit a bit identici; nella prima attivazione un bug del client aveva confrontato l'hash wire grezzo con l'hash canonico; per identità dei byte wire anche la prima risposta era conforme all'oracolo).
- Alle `22:54:45.239459Z` il client privato si è però fermato al controllo `auth_pre_positive` (`pod_zero_unknown_or_churn`) prima delle sonde di salute e autenticazione post-cold (`0` eseguite), prima del benchmark a `CC8` e `CC16` (`0/72` richieste eseguite) e prima dell'osservazione dello scale-to-zero naturale: la guardia `running_replica_cohort` del client richiedeva il campo `name` negli elementi di `GET /v1/container-deployments/{name}/replicas`, mentre lo schema OpenAPI ufficiale di Verda (`ReplicaInfo`) definisce `required: ["id", "status", "started_at"]` senza alcuna proprietà `name` (il payload grezzo di `/replicas` all'istante dell'errore non è stato persistito, quindi non si afferma come fatto provato lo stato istantaneo della replica).
- La chiusura failure-safe ha messo in pausa il deployment e confermato `status: "paused"`, `min_replica_count=0` e `0` repliche attive alle `22:55:17.079104Z` e nella verifica indipendente del parent alle `2026-11-01T23:06:00.268201+00:00`. Il rollout non è quindi completato né certificato pronto per la produzione; vedi il [report sul rollout dell'immagine ordinaria N8 e B8](../substrate/traces/reports/2026-11-01-verda-n8-b8-ordinary-image-rollout.md) e la [guida Verda](verda-service.md).
