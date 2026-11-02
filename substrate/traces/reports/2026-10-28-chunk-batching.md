---
status: completed
created_at: 2026-10-28
updated_at: 2026-10-29
implementation_status: verified
live_comparison_status: completed_b1_b4_b8_b16_verified
---

# Batching dei chunk: sorgente verificato e confronto GPU completato

## Risultato

Il batching richiesto e' implementato su `dev`, con configurazione server `PII_MODEL_BATCH_SIZE=1/4/8/16` e default `1` invariato nel sorgente. Il modello riceve gruppi consecutivi di chunk dello stesso tratto non protetto, senza mescolare richieste, file, seed o categorie. Pesi, precisione `float32`, otto copie del modello, chunking, autenticazione, immagine pubblicata `c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714` e contratto API restano invariati.

**Il confronto live completo 4x6 (`B1`, `B4`, `B8`, `B16` a concorrenza `1`, `2`, `4`, `8`, `16`, `32`) su singola L40S e' completato e verificato indipendentemente dal coordinatore:** tutte le 24 celle (`402/402` richieste per batch, `1206` nuove misure su `B4`/`B8`/`B16` piu' le `402` misure storiche preservate di `B1`, per `1608` righe HTTP comparabili totali su `81` raffiche e `27` gruppi per batch, oltre a un warmup autenticato escluso per matrice) hanno restituito HTTP `200` con lo stesso corpo (`45174` byte, `63` chunk) e l'oracolo canonico esatto (`ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`). `B1` non e' stato rieseguito.

A concorrenza `32`, la latenza media scende da `10,872464 s` (`B1`, p95 `14,007766 s`, `2,253740` richieste/s) a `6,630575 s` (`B4`, p95 `9,369125 s`, `3,392860` richieste/s), `5,974584 s` (`B8`, `-45,05%` rispetto a `B1`, p95 `8,247637 s`, `4,026919` richieste/s, pari a `1,78677x` ossia `+78,68%` di throughput) e `5,597851 s` (`B16`, `-48,51%` rispetto a `B1`, p95 `8,063148 s`, `3,919794` richieste/s). **`B8` e' il candidato raccomandato per la validazione su immagine di produzione** (miglior throughput osservato a `CC8`, `CC16` e `CC32` con maggiore margine VRAM rispetto a `B16`), senza modifica automatica del default `1` nel sorgente.

**Stato finale nativo verificato alle `2026-10-29T18:57:48.974474+00:00`: `paused`, minimo `0`, massimo `1`, concorrenza `32` e `replicas.list: []` (zero repliche attive).** Il cleanup ha spento il deployment alle `18:51:00.242Z` e il successivo audit read-only del parent ha confermato che il compute di questo deployment di test e' spento (senza dichiarare fatturazione globale zero per l'intero account). L'overlay diagnostico `B16` resta configurato ma inattivo.

## Modifica implementata

- `src/app/model_batching.py` risolve il valore una volta all'avvio. Accetta1/4/8/16 canonici dopo trim; valori assenti, vuoti o non supportati tornano a1. Il client non puo' impostarlo.
- `src/app/app.py` raggruppa i chunk dentro una singola chiamata al detector v1. Ogni gruppo usa la corsia nativa, passando il batch esplicito. Il percorso B1 conserva chiamate singleton, compatibilita' dei risultati e ordine dei controlli precedenti.
- Le righe di un risultato multi-chunk devono corrispondere esattamente agli input, incluse righe vuote e coda incompleta. Risultati ambigui, mancanti o extra, offset locali non validi e score non finiti falliscono senza output parziale e con errore generico.
- Offset originali, Unicode, sovrapposizioni, filtro delle categorie prima del merge, protezione del seed e ordine dei file rimangono gestiti come prima. Il legacy `detect_model` non cambia.
- La deadline e' cooperativa prima/dopo ogni gruppo e durante l'attesa della corsia; non interrompe un forward gia' in corso. Un gruppo maggiore puo' trattenere la corsia piu' a lungo e aumentare memoria e attesa. Non aumenta automaticamente il budget60s.

Il fixture da45000caratteri ha63chunk. I conteggi statici sono63/16/8/4chiamate alla pipeline per B1/B4/B8/B16. Non sono speedup misurati.

## Verifica indipendente

Il coordinatore ha eseguito il comando dichiarato `python -m unittest discover -v tests` con Flask/PyMuPDF alle versioni del repository:

- Python3.11: **1119test superati, nessuno skip**; baseline iniziale1041. Una successiva esecuzione dopo la documentazione ha nuovamente superato1119test.
- Python3.14: **1119test superati, nessuno skip** in un ambiente locale separato, senza Torch, modelli o dataset scaricati.
- Copertura eseguibile del delta: adapter21/21, helper57/57, package193/193 e runtime279/280; **550/551linee, 99,82percento**. Helper e package100percento anche con i rami; runtime99percento nel report combinato linee/rami. La linea non coperta e' un controllo difensivo dopo il ripristino dell'oggetto modello.
- Nuovi test su batching, cardinalita', Unicode/overlap, deadline prima/dopo il forward e in attesa, categorie, seed, assenza di accumulo fra chiamate, integrita'/rollback, warmup su otto copie, barriera e trasporto in un processo separato.
- `git diff --check` superato. Nessun nuovo commento nei sei file Python nuovi. Nessun test eliminato, saltato o indebolito.

