---
status: completed
created_at: 2026-10-30
implementation_status: verified
live_comparison_status: completed_n8_n12_n16_b8_verified
---

# Confronto di 8, 12 e 16 copie del modello a B8 e tempi di avvio

## Verdetto e riepilogo a concorrenza 32

La serie live a batch fisso `PII_MODEL_BATCH_SIZE=8` (`B8`) confronta `8`, `12` e `16` copie del modello (processi worker Gunicorn indipendenti) sul deployment Verda `envai-pii-test` con singola GPU L40S (`size=1`, `max_replica_count=1`, `concurrent_requests_per_replica=32`), precisione `float32`, pesi v1.5.0 e immagine pinnata `ghcr.io/digitalygo/envai-pii@sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714` (`1.0.0-dev.7`). Il [precedente report sul batching dei chunk](2026-10-28-chunk-batching.md) e il relativo [piano sul batching](../plans/2026-10-28-chunk-batching.md) restano storici e invariati: la vecchia riga `8 copie / B8` (`4,026919 req/s`) non e' stata riutilizzata come controllo, ma e' stato eseguito un nuovo controllo `N8 / B8` (`copy-20261029-n8`) espressamente autorizzato nella stessa serie sperimentale.

Tutte le tre nuove matrici (`N8`, `N12`, `N16` ai livelli di concorrenza client `1`, `2`, `4`, `8`, `16`, `32`) hanno completato `402/402` richieste HTTP `200` validate per conteggio (`1206/1206` nuove richieste misurate totali con ID compositi unici su `81` raffiche e `27` gruppi per matrice, piu' `1` richiesta HTTP `200` autenticata di warmup esclusa per matrice e zero replay di richieste misurate), tutte con lo stesso corpo JSON sintetico (`45000` caratteri Unicode, `63` chunk, `45174` byte UTF-8, categorie predefinite attive, nessun seed) e lo stesso oracolo canonico di risposta (`ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`).

| Copie (`B8` fisso) | Richieste/s a `CC32` (vs `N8`) | Media `CC32` (s) | P95 `CC32` (s) | Avvio same-pod Gunicorn `Listening -> all ready` (s) | VRAM max usata (GiB / libera min %) | Picco RAM kernel (GiB / libera min %) | PID max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `8` (`N8`) | `3,861909` (controllo) | `5,971478` | `8,015375` | `15,450720` (controllo) | `14,106934 GiB` (`70,224%`) | `9,026581 GiB` (`84,437%`) | `108` |
| `12` (`N12`) | `4,001195` (`+3,60665%`) | `5,793653` | `7,899093` | `17,542707` (`+13,54%`) | `21,160950 GiB` (`55,334%`) | `13,468067 GiB` (`76,784%`) | `149` |
| `16` (`N16`) | `3,818058` (`-1,13547%`) | `5,637245` | `8,197978` | `19,874904` (`+28,63416%`) | `28,213013 GiB` (`40,449%`) | `17,920856 GiB` (`69,104%`) | `191` |

Salire da `8` a `12` o `16` copie a `B8` produce variazioni minime di throughput a `CC32` (`+3,60665%` per `N12` e `-1,13547%` per `N16` rispetto al controllo `N8` della stessa serie), senza un guadagno materiale netto e senza pretesa di significativita' statistica su singola corsa per conteggio. Anche ai livelli intermedi non emerge un vincitore universale: a `CC16`, ad esempio, `N16` registra `3,726926 req/s` contro `3,675123 req/s` di `N8` e `3,602240 req/s` di `N12`, mentre a `CC4` e `CC8` guida leggermente `N12` (`2,690256` e `3,203094 req/s`). Al contrario, l'impronta di memoria cresce in modo marcato (`+7,054 GiB` di VRAM per `N12`, `+14,106 GiB` per `N16`) e il tempo di avvio interno al pod (`first_gunicorn_listening_to_all_ready`) sale di `+4,424184 s` (`+28,63416%`) passando da `8` a `16` copie.

**Raccomandazione operativa:** **`8` copie del modello con `PII_MODEL_BATCH_SIZE=8` (`N8 / B8`) rappresentano il miglior compromesso candidato tra consumo di risorse, tempo di avvio e prestazioni per carichi fino a `32` client concorrenti.** Non costituiscono un limite fisico massimo dell'hardware ne' un SLA. Nessun profilo o default e' stato promosso automaticamente: nel sorgente `src/app/model_batching.py` il default resta `1`, l'immagine pubblicata `1.0.0-dev.7` resta invariata e sul deployment `envai-pii-test` rimane configurato ma inattivo l'ultimo profilo diagnostico `N16 / B8` (`status: "paused"`, `min_replica_count: 0`, `max_replica_count: 1`, `concurrent_requests_per_replica: 32`, `replicas.list: []` verificato alle `2026-10-30T00:44:20.956746+00:00`, compute spento per questo deployment senza dichiarare fatturazione zero globale sull'account).

