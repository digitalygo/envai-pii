---
status: completed
created_at: 2026-10-28
updated_at: 2026-10-28
measurement_run_id: verda-20261028-gpu8-uuid
preliminary_protocol_deviation: true
---

# Monitoraggio GPU con otto copie del modello

## Risultato

**402 richieste misurate, tutte 200 e validate**, su una L40S con otto copie del modello, float32 e batch B1 invariati. Nessun errore o ricambio di worker durante le misure.

Con 32 richieste simultanee: media **10,82 secondi**, p95 **17,03 secondi**, throughput **2,05 richieste/s**, attivita' GPU media campionata **77,83 percento**, picco **100 percento**, potenza media **233,25 W**. La VRAM globale massima registrata e' **13,48 GiB su 47,38 GiB** visibili.

Il coordinatore ha ricontrollato tutti i record grezzi, la correlazione e i campioni originali tramite le API del provider. Il risultato riguarda questa matrice sintetica, non accuratezza generale, SLA, costo della fattura o una promozione in produzione.

La replica e' mantenuta calda con **minimo1/massimo1**, come gia' impostato dall'utente, otto modelli e concorrenza provider32. Il provider continua a riportare `updating`, non `healthy`: una replica e' `running`, otto worker sono pronti e le 402 analisi hanno risposto correttamente. Non si nasconde questa differenza fra stato del controllo e servizio verificato.

## Tempi e throughput

Secondi end-to-end, esclusi avvio, warmup e validazione client. Ogni richiesta usa lo stesso documento sintetico da 45000 caratteri. P95 nearest-rank calcolato sui singoli risultati, non mediando percentili.

| Richieste simultanee | Richieste valide | Media s | P95 s | Massimo s | Richieste/s |
| --- | --- | --- | --- | --- | --- |
| 1 | 30/30 | 1,946 | 2,032 | 2,097 | 0,514 |
| 2 | 36/36 | 2,423 | 3,654 | 3,704 | 0,782 |
| 4 | 48/48 | 2,748 | 4,817 | 5,387 | 1,168 |
| 8 | 96/96 | 3,798 | 5,741 | 6,051 | 1,526 |
| 16 | 96/96 | 6,139 | 10,009 | 10,897 | 1,701 |
| 32 | 96/96 | 10,820 | 17,031 | 18,535 | 2,048 |

Il throughput e' successi divisi per la somma delle durate delle raffiche, non per la somma delle latenze sovrapposte e non per tutto il tempo della procedura. Sono 81 raffiche in 27 gruppi; rispettivamente10/6/4/4/2/1 gruppi di tre per concorrenza1/2/4/8/16/32.

Finestra effettiva delle richieste: `2026-10-28T10:46:15.855979Z–10:51:43.096496Z`, durata327,240517secondi. Non si misura il cold start.

## Attivita' GPU e potenza

Medie dei campioni NVML presi circa ogni secondo, solo quando almeno una richiesta misurata e' in trasporto. Avvio, warmup, attesa, intervalli fra raffiche e campioni successivi sono esclusi.

| Richieste simultanee | Campioni attivi | GPU media % | GPU massima % | Potenza media W | Potenza massima W |
| --- | --- | --- | --- | --- | --- |
| 1 | 57 | 17,65 | 20 | 135,16 | 148,64 |
| 2 | 47 | 25,66 | 61 | 152,72 | 187,14 |
| 4 | 40 | 54,35 | 99 | 180,10 | 242,10 |
| 8 | 63 | 60,79 | 100 | 201,66 | 271,34 |
| 16 | 55 | 70,44 | 100 | 215,04 | 278,32 |
| 32 | 48 | 77,83 | 100 | 233,25 | 279,08 |

Sulle finestre attive complessive: **310 campioni**, GPU media51,05percento, potenza media186,50W e massima279,08W. Il limite di potenza letto dal driver e'350W. Questa media complessiva mescola carichi diversi: non sostituisce le righe per concorrenza.

La raccolta completa contiene698 campioni validi del solo proprietarioPID82:310 attivi e388 esclusi. Non ci sono duplicati, anomalie temporali, campioni indisponibili, proprietari diversi o run diversi. La lettura NVML dura al massimo4ms nei campioni attivi.

Copertura rispetto alle opportunita' nominali a1Hz sulle finestre di trasporto:99,36percento complessivo, almeno40campioni per cella contro il minimo richiesto10. La copertura per cella varia circa95–100percento ed e' limitata a1 quando il conteggio supera le opportunita' arrotondate. I singoli arrotondamenti per cella non sommano al medesimo arrotondamento globale. Non e' una misura continua o una percentuale di richieste verificate.