Quality-gate-a: **PASS**. Security-review-specialist-a: **PASS**, revisione stretta e read-only del delta. Pacchetto di nove file `0fcada80459283e62029f9cea50ab9cc5146539ae5fdf28eaa9cb3ef6aeeb971`, ricontrollato invariato prima e dopo il tentativo cloud. Non e' una certificazione del servizio o del provider.

Advisory non bloccante: il helper di grouping, chiamato direttamente con un float/bool invece di un int, non applica sempre il fallback descritto. Quel percorso e' irraggiungibile attraverso la configurazione server, che produce soltanto gli int supportati; non e' esposto al client. Non e' stato modificato dopo i gate per un input interno non usato.

## Variante diagnostica e immagine

L'immagine pubblicata c1d9 contiene ancora il vecchio sorgente: nessuna immagine e' stata ricostruita o pubblicata. Impostare soltanto la variabile su quell'immagine non attiva il nuovo adapter.

Per il test e' stato preparato un pacchetto opt-in che conserva immagine e pin del file base e installa la funzione AST e il helper esatti della consegna, con identita' separata. Il callback registrato mantiene lo stesso oggetto, cosi' richieste con e senza selezione delle categorie usano la stessa funzione. Installazione e warmup del v1 su ogni copia precedono la barriera di readiness. Il modello originale viene ripristinato dopo il proxy di misura del warmup.

L'archivio XZ e'17160byte, SHA256 `c4eea72b82406fe5025bd4abf51bef958077f12108dd49c2bc20f6ae35a6d12a`. Ogni proposta usa55argomenti e56carrier env, ciascuno<=253byte, entro i limiti e il margine. Gli otto valori fissi del runtime e il batch vengono impostati nel bootstrap verificato, non persi. Vecchi archivi e sorgenti del package/runtime/monitor rimangono byte-identici. Builder e runtime devono avere lo stesso minor Python per il hash del bytecode; il builder operativo usa3.11 come l'immagine.

Questa e' diagnostica, non un meccanismo di release di produzione. L'overlay B1 e' poi partito sulla L40S alle16:03Z, attestato su tutti gli otto worker e usato nelle402misure successive. L'overlay B4 ha superato il primo warmup del 29 ottobre senza matrice in quel tentativo; le successive matrici B4/B8/B16 sono riportate nella ripresa finale sotto.

## Primo tentativo live e stato storico delle14:40Z

Prima del tentativo una L40S era attiva con otto modelli B1 e minimo1. La manutenzione autorizzata preservava una sola allocazione per volta. L'operatore ha effettuato un solo ciclo pausa/PATCH/ripresa, senza scaling PATCH o restart esplicito:

1. Vecchio pod `envai-pii-test-79c9745ff6-fs47w` eliminato alle14:16:26Z, zero repliche osservato prima del PATCH.
2. Un solo PATCH HTTP200 ha configurato il candidato diagnostico B1. Comando ed entrypoint sono risultati esatti, ma le variabili non sono state sostituite come ipotizzato.
3. Verda ha unito49variabili precedenti e56nuove: **105voci native**. Il gate conservativo che chiedeva esattamente56voci si e' fermato. Il coordinatore ha poi verificato indipendentemente che tutte le105voci sono l'unione esatta dei due profili noti, entrambi i sottoinsiemi intatti, senza nomi o valori sconosciuti. Nessuna cancellazione di env non documentata e' stata tentata.
4. Una sola ripresa HTTP201 ha richiesto il nuovo pod `envai-pii-test-6b6995cd44-ltlrx`, creato alle14:18:56Z. Alle14:19:04Z e nei successivi eventi il provider segnala assenza di nodi per il tipo richiesto; il container non raggiunge running.

La creazione dell'oggetto replica non prova l'allocazione o l'avvio di una GPU. I controlli indipendenti finali alle **14:40:37Z** confermano:

- `unhealthy`, non in pausa, una replica metadata in `error`, nessuna replica `running`;
- L40Sx1 desiderata, minimo1/massimo1/concorrenza32, otto modelli configurati ma non pronti;
- stessa immagine, porta, probe e memoria condivisa;
- B1 diagnostico configurato ma non eseguito, B4/B8/B16 mai applicati;
- evento nativo `SchedulingFailed`, dieci occorrenze raggruppate, messaggio verificato contenente `no nodes available for the selected instance type right now`.

Il minimo1 e' mantenuto perche' appartiene all'utente. Non e' una promessa di capacita' disponibile, e non e' stata creata un'altra GPU per aggirare il blocco. Nessun dato precedente e' stato riciclato come nuova misura.

## Ripresa: B1 misurato e auditato

La L40S e' tornata running senza un'altra mutation del coordinatore. Otto PID70–77 hanno attestato base e overlay B1, tutti gli hash corretti e warmup63chunk. La replica pronta e' stata riutilizzata, senza pausa o replica aggiuntiva. Un warmup HTTP autenticato escluso e le402misure hanno tutte restituito200 con l'oracolo esatto.

Finestra delle richieste: `2026-10-28T18:37:31.379614Z–18:42:29.808810Z`,81raffiche/27gruppi, nessun replay.

