# Capacita' su una singola GPU RunPod, 2026-10-25

Report di un esperimento diagnostico autorizzato sul Pod `38bhifvthu51px` (una A40). Risponde alla domanda: quanto lavoro puo' fare una sola GPU prima di pensare a piu' GPU o a un budget Serverless. Non e' una modifica del servizio pubblico e non e' una release.

> [!warning]
> Stato aggiornato al 2026-10-25 23:31:48 UTC (2026-10-26 ora locale): il Pod `38bhifvthu51px` e' **spento** (`EXITED`) su richiesta dell'utente. Nessun URL live e' disponibile e il servizio non e' in esecuzione. Le misure di questo report sono dati storici datati; la frase "servizio lasciato acceso" descrive lo stato di quel momento, non quello attuale. Vedi la sezione finale "Esperimento con coda a 4 modelli fissi".

## Sintesi

- Il limite di 2 client del [report di carico e prezzi](runpod-load-pricing.md) era il budget operativo seriale della configurazione di allora (v4, un forward alla volta), non un limite della A40.
- Il primo passo efficiente e' rendere piu' efficiente il core su una GPU, non assegnare una GPU a ogni richiesta. Un futuro Serverless con minimo 0 e massimo 1 e' solo una proposta di budget iniziale, non e' stato distribuito. Con 1000 job in arrivo si accoda e si applica backpressure su 1000 job, non si servono 1000 GPU.
- Quattro copie del modello sulla stessa GPU sono risultate fattibili, con 16 chiamate core in volo configurate. Gli slot non sono 16 forward GPU contemporanei: con 4 repliche ogni proprietario esegue una pipeline.
- Il servizio pubblico, dopo il ripristino, resta con un worker, batch 1 e ammissione 4 attive, 4 in coda, 5 s. Non include queste ottimizzazioni sperimentali e il parallelismo 16 non e' attivo.
- Il candidato "4 processi con batch di 16 chunk" richiede implementazione e validazione con carico HTTP normale e accuratezza prima della produzione.

## Ambito e ambiente

| Voce | Valore |
| --- | --- |
| Pod e GPU | `38bhifvthu51px`, una A40 fisica, CUDA conta 1 device per tutti i worker (stesso device ereditato) |
| Tariffa | `0.59` USD/h, servizio lasciato acceso come richiesto dall'utente |
| Modello | incluso nell'immagine, revisione del modello `v1.5.0`, Torch `2.13.0+cu130`, `float32`, invariati |
| Sorgente e immagine | invariati; nessuna modifica ai pin ML; nessuna modifica persistente al codice o all'API |
| Orchestratore | `21:19:44.545Z` fino a `21:22:17.190Z`, `152.64458` s, 0 skip, 0 errori |
| Eventi | 71 eventi (22 `CASE`, 22 `WARMUP`) e marcatori del supervisore |
| Esiti | 22 casi, 240 richieste misurate, tutte `200`, tutte valide e con corrispondenza semantica con la baseline |

Il corpus contiene 8 documenti legali sintetici per dimensione (1000 e 45000 caratteri), con otto template distinti, tutte le categorie e nessun seed. Un documento da 45000 caratteri vale circa 64 chunk (finestra di 120 parole, sovrapposizione 20).

## Metodo e limiti