Il valore367 nell'artefatto di readiness e' una fotografia presa alle10:46:13Z, prima del warmup valido;698 e' il conteggio finale, dopo la matrice. Non sono conteggi dello stesso intervallo.

## Memoria e task

| Metrica | Massimo registrato | Capacita' o riferimento |
| --- | --- | --- |
| VRAM globale usata | 13,482 GiB | 47,384 GiB visibili, minimo71,55percento libero |
| Picco RAM del cgroup | 8,804 GiB | limite58 GiB |
| RAM corrente campionata | 9452306432 byte | minimo84,82percento di margine |
| Task del cgroup, thread compresi | 105 | guardia operativa409, budget sperimentale512 |
| Massimo Torch per processo | 1269087744 byte | non sommato come falso picco globale simultaneo |

La VRAM e' totale CUDA meno minimo libero campionato, non un picco continuo garantito. Il picco RAM e' il contatore kernel `memory.peak` della replica; puo' comprendere l'avvio. Parametri1230259380byte e buffer512byte per copia, dtypefloat32.

Il leaf cgroup dichiara `pids.max=max`: limite reale non finito, non dato mancante. Il budget512 e la guardia409 sono controlli sperimentali separati, non una quota o garanzia del provider; antenati e limiti host restano sconosciuti. I contatori HTTP per worker includono anche probe del provider e non sono usati come conteggio delle inferenze misurate.

## Cosa dimostrano i dati

- La GPU non resta inutilizzata sotto carico: l'attivita' media sale con la concorrenza e raggiunge picchi100percento da otto richieste simultanee in su.
- Non lavora pero' costantemente al100percento: a concorrenza32 la media dei campioni e'77,83percento. I picchi del grafico non bastavano a descrivere l'intera prova.
- Non manca VRAM in questa matrice: circa13,48GiB occupati su47,38. C'e' margine di memoria, ma non e' una misura della potenza di calcolo residua.
- Aumentare le richieste aumenta sia throughput sia attesa. Otto modelli condividono comunque una sola GPU e ogni copia conserva il percorso seriale a blocchi, batch1.
- Il prossimo confronto motivato e' batching dei chunk e profilazione separata di tokenizzazione, attesa della corsia, forward GPU e aggregazione. Non e' stato eseguito qui e non se ne promette un guadagno.

NVML misura attivita' del dispositivo, **non occupazione degli SM o FLOPs**. La frequenza di lettura non coincide necessariamente con la finestra interna del driver. Nemmeno una potenza sotto il limite dimostra da sola assenza di un collo di bottiglia. I dati non ripartiscono il tempo fra CPU, code, GPU, rete e proxy; non viene dichiarato un componente dominante senza quella profilazione.

## Metodo e integrita'

- Otto processi Gunicorn indipendenti, nessun preload, una L40S visibile per processo. Un solo campionatore globale nella replica, associato al dispositivo CUDA tramite UUID verificato con NVML.
- Immagine immutata `sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714`, modello v1.5.0, Torch2.13/cu126, float32, B1. Nessuna modifica al motore, all'autenticazione o alle route.
- Corpo45174byte, testo45000caratteri Unicode, SHA256 `d2a274f2ab87b0d3d71f2b9be595350e5a9ce0c919f11a7eea12a2d168d33b59`. Tutte le risposte coincidono con l'oracolo canonico `ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`.
- Ingresso provider32; per worker16analisi ammesse,32in coda, attesa30s e analisi60s. OMP/MKL1 e tokenizer parallelism disabilitato. Non sono32forward GPU simultanei.
- Persistenza dopo ogni raffica, una sola chiamata per sender, nessun replay o sostituzione delle402misure. Watchdog esterno e timeout finiti; errori e dati mancanti non sono trasformati in successi o zeri.
- Il coordinatore ha validato tutti i402ID compositi unici, corpi/oracoli/status/timing, tutte le sei medie/p95/throughput e il completo piano di81raffiche.
- Ha ricalcolato indipendentemente le maschere temporali dei310campioni attivi e confrontato l'intera correlazione. Sei query native da60s, nessuna troncata a1000righe, hanno recuperato331campioni GPU originali intorno alla matrice: **tutti i310usati coincidono esattamente** con gli artefatti. Recuperati anche1328eventi base dei PID82–89, senza exit/child_exit/startup_failed nella finestra misurata.

