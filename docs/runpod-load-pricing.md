# Benchmark di carico e prezzo su RunPod, 2026-10-25

Benchmark autorizzato dall'utente dell'API `envai-pii` sul Pod di test. Risponde a due domande: quanto costa il Pod per carattere di testo analizzato e quanti client concorrenti il servizio gestisce bene. Tutti gli input sono paragrafi legali italiani sintetici. I costi sono USD approssimati, mai EUR.

> [!note]
> Aggiornamento successivo: il budget di 2 client qui sotto era il budget operativo seriale di allora, non un limite della A40. Un esperimento diagnostico sulla stessa GPU ha trovato un candidato piu' efficiente (4 processi e batch di 16 chunk). Leggere il [report sulla capacita' di una singola GPU](runpod-single-gpu-capacity.md). I prezzi e le unita' di questo report derivano da numeri HTTP precedenti e non si estendono a una nuova tariffa.

## Sintesi

- Il costo del Pod nella finestra occupata per documenti JSON lunghi e' circa `0.0056` USD per 1M di caratteri alla tariffa osservata. E' solo la tariffa del Pod mentre e' caldo e occupato, non un prezzo di vendita.
- Un Pod acceso 24x7 costa `424.80` USD per 30 giorni. A 10M di caratteri al mese sono `42.48` USD per 1M di caratteri. Il costo fisso, non quello della finestra occupata, guida il prezzo commerciale.
- Per documenti lunghi, come budget operativo iniziale e prudente, usare un tetto di 2 client. Non e' un ottimo universale dimostrato. Con 4 client il throughput e' `+5.99%` e la coda peggiora molto. Con 6 e 8 client compaiono risposte `429`.
- Non abbassare ora il limite del server da 4 a 2. Serve un'approvazione separata dell'utente e un riavvio di configurazione separato. L'ammissione attuale a 4 attive resta invariata.

## Ambito e ambiente

| Voce | Valore |
| --- | --- |
| Pod | `38bhifvthu51px`, `RUNNING` |
| Digest immagine | `sha256:c71a392411ab14aed2d4b28bb8e84e5e727f32df6e24e5238b11715d3fbaf9ef` (`v1.0.0-dev.4`) |
| Hardware | A40 x1, Secure Cloud EU-SE-1, `0.59` USD/h |
| Memoria host e CPU | 50 GB di RAM di sistema e 9 vCPU (RAM di sistema, non VRAM); VRAM a catalogo 48 GB |
| Destinazione | URL proxy HTTPS standard del Pod, header segreto esistente, mai stampato |
| Ammissione del server | Predefiniti invariati: 4 attive, 4 in coda, 5 s di attesa in coda |
| Vecchio Pod | `2glj7taobhnhvg` resta `EXITED`, configurazione invariata |

Nessuna modifica a Pod, immagine, modello, chiave, hardware, limiti o training, e nessun nuovo Pod creato.

## Metodo