## Formule di performance e tabella delle 18 celle

Per ogni cella (copie `N` x concorrenza client `CC`), le metriche sono ricalcolate direttamente dai record HTTP grezzi (`bursts.jsonl`) e dai campioni NVML a `1 Hz` del worker proprietario (`min(PID)`):

- `requests_per_second = success_count / sum(group_elapsed_seconds)`, sommando il campo delle singole raffiche della cella; setup e pause di gestione fra raffiche sono esclusi dal denominatore.
- `mean_s` e `p95_s` sono calcolati sulle durate client end-to-end delle richieste validate; il p95 usa il nearest-rank dell'intera cella, non la media dei percentili dei gruppi.
- `gpu_mean_percent`, `memory_controller_mean_percent` e `power_mean_milliwatts / 1000` sono medie sui soli campioni NVML i cui intervalli di campionamento intersecano le finestre di trasporto effettive della cella; `coverage_fraction` esprime la copertura nominale a `1 Hz`.

Il task e' iniziato il `2026-10-29` e si e' concluso dopo la mezzanotte UTC del `2026-10-30`; per continuita' di tracciamento gli identificativi di run (`copy-20261029-n8`, `copy-20261029-n12`, `copy-20261029-n16`), il [piano della serie](../plans/2026-10-29-copies-startup-comparison.md) e la cartella privata `/home/lorenzo/private/tmp/envai-pii-copies-startup-20261029/` mantengono intenzionalmente la data `2026-10-29`.

| Copie (`B8`) | Run ID e pod misurato | PID pronti (owner NVML) | Finestra richieste misurate (UTC) | SHA-256 `bursts.jsonl` |
| --- | --- | --- | --- | --- |
| `8` | `copy-20261029-n8` (`envai-pii-test-7cf76d48bf-v7rfm`) | `240-247` (`240`) | `2026-10-29T23:20:49.227942Z` - `23:24:01.848945Z` | `dcd13a0a6adfda34fa90f39b710a08d162111deba8c2f73a8895df4e37f7cf14` |
| `12` | `copy-20261029-n12` (`envai-pii-test-5748cbf69d-mv9dd`) | `241-252` (`241`) | `2026-10-30T00:13:06.485549Z` - `00:16:23.484341Z` | `ce08cdcafa508cd55dc71725e6ed2158c511b684c50243f604b78e36372e5484` |
| `16` | `copy-20261029-n16` (`envai-pii-test-888b88f44-rcd47`) | `240-254, 256` (`240`) | `2026-10-30T00:33:56.707109Z` - `00:37:11.770536Z` | `d8042db2138c96436d6759ade710453702a4e68a22ddfe1092618fd6f384ec76` |

Dettaglio completo delle 18 celle misurate (`leader-comparison.json`):