## Correzione diagnostica, manutenzione e deviazioni

Gli otto modelli erano gia' pronti, ma il vecchio monitor si fermava con `uuid_invalid`. PyTorch espone un oggetto `_CUuuid` con `.bytes` composto da16interi; il normalizzatore iniziale non lo supportava. La correzione accetta solo forme valide e bounded, senza conversione arbitraria `str`, senza usare ciecamente indice0 e senza allentare la corrispondenza con il UUID NVML.

Nuovo run `verda-20261028-gpu8-uuid`, archivio `6c84cf08d6c5299ab520373c6e78bebd3c7797fd6f3634e89c98ed19aabae7a8`, profilo canonico `3cc02fb1c11dba32e456020e14c89a1683d9717500a2beb49197a31d11b2a877`. Trasporto verificato:56argomenti e49variabili, ogni valore al massimo253byte, frammenti rimossi prima dell'exec. L'archivio predefinito `02997f57` rimane byte-identico.

Per applicare il solo aggiornamento diagnostico senza due allocazioni contemporanee e' stata fatta una pausa controllata, con minimo1 desiderato conservato:

1. Pausa HTTP201 alle10:39:05.147640Z; zero repliche osservato alle10:39:19.453030Z.
2. Un solo PATCH HTTP200 alle10:39:19.640281Z e readback esatto alle10:39:23.637189Z.
3. Ripresa HTTP201 alle10:39:23.849085Z; nuova replica `envai-pii-test-79c9745ff6-fs47w` creata e schedulata alle10:39:44Z.
4. Otto PID82–89 pronti alle10:40:04Z, proprietario del campionatore82. Nessuna sovrapposizione con il vecchio pod, eliminato alle10:39:14Z secondo i log di sistema indipendenti.

Non ci sono stati PATCH di scaling, uso dell'endpoint restart, hardware aggiuntivo o ripristino a una/quattro copie. Il valore minimo1 era gia' dell'utente e rimane1; la nuova replica sostituisce quella precedente nello stesso servizio.

Sono conservate due deviazioni preliminari, senza falsificarle come protocollo interamente pulito:

- Un cursore incrementale ha mancato gli eventi ready arrivati in ritardo. Una rilettura completa della vita del pod li ha recuperati **prima del warmup valido e delle misure**; non e' stata ripetuta l'attivazione.
- Un POST preliminare senza autenticazione alle10:45:25Z ha ricevuto il404 di19byte del provider, prima dell'applicazione. Era aggiuntivo e non previsto; e' conservato ed escluso dalle misure. Poi un solo warmup autenticato ha risposto200 fra10:46:13.875147Z e10:46:15.850687Z, con oracolo corretto. Le402misure iniziano alle10:46:15.855979Z.

Contabilita' endpoint: **404 POST totali**, cioe'402misurati200, un warmup autenticato200 e un preliminare non autenticato404. La matrice non ha errori; l'intera procedura non e' descritta come priva di errori HTTP. Nessun contenuto di richiesta/risposta/delta o credenziale e' conservato.

## Limiti

Un solo testo sintetico ripetuto, pochi gruppi ai carichi alti e nessuno stress prolungato. Le medie sono descrittive, non uno SLO o una prova di accuratezza/GDPR/PDF completo. I conteggi per concorrenza differiscono per ottenere campioni GPU sufficienti. Il chip fisico puo' essere diverso dalle precedenti assegnazioni L40S: non si attribuiscono differenze rispetto al vecchio confronto a un'ottimizzazione del modello, che non e' stata fatta.

La prova copre l'API v1 stateless. Cache PDF e preferenze legacy restano locali ai worker: non e' una qualificazione in produzione dell'intero servizio o di failover trasparente.

La potenza fisica non e' la fattura. Verda pubblicizza assenza di costi idle e documenta minuti con utilizzo, incluso avvio/spegnimento; il caso di una replica minimo1 gia' pronta e senza traffico non e' esplicitato in quelle pagine. Non si dichiara ne' un costo idle certo ne' una GPU warm riservata gratuita senza conferma contrattuale o dati di fatturazione.

## Verifiche e stato mantenuto