- Strumento: un driver Python personalizzato, non k6 (k6 non e' installato). SHA-256 del driver as-tested, 64 caratteri: `ac79687146dc92fd62f45c7a9edd51cc02240db0afc3061c483b69b78bd76dcc`.
- Richieste: `POST /api/v1/analyses` JSON, tutte le categorie (nessun filtro), nessun seed, paragrafi legali italiani sintetici variati, un'email univoca per richiesta, dimensioni Unicode esatte di 100, 1000, 10000 e 45000 caratteri spazi inclusi.
- Fasi di prezzo: 2 worker continui, al massimo 100 tentativi o 120 s per profilo. Un warmup di 4 richieste per dimensione e' stato eseguito fuori dai numeri di prezzo e dalle tabelle di costo per profilo. Il warmup e' invece incluso nel costo GPU dell'intera esecuzione (491.644 s, `0.080575` USD, vedi "Contesto dei costi").
- Il profilo da 45000 e' stato interrotto al taglio di 120 s e poi svuotato (drain): la durata totale effettiva e' stata di 121.10 s, drain incluso (circa 1.10 s oltre il taglio). Per questo contiene 79 campioni invece di 100. Nessun timeout arbitrario.
- Fasi di carico: JSON da 45000 caratteri con 1, 4, 6 e 8 client per 60 s piu' drain. La riga da 2 client riusa la fase di prezzo. Un burst da 12 client, una chiamata per client.
- Esecuzione completa: da `18:15:42.609Z` a `18:23:54.253Z`, 491.644 s (8 min 12 s). Limiti: 900 s obiettivo, 25 RPS, 1500 richieste totali. Le risposte `429` hanno backoff di 0.5 s.
- Validazione: ogni risposta `200` e' stata controllata per il proprio valore mascherato, il proprio delta, l'assenza di marcatori estranei e i conteggi dei segnaposto.
- Fase PDF opzionale, esplorativa: 469 richieste, tutte `200`, 469390 caratteri estratti (media circa 1001), tutti PDF nativi digitali, senza OCR. Vedi "Limite del driver sui PDF".

## Contabilita' delle richieste

- 1075 chiamate in totale, incluse 6 chiamate di preflight.
- 1069 righe registrate: 1044 `200` validate piu' 25 `429` attese. Nessun errore di rete, `5xx`, `408`, errore di autenticazione o errore di validazione.
- I 6 controlli di preflight sono passati, inclusi 2 `401` attesi.
- Il riepilogo dell'esecuzione riporta 1050 successi perche' conta i 6 controlli di preflight. Non va letto come 1050 risposte HTTP `200`.
- Le fasi misurate escludono il warmup. I p95 sono nearest-rank sulle sole richieste riuscite, mai sulle `429` veloci.

## Tabella dei prezzi (JSON, 2 client)

Il costo per 1M di caratteri e' `0.59 x secondi trascorsi / 3600 / caratteri riusciti x 1M`. Usa il tempo effettivamente trascorso nella fase e mai la somma dei tempi delle richieste sovrapposte. La colonna normalizzata e' la latenza della richiesta scalata a 100 caratteri, non la latenza di una richiesta da 100 caratteri. Il warmup e' escluso da questa tabella.

| Dimensione (caratteri) | n | Media (s) | p95 (s) | Normalizzata (s per 100 caratteri) | USD per 1M caratteri |
| --- | --- | --- | --- | --- | --- |
| 100 | 100 | 0.137281689 | 0.285358102 | 0.137281689 | 0.116323426 |
| 1000 | 100 | 0.132594482 | 0.174578394 | 0.013259448 | 0.011194146 |
| 10000 | 100 | 0.671338752 | 0.994068804 | 0.006713388 | 0.005534414 |
| 45000 | 79 | 3.053452668 | 5.031468124 | 0.006785450 | 0.005582753 |

- Per i due profili corti il flag di pacing e' stato attivato: il flag scatta a qualsiasi attesa, anche per i circa 40 ms di avvio, quindi non prova una saturazione sostenuta a 25 RPS. Il pacing globale puo' aver ridotto l'occupazione a 2 client. La media misurata e' di 100 successi in 7.098 s, circa 14 RPS, sotto il tetto di 25 RPS (profilo da 100 caratteri). Non e' una stima della capacita' senza tetto a 2 client.
- Per i profili da 10000 e 45000 i flag di riduzione dell'occupazione sono falsi. La preparazione dei PDF nel driver incide comunque sull'occupazione nella fase PDF.
- Una richiesta da 45000 caratteri si normalizza a 6.79 ms per 100 caratteri, ma la sua latenza reale e' 3.05 s.
- I secondi aggregati del Pod per 100 caratteri differiscono dalla latenza per richiesta. Per 45000 caratteri il valore aggregato e' `0.0034064` s, preso dal file delle metriche e non da una stima manuale.
- Il prezzo unitario PDF non e' usato per il costo commerciale (vedi "Limite del driver sui PDF").

## Tabella di carico (JSON da 45000 caratteri)

| Client | Riusciti / tentativi | Media (s) | p95 (s) | Caratteri/s | Note |
| --- | --- | --- | --- | --- | --- |
| 1 | 40 / 40 | 1.531 | 1.795 | 29338 | Coda piu' bassa |
| 2 | 79 / 79 | 3.053 | 5.031 | 29356 | Riferimento |
| 4 | 44 / 44 | 5.706 | 11.679 | 31115 | Max 26.149 s |
| 6 | 43 / 45 | 8.673 | 12.961 | 29028 | 2 `429` (4.44%) |
| 8 | 47 / 64 | 8.777 | 14.488 | 31860 | 17 `429` (26.56%) |
| 12 (burst) | 6 / 12 | 6.287 | 8.117 | 32593 | 6 `200`, 6 `429` |

- 4 client: throughput `+5.99%` rispetto a 2 client. 8 client: `+8.53%` rispetto a 2 client, non 4x. Sono aumenti modesti (circa 6% e 8.5%), non una prova di capacita'.
- 1 client ha un p95 piu' basso a parita' sostanziale di throughput in caratteri/s rispetto a 2 client (29338 contro 29356).
- Media e latenza di coda peggiorano all'aumentare dei client.
- 8 client non sono 8 analisi attive: il server ammette 4 attive e 4 in coda, e il resto viene rifiutato con `429`.
- Causa probabile: il forward del modello e' gestito da un solo thread nativo e processa un chunk per chiamata (`src/app/runtime_execution.py`, `src/app/app.py`), con tokenizzazione, forward e serializzazione su CPU in sequenza. E' un modello del comportamento, non una causa radice profilata.
- Una possibile iniquita' nel gate nativo e' un fattore potenziale, non dimostrato, e la traccia CPU non supporta un'affermazione piu' forte.

## Limite del driver sui PDF

- Il driver locale genera e apre i PDF nei thread worker del client, senza un proprietario nativo PDF dedicato come invece ha il servizio (la sorgente statica del bench, `_prepared_pdf` chiamata da `_attempt`, gira in 2 worker).
- Non riusare questo percorso di carico PDF come as-tested prima di pre-generare il corpus oppure di usare un unico proprietario PDF. Il bench JSON non e' interessato.
- Le 469 richieste PDF validate con `200` non hanno causato crash, ma non supportano alcuna affermazione sul prezzo commerciale dei PDF.
- E' un limite del client di carico, non una regressione del proprietario PyMuPDF del servizio.
- Le evidenze descrivono la versione effettivamente usata: il percorso PDF del driver non e' stato corretto ne' riprovato. La sua correzione resta un prerequisito per futuri benchmark PDF; non modifica i risultati JSON.
- Le prestazioni PDF vanno considerate esplorative.

## Raccomandazione

1. Documenti lunghi: come budget operativo iniziale e prudente, prevedere un tetto di 2 client. Non e' un ottimo universale dimostrato. Non alzare il limite di 4 attive e non cambiare l'ammissione attuale a 4 senza approvazione.
2. Abbassare il limite del server da 4 a 2 richiederebbe l'approvazione dell'utente e un riavvio di configurazione separato. Non e' stato applicato.
3. Se un SLO di latenza stretto conta piu' del throughput, 1 client ha la coda piu' bassa (p95 inferiore con lo stesso throughput in caratteri/s). Gli aumenti di 6% (4 client) e 8.5% (8 client) sono modesti e non sono una prova di capacita'.
4. Un utilizzo GPU piu' alto probabilmente richiede batching o ottimizzazione della pipeline, non piu' client HTTP. E' un'ipotesi, non implementata e non misurata.
5. Prezzo: fissare un addebito minimo per richiesta piu' una tariffa a volume per carattere, entrambi basati su un modello di utilizzo e di domanda.

## Contesto dei costi

- Finestra di traffico: 491.644 s x `0.59` USD/h / 3600 = `0.080575` USD di tempo GPU. E' la finestra del benchmark, non la fattura dell'account. Include il warmup, che invece e' escluso dalle tabelle di prezzo e costo per profilo.
- Il costo unitario della finestra occupata (circa `0.0056` USD per 1M di caratteri) esclude altro tempo inattivo o fuori finestra e il warmup. Non e' un prezzo di vendita.
- Pod fisso: 720 h x `0.59` = `424.80` USD per 30 giorni. Questa cifra mensile NON esclude il tempo inattivo: e' il tempo GPU fisso completo, idle incluso. Esclude storage, rete, tasse, retry e margine. A 10M di caratteri al mese: `42.48` USD per 1M di caratteri (verificato con calcolatrice), contro `0.0056` USD nella finestra occupata.
- Tutti gli importi sono in USD, mai in EUR.

## Telemetria

Fonte: 34 campioni runtime nativi del Pod (32 durante l'esecuzione, inattivo prima e dopo).

| Contatore | Intervallo |
| --- | --- |
| CPU | da 0 a 14% |
| RAM | 2% costante |
| Utilizzo GPU | da 0 a 36% |
| Contatore utilizzo memoria GPU | da 0 a 10% |

- I contatori del provider sono in cache e grossolani. I poll arrivavano ogni 5-6 s con buchi (fino a circa 90 s nel periodo attivo, 156.687 s sull'intera serie incluso l'inizio inattivo). Non e' uno scrape continuo a 5 s e non da' picchi precisi ne' percentuali di tempo.
- Il denominatore CPU non e' verificato: non convertire il 14% in core.
- Il contatore di memoria GPU non e' validato come VRAM allocata: non leggere il 10% come 4.8 GB ne' come "0 liberi". Non sono disponibili byte di VRAM.
- Non e' stato osservato alcun esaurimento di risorse. Non e' una prova di margine per aumentare la concorrenza.
- Stato finale inattivo: CPU 0, GPU 0, RAM 2. I log mostrano un solo avvio del worker, modello pronto e nessun segnale fatale, di out-of-memory o di riavvio. Il server non e' andato in crash.

## Limiti di questa evidenza

- Una sola esecuzione a caldo, su questo hardware e corpus sintetico. Non e' un soak test e non certifica accuratezza, GDPR, prestazioni su documenti reali o capacita' massima.
- Lo stress completo da 15 minuti e k6 non sono stati eseguiti (e' stata eseguita l'esecuzione personalizzata da 8 minuti).
- Un'esecuzione di conferma opzionale nella finestra di 15 minuti non e' partita perche' il tempo di guardia residuo era di 111 s, sotto i 150 s richiesti. Nessuna seconda invocazione e nessuna affermazione di ripetizione.
- Gli artefatti temporanei restano locali e non sono committati. La chiave API e la collezione privata non sono mai state copiate in Git.
- Le misure usano gli header del client canonico. In un controllo successivo una sonda urllib generica ha ottenuto `403`, mentre la sonda con gli header canonici ha ottenuto `200` e modello su CUDA. Non attribuire quel `403` a un errore d'inferenza; verificare separatamente la compatibilita' di altri client.
- Prima del traffico live il driver ha superato il gate di qualita' e la revisione mirata di chiave, TLS e origine. Questo non equivale a una certificazione generale delle prestazioni o della sicurezza del servizio.

## Verifica

- Indipendente: 40 test del driver e 856 test del repository eseguiti effettivamente, tutti passati, senza skip. La copertura del driver e' 552/597 righe (92.46%) su sorgenti fuori da Git, una verifica temporanea e non una modifica all'API.
- Il delta di test e copertura obbligatori sul repository e' N/A, perche' la modifica e' solo Markdown e non ha delta eseguibile. Nessuna affermazione di nuova copertura per la sorgente precedente (236 righe al 100%).
- Il quality gate e' passato dopo 2 correzioni minime di test e di reportistica. Una revisione di sicurezza mirata e' passata per gestione della chiave, TLS, origine e assenza di mutazioni.
- Conteggi, percentili e costi sono stati ricalcolati indipendentemente dai metadati delle singole richieste, con risultati coincidenti.

## File sorgente

- `/tmp/envai-pii-load-20261025/results.json`: riepilogo dell'esecuzione con fasi annidate.
- `/tmp/envai-pii-load-20261025/requests.jsonl`: solo metadati per richiesta.
- `/tmp/envai-pii-load-20261025/telemetry.json`: 34 campioni.

Guide correlate: [guida al servizio RunPod](runpod-service.md), [CI e automazione GHCR](ci-release.md), [changelog](CHANGELOG.md).

Per la capacita' di una singola GPU, i dati su batch e repliche e le correzioni al budget di 2 client, vedi il [report sulla capacita' di una singola GPU](runpod-single-gpu-capacity.md). Il mix di unita' di questo report resta quello dei vecchi numeri HTTP e non ne deriva una nuova tariffa.