| Copie | Concorrenza | Successi | Media (s) | P95 (s) | Somma gruppi (s) | Richieste/s | GPU media (%) | Mem ctrl medio (%) | Campioni attivi | Copertura 1 Hz (%) | Potenza media (W) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `8` | `1` | `30/30` | `0,953667` | `1,011292` | `28,611927` | `1,048514` | `14,11` | `4,64` | `28` | `96,55` | `135,39` |
| `8` | `2` | `36/36` | `1,199689` | `1,699316` | `22,392978` | `1,607647` | `24,36` | `7,59` | `22` | `95,65` | `154,62` |
| `8` | `4` | `48/48` | `1,388004` | `2,321551` | `19,618087` | `2,446722` | `50,50` | `15,11` | `18` | `90,00` | `189,47` |
| `8` | `8` | `96/96` | `1,942580` | `2,611637` | `30,081300` | `3,191351` | `64,33` | `19,67` | `30` | `96,77` | `233,48` |
| `8` | `16` | `96/96` | `3,301515` | `4,466162` | `26,121573` | `3,675123` | `77,67` | `23,83` | `24` | `88,89` | `260,05` |
| `8` | `32` | `96/96` | `5,971478` | `8,015375` | `24,858170` | `3,861909` | `80,33` | `24,83` | `24` | `96,00` | `269,98` |
| `12` | `1` | `30/30` | `0,958725` | `1,023696` | `28,763497` | `1,042989` | `17,45` | `5,38` | `29` | `100,00` | `131,10` |
| `12` | `2` | `36/36` | `1,069414` | `1,672388` | `19,715332` | `1,825990` | `22,76` | `7,19` | `21` | `100,00` | `148,60` |
| `12` | `4` | `48/48` | `1,266211` | `1,809993` | `17,842171` | `2,690256` | `63,00` | `18,81` | `16` | `88,89` | `194,30` |
| `12` | `8` | `96/96` | `1,907168` | `2,641978` | `29,971026` | `3,203094` | `54,60` | `16,67` | `30` | `100,00` | `237,62` |
| `12` | `16` | `96/96` | `3,193339` | `4,570446` | `26,650086` | `3,602240` | `69,15` | `21,31` | `26` | `96,30` | `264,92` |
| `12` | `32` | `96/96` | `5,793653` | `7,899093` | `23,992832` | `4,001195` | `78,87` | `24,04` | `23` | `95,83` | `280,18` |
| `16` | `1` | `30/30` | `0,962062` | `1,042491` | `28,863798` | `1,039364` | `14,55` | `4,61` | `31` | `100,00` | `133,72` |
| `16` | `2` | `36/36` | `1,087959` | `1,613176` | `20,140100` | `1,787479` | `34,71` | `10,76` | `21` | `100,00` | `160,12` |
| `16` | `4` | `48/48` | `1,296024` | `1,778420` | `18,246771` | `2,630602` | `47,35` | `13,71` | `17` | `89,47` | `195,13` |
| `16` | `8` | `96/96` | `1,899778` | `2,814650` | `30,505831` | `3,146939` | `54,38` | `17,00` | `32` | `100,00` | `224,22` |
| `16` | `16` | `96/96` | `3,151280` | `4,402871` | `25,758494` | `3,726926` | `64,30` | `19,93` | `27` | `100,00` | `256,71` |
| `16` | `32` | `96/96` | `5,637245` | `8,197978` | `25,143670` | `3,818058` | `71,54` | `22,54` | `26` | `100,00` | `267,32` |

## Analisi dei tempi di avvio e limiti metodologici

Ogni conteggio (`8`, `12`, `16`) dispone di **una sola osservazione di avvio (`observation_count: 1`)**, che non costituisce uno studio replicato di cold start ne' una distribuzione statistica.