- Parent:1041test del repository senza skip,69test mirati anche su Python3.14, copertura100percento dei39eseguibili e rami del blocco UUID modificato. Complessivo circa90percento linee,89percento includendo i rami. Revisione indipendente di qualita':PASS. Nessun core API/auth/segreto/dato sensibile modificato, quindi nessuna nuova revisione automatica di sicurezza applicabile; non e' una certificazione.
- Un analista read-only ha confermato conteggi/formule/identita' e segnalato limiti di interpretazione. Il coordinatore ha ricalcolato anche tutti i p95 direttamente dai record grezzi. Il conteggio367/698 e' ricondotto ai diversi istanti di acquisizione, non a campioni mancanti.
- Medie di latenza e valori principali verificati con calcolatrice; byte/GiB con convertitore; mW/W verificati dividendo per1000. Non sono usati risultati di conversione con alias SI ambiguo.
- Definizione finale e49variabili rilette esattamente dal coordinatore. Una replica L40S `running`, minimo1/massimo1/concorrenza32 e stato provider `updating`, non trasformato in `healthy`. La disponibilita' applicativa e' dimostrata dalle risposte valide, non dal solo stato del controllo.
- Nessun commit, push, staging, modifica a `src/app/` o `Dockerfile.gpu`, nuovo modello, batch, immagine o risorsa estranea. Il servizio e' lasciato caldo secondo l'impostazione dell'utente; non viene forzato a zero come se fosse una risorsa temporanea nuova.

## Storia dei tentativi precedenti

- Il primo pacchetto diagnostico e' stato rifiutato per il limite non documentato253caratteri per valore di ambiente. La consegna ibrida ha risolto quel limite, senza cambiare l'inferenza.
- Il tentativo L40S delle08:22Z non era schedulabile per mancanza di nodi; nessun dato da quel tentativo e' stato riciclato.
- Il cambio manuale a RTX PRO6000 e' stato verificato e non sovrascritto. Il vecchio guard L40S e lo stack cu126 richiedevano qualificazione prima di testare Blackwell; non e' stato generato carico da noi su quella GPU.
- Al ritorno L40S, otto modelli erano pronti ma il monitor non accettava il UUID CUDA. La correzione documentata sopra ha prodotto i primi contatori GPU validi e questa matrice completa.
- Gli errori precedenti di delega restano nel piano e nell'operazione storica. La successiva esecuzione primaria ha funzionato; non e' servita una modifica globale agli agenti.

## Indicazioni per la produzione

Sono proposte, non impostazioni applicate: base calda se serve bassa latenza; capacita'/SLA concordati quando necessari; fallback su hardware/regioni/provider prequalificati; coda applicativa persistente cifrata con idempotenza, retention e retry limitati; allarmi suSchedulingFailed, eta' della coda e repliche realmente pronte.

Otto modelli sulla stessa GPU non sono otto domini di guasto. Una soglia minima di autoscaling non garantisce capacita' sostitutiva; la coda locale e' in memoria e quella Verda scade secondo un TTL che include attesa e inferenza. Il fallback deve considerare immagine CUDA, esiti del modello, stato legacy e residenza dei dati. Nessuna nuova infrastruttura di produzione e' stata creata.

## Fonti e percorsi

- [Piano e registro di esecuzione](../plans/2026-10-27-verda-model-copies.md).
- [Operazione condivisa](../operations/2026-10-21-runpod-service.md).
- [Confronto precedente delle quattro configurazioni](2026-10-27-verda-model-copies.md).
- [Binding ufficiale PyTorch del UUID CUDA](https://github.com/pytorch/pytorch/blob/main/torch/csrc/cuda/Module.cpp).
- [Scaling, TTL e health check di Verda](https://docs.verda.com/containers/scaling/).
- [Compute e minimo di repliche Verda](https://docs.verda.com/infrastructure-as-code/terraform/containers-containers/).
- [Regole pubblicate di fatturazione Serverless](https://docs.verda.com/containers/overview/) e [pagina Serverless di Verda](https://verda.com/serverless-containers).
- Strumenti: `tools/verda_model_experiment/gpu_monitor.py`, `gpu_runtime.py`, `gpu_profile.py`, `package.py`.
- Evidenze private: `/home/lorenzo/private/tmp/envai-pii-verda-gpu-profile-20261028/uuid1020-*`; vecchi prefissi conservati separatamente. File principali: `uuid1020-bursts.jsonl`, `uuid1020-gpu-samples.jsonl`, `uuid1020-base-events.jsonl`, `uuid1020-profile.json` (risultato del runner, non un payload da inviare), `uuid1020-correlation.json`, `uuid1020-report.json`, `uuid1020-ready.json`, `uuid1020-warmup.json`, `uuid1020-warmup-unauth-404.json`, `uuid1020-activation.json`, `uuid1020-final.json`.