- Si chiama direttamente `guardrail_api.process_request`, il core di produzione, dentro il container con ammissione privata a concorrenza da 1 a 16. Mancano HTTP, TLS, rete e proxy.
- Corpus diverso dal benchmark HTTP precedente: nessun confronto assoluto con quei numeri.
- Serie brevi a concorrenza fissa con N pari a `max(8, 2*cc)`, non un soak test da 15 minuti. Con n pari a 8, 16 o 32 gli intervalli di confidenza e le code sono poco affidabili.
- Inizializzazione e warmup sono separati. Per le repliche si fa un warmup lungo con B16 prima di una barriera di READY, in Python nuovo con `exec` (non fork, che per CUDA non e' sicuro).
- NVML con UUID rigoroso non e' disponibile (motivo `device_uuid_unavailable`): la percentuale di utilizzo GPU ad alta frequenza e' non disponibile, non 0. Memoria libera e allocata CUDA ed eventi CUDA sono reali. I vecchi valori 0/10% di "memoria" della telemetria provider non erano RAM allocata.
- `cpu_thread_count` di Torch (48) conta thread configurati disponibili sull'host, non 48 core usati; il Pod nativo ha 9 vCPU. Si riporta `process_time` rispetto al tempo effettivamente trascorso, senza dedurre una quota CPU normalizzata.
- Il tempo `pipeline.preprocess` misura probabilmente solo la creazione del generatore lazy (ChunkPipeline), campo in microsecondi, non la tokenizzazione completa. E' escluso da ogni affermazione sul collo di bottiglia CPU e non si diagnostica il tokenizer come unico collo di bottiglia.
- Il tempo degli eventi CUDA sullo stream include dispatch e contesa: non e' una percentuale di utilizzo degli SM.
- La matematica dei pesi dell'API sorgente e' invariata.

## Memoria in byte reali

Conversioni verificate da byte a GiB. La memoria CUDA visibile misurata e' riportata separatamente dalla capacita' nominale di 48 GB del catalogo.

| Misura | Byte | GiB |
| --- | --- | --- |
| Totale GPU visibile a CUDA | `47699722240` | `44.423828` |
| Parametri e buffer per modello | `1230259892` | `1.145769` |
| Allocata da Torch (un modello) | `1258966528` | `1.172504` |
| Riservata da Torch (un modello, B16) | `1405091840` | circa `1.309` |
| Massimo allocato per processo (B16) | `1375418880` | `1.280959` |
| Usata globale, 1 copia, B16 | `1745027072` | `1.625183` |
| Usata globale, 2 copie | `3487039488` | `3.247559` |
| Usata globale, 4 copie | `6971129856` | `6.492371` |

- La memoria usata globale e' totale meno libera ai checkpoint di campionamento. Il picco globale di VRAM non e' stato misurato, solo i checkpoint; per processo si distinguono memoria riservata, allocata e contesto CUDA.
- Con 4 copie circa il 14.6% della VRAM visibile risulta usato e non ci sono stati OOM. Lo spazio libero resta ampio, ma non prova che altre copie continuino a migliorare. Il massimo di repliche provato e' 4, non il massimo fisico.

## Sweep del batch su una copia

Stesso corpus da 45000, 8 documenti per caso, concorrenza 1. Il batch e' di chunk della stessa analisi, non di richieste intere. Tempi in secondi.

| Batch | Media | P95 | QPS | Rispetto a B1 |
| --- | --- | --- | --- | --- |
| 1 | `1.138052` | `1.271345` | `0.877400` | `1.000000x` |
| 2 | `0.807343` | `0.921910` | `1.236362` | circa `1.409x` |
| 4 | `0.663785` | `0.688345` | `1.502859` | circa `1.713x` |
| 8 | `0.652970` | `0.700669` | `1.527534` | circa `1.741x` |
| 16 | `0.605421` | `0.624281` | `1.647219` | `1.877386x` |

B16 e' il migliore tra quelli provati, non un ottimo universale: B32 e B64 non sono stati eseguiti. Tutte le uscite sono uguali, per hash del corpo JSON, al controllo diagnostico con batch 1 che riproduce il rilevatore esistente. E' una prova minima di equivalenza su questo corpus, non un confronto HTTP con l'endpoint pubblico ne' una certificazione di accuratezza.

## Concorrenza su una copia con B16

Lunghi da 45000, 8 richieste per cc1, 2 e 4; 16 per cc8; 32 per cc16. Separato dallo sweep (la varianza del tempo trascorso cambia con n=8 e cc1).

| Client | Media | P95 | QPS |
| --- | --- | --- | --- |
| 1 | `0.623784` | `0.734020` | `1.599190` |
| 2 | `1.181016` | `1.420485` | `1.581120` |
| 4 | `2.311133` | `4.620415` | `1.569320` |
| 8 | `4.988518` | `9.807284` | `1.421750` |
| 16 | `9.483658` | `20.340397` | `1.403390` |

Aumentare i client alza l'attesa: il QPS di una copia resta quasi piatto da 1 client in su. Non si possono promettere 1000 risposte immediate.

## Repliche con B16, 4 client per processo

| Copie | Globale | Richieste | Media combinata | P95 combinato | QPS aggregato | Tempo a muro |
| --- | --- | --- | --- | --- | --- | --- |
| 1 (cc8) | 8 | 16 | `4.988518` | `9.807284` | `1.421750` | `11.253760` s |
| 2 | 8 | 16 | `2.864798` | `4.676395` | `2.062972` | `7.755803` s |
| 4 | 16 | 32 | `4.311380` | `7.286045` | `3.013062` | `10.620426` s |
| 1 (cc16) | 16 | 32 | `9.483658` | `20.340397` | `1.403390` | `22.801947` s |

- Rapporti: 4 copie contro il controllo B1 `3.434081x`; 4 contro una copia a cc16 e B16 `2.146990x`; 2 contro una copia a cc8 `1.451012x`. Media e P95 a cc16 migliorano molto con la replicazione.
- Il QPS aggregato usa il tempo a muro globale (`7.755803` e `10.620426` s), che comprende uscita e drain dei processi: non e' il regime stazionario di un server. I QPS per worker non si sommano perche' i tempi sono diversi. Il P95 combinato a 4 copie non e' `6.119` per worker.
- La contesa e' reale: il tempo CUDA per richiesta cresce rispetto a una copia. La replicazione non e' scalata in modo lineare, perche' il calcolo GPU e' condiviso.

## Testi corti

Una copia, B16, 1000 caratteri: cc1 media `0.020770` s e `47.605` QPS; cc16 media `0.409840` s e `28.688` QPS. Il test per replica a 1000 caratteri non e' stato eseguito e 100 caratteri non sono stati ritestati. I risultati sulle repliche per documenti lunghi non valgono per tutte le dimensioni di testo.

## Procedura operativa del provider

- Una PATCH dei soli argomenti ricicla il container in automatico, in modo asincrono. La prima procedura prevedeva solo metadati, ma PATCH degli argomenti, riavvio esplicito e ripristino anticipato hanno causato 3 cicli di container e perso i log diagnostici iniziali: nessuno di questi dati e' usato come risultato.
- La procedura corretta e' stata: PATCH dei soli argomenti senza riavvio esplicito, comando lasciato fino a DONE, tutti i record catturati prima del PATCH finale di ripristino (anch'esso con riciclo automatico).
- In tutto 5 sostituzioni di container osservate e una sola azione di riavvio esplicita, sempre sullo stesso Pod e sulla stessa GPU. Non e' corretto dire "un solo riavvio effettivo".
- Primo T0 `21:11:13Z` con scadenza originale dei 15 minuti `21:26:13Z`. La diagnostica senza esposizione HTTP va dalle `21:19:44.545Z` alle `21:22:17.190Z`. Il container finale ha usato il comando predefinito `21:24:18Z`, modello pronto `21:24:25Z`, salute verificata `21:25:52Z`, prima della scadenza.
- Dopo il ripristino, i campi mutabili di configurazione, riletti indipendentemente a fine prova, coincidono con la baseline: argomenti vuoti, immagine, ambiente, hardware e costo `0.59`; il comando e l'entrypoint derivati sono omessi, come normale. Il vecchio Pod `2glj7taobhnhvg` resta `EXITED` e intatto.
- Smoke canonico di ripristino: 6 superati (il 401 negativo e' atteso), con verifica che i log e gli artefatti non contengano il token reale. Nessuna nuova GPU, chiave, porta, volume o immagine, nessun stop o start. Nessuna ottimizzazione in-place dell'API e il predefinito B1 e' stato ripristinato.

## Verifica

- Test: 93 test temporanei e 856 test del repository, tutti superati, senza skip. Copertura `1195/1340` righe, `89.18%`, ogni file sopra `86%`.
- Il quality gate e la revisione di sicurezza pre-live sono passati.
- Nessun cambiamento persistente al codice o all'API. Il repository ha solo modifiche alla documentazione.
- Gli helper e le evidenze locali sono conservati per l'audit. L'ambiente virtuale temporaneo viene rimosso alla chiusura delle verifiche.

## Provenienza dei file

Cartella `/tmp/envai-pii-gpu-capacity-20261025/logs/`:

- `remote-final.json`: 71 eventi e marcatori del supervisore (fonte dei numeri sopra, ricalcolati indipendentemente);
- `remote-events-before-restore.json`: eventi catturati prima del ripristino;
- `verification.json`, `unit-tests.txt`, `coverage.txt`, `leader-coverage.json`, `leader-tests.log`, `repository-tests.log`: verifiche dei test.

La baseline usa gli hash dei corpi JSON degli 8 documenti sintetici, registrati nei file grezzi. I numeri a precisione piena sono nei file grezzi.

Guide correlate: [benchmark di carico e prezzi](runpod-load-pricing.md), [guida al servizio RunPod](runpod-service.md), [changelog](CHANGELOG.md).

## Esperimento con coda a 4 modelli fissi

Aggiornamento del 2026-10-26; gli orari degli eventi sono in UTC del 2026-10-25. Riporta un esperimento diagnostico, non una distribuzione di ottimizzazioni: nessuna ottimizzazione sorgente o API e' stata abilitata.

### Cattura parziale

Fonte: `/tmp/envai-pii-gpu-queue-20261025/logs/remote-final.json`. La cattura e' **parziale** e l'esecuzione da 9 round e 288 richieste non va considerata completa.

- Eventi catturati: 5 `START`, 4 `READY`, 248 `REQUEST`, 28 `ROUND_DONE`, 7 `ROUND_SUMMARY`; zero `ERROR`, zero `DONE` e zero eventi del supervisore.
- Round 0..6 completi (224 richieste); il round 7 ha solo 24 richieste su 32 e il round 8 manca. Il round 7 e' escluso del tutto dalle statistiche per evitare un bias da coda mancante.
- Limite operativo: la cattura dei log nativi RunPod e' andata in timeout, quindi le ultime 40 richieste e il `DONE` radice non sono verificabili (`metricsCaptureComplete` e `completeObserved` falsi). L'assenza di `ERROR` registrati non prova che l'esecuzione sia riuscita per intero.
- I dati sono stati salvati in locale prima della pulizia. Non sono state eseguite altre prove GPU per colmare il vuoto: il Pod e' stato spento su richiesta dell'utente.
- Tutte le richieste catturate: `200`, hash, controlli di sanita' e contabilita' di fase validi. Gli hash dei corpi corrispondono all'oracolo della baseline B1 su otto documenti.
- Pipeline su CUDA reale, ma senza HTTP, TLS, proxy o avvio a freddo e senza nuova certificazione di accuratezza.

### Confronto bilanciato

Round 0..5: 192 richieste, 64 per livello di concorrenza globale (CC) 4, 8 e 16, con gli stessi 4 modelli persistenti (PID invariati), B16, su una A40, con otto documenti sintetici da 45000 caratteri. Tempi in secondi.

| CC | Media | p95 | QPS | Coda | Proprietario | Fuori |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | 1.166477 | 1.325426 | 3.394969 | 0.000618 | 1.081110 | 0.084750 |
| 8 | 2.264553 | 3.454907 | 3.342771 | 1.026372 | 1.162027 | 0.076153 |
| 16 | 4.200455 | 5.837477 | 3.351383 | 2.980071 | 1.145755 | 0.074629 |

- Per ogni richiesta vale `TOTALE = attesa + proprietario + fuori`. A CC16 circa il 71% della risposta media e' attesa del gate nativo e dell'esecutore, non una coda di ammissione dell'App.
- Scomposizione del proprietario a CC16 senza sovrapposizioni: `PRE` 0.088196, chiamata `FORWARD` 0.764585, `POST` 0.261121, `SYNC` 0.000217, `OTHER` 0.031636 (somma 1.145755).
- L'evento CUDA del forward (688.430443 ms a CC16, 697.577316 ms a CC4) si sovrappone alla chiamata `FORWARD`: non si somma al tempo del proprietario e non e' utilizzo degli SM. Il timer corretto del pre-processo con generatore pigro misura il tempo reale dell'iterazione, non secondi CPU.
- La contesa sulla GPU tra le 4 copie esiste ancora, ma con modelli fissi portare le richieste da 4 a 16 non ha aumentato ne' il tempo di forward ne' il QPS: l'aumento della latenza e' dovuto quasi interamente all'attesa in coda.
- Il round 6 (CC8, completo) e' una sensibilita' extra e non entra nella tabella primaria, che resta a 64 richieste per livello.

### Interpretazione e limiti

- Miglior candidato provato: 4 attive in totale (una per modello) con coda limitata a monte. Non va confuso con le 4 attive del servizio distribuito con un solo modello.
- Quattro copie non sono il massimo fisico della GPU.
- Il QPS di `3.013` del report precedente non e' confrontabile direttamente: quell'aggregato includeva il drenaggio all'uscita dei processi, i round persistenti nuovi no.
- Prezzi invariati (`0.59` USD/h quando il Pod e' acceso).

### Verifiche sorgente

Helper sorgente: 36 test, 34 test di sicurezza riutilizzati e 856 test del repository superati. Quality gate e revisione di sicurezza mirata superati. Copertura del delta nuovo: 667/802 = 83.167% (driver 478/588, supporto 189/214). Nessuna modifica a framework, pin, dtype o precisione.

### Cronologia operativa e stato finale

| Evento (UTC, 2026-10-25) | Ora |
| --- | --- |
| `PATCH` degli argomenti diagnostici (T0) | 23:15:21.301 |
| `PATCH` per ripulire gli argomenti | 23:26:55.326 |
| Salute del modello su CUDA `200` (entro T0+900 s) | 23:28:25.513 |
| Invio dell'azione di stop autorizzata | 23:31:46.678 |
| `EXITED` verificato | 23:31:48.038 |

- Due `PATCH` con riciclo automatico, zero riavvii espliciti. La configurazione mutabile nativa e' tornata alla baseline.
- Lettura fresca indipendente: `EXITED`, argomenti `''`, `runtime=null`. E' stato fermato solo `38bhifvthu51px`; disco 20 GB, nessun mount, nessuna eliminazione o terminazione.
- Calcolo GPU/CPU spento. Un eventuale costo di storage persistente non e' quantificato e non si afferma che lo storage sia gratuito.
- Configurazione attuale (fermo): un worker, B1, 4 attive, 4 in coda, 5 s. Gli argomenti predefiniti fanno ripartire il servizio normale al prossimo avvio autorizzato dall'utente, senza riesecuzione diagnostica; non si implica che sia in esecuzione.
- File grezzi conservati in locale e privati; l'ambiente virtuale temporaneo viene rimosso alla chiusura.

## Tentativo di aumento delle copie del 2026-10-26

La diagnostica progressiva e' pronta per provare 4, 8, 12, 16 e 20 copie, con una richiesta attiva per modello, margini su RAM/VRAM/processi e arresto entro un tempo massimo. Venti e' soltanto il tetto della prova, non una capacita' dimostrata. Preparazione offline: 45 test nuovi, 34 controlli riutilizzati e 856 test del repository superati; copertura del delta 646/753, 85.79%, quality gate e revisione di sicurezza superati.

**Nessuna nuova misura GPU e' stata ottenuta.** Il primo avvio con il comando diagnostico ha restituito `504 Gateway Time-out`; il Pod e' rimasto `EXITED`. Una seconda e ultima verifica con gli argomenti normali, alle 13:08:47 UTC, ha ricevuto un rifiuto esplicito di capacita': le GPU dell'host a cui il Pod fermo e' vincolato sono occupate. Questo non dimostra che manchino A40 in tutti i data center.

La lettura finale conferma `38bhifvthu51px` spento, runtime assente, argomenti vuoti e configurazione invariata. Nessun Pod sostitutivo e' stato creato. I risultati su quattro copie delle sezioni precedenti restano gli ultimi verificati; i livelli superiori non sono stati eseguiti. Per provare un altro host occorre autorizzare una nuova risorsa con una sola GPU e spegnimento a fine prova.

Evidenze locali: `/tmp/envai-pii-gpu-replicas-20261026/logs/remote-final.json` per il timeout e `retry-final.json` per il rifiuto di capacita'. Entrambe riportano zero eventi dell'esperimento e cattura non completa.

### Nuovo Pod autorizzato, prova non eseguita

Dopo il consenso esplicito e' stato creato un solo nuovo Pod, `w2oo9fxu89gpy5`, A40 Secure EU-SE-1, a 0.59 USD/ora, con 55 GB di RAM e 10 vCPU. L'immagine e i riferimenti d'ambiente erano invariati; nessuna porta pubblica, SSH, Jupyter o volume.

La prova **non e' partita**: un errore del controllo operativo ha interpretato il campo di risposta `globalNetworking: {enabled: false}` come difforme dal valore richiesto `false`, sebbene fossero equivalenti. Il Pod e' stato fermato prematuramente, rilasciando la GPU mentre l'immagine veniva ancora scaricata. L'errore non e' del modello o della configurazione richiesta. Il download e' terminato alle 14:45:18 UTC; i successivi tentativi di ripresa dello stesso Pod sono stati rifiutati per mancanza di GPU libere sul suo host. Non e' stato creato un secondo sostituto.

Il 2026-10-26 alle 14:52:01 UTC e nelle letture indipendenti successive il nuovo Pod risulta `EXITED`, runtime assente e argomenti ripristinati. Anche entrambi i Pod precedenti sono spenti. Nessun nuovo `READY`, `CASE` o `STAGE_SUMMARY` e' stato raccolto: quattro copie restano il massimo verificato, non quello fisico. Serve un'ulteriore autorizzazione per un altro Pod su un nuovo host; non riavviare o creare risorse automaticamente.

Evidenze locali: `logs/new-pod-final.json` e `logs/new-pod-resume-final.json` nella cartella della diagnostica progressiva. Il primo evento di creazione e' alle 14:41:34 UTC; lo stop prematuro e' stato richiesto alle 14:42:11 UTC. La scadenza originale di arresto e' stata mantenuta.