| Metrica di avvio | `8` copie (`N8`) | `12` copie (`N12`) | `16` copie (`N16`) | Significato e limiti |
| --- | --- | --- | --- | --- |
| `first_gunicorn_listening_to_all_ready` (s) | `15,450720` | `17,542707` | `19,874904` | **Proxy comparabile principale** (clock nativo dello stesso pod, da `Listening at` sul PID `1` all'ultimo `batch_ready` di tutte le `N` copie; `+4,424184 s` / `+28,63416%` per `N16` vs `N8`) |
| `first_worker_boot_to_all_ready` (s) | `15,444970` | `17,537627` | `19,868978` | Clock nativo dello stesso pod dal primo boot worker all'ultimo `batch_ready` di tutte le `N` copie |
| `provider_pull_phase` (`Pulling -> Pulled`, s) | `197,0` | `null` (`provider_pulling_unavailable`) | `null` (`provider_pulling_unavailable`) | In `N8`: `23:17:01Z -> 23:20:18Z` (include verifica, checksum, scheduling o pull). In `N12`/`N16`: evento `Pulling` non emesso (non equivale a `0 s`) |
| `image_cache.status` | `unknown` | `unknown` | `unknown` | `trusted_cache_metadata_unavailable` su tutti e tre i pod |
| `resume_requested_to_accepted` (s) | `0,326` | `0,288` | `0,335` | Latenza API management del POST `resume` |
| `resume_accepted_to_last_ready_event` (s) | `220,147965` | `26,108766` | `26,620396` | Cross-clock tra accettazione client e ultimo evento ready nei log provider (`provider_client_clock_offset_unmeasured`) |
| `resume_requested_to_last_ready_event` (s) | `220,473965` | `26,396766` | `26,955396` | Cross-clock tra richiesta client e ultimo evento ready nei log provider |
| `resume_accepted_to_ready_observed` (s) | `232,382` | `32,050` | `38,955` | Clock client fino al completamento del gate di lettura log: include ingestione log e polling, non il tempo di caricamento dei modelli |
| `resume_requested_to_ready_observed` (s) | `232,708` | `32,338` | `39,290` | Clock client dalla richiesta `resume` all'osservazione del gate |
| `resume_accepted_to_first_valid_response` (s) | `233,481720` | `33,188905` | `40,365413` | Include l'attesa del collector prima di inviare il warmup HTTP escluso (`warmup_transport`: `0,975753 s`, `0,991116 s`, `1,209247 s`); non garantisce il primo istante HTTP possibile |
| `resume_requested_to_first_valid_response` (s) | `233,807720` | `33,476905` | `40,700413` | Dalla richiesta `resume` alla fine del warmup HTTP escluso |
| `container_created_to_started` / `container_started_to_all_ready` | `null` | `null` | `null` | `provider_multiple_container_events` (`N8`) / `provider_timestamp_ambiguous` (`N12`, `N16`): il provider emette due eventi `Created` e due `Started` indistinguibili tra init e main container |

Vincoli interpretativi sulle misure di avvio:

- **Cosa misura il proxy same-pod (`15,451 s` / `17,543 s` / `19,875 s`):** l'intervallo nativo tra l'evento `Listening at` di Gunicorn (PID `1`: `23:20:19.774245Z` per `N8`, `00:12:41.296059Z` per `N12`, `00:33:21.890492Z` per `N16`) e l'ultimo evento `batch_ready` (`23:20:35.224965Z`, `00:12:58.838766Z`, `00:33:41.765396Z`) usa un unico orologio di pod post-pull e cresce monotonicamente con il numero di copie (`+2,091987 s` a `12` copie, `+4,424184 s` ossia `+28,63416%` a `16` copie). Questo intervallo comprende l'inizializzazione dell'applicazione e del modello, l'inizializzazione CUDA, il warmup per worker da `63` chunk a `B8` (`8` chiamate, somma `63`, max `8`) e la barriera di prontezza di tutte le `N` copie; non misura il solo caricamento puro dei pesi da disco.
- **Perche' `220,1 s` contro `26,1 s` / `26,6 s` non indica che `12` o `16` copie si avviino piu' velocemente:** in `N8` il provider ha registrato `Pulling` (`23:17:01Z`) e `Pulled` (`23:20:18Z`, `197 s`), mentre in `N12` e `N16` ha registrato solo `Pulled` (`00:12:39Z` e `00:33:20Z`) senza `Pulling` (`provider_pulling_unavailable`), e in nessuna delle tre corse esistono metadati fidati sullo stato della cache dell'immagine (`trusted_cache_metadata_unavailable`). La misura N8 include quindi una lunga fase provider prima del boot di Gunicorn; il confronto tra `220,1 s` e `26,1-26,6 s` non permette di attribuire isolatamente la differenza al numero di copie.
- **Ambiguita' degli eventi container di sistema:** per ogni pod i log di sistema Verda riportano due occorrenze di `Created` e due di `Started` (ad esempio init/sidecar e main container, come due righe distinte `count=1` alle `23:17:00Z` e `23:20:18-19Z` in `N8`, o aggregate in `N12`/`N16`) senza indicare il nome del container. Scegliere l'ultimo timestamp come avvio del container principale sarebbe un'ipotesi non verificata; il parser registra quindi `null` con motivazione esplicita e usa gli eventi applicativi Gunicorn come riferimento rigoroso.

## Risorse, vincoli e guardie prospettiche

Su tutti e tre i pod della serie la memoria GPU visibile riportata da NVML e' `50869764096` byte (`47,376159668 GiB`, distinta dai `50878152704` byte / `47,384 GiB` osservati sui nodi della precedente serie sul batching), il limite RAM del container e' `62277025792` byte (`58 GiB`) e il limite cgroup `pids.max` del nodo e' finito e pari a `580081` (`pids_limit_state: "bounded"`, non `unbounded`). Il budget sperimentale resta fissato a `512` task con guardia a `409` (`20%` di margine), che costituisce un tetto di sicurezza dell'esperimento e non una quota del provider.

| Copie (`B8`) | VRAM max usata (GiB / byte) | VRAM libera min (%) | Picco RAM kernel (GiB / byte) | RAM corrente max (byte) | RAM libera min (%) | PID readiness / max (guardia `409` / budget `512` / cgroup `580081`) | Campioni NVML totali / attivi / inattivi (min/cella) | Campioni base | Anomalie NVML / churn |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `8` (`N8`) | `14,1069335938 GiB` (`15147204608`) | `70,224%` | `9,02658081055 GiB` (`9692217344`) | `9692209152` | `84,437%` | `62` / `108` | `211` / `146` / `65` (`18`) | `836` | `0` / `0` |
| `12` (`N12`) | `21,1609497070 GiB` (`22721396736`) | `55,334%` | `13,4680671692 GiB` (`14461227008`) | `14458363904` | `76,784%` | `99` / `149` | `209` / `145` / `64` (`16`) | `1238` | `0` / `0` |
| `16` (`N16`) | `28,2130126953 GiB` (`30293491712`) | `40,449%` | `17,9208564758 GiB` (`19242373120`) | `19240988672` | `69,104%` | `131` / `191` | `214` / `154` / `60` (`17`) | `1705` | `0` / `0` |

Tutte le tre configurazioni rispettano ampiamente la soglia minima del `20%` di memoria RAM e VRAM libera e la guardia di `409` PID. Prima di ciascun incremento del numero di copie sono state verificate le guardie prospettiche basate sui picchi reali osservati per copia con `2 GiB` (`2147483648` byte) di margine di caricamento aggiuntivo:

- **Da `N8` a `N12` (`leader-n12-prospective-guard.json`):** VRAM proiettata `24868290560` B e richiesta con margine `20%` `31085363200` B (`< 50869764096` B); RAM proiettata `16685801472` B e richiesta `20857251840` B (`< 62277025792` B); PID proiettati `164` e richiesti `205` (`<= 512`). Esito: `allowed: true`.
- **Da `N12` a `N16` (`leader-n16-prospective-guard.json`):** VRAM proiettata `32442679296` B e richiesta con margine `20%` `40553349120` B (`< 50869764096` B); RAM proiettata `21426256556` B e richiesta `26782820695` B (`< 62277025792` B); PID proiettati `201` e richiesti `252` (`<= 512`). Esito: `allowed: true`.

Ogni profilo e' stato eseguito in una riattivazione distinta del deployment, per cui il nodo host fisico e lo stato della cache possono differire tra `N8`, `N12` e `N16` (nessun UUID GPU grezzo viene salvato negli artefatti). Le percentuali NVML misurano la frazione di tempo con motore attivo a livello di dispositivo e non l'occupazione degli SM, i FLOPs o la causa isolata di un collo di bottiglia; i watt campionati non rappresentano la fatturazione del provider.

## Pacchetto diagnostico, verifiche e tentativi intermedi

### Perimetro del codice e verifiche offline

- **Core applicativo invariato, harness diagnostico esteso:** `src/app/app.py`, `src/app/model_batching.py`, `tests/test_model_batching.py`, `tools/verda_model_experiment/fixture.py` e `tools/verda_model_experiment/transport.py` sono rimasti byte-identici (`base_app_sha256` `b0ec5163cd0d9eee05922d4b80718eb26abc762b0612935e1f1ad8275dc3848e`, `helper_sha256` `31a9d653891e401e86f2c110311bba2417dee5c2450c4081c55bee88e328424d`, `detector_source_sha256` `1a0f57a3e4563e8f66b245d38db175f5c368238a53334176c4cd49045e16477e`, `detector_code_sha256` `0a16342e7c87a5053c5f2a74579ba3be9c7a3f5f3964f1afde059b13518d1953`, `manifest_sha256` `a7e71ece5e05307ff9a40f74b1b7542616ad5c733d983628767933d5210d7684`). Poiche' il vecchio manifesto a 9 file (`0fcada80459283e62029f9cea50ab9cc5146539ae5fdf28eaa9cb3ef6aeeb971`) includeva anche `batch_package.py`, `batch_runtime.py` e i relativi test, quel manifesto a 9 file **non** e' invariato nel suo complesso: i moduli diagnostici di packaging, runtime, risorse, collector e startup sono stati estesi per supportare `8`, `12` e `16` copie, mentre lo snapshot pre-task dei file diagnostici precedenti e' archiviato privatamente in `/home/lorenzo/private/tmp/envai-pii-copies-startup-20261029/source-baseline/`.
- **Nuovo pacchetto di 21 file e archivio diagnostico:** il manifesto corrente dei 21 file diagnostici e di test (`review-manifest.json`) ha digest `46d02491337709447e475ebaca92e61f444bf0ae9871f638a04ffce585047a0e`. Il nuovo archivio XZ generato con Python 3.11 misura `17216` byte, SHA-256 `015dd46695c207a36af412bafde7e96031ccce1c5b81ae5a34726f9bbe13dcdb`; ogni profilo usa `56` argomenti comando (limite `64`, margine `8`), `56` variabili carrier `ENVAIPI_VERDA_BATCH_ARCHIVE_*` (`<= 253` byte ciascuna) e gli stessi 8 parametri runtime fissi per processo. L'ambiente nativo del deployment contiene `105` voci (le `49` variabili storiche piu' le `56` nuove variabili carrier), aggiornate una sola volta nel PATCH corretto di `N8` e lasciate intatte per `N12` e `N16`.
- **Test e copertura (`leader-tests.log`, `post-n12-tests.log`, `post-n16-tests.log`, `leader-delta-coverage.json`):** la suite dichiarata `python -m unittest discover -v tests` eseguita dal coordinatore supera **1233 test senza alcuno skip** (`74,308 s` dopo `N16`, rispetto ai `1231` test prima dell'affinamento offline di `startup.py`), senza download di Torch, modelli o dataset e senza commenti aggiunti nel codice. La copertura delle righe eseguibili del delta sui 21 file e' **`412/443` (`93,0023%`)** per il codice di produzione e **`946/949` (`99,6839%`)** per i test.
- **Gate di qualita' e sicurezza:** `quality-gate-a` ha restituito **PASS** sul pacchetto corrente di 21 file (`46d02491337709447e475ebaca92e61f444bf0ae9871f638a04ffce585047a0e`) e **PASS** su ciascuna delle esecuzioni live `N8`, `N12` e `N16`. `security-review-specialist-a` ha restituito **PASS** mirato sul pacchetto iniziale di preparazione (`2979376b44178d5a6568c421d8a529ec86372d9282010621901e9c07fc822acf`); il successivo passaggio da `2979376b...` a `46d02491...` ha modificato esclusivamente `tools/verda_model_experiment/startup.py` e `tests/test_verda_startup.py` per registrare come `unknown` i timestamp di sistema ambigui del provider, lasciando invariati runtime server, archivio, core applicativo e trasporto. Per questa sola correzione numerica offline e per le configurazioni remote non e' stata quindi eseguita ne' dichiarata una nuova security review automatica sull'intero manifesto `46d02491...`.

### Trasparenza sui tentativi intermedi e sul recupero read-only

1. **Primo tentativo `N8` rifiutato in pre-attivazione (`n8-b8/`):** il subagent primario ha inviato nel PATCH del deployment tutte le `105` variabili d'ambiente unite (`body_bytes: 47887`, SHA-256 `cc7e6171536a5cf55e5af3a7be760a4d69b1b581b22680fd1f1aa7d523347543`) anziche' le sole `56` variabili carrier del builder, ricevendo HTTP `400` (`deployment_patch:management_http (400)`), con `0` attivazioni GPU e `0` richieste di inferenza, e ha confermato `paused`/`min=0`/`0` repliche alle `23:08:28.050Z`. Nel file `n8-b8/final.json` (preservato inalterato) il campo `deployment_patch.attempted` riporta erroneamente `false`, mentre il registro autorevole della chiamata PATCH `400` e' conservato in `n8-b8/api-ledger-final.json`.
2. **Secondo tentativo `N8` (`n8-b8-corrected/`) e recupero offline dello startup:** il subagent di fallback ha inviato il payload corretto con le `56` variabili del builder (`body_bytes: 33332`, SHA-256 `a2421aa719226fd45fe8fa8a2572ea24551f6d313754d292739bc815df32aba5`), verificato nel readback l'unione attesa di `105` variabili, attivato una sola volta la GPU (`pod envai-pii-test-7cf76d48bf-v7rfm`), completato il warmup escluso, tutte le `402/402` richieste misurate e il cleanup a `paused`/`min=0`/`0` repliche alle `23:25:13.326Z`. Nella raccolta finale di startup il parser ha incontrato due eventi `Created` e due `Started` distinti con `count=1` (init e main container), salvando `status: "partial_only"` e `error_code: "system_event_duplicate_mismatch"` in `n8-b8-corrected/startup.json` (preservato senza modifiche). Dopo l'aggiornamento offline del solo parser `startup.py` e dei relativi test (`1233` test superati), il coordinatore ha ricostruito in sola lettura `leader-n8-startup.json` (con `leader-n8-startup-audit.json` e `leader-n8-system-metadata.json`) dai log nativi del pod senza riattivare la GPU e senza rieseguire richieste.
3. **Esecuzione `N12` (`n12-b8/`) e `N16` (`n16-b8/`):** prima di `N12`, `backend-dev-b` si e' fermato senza eseguire chiamate o modifiche per chiedere una conferma ridondante del branch `dev`; il fallback sequenziale `backend-dev-c` ha ricevuto il task con l'autorizzazione `dev` esplicita ed eseguito `N12` in un solo PATCH del comando entrypoint (`body_bytes: 14060`, SHA-256 `0a79c32d4098463ee6e10bb010738f6b45bbf40e3766f196f586804ba58805a6`, senza reinviare `env`), una sola attivazione `min=1`/`resume`, `402/402` misure e cleanup a `paused`/`min=0`/`0` repliche alle `00:16:42.664Z`. Allo stesso modo `N16` ha applicato un solo PATCH entrypoint (`body_bytes: 14060`, SHA-256 `a7db5a52320497bcedf8b3ae28dc4135f86fef183198e9d7fe8ef3d3958c7a8a`), una sola attivazione `min=1`/`resume`, `402/402` misure e cleanup alle `00:38:14.931Z`. Gli audit read-only del coordinatore (`leader-n12-audit.json` su `230` righe native di startup e `leader-n16-audit.json` su `353` righe native in due finestre `279 + 74`) hanno confermato l'esatta coincidenza dei riepiloghi `leader-n12-startup.json` e `leader-n16-startup.json`.

## Verifica finale dello stato e della consegna

Alle `2026-10-30T01:09:57.158686+00:00` ulteriori letture native del parent confermano `paused`, minimo `0`, massimo `1`, concorrenza `32`, zero repliche, entrypoint `N16 / B8` esatto e vecchie `49` env preservate nell'unione `105` (`leader-final-verification.json`). Verificati source manifest immutato, tutte le `18` celle nel rapporto, struttura e link Markdown, permessi privati `0600`/`0700` e assenza dei tre valori di credenziali reali in `146` file. Nessun client o driver del task rimane attivo; nessun commit o staging e nessuna nuova pubblicazione.

## Percorsi e riferimenti

- [Piano di confronto 8/12/16 copie e startup](../plans/2026-10-29-copies-startup-comparison.md), [report storico sul chunk batching](2026-10-28-chunk-batching.md) e [operazione del servizio GPU](../operations/2026-10-21-runpod-service.md).
- [Guida del servizio Verda](../../../docs/verda-service.md), [guida del chunk batching](../../../docs/chunk-batching.md) e [changelog](../../../docs/CHANGELOG.md).
- Evidenze private in `/home/lorenzo/private/tmp/envai-pii-copies-startup-20261029/` (`leader-comparison.json`, `leader-n8-startup.json`, `leader-n8-startup-audit.json`, `leader-n8-system-metadata.json`, `leader-n12-startup.json`, `leader-n12-audit.json`, `leader-n12-prospective-guard.json`, `leader-n16-startup.json`, `leader-n16-audit.json`, `leader-n16-prospective-guard.json`, `review-manifest.json`, `leader-delta-coverage.json`, `leader-coverage.json`, `leader-tests.log`, `post-n12-tests.log`, `post-n16-tests.log`, `source-baseline/` e le directory `n8-b8/`, `n8-b8-corrected/`, `n12-b8/`, `n16-b8/`). Nessun segreto, token, corpo di richiesta/risposta, `dictionary_delta` o UUID GPU grezzo e' salvato negli artefatti; i driver temporanei sono stati rimossi e il venv Python 3.11 preesistente e' stato preservato.
