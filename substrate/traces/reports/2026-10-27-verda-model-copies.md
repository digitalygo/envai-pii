---
status: completed
created_at: 2026-10-27
protocol_deviation: true
---

# Confronto delle copie del modello su Verda

## Risultato

Il confronto delle quattro configurazioni e' completato. Piu' copie sulla stessa L40S migliorano la capacita' osservata, ma non in modo lineare e non eliminano l'accodamento.

Con 32 richieste simultanee, quattro copie hanno media 14,75 secondi e otto copie 11,84 secondi, con tutti i tentativi riusciti. Il throughput valido passa da 1,577 a 1,720 richieste/s: circa il 9,1 percento in piu', mentre la risposta media migliora del 19,7 percento. Con quattro richieste simultanee, invece, quattro copie sono leggermente piu' rapide di otto in questa serie.

E' mantenuta la **configurazione con otto copie**, perche' e' l'ultima verificata, non come scelta automatica del vincitore. Il deployment e' `healthy`, non in pausa, con **zero repliche a riposo**, minimo 0 e massimo 1. La prossima richiesta puo' avviare una GPU e caricare le otto copie.

La prova comprende una deviazione: il primo avvio N8 si e' interrotto dopo tre risposte valide a concorrenza uno; quella cella e' stata ripetuta durante la ripartenza. I tre campioni iniziali sono conservati e inclusi, non cancellati. La riga N8/CC1 sotto e' pertanto un aggregato descrittivo a posteriori di sei campioni su due attivazioni. I dettagli e i valori separati sono nella sezione sulla deviazione.

## Tempi medi di risposta

Secondi sulle sole risposte 200 validate. Sono inclusi rete, proxy e accodamento; sono esclusi avvio, warmup, preparazione e validazione del client.

| Richieste simultanee | 1 modello | 2 modelli | 4 modelli | 8 modelli |
| --- | --- | --- | --- | --- |
| 1 | 1,84 | 1,95 | 1,97 | 1,87 |
| 2 | 3,15 | 2,43 | 2,38 | 1,93 |
| 4 | 5,26 | 3,27 | 2,54 | 2,72 |
| 8 | 11,13 | 5,86 | 3,97 | 3,29 |
| 16 | 23,86 | 12,24 | 7,13 | 6,06 |
| 32 | 31,88 | 25,48 | 14,75 | 11,84 |

Con un modello, la riga da 32 ha **76 successi su 96 e 20 risposte 429**, dopo attese di circa 30 secondi. La media 31,88 riguarda solo i 76 successi. Tutte le altre celle hanno risposte 200 validate per ogni tentativo. Ogni cella usa tre raffiche, pari a 3 volte la concorrenza richiesta; l'eccezione N8/CC1 usa sei risposte singole anziche' tre.

## Code di risposta osservate

P95 nearest-rank dei successi, in secondi. Sono campioni brevi, non garanzie statistiche di servizio.

| Richieste simultanee | 1 modello | 2 modelli | 4 modelli | 8 modelli |
| --- | --- | --- | --- | --- |
| 1 | 1,86 | 2,00 | 2,06 | 1,94 |
| 2 | 3,51 | 3,57 | 3,70 | 2,04 |
| 4 | 6,74 | 5,58 | 3,76 | 5,26 |
| 8 | 13,53 | 7,26 | 5,61 | 5,49 |
| 16 | 27,19 | 15,89 | 11,73 | 10,96 |
| 32 | 45,03 | 31,04 | 22,34 | 18,90 |

A concorrenza 32 i massimi sono rispettivamente 53,95, 32,11, 23,32 e 20,19 secondi. N8/CC1 comprende i sei campioni descritti sopra.

## Throughput valido

Richieste validate al secondo, calcolate come successi divisi per la somma delle durate delle raffiche. Non si sommano le latenze di richieste sovrapposte. Avvio, warmup, attese fra raffiche e spegnimento sono esclusi: questa non e' una contabilizzazione della fattura.

| Richieste simultanee | 1 modello | 2 modelli | 4 modelli | 8 modelli |
| --- | --- | --- | --- | --- |
| 1 | 0,543 | 0,512 | 0,507 | 0,536 |
| 2 | 0,578 | 0,776 | 0,756 | 1,017 |
| 4 | 0,595 | 0,924 | 1,260 | 1,087 |
| 8 | 0,590 | 1,112 | 1,437 | 1,576 |
| 16 | 0,588 | 1,065 | 1,550 | 1,513 |
| 32 | 0,544 | 1,011 | 1,577 | 1,720 |

A 32 richieste, otto copie hanno circa 3,16 volte il throughput valido di una copia. Il confronto comprende il diverso numero di risposte rifiutate nella configurazione a una copia; non e' una moltiplicazione lineare della potenza della GPU.

## Successi e campioni

| Copie | Tentativi misurati inclusi | Risposte valide | Errori HTTP |
| --- | --- | --- | --- |
| 1 | 189 | 169 | 20 risposte 429 a CC32 |
| 2 | 189 | 189 | 0 |
| 4 | 189 | 189 | 0 |
| 8 | 192 | 192 | 0 |
| Totale | 759 | 739 | 20 |