| Concorrenza | Successi | Media s | P95 s | Richieste/s | GPU media % | Campioni attivi | Potenza media W |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 30/30 | 1,823 | 1,852 | 0,548 | 16,11 | 54 | 153 |
| 2 | 36/36 | 1,939 | 2,029 | 1,015 | 45,83 | 36 | 185 |
| 4 | 48/48 | 2,574 | 3,613 | 1,282 | 64,06 | 36 | 205 |
| 8 | 96/96 | 3,560 | 5,473 | 1,663 | 71,65 | 57 | 235 |
| 16 | 96/96 | 6,288 | 9,396 | 1,769 | 71,59 | 54 | 240 |
| 32 | 96/96 | 10,872 | 14,008 | 2,254 | 87,14 | 42 | 273 |

Il parent ha verificato ogni ID composto, corpo/oracolo/status/timing e ricalcolato le sei celle dai record grezzi. Un falso FAIL del verificatore locale confondeva case_index1..6 con concorrenza1/2/4/8/16/32; il report originale resta conservato, non e' stato riscritto ne' ripetuto il benchmark. Il fallback si e' fermato su un campo paused inesistente e il successivo subagent e' stato interrotto prima di altre esecuzioni. Nessuno di questi e' un errore del modello.

Audit nativo parent: sei finestre esplicite<=55s,1511righe, nessuna troncata a1000;302campioni NVML validi,279attivi/23esclusi e1192samplesbase. Otto PID corretti, flag sorgente/settings veri, nessun exit/child_exit/startup_failed nella finestra. Ogni cella ha almeno36campioni, copertura totale nominale1Hz98,59percento. Nessuna anomalia di clock, identita', schema o duplicazione. Warmup, attese e intervalli senza richieste sono esclusi.

GPU media complessiva58,91percento, picco100percento; potenza media215,69W e picco308,333W. VRAM massima campionata13,482GiB su47,384GiB, almeno71,55percento libera. RAM corrente massima9454882816byte, picco kernel8,806GiB su58GiB; il picco kernel puo' includere l'avvio. Task massimi102 con leaf pids.max esplicitamente unbounded e budget sperimentale512/guardia409, non quota provider. Il massimo Torch per processo e'1269087744byte, non un picco globale sommabile. Unita' e margini verificati con calcolatrice e convertitore.

Il digest dei302record GPU ordinati e' `990acc9eac4f8f4eba37022b26e0ed7e47b36d67ecefbafb26260c0289938034`; dei record base filtrati `6f924cce10944b2c378594ac576498bc499de103e70fe7021725c46099d1ba76`. I record HTTP grezzi sono conservati in resume1818-b1-bursts.jsonl. Il delegate per l'archiviazione NVML ha rifiutato prima di scrivere: i campioni GPU sono stati letti e analizzati direttamente dal parent nelle API, non esiste un archivio JSONL locale completo di quei302campioni. Questo limita la riproducibilita' oltre la retention del provider.

Questi sono nuovi dati B1, non miglioramenti attribuibili a B4/B8/B16. I due momenti B1 usano la stessa classe GPU e modello, ma non isolano nodo, frequenze, CPU o distribuzione delle connessioni. NVML misura attivita' device-global, non occupazione degli SM/FLOPs o costo di fattura.

## Blocco storico del credito prima della ripresa del29ottobre

Alla ripresa successiva il deployment era gia' paused/zero, con il vecchio pod eliminato alle22:03:09Z. La causa di quella pausa non viene inferita dal solo evento di eliminazione. L'operatore ha comunque applicato un PATCH entrypoint-only B4 e ha riferito tre resumeHTTP400 con codice insufficient_funds, senza creare repliche o mandare inferenze.

La precondizione assegnata one-running non era soddisfatta e i tre tentativi eccedono l'unico resume richiesto. Sono deviazioni operative conservate, non una procedura pulita o un'autorizzazione a retry ulteriori. Nessun saldo, pagamento, segreto o altro deployment e' stato cambiato.

Il parent ha verificato indipendentemente alle23:37:36Z: `paused`, replicas.list vuota, B4 esatto, tutte105env note, stessa immagine, L40S desiderata1, minimo1/massimo1/concorrenza32. B4 non ha fatto warmup ne' misura, B8/B16 mai applicati. I file continue2323-b4-* conservano gli esiti; il parent non ha ripetuto il resume rifiutato.

## Ripresa del29ottobre: warmup B4 riuscito, collector bloccato

Dopo il messaggio dell'utente sul credito risolto, il parent legge healthy/min0/zero. Il primary-a restituisce empty response/provider error. Il fallback-b duplica/v1 nel client, non invia inferenze e ripristina min0/pausa. Il member-c corregge il confronto dell'image-object e tratta le letture di scaling inizialmente stale come eventual consistency: una precedente falsa lettura viene chiusa senza avviare GPU, il ciclo successivo porta minimo1, resume201 e avvio reale.

Il pod `envai-pii-test-bb8bc47ff-w2kht` parte alle10:12:49Z. Tutti gli ottoPID82–89 attestano base e overlay B4, source/settings veri, float32 e gli stessi parametri. Le16chiamate/somma63/max4 del warmup confermano il batch effettivo. Un solo POST HTTP escluso dalla matrice, alle10:13:34Z, restituisce200 e l'oracolo originale esatto:45174byte inviati,45746ricevuti,1,36s. E' un warmup, non una latenza di benchmark o prova di speedup. Il parent legge gli artefatti c0950-b4-* e conferma il pod running/min1/max1/32 tramite API alle10:17Z. Alle13:23:09Z legge inoltre direttamente248righe native storiche:8base-ready e8batch-ready, tutti i cinque hash e i parametri esatti, non soltanto i booleans del delegate.

