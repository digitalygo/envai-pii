# Avvio dei worker GPU e batching lato server

Questa guida descrive la configurazione di avvio dei processi Gunicorn, il batching dei chunk lato server e la verifica opzionale di warmup per ciascun worker nel sorgente ordinario dell'immagine GPU (`Dockerfile.gpu`, `src/app/gunicorn_config.py`, `src/app/gpu_worker_startup.py`, `src/app/model_batching.py` e `src/app/cloud_service.py`). I contratti HTTP e il formato delle risposte restano quelli descritti in [GUARDRAIL_API.md](GUARDRAIL_API.md).

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

## Requisiti dell'immagine container per il rollout

Il supporto a `PII_GUNICORN_WORKERS`, `PII_MODEL_BATCH_SIZE` e `PII_VERIFY_MODEL_STARTUP` richiede una nuova immagine GPU costruita a partire dal sorgente che include `src/app/gpu_worker_startup.py`, `src/app/model_batching.py` e il `CMD` aggiornato in `Dockerfile.gpu`. Impostare queste variabili d'ambiente su un'immagine precedente (ad esempio `1.0.0-dev.7`, distinta dalla versione `v1.5.0` dei pesi del modello) non attiva il batching né il pool multi-worker, perché quell'immagine non contiene i moduli corrispondenti e forza `--workers 1` nella riga di comando di Gunicorn.

La pubblicazione tramite GitHub Actions di una nuova prerelease dev dell'immagine GPU e il rollout operativo con `PII_GUNICORN_WORKERS=8` e `PII_MODEL_BATCH_SIZE=8` sono passaggi successivi non ancora eseguiti. Questa guida documenta il comportamento del sorgente attuale e non dichiara alcuna versione o digest di immagine rilasciata, stato di prontezza del deployment corrente, SLA o limite fisico massimo di throughput.