La matrice delle quattro esecuzioni complete contiene 756 tentativi e 736 successi. I tre ulteriori successi CC1 del primo avvio N8 portano il totale effettivo a 759/739. Warmup e probe di salute non sono inclusi. Non vengono contate come nuove misure le precedenti prove HTTP a configurazione originale o le diagnostiche A40.

Ogni risposta valida conserva l'oracolo canonico della versione pubblicata. Sono verificati forma del contratto, mascheramento, delta e hash; non e' una certificazione dell'accuratezza su documenti reali.

## Memoria sulla stessa allocazione GPU

| Copie | VRAM globale massima registrata | Picco RAM del cgroup | Massimo task osservato |
| --- | --- | --- | --- |
| 1 | 1,688 GiB | 1,150 GiB | 42 |
| 2 | 3,373 GiB | 2,243 GiB | 49 |
| 4 | 6,742 GiB | 4,429 GiB | 73 |
| 8 | 13,482 GiB | 8,787 GiB | 109 |

CUDA espone **47,384 GiB** totali e il limite RAM del cgroup e' **58 GiB**. Con otto copie la VRAM massima registrata e' circa il **28,45 percento** del totale visibile. Questo misura memoria occupata, non percentuale di calcolo GPU utilizzata.

La VRAM globale e' totale meno minimo libero campionato: non e' un picco continuo garantito. Il picco Torch per processo e' distinto e non viene sommato come falso picco globale simultaneo. Per copia: parametri 1230259380 byte, buffer 512 byte, float32; il massimo Torch per processo osservato e' 1269087744 byte.

Il cgroup dichiara `pids.max=max`: non c'e' un limite PID finito visibile sul leaf. Solo con questa prova esplicita, il controller adotta un **budget sperimentale di 512 task**, thread compresi, con margine del 20 percento. E' un tetto di controllo, non una quota del provider, un limite kernel o una garanzia su antenati o host. Dati mancanti o invalidi restano bloccanti e un limite reale piu' basso prevale sempre. RAM e VRAM mantengono il margine del 20 percento sulle capacita' finite osservate.

Quota CPU non esposta come limite finito. L'affinita' di 192 CPU non significa 192 core assegnati. La CPU e la VRAM libere non dimostrano da sole capacita' di throughput ulteriore.

## Metodo e configurazione controllata

- Una L40S per replica e massimo una replica configurata. Si e' atteso lo zero prima dei cambi di profilo; la GPU fisica puo' cambiare fra assegnazioni, quindi il confronto e' sulla stessa classe di allocazione, non una prova di identita' del chip.
- Una copia del modello per processo Gunicorn indipendente, senza preload. Non e' stato aggiunto un pool applicativo di produzione o un motore di batching fra richieste.
- Immagine `1.0.0-dev.7`, digest `sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714`, modello v1.5.0, Torch 2.13.0 cu126, float32 e batch B1 invariati. B16 non e' stato misurato qui.
- Testo sintetico identico da 45000 caratteri Unicode, tutte le categorie e nessun seed. Corpo JSON 45174 byte, SHA256 `d2a274f2ab87b0d3d71f2b9be595350e5a9ce0c919f11a7eea12a2d168d33b59`.
- Ingresso provider 32; per worker 16 analisi attive e 32 in coda con timeout 30 secondi; analisi 60 secondi. OMP/MKL a un thread e parallelismo tokenizer disabilitato in tutte le varianti. Piu' worker aumentano anche i limiti HTTP aggregati e possono cambiare la distribuzione delle connessioni: il beneficio non va attribuito esclusivamente alla VRAM.
- Ogni worker termina il warmup sintetico e la barriera prima dell'accettazione HTTP. La prova richiede il numero atteso di PID correnti, modello CUDA, sorgenti e impostazioni corrette. Nessun ricambio di worker e' stato osservato durante le finestre misurate delle esecuzioni complete.
- Ogni chiamata riceve un solo tentativo dal client, senza pacing o sostituzione delle risposte fallite. La ripartenza operativa extra N8/CC1 e' una deviazione separata, non nascosta nella contabilita'.
- Watchdog di processo e timeout finiti obbligatori. Dopo l'ultima richiesta solo letture di gestione, nessun keepalive verso l'endpoint. Le uscite naturali successive alle misure non sono considerate churn.

## Deviazioni e limiti

### Ripartenza N8 e campioni aggiuntivi

Il primo avvio N8 ha prodotto tre risposte CC1 valide fra `22:04:18Z` e `22:04:25Z`. Le evidenze registrano lo stop `pid_limit_unknown` e una cella non consolidata. L'operatore attribuisce lo stop a una finestra vuota di telemetria interpretata erroneamente; la causa precisa non e' stata rieseguita da un sorgente salvato. E' stato temporaneamente ripristinato l'ultimo profilo sperimentale sicuro, quattro copie, non la configurazione originaria a una copia.