Il successivo collector-c fallisce `UpstreamIdleTimeout` prima di qualunque complete1017-* o record misurato. Anche il tentativo limitato di preparare un comando offline fallisce prima di creare il modulo o i test previsti. Il fallback-b per il cleanup rifiuta il ruolo senza azioni; il cleanup-c corto riesce. Questi sono errori dell'esecutore, non nuove prove fallite del modello. Non sono stati riutilizzati dati B1 come B4 e non sono state indebolite le verifiche.

| Batch | Misure valide | Evidenza attuale |
| --- | --- | --- |
| 1 | 402/402 | Matrice e audit GPU verificati |
| 4 | Non eseguite | Otto modelli e un warmup canonicale corretto |
| 8 | Non eseguite | Mai attivato |
| 16 | Non eseguite | Mai attivato |

## Spegnimento storico delle 13:23Z prima del completamento

Il cleanup alle 11:46:04Z invia una pausa 201 e un PATCH 200 del solo minimo 0, senza retry del workload. I GET indipendenti parent alle 11:48, 13:13:51 e 13:23:09Z confermano **paused/min0/max1/concorrenza 32 e replicas.list vuota**. Nessun'altra macchina o deployment e' stato cambiato. Il comando B4 rimaneva configurato ma inattivo in quel checkpoint intermedio.

La fonte e i nove hash `0fcada80` erano immutati, e in quel momento `batch_experiment.py` e il relativo test non erano ancora stati creati. La suite parent aveva superato 1119 test in 40,132s, nessuno skip, con `quality-gate-a` **PASS sul solo cleanup** intermedio.

## Ripresa finale del 29 ottobre: modulo collector/transport e matrici B4, B8 e B16 completate

### Verifica del pacchetto collector e transport riutilizzabile

Per eliminare il blocco dell'esecutore senza toccare il core applicativo (`0fcada80459283e62029f9cea50ab9cc5146539ae5fdf28eaa9cb3ef6aeeb971`, copertura `550/551` linee, `99,82%` invariata), e' stato introdotto un pacchetto riutilizzabile di quattro file (funzioni e moduli Python, nessuna CLI implementata) con digest manifesto `1a66159cd95884b24b4e58994470b6b77861775887380f7ef636b75047188776`:

- `tools/verda_model_experiment/batch_experiment.py`: SHA256 `98a895f1d4ad37db8c53d466aa89bd5d2969b37aa9a2f8cb64589d817b95b3bb`
- `tools/verda_model_experiment/transport.py`: SHA256 `f1d272d03d30a7d2769aa3921e491668120e53b64ad09128dda8db323d5f3adb`
- `tests/test_verda_batch_experiment.py`: SHA256 `9f945a6da6037f7300fc35f92e12c9cd7bd760c1a55dd5b7e79b3a4ea01c23fd`
- `tests/test_verda_transport.py`: SHA256 `428ae1117520e01f78edde25b07cce8b553d3ff3429f927db2478b200ba25767`

Il coordinatore ha eseguito indipendentemente `python -m unittest discover -v tests`:

- **1187 test superati, nessuno skip** (esecuzione post-B16 in `59,068 s`, log `post-b16-tests.log`; confermati anche in `leader-tests.log`, `post-b4-tests.log` e `post-b8-tests.log`).
- Copertura degli statement sui nuovi moduli (`leader-coverage.json`): **`866/934` linee eseguibili (`92,72%`)**, di cui `batch_experiment.py` `564/627` linee (`89,95%`, combinata linee+rami `86%`) e `transport.py` `302/307` linee (`98,37%`), con copertura combinata linee+rami complessiva del `90%`.
- `quality-gate-a` e `security-review-specialist-a` sul nuovo client collector/transport: **PASS**.
- `quality-gate-a` sulle esecuzioni live `B4`, `B8` e `B16`: **PASS** (`B16` accettato con l'audit storico read-only del parent descritto sotto). Nessuna nuova review automatica di sicurezza sul core applicativo per i soli toggle remoti di configurazione.

### Finestre temporali e integrita' dei 1608 record HTTP

Tutte le quattro matrici usano la stessa L40S (`size=1`, `max_replica_count=1`), otto processi worker Gunicorn con otto copie del modello in `float32`, immagine `ghcr.io/digitalygo/envai-pii@sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714` e overlay diagnostico verificato (`base_app_sha256` `b0ec5163cd0d9eee05922d4b80718eb26abc762b0612935e1f1ad8275dc3848e`, `helper_sha256` `31a9d653891e401e86f2c110311bba2417dee5c2450c4081c55bee88e328424d`, `detector_source_sha256` `1a0f57a3e4563e8f66b245d38db175f5c368238a53334176c4cd49045e16477e`, `detector_code_sha256` `0a16342e7c87a5053c5f2a74579ba3be9c7a3f5f3964f1afde059b13518d1953`, `manifest_sha256` `a7e71ece5e05307ff9a40f74b1b7542616ad5c733d983628767933d5210d7684`).

| Batch | Pod misurato | PID pronti (owner NVML) | Warmup worker (chiamate / somma / max) | Finestra richieste misurate (UTC) | Richieste valide (raffiche / gruppi) | SHA256 `bursts.jsonl` |
| --- | --- | --- | --- | --- | --- | --- |
| `1` (storico preservato) | replica del 28 ottobre | `70-77` | `63 / 63 / 1` | `2026-10-28T18:37:31.379614Z` - `18:42:29.808810Z` | `402/402` (`81 / 27`) | `57edaf2e70e8fb8212d65e1eecc502951590afeaa85385d29758b4284b13f993` |
| `4` | `envai-pii-test-bb8bc47ff-2q8l5` | `83-90` (`83`) | `16 / 63 / 4` | `2026-10-29T16:41:46.700559Z` - `16:46:02.938611Z` | `402/402` (`81 / 27`) | `ba2d9ea0aafa81eb1c81a76e084ea9ffce8c5c968b9219a4d43ccbc45c741c60` |
| `8` | `envai-pii-test-7596b899c7-qdk9c` | `82-89` (`82`) | `8 / 63 / 8` | `2026-10-29T17:44:44.862892Z` - `17:48:39.565890Z` | `402/402` (`81 / 27`) | `31124d70bda71c598e38dc408bb99ee7a5a98415105a179b68e3adc9a28aa775` |
| `16` | `envai-pii-test-8449bf7c67-qxrkq` | `82-89` (`82`) | `4 / 63 / 16` | `2026-10-29T18:45:55.480513Z` - `18:49:57.710973Z` | `402/402` (`81 / 27`) | `28abd4687c53abe6df2bbdbf482c7ca702a9e8021caecb6a539c92d345797614` |

Ogni nuova matrice (`B4`, `B8`, `B16`) ha eseguito esattamente `1` richiesta HTTP `200` di warmup autenticata ed esclusa dalle statistiche, seguita da `402` richieste misurate (`403` POST di inferenza per matrice, `1206` nuove richieste misurate tutte `200` con oracolo canonico `ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`). `B1` non e' stato rieseguito (`b1_replayed: false`) e le sue `402` righe sono state ricalcolate direttamente dal JSONL grezzo originale.

### Tabella comparativa completa delle 24 celle (latenza, throughput e metriche GPU)

I valori seguenti provengono da `leader-comparison.json` e dalle correlazioni verificate dal parent. Per `B1`, le statistiche GPU provengono dall'audit nativo storico del 28 ottobre (la percentuale del memory controller per singola cella e il JSONL locale dei campioni NVML non erano stati archiviati in `B1` e restano indicati come `n/d`, senza valori inventati).

| Batch | Concorrenza | Successi | Media (s) | P95 (s) | Somma gruppi (s) | Richieste/s | GPU media (%) | Mem ctrl medio (%) | Campioni attivi | Copertura 1 Hz (%) | Potenza media (W) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `1` | `1` | `30/30` | `1,823119` | `1,852424` | `54,695531` | `0,548491` | `16,11` | `n/d` | `54` | `n/d` | `153,00` |
| `1` | `2` | `36/36` | `1,938944` | `2,028758` | `35,453986` | `1,015401` | `45,83` | `n/d` | `36` | `n/d` | `185,00` |
| `1` | `4` | `48/48` | `2,574119` | `3,612551` | `37,448542` | `1,281759` | `64,06` | `n/d` | `36` | `n/d` | `205,00` |
| `1` | `8` | `96/96` | `3,560389` | `5,472892` | `57,734196` | `1,662793` | `71,65` | `n/d` | `57` | `n/d` | `235,00` |
| `1` | `16` | `96/96` | `6,288389` | `9,395524` | `54,279588` | `1,768621` | `71,59` | `n/d` | `54` | `n/d` | `240,00` |
| `1` | `32` | `96/96` | `10,872464` | `14,007766` | `42,595861` | `2,253740` | `87,14` | `n/d` | `42` | `n/d` | `273,00` |
| `4` | `1` | `30/30` | `1,153778` | `1,249313` | `34,615613` | `0,866661` | `11,94` | `1,09` | `35` | `100,00` | `132,81` |
| `4` | `2` | `36/36` | `1,198030` | `1,309262` | `21,950506` | `1,640053` | `29,00` | `3,37` | `19` | `86,36` | `152,67` |
| `4` | `4` | `48/48` | `1,509908` | `2,564284` | `21,106890` | `2,274139` | `45,05` | `5,38` | `21` | `95,45` | `196,70` |
| `4` | `8` | `96/96` | `2,201538` | `3,488409` | `36,340362` | `2,641691` | `53,05` | `7,11` | `38` | `100,00` | `221,39` |
| `4` | `16` | `96/96` | `3,735209` | `5,626851` | `31,650870` | `3,033092` | `63,61` | `8,45` | `31` | `96,88` | `244,99` |
| `4` | `32` | `96/96` | `6,630575` | `9,369125` | `28,294714` | `3,392860` | `69,62` | `9,28` | `29` | `100,00` | `259,52` |
| `8` | `1` | `30/30` | `1,027804` | `1,094380` | `30,836053` | `0,972887` | `15,03` | `4,83` | `30` | `96,77` | `144,38` |
| `8` | `2` | `36/36` | `1,102440` | `1,622194` | `20,380870` | `1,766362` | `28,70` | `9,10` | `20` | `95,24` | `159,68` |
| `8` | `4` | `48/48` | `1,341716` | `1,923248` | `19,041750` | `2,520777` | `43,67` | `13,67` | `18` | `90,00` | `174,03` |
| `8` | `8` | `96/96` | `1,981459` | `2,677468` | `30,728976` | `3,124087` | `69,25` | `21,79` | `28` | `90,32` | `230,66` |
| `8` | `16` | `96/96` | `3,223674` | `4,614377` | `27,807128` | `3,452352` | `71,00` | `21,50` | `26` | `92,86` | `251,96` |
| `8` | `32` | `96/96` | `5,974584` | `8,247637` | `23,839568` | `4,026919` | `81,17` | `25,09` | `23` | `95,83` | `283,06` |
| `16` | `1` | `30/30` | `1,014894` | `1,072646` | `30,448639` | `0,985266` | `12,94` | `4,33` | `33` | `100,00` | `139,09` |
| `16` | `2` | `36/36` | `1,165427` | `1,760677` | `22,366161` | `1,609574` | `25,30` | `8,26` | `23` | `100,00` | `164,13` |
| `16` | `4` | `48/48` | `1,364104` | `2,016599` | `18,853564` | `2,545938` | `37,39` | `12,28` | `18` | `94,74` | `167,96` |
| `16` | `8` | `96/96` | `1,988593` | `2,751272` | `31,707120` | `3,027711` | `63,93` | `20,86` | `28` | `87,50` | `236,45` |
| `16` | `16` | `96/96` | `3,550220` | `5,548307` | `29,878071` | `3,213059` | `60,10` | `19,38` | `29` | `96,67` | `249,37` |
| `16` | `32` | `96/96` | `5,597851` | `8,063148` | `24,491081` | `3,919794` | `75,96` | `24,56` | `25` | `100,00` | `276,44` |

### Risorse campionate, margini di sicurezza e conteggio campioni NVML

La VRAM visibile del dispositivo e' `50878152704` byte (`47,383972168 GiB`, arrotondato a `47,384 GiB`) e il limite RAM del container e' `62277025792` byte (`58 GiB`). Il cgroup leaf `pids.max` e' `unbounded` (`pids_limit: null`); la guardia `409` su budget sperimentale `512` e' un limite di sicurezza dell'esperimento, non una quota del provider.

| Batch | VRAM max usata (GiB / byte) | VRAM libera min (%) | Picco RAM kernel (GiB / byte) | RAM corrente max (byte) | RAM libera min (%) | PID max | Campioni NVML totali / attivi | Campioni base | GPU media globale / Mem ctrl (%) | Potenza media / picco (W) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `1` (storico) | `13,482 GiB` | `71,550%` | `8,806 GiB` | `9454882816` | `>= 84,8%` | `102` | `302 / 279` | `1192` | `58,91% / n/d` | `215,69 / 308,333` |
| `4` | `13,7943115234 GiB` (`14811529216`) | `70,888%` | `8,8021812439 GiB` (`9451270144`) | `9450012672` | `84,826%` | `106` | `275 / 173` | `1091` | `45,79% / 5,87%` | `203,55 / 310,353` |
| `8` | `14,0911865234 GiB` (`15130296320`) | `70,262%` | `8,80100250244 GiB` (`9450004480`) | `9447849984` | `84,829%` | `103` | `249 / 145` | `990` | `51,47% / 15,99%` | `208,12 / 326,357` |
| `16` (collector) | `15,2630615234 GiB` (`16388587520`) | `67,789%` | `8,80948638916 GiB` (`9459113984`) | `9458876416` | `84,812%` | `105` | `263 / 156` | `1054` | `45,60% / 14,83%` | `206,10 / 340,111` |
| `16` (audit parent) | `15,2630615234 GiB` (`16388587520`) | `67,789%` | `8,80948638916 GiB` (`9459113984`) | `9458876416` | `84,812%` | `105` | `268 / 156` | `1070` | `45,60% / 14,83%` | `206,10 / 340,111` |

In tutte le matrici `B4`, `B8` e `B16` il minimo di campioni NVML attivi per singola cella e' almeno `18` (soglia richiesta `10`), con `0` anomalie di correlazione, clock, cross-worker, duplicazione o schema e `0` uscite di worker o churn di replica durante l'intera finestra misurata.

### Trasparenza metodologica e deviazioni operative preservate

La procedura complessiva ha incontrato errori operativi intermedi nei subagent, tutti chiusi in sicurezza a `paused`/`min=0`/`0` repliche e preservati nei rispettivi file senza essere nascosti o trasformati in PASS:

1. **Tentativi `B8` prima del run completato (`live-b8`, `live-b8-ready`, poi `live-b8-c`):**
   - Il membro primario (`backend-dev-a`) e' terminato con errore del provider prima di creare file.
   - Il fallback (`backend-dev-b`) ha prima registrato un falso stop pre-resume (`live-b8/final.json` alle `17:11:42.832Z`, `unexpected_RuntimeError`) perche' il readback limitato dopo il PATCH dell'entrypoint `B8` non si era ancora propagato; i successivi controlli read-only (`cleanup-followup.json` e `final-followup.json` alle `17:13:59.576Z`) hanno confermato che l'entrypoint `B8` era gia' applicato con `0` chiamate di inferenza e deployment fermo a `paused`/`min=0`/`0` repliche.
   - Nel secondo tentativo (`live-b8-ready`), il fallback ha attivato il deployment (`min=1` e `resume`), ma il suo client ha esaurito la deadline di raccolta dei log di readiness (`log_collection_deadline`) con `0` warmup e `0` richieste HTTP misurate, ha eseguito il cleanup a `paused`/`min=0`/`0` repliche (`17:30:45.441Z`) e poi ha sollevato un `AttributeError` durante la costruzione del ledger API post-cleanup (`api-ledger.json` registra `accounting_complete: false` per i conteggi intermedi di polling pre-cleanup, finalizzato offline alle `17:32:58.129Z` senza ripetere mutazioni o inferenze).
   - Il membro `backend-dev-c` (`live-b8-c`) ha riutilizzato il comando verificato di `B4` con clock monotoni coerenti per le deadline di readiness, completando warmup, `402/402` richieste, correlazione GPU e cleanup (`17:48:59.265Z`).
2. **Tentativi `B16` e doppia attivazione sequenziale (`live-b16-attempt1-preflight-failed`, `live-b16-attempt2-gate-failed`, poi `live-b16-c`):**
   - **Tentativo 1 (`live-b16-attempt1-preflight-failed`, `18:25:59.148Z`):** fermato in preflight per un confronto errato della chiave `healthcheck` (`healthcheck: false`), con `0` mutazioni e `0` inferenze.
   - **Tentativo 2 (`live-b16-attempt2-gate-failed`, pod `envai-pii-test-8449bf7c67-zmnt5`):** ha applicato il PATCH entrypoint `B16`, impostato `min=1` ed eseguito `resume` (prima attivazione GPU `B16`), ma il polling di readiness non ha raccolto in tempo tutte le righe di ingestione (`RuntimeError: readiness gate not satisfied within budget`) con `0` warmup e `0` inferenze; ha quindi eseguito il cleanup verificato a `paused`/`min=0`/`0` repliche alle `18:35:55.830Z`.
   - **Tentativo 3 (`live-b16-c`, pod `envai-pii-test-8449bf7c67-qxrkq`):** e' partito con l'entrypoint `B16` gia' configurato (`state_at_start: b16_exact`, `patched_this_run: false`, senza reinviare il PATCH del deployment), ha eseguito una seconda attivazione sequenziale della singola GPU (`min=1` e `resume`), ha verificato gli otto PID `82-89`, il warmup `4/63/16`, il warmup HTTP escluso e tutte le `402/402` richieste misurate, terminando con cleanup a `paused`/`min=0`/`0` repliche alle `18:51:00.242Z`.
   - Per `B16` si sono quindi verificate **due attivazioni GPU sequenziali** (mai due GPU simultanee e nessun replay di richieste HTTP misurate).
3. **Motivo `gpu_log_collection_failed` in `B16` e audit storico read-only del parent:**
   - Nel file originale `live-b16-c/matrix-b16/result.json` (preservato inalterato), il campo `stop_reason` vale `gpu_log_collection_failed` perche' la rilettura finale dei log post-matrice ha esaurito il budget di `30 s` del collector. Nonostante cio', `matrix_complete: true` e `gpu_evidence_sufficient: true` erano gia' veri nel file originale, con `263` campioni NVML (`156` attivi e `107` inattivi) e `1054` campioni base.
   - L'affermazione di un delegato secondo cui mancherebbero `40` campioni negli ultimi `26 s` della matrice **e' smentita dai dati grezzi e respinta**: i `263` campioni originali contenevano gia' tutti i `156` campioni attivi dell'intera matrice, inclusi tutti i `25` campioni attivi degli ultimi `24,491 s` (`CC32`, copertura `100%`).
   - Il parent ha eseguito un audit read-only tramite management API (`leader-b16-audit.json` e `leader-b16-gpu-correlation.json`, `2026-10-29T18:57:48.974474+00:00`) con `6` query storiche non troncate (`<= 55 s` ciascuna) sull'intervallo `2026-10-29T18:44:50.480513+00:00` - `18:50:07.710973+00:00`, recuperando `268` campioni NVML (`leader-b16-gpu-samples.jsonl`), `1070` campioni base (`leader-b16-base-samples.jsonl`) e tutte le attestazioni di readiness degli otto PID `82-89`. L'audit non rimuove alcun campione originale e aggiunge `5` campioni (`1` pre-matrice e `4` post-HTTP) tutti **inattivi ai fini della correlazione** (esterni alle finestre di trasporto delle richieste misurate; inattivo per la correlazione non significa utilizzo GPU grezzo pari a zero). Tutte le `156` osservazioni attive e tutte le statistiche per cella e complessive coincidono al bit con la correlazione originale. `quality-gate-a` ha accettato `B16` sulla base di questo audit read-only senza riscrivere `result.json`.

### Interpretazione tecnica e raccomandazione

- **Guadagno rispetto a `B1`:** raggruppare i chunk riduce drasticamente la latenza e aumenta il throughput a tutti i livelli di concorrenza. A `CC32`, `B8` riduce la latenza media del **`45,05%`** (`5,974584 s` contro `10,872464 s`) e il p95 da `14,007766 s` a `8,247637 s`, portando il throughput da `2,253740` a **`4,026919` richieste/s** (**`1,78677x`**, ossia **`+78,68%`**). `B16` riduce la latenza media a `CC32` del **`48,51%`** (`5,597851 s`, p95 `8,063148 s`), con `3,919794` richieste/s.
- **Confronto `B8` vs `B16`:** `B8` ottiene il throughput (`requests_per_second`) piu' alto osservato a `CC8` (`3,124087` vs `3,027711`), `CC16` (`3,452352` vs `3,213059`) e `CC32` (`4,026919` vs `3,919794`), oltre a latenze medie e p95 inferiori a `B16` per `CC2`, `CC4`, `CC8` e `CC16`, mantenendo piu' margine VRAM (`70,262%` libera, picco `14,091 GiB` contro `67,789%` libera e `15,263 GiB` di `B16`). `B16` prevale sulla latenza media solo a `CC1` (`1,014894 s` vs `1,027804 s`) e `CC32` (`5,597851 s` vs `5,974584 s`) e per un margine minimo di RPS a `CC4` (`2,545938` vs `2,520777`), non risultando un vincitore universale.
- **Limiti d'interpretazione:** le quattro matrici sono state eseguite in finestre temporali diverse e su allocazioni pod distinte, senza isolare causalmente nodo fisico, stato termico, distribuzione delle connessioni HTTP fra gli otto worker o cadenza dei contatori. Il test usa un singolo documento sintetico da `45000` caratteri (`63` chunk) e non costituisce uno studio statistico multi-corpus, un SLA o una certificazione di accuratezza del modello. I contatori NVML (`gpu_activity_percent` e `memory_controller_activity_percent`) misurano la frazione di tempo con motore attivo sul dispositivo, non l'occupazione degli SM/FLOPs ne' la banda di memoria in byte, e i watt campionati non rappresentano la fatturazione del provider.
- **Raccomandazione operativa:** mantenere il default `PII_MODEL_BATCH_SIZE=1` nel sorgente (nessuna attivazione automatica e nessuna ricostruzione dell'immagine in questo task) e proporre **`PII_MODEL_BATCH_SIZE=8` (`B8`) come candidato per la validazione su una futura immagine di produzione**.

## Stato finale del deployment e percorsi

Alle **`2026-10-29T18:57:48.974474+00:00`** (`leader-b16-audit.json`), i controlli nativi read-only del parent dopo il cleanup delle `18:51:00.242Z` confermano:

- stato `paused`, `min_replica_count: 0`, `max_replica_count: 1`, `concurrent_requests_per_replica: 32`, `replicas.list: []`;
- comando overlay diagnostico `B16` ancora configurato su `envai-pii-test-0` ma inattivo (compute spento per questo deployment; nessuna affermazione di costo zero globale per l'account);
- nessuna modifica a `src/app/app.py`, `src/app/model_batching.py` (default `1`), `Dockerfile.gpu`, autenticazione, segreti o altri deployment.

Un'ulteriore verifica nativa read-only alle `2026-10-29T19:26:42.223652+00:00` conferma lo stesso stato spento e l'entrypoint B16 esatto (`leader-final-verification.json`). Il parent ha inoltre confrontato entrambe le tabelle documentali di 24 celle con i risultati grezzi verificati, controllato i permessi privati e verificato l'assenza dei tre valori di credenziali reali in 76 file del task.

## Percorsi e limiti

- [Guida del parametro](../../../docs/chunk-batching.md), [contratto API](../../../docs/GUARDRAIL_API.md) e [stato Verda](../../../docs/verda-service.md).
- [Piano e ledger](../plans/2026-10-28-chunk-batching.md), [ricerca iniziale](../research/2026-10-28-chunk-batching-inspection.md), [handoff storico superato](../research/2026-10-29-chunk-batching-handoff.md) e [precedente B1 misurato](2026-10-28-verda-eight-model-gpu-profile.md), che rimane storico.
- Evidenze private della ripresa finale: `/home/lorenzo/private/tmp/envai-pii-batching-resume-20261029/` (permessi `0700`, file `0600`), inclusi `leader-comparison.json`, `leader-b16-audit.json`, `leader-b16-gpu-correlation.json`, `leader-b16-gpu-samples.jsonl`, `leader-b16-base-samples.jsonl`, `collector-review-manifest.json`, `leader-all-evidence-manifest.json`, `leader-coverage.json`, `leader-tests.log`, `post-b4-tests.log`, `post-b8-tests.log`, `post-b16-tests.log` e le directory `live-b4/`, `live-b8/`, `live-b8-ready/`, `live-b8-c/`, `live-b16-attempt1-preflight-failed/`, `live-b16-attempt2-gate-failed/` e `live-b16-c/`, oltre alla directory storica `/home/lorenzo/private/tmp/envai-pii-batching-20261028/` (`resume1818-b1-*`). Nessun segreto reale, corpo di richiesta/risposta, `dictionary_delta`, bearer token, comando raw o UUID GPU grezzo e' salvato negli artefatti.
- Nessun processo, container o server locale effimero resta attivo. Nessun commit, stage, push o nuova release e' stato eseguito. Test e copertura per la sola chiusura documentale Markdown sono N/A; restano invariati i **1187 test superati senza skip** e le coperture verificate del codice (`99,82%` core batching, `92,72%` statement / `90%` combinata per collector e transport).