Successivamente N8 e' stato riattivato e l'intera matrice e' stata ripetuta. Questa ripetizione **non rispetta completamente il protocollo no-replay dichiarato**. Non e' un errore misurato della GPU o un'autorizzazione retroattiva a scartare campioni.

I tre risultati iniziali hanno media 1,925678 secondi; i tre CC1 dell'esecuzione completa successiva hanno media 1,806289 secondi. Tutti e sei sono conservati e inclusi nella tabella principale: media descrittiva aggregata **1,865984 secondi**, p95 1,937903, sei successi. L'aggregato attraversa due attivazioni, non e' una cella omogenea di un'unica esecuzione. Le altre cinque celle N8 usano soltanto le tre raffiche dell'esecuzione completa.

Il file aggregato del primo tentativo indica erroneamente zero successi perche' la cella non era stata consolidata; i tre record grezzi hanno tutti 200, validazione e oracolo corretti. Il coordinatore e un analista read-only hanno verificato la discrepanza senza riscrivere le evidenze iniziali. La copia completa del primo tentativo resta separata.

Gli eventi del provider mostrano la cancellazione della prima replica alle `22:06:34Z`, il rollback metadata a quattro copie con zero repliche e la creazione della replica della successiva prova N8 alle `22:08:34Z`. Non risultano sovrapposizioni di queste due allocazioni.

### Recupero della rendicontazione

Le esecuzioni N2 e N4 hanno richiesto un recupero read-only di alcuni riepiloghi post-traffico dopo errori locali di scope nel finalizzatore. Le richieste misurate non sono state ripetute; i record originali sono intatti e gli eventi del provider confermano lo spegnimento. Alcuni totali delle sole GET di gestione non sono disponibili e non vengono inventati.

L'aggregato vuoto di readiness finale N1 deriva da una query tardiva: il coordinatore ha verificato 196 eventi della corretta finestra della replica servente. Per N8 il coordinatore ha verificato indipendentemente 1008 eventi paginati, otto PID pronti e nessun exit/churn nella finestra misurata.

### Generalizzazione

Un solo documento sintetico ripetuto, poche raffiche, numero ridotto di campioni ai carichi bassi. Non e' uno stress prolungato, una prova di accuratezza, GDPR, anonimizzazione completa dei PDF o massimo fisico della GPU. Il p95 osservato non e' uno SLO.

Le cache PDF e le preferenze legacy rimangono locali ai worker e non condivise. I risultati riguardano l'API v1 stateless, non una validazione di produzione dell'intera API. Lo scale-to-zero comporta cold start futuri; l'avvio delle diverse quantita' di copie non e' stato confrontato in condizioni di cache controllate.

## Configurazione mantenuta

- Otto copie configurate sulla singola allocazione L40S, caricate alla prossima attivazione.
- Deployment `healthy`, non in pausa, **zero repliche a riposo**; minimo 0 e massimo 1.
- Concorrenza provider 32, stesse otto variabili di controllo delle prove, comando compatto verificato.
- Immagine, modello, precisione e handler applicativi invariati.
- Nessun ripristino della configurazione originaria e nessuna promozione automatica del vincitore.

La configurazione a otto copie e' stata riletta indipendentemente dalle API di gestione dopo lo scale-to-zero delle `22:13:04Z`. Non e' stato inviato ulteriore traffico di inferenza per questa verifica. Il codice sperimentale e il report restano sul worktree `dev`, senza staging, commit o push.

## Verifica e provenienza

- 972 test del repository e strumenti superati dal coordinatore, senza skip; copertura complessiva circa 92 percento, controller locale 97 percento. I successivi passaggi sono operativi e Markdown, senza ulteriori modifiche eseguibili.
- Gate di qualita' indipendenti superati per pacchetto, limiti argv e controller. Bootstrap verificato con processo nuovo e con la versione effettiva Gunicorn 26.2.0; integrazione ZIP_LZMA sull'immagine GPU provata dalle quattro varianti reali.
- Metadati e hash, non testi o dizionari delle risposte. Credenziali in memoria, TLS normale, origini vincolate e redirect disabilitati. Nessuna chiave del provider passata al container.
- Medie ricalcolate da tutti i record grezzi e verificate con calcolatrice; conversioni byte/GiB verificate con il convertitore. I limiti e la deviazione N8 sono mantenuti espliciti.
- [Piano e registro di esecuzione](../plans/2026-10-27-verda-model-copies.md).
- [Operazione del servizio GPU](../operations/2026-10-21-runpod-service.md).
- Strumenti portabili: `tools/verda_model_experiment/`.
- Evidenze private principali: `/home/lorenzo/private/tmp/envai-pii-verda-replicas-20261027/`, prefissi `n1-cmd64-`, `n2-cmd64-`, `n4-cmd64-`, `n8-cmd64-`.
- Primo avvio N8 conservato: `/home/lorenzo/private/tmp/envai-pii-verda-replicas-20261027-attempt1-guard-bug/`.
