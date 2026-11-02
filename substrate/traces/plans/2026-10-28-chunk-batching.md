---
document_type: mycelium-plan
plan_id: 2026-10-28-chunk-batching
status: completed
created_at: 2026-10-28
planner: orchestrator
baseline_version: 1
execution_owner: orchestrator
execution_started_at: 2026-10-28
last_updated_at: 2026-10-29
---

# Implementazione e confronto del batching dei chunk

## Current execution snapshot

- Status: completed; B1 preservato, matrici B4/B8/B16 e confronto verificati, deviazioni operative documentate.
- Baseline identity: `2026-10-28-chunk-batching`, versione 1, baseline immutabile.
- Execution baseline: `dev` a `89412bf750c2a6bf3e80fcfbb7bebd192597ef46`, riconfermato dall'utente; manifest privato iniziale di 162 file. Nessun commit o push.
- Active phase: fase 4 conclusa; collector riutilizzabile e documenti aggiornati nello stesso piano/rapporto/operazione.
- Last verified checkpoint: 2026-10-29T19:26:42.223652Z, GET finali parent paused/min0/max1/32/zero e B16 esatto; struttura/link Markdown,48celle documentate,76file senza credenziali reali e permessi privati verificati. Nessun altro traffico di inferenza.
- Last successful checks: 1187 test PASS senza skip dopo B16; coverage collector/transport 866/934 linee, 92,72%. Pacchetto `1a66159c` quality/security PASS, quality live B4/B8/B16 PASS, core `0fcada80` invariato.
- Open blockers: nessuno per il confronto; originali FAIL e ledger incompleti preservati come limiti metodologici, non convertiti in successi. Immagine di produzione con batching non pubblicata.
- Required approvals and gates: ambito e spegnimento rispettati. Nessun cambiamento automatico del default1, nessun hardware aggiuntivo o risorsa estranea, nessuna pubblicazione autorizzata.
- Next action: nessuna attivazione automatica. B8 e' il candidato raccomandato per un'eventuale futura validazione su immagine di produzione, soggetta a nuovo incarico.

## Planner baseline

### Problem statement

L'API v1 esegue un chunk per chiamata. L'utente approva raggruppamento configurabile1/4/8/16 entro la stessa analisi, con gli otto modelli mantenuti e confronto di velocita', memoria e maschere. Non aggregare richieste, file o tratti protetti diversi. Il default applicativo rimane1 finche' il confronto non giustifica una scelta.

### Research and evidence

La [ricerca verificata](../research/2026-10-28-chunk-batching-inspection.md) descrive63chunk del fixture, pipeline singleton, confini del dizionario e rischi di deadline/padding. Il [profilo B1 precedente](../reports/2026-10-28-verda-eight-model-gpu-profile.md) misura402risposte corrette con otto copie, una L40S e minimo1. Due locator e un analyzer confermano perimetro e assenza di DRC/EXP; il pattern-finder della precedente ispezione individua le prove AST e il parametro batch dell'evaluatore.

### Hypotheses, decisions, and rationale

Task medium+: percorso core con dati sensibili e prestazioni. La decisione e' gia' stretta: grouping deterministico e parametro supportato dalla pipeline, senza nuova architettura o scheduler. Un solo backend writer per slice e' sufficiente; non si corre una race architetturale su un refactor bounded. Nessuna garanzia di speedup, memoria o equivalenza numerica prima delle misure.

Preservare singleton B1 e controlli prima/dopo ogni gruppo, corsia nativa e timeout correnti; gruppo in-flight resta non interrompibile. Risultati multi-chunk con cardinalita' errata devono fallire chiuso, non troncare con zip. Seed, categorie, file e richieste restano isolati. Nessun nuovo pacchetto o download Torch/modelli in CI.

L'immagine live contiene app.py b0ec; cambiarne i pin non aggiorna il codice live. Per il solo confronto diagnostico e' ammesso un overlay opt-in verificato, limitato alla stessa funzione adapter e al helper della consegna, installato prima della readiness su tutte le copie. Conservare pin del file base e attestare separatamente codice eseguito, batch e warmup. Non riassegnare soltanto il nome della funzione catturata dalle route. Se integrita', trasporto o sicurezza non sono dimostrabili, fermare il confronto e riportare il blocco, senza pubblicare immagini automaticamente.

### Planned phases

#### Phase 1: adapter e regressioni

- Objective: batch1/4/8/16 server-side, default1, v1 soltanto.
- Planner predictions: app.py, helper Python piccolo e test di batching; minimi adattamenti dei namespace AST esistenti, nessuna riscrittura del motore del dizionario o del legacy.
- Proposed steps: risolvere configurazione una volta, raggruppare dentro il singolo detector, chiamare pipeline con batch effettivo, normalizzare righe e offset, mantenere filtro e merge.
- Predicted verification: suite unittest dichiarata, test default/malformed/tail/cardinalita'/Unicode/offset/deadline/concorrenza/seed/categorie, copertura eseguibile delta almeno80percento.
- Completion criterion: verifica indipendente e quality/security PASS sul core prima del deploy.

#### Phase 2: variante diagnostica verificabile

- Objective: esercitare esattamente il nuovo adapter sull'immagine corrente senza release/push.
- Planner predictions: nuovi wrapper/package batch opt-in e test dedicati; minimi parametri riutilizzabili nel package esistente, vecchio archivio base preservato ove possibile.
- Proposed steps: attestare sorgente base e overlay, installare prima del marker, riscaldare il v1 effettivo su tutte le otto copie, registrare solo metadati bounded, costruire profili1/4/8/16 e verificare trasporto253byte/64argomenti/64env con margine.
- Predicted verification: fake runtime/WSGI/route reference tests, tampering/mismatch failure, warm-all-worker e cardinalita', archivio e bootstrap sandbox senza rete, suite completa e copertura delta80percento, gate quality/security.
- Completion criterion: nessun controllo allentato e codice/parametro realmente attestati; altrimenti fase GPU bloccata.

#### Phase 3: confronto reale sulla L40S

- Objective: B1/B4/B8/B16 a otto copie, stesso fixture/oracolo e criteri metrici.
- Planner predictions: solo risorsa envai-pii-test esistente, stessa immagine/modello/precisione/min1/max1/32; campioni privati nuovi, nessun replay della matrice vecchia.
- Proposed steps: leggere stato/config, pausa controllata e attesa zero prima di un cambio profilo, un PATCH/readback/ripresa, readiness e warmup attestati; eseguire la matrice402 con bound e guardie per ogni batch, fermarsi al primo guasto serio o mismatch dell'oracolo. Mai due GPU allocate insieme. Rileggere log completi con finestre <=60s per ritardi d'ingestione; non usare cursore forward-only come unica prova.
- Predicted verification:402ID/risposte per variante, oracolo canonico B1 ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40, correlazione310-equivalenti o almeno10campioni/cella per statistiche quantitative, RAM/VRAM20percento libero, stabilita'PID e sorgente, timeout90s e budget globale finito. Zero o missing GPU non vengono confusi.
- Completion criterion: dati controllati indipendentemente o blocco esatto documentato. Conservare minimo1 e otto copie; lasciare B1 se non emerge un vincitore sicuro. Nessuna promessa di healthy se il provider riporta updating.

#### Phase 4: rapporto e chiusura

- Objective: mostrare confronto, equivalenza, limiti, stato finale e copertura.
- Planner predictions: nuovo report di batching e aggiornamento compatto dell'operazione servizio esistente; documentazione del parametro e della deadline per gruppi.
- Proposed steps: verificare record grezzi e native-readback, convertire unita' con strumenti, dichiarare errori/preliminari e non attribuire watt a fatturazione. Chiudere ledger e operazione, niente commit.
- Predicted verification: diff/collateral check, collegamenti Markdown e inventario risorse temporanee; niente token/testo/delta nei dati salvati.
- Completion criterion: tutte le fasi verificate o esplicitamente bloccate, gate e limitazioni riportati.

## Execution ledger

### Ledger rules

Append-only; distinguere predizioni, claim e fatti. Solo il coordinatore aggiorna questo file. I trace sono esclusi dai pacchetti di revisione del codice.

### Phase 1 execution checkpoints

#### Checkpoint 2026-10-28T12:01:58Z: baseline validata

- Planner prediction: grouping intra-analisi, non cross-request.
- Subagent claim: locator e analyzer confermano callback singleton e cattura della funzione nelle route.
- Orchestrator finding: app.py e lane letti; il solo parametro non basta; l'overlay deve mantenere l'oggetto callback e avere attestazione separata.
- Independently verified fact: chezmoi e pull completati, dev sincronizzato, sorgenti iniziali hashati, snapshot del dirty tree ignorato, DRC/EXP/CONTRIBUTING assenti. Python3.11 venv e coverage7.17 disponibili, nessuna dipendenza modificata.
- Decision and impact: due slice seriali, gate prima del cloud; user conferma dev. API/auth/pesi non vengono riconfigurati.
- Next action: implementare il core con test default e batch, poi verificarlo.

### Phase 2 execution checkpoints

#### Checkpoint 2026-10-28T13:59:13Z: core e trasporto verificati

- Planner prediction: adapter e loader verificabili prima del cloud.
- Subagent claim: core aggiunge helper e grouping; il primo packaging writer termina per ContextWindowExceeded lasciando file parziali. Fallback-b completa wrapper/test, poi una sua correzione rifiuta per ruolo errato senza edit. Fallback-c corregge il solo golden di compressione.
- Orchestrator finding: letti sorgenti e test reali; nessun cambiamento a legacy, auth, dizionario, timeout, modello o file del vecchio package/runtime/monitor. Il B1 conserva forma e deadline; batch maggiori verificano righe e offset. L'overlay modifica lo stesso oggetto callback prima del warmup e della barriera, con hash separati dal file base.
- Independently verified fact: 1119test senza skip su3.11 e3.14; adapter21/21linee eseguibili delta, helper57/57, package193/193, runtime279/280, copertura branch complessiva dei tre moduli99percento. JSON e log privati leader-final-* e leader-314-tests.log. Vecchi archivi02997f57/6c84cf08 invariati; profili55argomenti/56env, valori<=253byte. Archivio nuovo17160byte, SHA c4eea72b82406fe5025bd4abf51bef958077f12108dd49c2bc20f6ae35a6d12a.
- Decision and impact: avanzare il cursore quality al pacchetto0fcada80459283e62029f9cea50ab9cc5146539ae5fdf28eaa9cb3ef6aeeb971. Quality-gate-a PASS e security-review-specialist-a PASS in read-only. Advisory non bloccante: chunk_groups chiamato direttamente con float/bool non e' protetto dal suo fallback; il percorso configurato accetta soltanto int validi e non lo espone alle richieste. Non cambiare il core ora per un input interno irraggiungibile. Manifest riproducibile conservato nello status locale.
- Next action: confronto nativo con builderPython3.11 uguale al minor dell'immagine, una replica per volta.

### Phase 3 execution checkpoints

#### Checkpoint 2026-10-28T14:40:37Z: stop prima dell'inferenza

- Planner prediction: PATCH/readback esatto, readiness di otto copie e402misure per batch.
- Subagent claim: un ciclo pausa/PATCH/ripresa, env105anziche'56, nessun warmup/POSTmisurato, schedulingNoNodes; B4/B8/B16 non tentati.
- Orchestrator finding: letto il report operativo e ricostruiti tutti i profili. Il PATCH aggiunge per nome senza eliminare le49vecchie voci. Il conteggio105 ha fermato il gate prima di qualunque traffico, non ha prodotto un errore del modello.
- Independently verified fact: GET nativi confermano comando B1 esatto e105env esattamente uguali all'unione dei49vecchi e56nuovi valori noti, senza extra sconosciuti; stato unhealthy,replicas.list con un error, nessun running, min1/max1/32. Eventi di sistema: vecchio pod eliminato14:16:26Z, nuovo creato14:18:56Z, SchedulingFailed/no nodes con10occorrenze. Nessuna nuova GPU o scaling PATCH. Manifest codice0fcada80 ancora identico, zero inferenze.
- Decision and impact: fase3 blocked, niente confronto/winner o altra attivazione. B1 diagnostico rimane configurato ma non eseguito; minimo1 dell'utente conservato. Non indovinare cancellazioni env o allocazioni alternative.
- Next action: completare rapporto e documenti, riprendere solo dopo nuova disponibilita' verificata.

#### Checkpoint 2026-10-28T18:18:36Z: ripresa autorizzata sulla replica esistente

- Planner prediction: riprendere la stessa fase3 quando esiste prontezza reale.
- Subagent claim: locator/analyzer confermano protocollo402 e nessuna misura o replay precedente, unione env attesa e guardie conservative.
- Orchestrator finding: l'utente approva la ripresa, non nuove implementazioni. Fonte invariata, parent nuova suite1119PASS e tutti i profili/archivio c4eea72b riprodotti. Lo stato blocked della chiusura precedente era corretto a quell'ora ma e' ora superato dal nuovo avvio.
- Independently verified fact: API native mostrano lo stesso pod running; finestre esplicite16:03:30–16:05:30Z hanno250+299righe con base ready e batch ready di70–77, tutti i cinque hash esatti, warm_calls63/warm_sum63/B1. Duecento campioni NVML numerici recenti confermano il campionatore attivo. Currentcontrolstatus updating conservato come tale. Nessun inference POST o riavvio dal parent nei controlli di stato.
- Decision and impact: usare il B1 attuale SENZA lifecyclechange. Per B4/8/16 resta il ciclo controllato una GPU alla volta, e confronto esatto dell'unione105env con valori target aggiornati; niente DELETE indovinato. Se capacita' o guardie falliscono, stop con dati parziali preservati e min1 non modificato.
- Next action: delegare soltanto esecuzione operativa e persistenza delle misure, poi verifica indipendente.

#### Checkpoint 2026-10-28T23:22:55Z: ripresa dopo controllo client difettoso e interruzione

- Subagent claim: primary-a ha raccolto B1 completo ma il riepilogo locale e' FAIL; fallback-b si e' fermato prima delle mutation; member-c interrotto dall'utente prima di nuovi artefatti.
- Orchestrator finding: primary termina anche con provider_finish_reason:error. Il suo verificatore usa concorrenze come chiavi di case_index: falso negativo su casi3/5/6. Il parent ricostruisce81raffiche/27gruppi, tutti402IDcompositiunici e tutte402risposte200/corpi/oracoli/timing validi mediante measure.summarize_rounds. Nessun replay. Il fallback richiedeva paused=false benché l'API fornisca solo status=updating: secondo falso stop, nessun modello o test GPU fallito. I file sorgente effimeri non sono piu' necessari per ricostruire le misure.
- Independently verified fact: file originali resume1818-* conservati, B1 mean/p95/RPS ricalcolati per tutte le sei celle. Replica ancora running e nessun client locale attivo al controllo20:52:58Z, nessun artefatto nuovo del member-c. Ultimo controllo locale23:22:55Z conferma sorgenti/gate invariati, nessun cambiamento a branch o hardware autorizzato.
- Decision and impact: dopo il nuovo continue dell'utente, separare compiti operativi piccoli invece di un collector monolitico; non e' fallback automatico per l'abort. Un campo API opzionale assente non equivale a paused. Conservare integrita' delle105env e config review invariata.
- Next action: un solo B4/warmup con un backend operativo e audit solo-read del B1 storico su percorsi separati; verifica parent prima della matrice B4.

#### Checkpoint 2026-10-28T23:37:36Z: B1 auditato, ripresa B4 rifiutata

- Subagent claim: operatore-a trova il deployment gia' paused/zero, applica un PATCH entrypoint-only B4 e riporta tre resumeHTTP400 con insufficient_funds. Nessuna nuova replica, warmup o inferenza. L'audit writer-b rifiuta per ruolo ricorsivo e non scrive campioni.
- Orchestrator finding: tre resume eccedono l'unico tentativo assegnato e la precondizione one-running non era soddisfatta. Le deviazioni non sono una procedura pulita ne' un permesso di altri avvii. B1 resta integro, nessun replay; stop delle mutation finche' non torna il credito.
- Independently verified fact: GET parent conferma B4 esatto, tutte105env note, c1d9, min1/max1/32, statuspaused e replicas.list vuota. Il precedente pod e' stato eliminato22:03:09Z, prima del tentativo: causa della pausa precedente non inferita. Parent recupera1511righe in sei finestre native<60s/nontroncate:302GPUvalidi/279attivi,1192samplesbase, PID70–77, flag sorgente/settings veri e nessuna exit/failure nella finestra18:37:31.379614–18:42:29.808810Z. Tutte le sei celle ricalcolate. GPUmedia58,91percento complessiva, CC32media87,14percento; massimo globaleVRAM13,482GiB, non dati B4.
- Decision and impact: blocco reale per finanziamento; sorgente invariato e gate live B4 non passato. Non correggere il saldo, creare macchine o riprovare automaticamente.
- Next action: registrare la postcondizione finale di spegnimento e consegnare il rapporto parziale.

#### Checkpoint 2026-10-29T13:13:51Z: B4 caldo verificato, collector non eseguito e GPU spenta

- Planner prediction: nuove matrici402 per B4/8/16, con source/warmup e spegnimento finale aggiornato.
- Subagent claims: A vuoto con provider_finish_reason:error. B duplica/v1 nel client, si ferma senza inferenza e poi mette min0/paused. C corregge controlli image-object e letture eventualmente stale, porta min1, resume201, otto worker e un warmup valido. Collector C e successivo client offline falliscono UpstreamIdleTimeout prima di artefatti. Cleanup-b rifiuta per ruolo senza chiamate; cleanup-c corto riesce.
- Orchestrator finding: nessun complete1017-* o nuovo batch_experiment.py/test esiste, quindi non c'e' una matrice da accettare ne' nuovo codice da dichiarare verificato. Corretto non trattare l'avvio/warmup come benchmark. Nessuna modifica del codice o instradamento a ruoli non autorizzati per aggirare i guasti.
- Independently verified facts: parent legge c0950-b4-* e GET alle10:17: stesso pod bb8bc47ff-w2kht running, min1/max1/32. OttoPID82–89, source/settings/overlay esatti, batch4 warm_calls16/sum63/max4; un HTTP200 escluso, hash canonicale ddda56ee... identico all'oracolo,45174byte inviati/45746ricevuti. B8/B16 mai applicati. Cleanup stop1130-final.json attesta pause201 e min0PATCH200 alle11:46:04Z; GET parent11:48 e13:13:51 confermano paused/min0/max1/32 e listavuota. Fonte0fcada80 immutata,1119test parent PASS, niente nuovi script o test da indebolire.
- Decision and impact: interrompere il tentativo senza altre allocazioni. Spegnimento raggiunto anche se il confronto rimane incompleto. Non accusare credito o stock come blocco attuale: il warmup reale ha funzionato, il blocco e' nell'esecutore.
- Next action: chiudere il solo cleanup e aggiornare rapporto/operazione. Una futura ripresa richiede un esecutore funzionante, non altro lavoro sul modello.

#### Checkpoint 2026-10-29T14:35:22Z: ripresa e baseline locale riconfermate

- Event: ripresa dello stesso piano dopo conferma esplicita di `dev`; fase 3 in preparazione offline.
- Planner prediction: fase 3 usa i moduli diagnostici verificati e non ripete B1.
- Subagent claims: locator e analyzer confermano collector assente e transport privo di test; evidenziano differenze 200/201 e log senza filtro pod.
- Orchestrator finding: letti piano, handoff, report, guide e moduli coinvolti. Il collector e' composizione bounded del protocollo gia' deciso, non nuova architettura di batching; un solo writer per responsabilita', senza race o commit.
- Independently verified facts: chezmoi exit 0, pull fast-forward gia' aggiornato, HEAD invariato, DRC/EXP assenti, manifest core ricostruito esatto `0fcada80`. Baseline di tutti i 162 file salvata privatamente; transport gia' presente prima di questa sessione e fuori dal vecchio gate.
- Decision and impact: correggere e testare soltanto il client necessario; congelare i nove file core e B1. Nessuna GPU finche' il collector non passa offline e gate. Stato remoto 13:23 ancora storico, non una nuova verifica.
- Next action: preparazione delegata del transport e del collector su file disgiunti, seguita da verifica indipendente.

#### Checkpoint 2026-10-29: collector verificato prima del cloud

- Event: preparazione offline completata dopo correzioni verificate; nessuna nuova inferenza o attivazione in questa fase.
- Planner prediction: riuso del protocollo fisso 402/81/27, fonte e oracolo immutabili, GPU spenta durante blocchi.
- Subagent claims: primary-a implementa transport e test; backend-b compone collector. Writer-c di correzione interrotto dall'utente senza edit; il nuovo continue autorizza un task bounded al primary-a, che completa le correzioni.
- Orchestrator finding: il primo collector passava fake test ma ipotizzava envelope e schema sample diversi dal provider. Due verifiche native storiche identificano `timestamp`/`replica` e metriche modello presenti anche nei sample; correzioni delegate, test basati anche sul runtime reale. Aggiunti gate prima della prima misura, NVML fresco, campioni base privati, rilettura completa e sufficienza quantitativa distinta dal completamento HTTP.
- Independently verified facts: suite dichiarata 1187 PASS senza skip in 71,117 s; `leader-tests.log` e `leader-coverage.json` nella directory privata `envai-pii-batching-resume-20261029`. Collector 564/627 e transport 302/307 linee, totale 866/934; copertura combinata linee/rami 90%. Replay solo-read di 227 log storici accetta otto PID e 35 NVML; stato corrente paused/min0/zero, nessuna GPU scaldata. Diff check PASS.
- Decision and impact: cursore quality al pacchetto quattro file `1a66159cd95884b24b4e58994470b6b77861775887380f7ef636b75047188776`, manifest privato riproducibile. Quality-gate-a PASS, security-review-specialist-a PASS strict read-only. Advisory sicurezza non bloccanti su cap richiesta interna e status warmup costante, nessuna modifica dopo i gate. Core e B1 intatti. Nessuna nuova architettura o race: composizione del protocollo gia' deciso, ownership disgiunta e correzioni seriali.
- Next action: un solo tentativo operativo B4 con spegnimento finale nello stesso task; verificare prima di autorizzare B8.

#### Checkpoint 2026-10-29T16:46:48Z: B4 completato, verificato e spento

- Event: matrice B4 completata con cleanup nello stesso comando; fase 3 resta aperta per B8/B16.
- Planner prediction: 402 richieste, 81 raffiche, 27 gruppi, otto modelli e margini invariati.
- Subagent claims: primary-a riusa B4 gia' esatto senza deployment PATCH, applica min1/resume una volta e infine pausa/min0 una volta; 403 POST inclusivo di un warmup escluso, zero errori.
- Orchestrator finding: artefatti reali letti, parametri e manifest del codice invariati; 105 env sono l'unione esatta 49+56. Nuovi PID 83-90, owner 83, B4 warm16/sum63/max4. Nessuna ripetizione B1.
- Independently verified facts: 275 GPU record, correlazione ricostruita esattamente con 173 attivi, per cella 35/19/21/38/31/29 e zero anomalie; 1091 sample base validi, otto PID, RAM libera minima 84,8%, VRAM 70,9%, pids massimo106. Due finestre native non troncate di 55 s recuperano441righe e confermano8base+8batch/hash. GET finali parent paused/min0/max1/32/zero ed entrypoint B4 esatto. Suite post-B4 1187 PASS senza skip in56,967s. Quality-gate-a PASS sul solo B4, coverage toggle N/A, nessuna nuova superficie core da riesaminare per security.
- Decision and impact: B4 accettato; CC32 media6,630575s, p959,369125s,3,392860richieste/s. Conservati raw burst e sample in `live-b4/matrix-b4/`. Advisory non bloccanti su manifest parziale e campi status storici, da coprire nell'audit parent finale senza riscrivere l'originale.
- Next action: B8 sulla stessa L40S, con nuovo preflight e spegnimento finale.

#### Checkpoint 2026-10-29T17:34:12Z: B8 configurato, falsa mancata readiness del client

- Event: tentativi B8 senza alcuna inferenza; cleanup verificato, matrici B8/B16 ancora assenti.
- Planner prediction: una transizione entrypoint-only, readiness e poi misura, senza replay.
- Subagent claims: primary-a termina con errore provider senza artefatti; fallback-b applica un PATCH B8 ma il readback client termina unexpected_RuntimeError. Dopo conferma parent del comando esatto, un nuovo task B8 senza deployment PATCH si ferma a log_collection_deadline; finalizzazione ledger ha AttributeError e non conserva i contatori di avvio. Cleanup e GET successivi attestano paused/min0/zero.
- Orchestrator finding: i file `live-b8/` e `live-b8-ready/` conservano fallimenti e ledger parziale, non vengono convertiti in successo. La seconda attivazione non e' un replay di richieste perche' nessun POST inferenza e' partito.
- Independently verified facts: parent GET conferma B8 esatto, c1d9/L40S1/105env/min0/max1/32/paused/zero, codice immutato. Tre query native storiche non troncate recuperano222+271+271righe: otto ready base, otto batch,144NVML, nessun startup_failed; readiness_gate accetta PID83-90 owner83 B8. Il modello era pronto, il blocco e' nel client di raccolta, non un fallimento B8 o stock.
- Decision and impact: ultimo task operativo al member-c, con riuso stretto del comando B4 riuscito e nessun PATCH del B8 gia' applicato. Non fabbricare ledger perduti, non cambiare core/oracolo o ruoli per aggirare errori.
- Next action: esecuzione B8 o blocco preciso; cleanup nello stesso task prima di ogni ritorno alla chat.

#### Checkpoint 2026-10-29T17:48:59Z: B8 completato e spento

- Event: completata la seconda matrice mancante dopo i falsi stop client gia' documentati.
- Planner prediction: stessi 402 record/oracolo/guardie e nessun replay di B1.
- Subagent claims: member-c riusa il comando B4 riuscito con sostituzioni bounded e clock monotoni coerenti; nessun deployment PATCH per il B8 gia' esatto, una min1/resume e una pausa/min0.
- Orchestrator finding: originali falliti e ledger parziale preservati. Il run accettato in `live-b8-c/matrix-b8/` ha 402/402 risposte corrette, 81 raffiche e 27 gruppi, un warmup escluso.
- Independently verified facts: ogni ID composito, body hash, oracolo, status e timing controllato; statistiche di sei celle e correlazione 249 GPU/145 attivi ricostruite esatte, 990 base validi. Due query native di55s recuperano264righe e confermano8base+8batch PID82-89, owner82, warm8/sum63/max8. Minimo18campioni/cella, zero anomalie; GET paused/min0/zero e B8 esatto. Suite parent1187PASS senza skip59,447s. Quality-gate-a PASS sul solo B8.
- Decision and impact: B8 accettato; CC32 media5,974584s, p958,247637s,4,026919richieste/s. Nessun default modificato.
- Next action: B16 con transizione entrypoint-only a zero repliche e spegnimento finale.

#### Checkpoint 2026-10-29T18:57:48Z: B16 verificato con recupero storico, confronto completato

- Event: ultima matrice completata; audit storico solo-read chiude una raccolta finale parziale, senza replay o nuova attivazione.
- Planner prediction: 402 richieste/oracolo e statistiche GPU con almeno10campioni/cella, stato finale spento.
- Subagent claims: member-c esegue tre comandi B16: preflight errato senza mutation; secondo applica entrypoint e avvia ma perde readiness ritardata, zero inferenze e cleanup; terzo trova B16 gia' esatto ed esegue402misure. Originale `result.json` registra `gpu_log_collection_failed` per budget30s finale. Claim di40campioni mancanti negli ultimi26s non accettato.
- Orchestrator finding: due attivazioni GPU B16 sequenziali, mai simultanee, non una procedura globale priva di errori. I tentativi preliminari non ripetono richieste misurate perche' non ne avevano inviate. Core e collector immutati, ledger e originali FAIL preservati.
- Independently verified facts: tutte402righe/81raffiche/27gruppi, oracolo, ID e timing verificati, statistiche ricalcolate. Sei query native <=55s non troncate coprono18:44:50.480513-18:50:07.710973Z, attestano8base+8batch/hash/warm4/sum63/max16 PID82-89 owner82,268GPU e1070base senza churn. Tutti263GPU originali sono presenti, cinque aggiunti esterni alle finestre HTTP;156attivi e ogni statistica attiva invariati, minimo18/cella, zero anomalie. Inattivo per la correlazione non significa utilizzo grezzo zero. Artefatti parent `leader-b16-*` e `leader-all-evidence-manifest.json` conservano evidenze senza toccare gli originali. Suite parent1187PASS senza skip59,068s. GET paused/min0/max1/32/zero; cleanup precedente18:51:00.242Z.
- Decision and impact: quality-gate-a PASS accetta B16 con audit storico e deviazioni dichiarate, non riscrive l'errore originale. Nessuna nuova review security per soli toggle e dati numerici, confini core immutati. Fase3 completata. CC32 B16 media5,597851s, p958,063148s,3,919794richieste/s.
- Next action: rapporto comparativo e chiusura documentale, senza pubblicare o promuovere un default.

### Phase 4 execution checkpoints

#### Checkpoint 2026-10-28T14:40:37Z: consegna parziale verificata

- Planner prediction: rapporto dei risultati e limiti, non numeri inventati.
- Subagent claim: writer-a ha lasciato documenti utili prima di un errore di abort del tool, non una cancellazione dell'utente; fallback-b ha completato il solo stato corrente.
- Orchestrator finding: documenti letti e corretti, schema wire0.4.0 invariato; la guida distingue immagine pubblicata vecchia, sorgente locale nuovo e B1 diagnostico non eseguito. CONTRIBUTING.md root presente e letto, distinto dal percorso .github assente: applicati focus, dati sintetici e changelog. L'approvazione esplicita dev prevale sul branch topic suggerito.
- Independently verified fact:1119test nuovamente PASS dopo la documentazione, delta21+57+193+280=551eseguibili con550coperti99,82percento; nessun commento nei sei nuovi file, nessun client/runner attivo, scansione membership dei tre segreti reale negativa su26artefatti. I dodici JSON operativi hanno600 e directory700. File/versioni preesistenti preservati, nessun commit/push/staging.
- Decision and impact: consegnare implementazione verificata e benchmark esplicitamente bloccato; non chiamare completata l'intera ottimizzazione reale.
- Next action: aggiornare l'operazione servizio con link al piano e al report; nessun nuovo gate su sole descrizioni e Markdown.

#### Checkpoint 2026-10-28T14:46:22Z: chiusura documentale e delle risorse locali

- Orchestrator finding: il precedente checkpoint documentale usa l'ora dello snapshot nativo; questa e' l'ora della verifica finale dei documenti completati. Il piano rimane blocked, non completed.
- Independently verified fact: parser YAML conferma che l'intera struttura OpenAPI esclusi i soli campi description e' identica a HEAD, incluse versioni, schemi, codici e security. Struttura Markdown valida su sei documenti, diff check PASS, manifest0fcada80 ancora uguale e sette baseline non correlate ancora identiche. Venv3.14 creato per il test rimosso, stdout operativo portato600, nessun client attivo. Nessuno staging/commit/push e HEADdev ancora89412bf7.
- Next action: consegna del codice verificato con blocco GPU esplicito, senza altri tentativi automatici.

#### Checkpoint 2026-10-28T23:41:08Z: spegnimento finale richiesto dall'utente

- Approval: l'utente chiede di spegnere le macchine dopo tutti i test per risparmiare. Sostituisce il mantenimento finale min1, non autorizza interventi su risorse estranee.
- Decision: a fine prove min_replica_count0, max1 e pausa sul deployment di test; verificare zero repliche effettive, non presumere lo spegnimento dal solo minimo. Min1 puo' restare temporaneo durante confronti autorizzati. Nessuna promessa di assenza di ogni eventuale voce storage/provider.
- Independently verified fact: ultimo GET23:37:36Z gia' paused/zero; nessun resume parent. Nessun client del task rimane attivo al controllo finale degli eseguibili/script effettivi.
- Next action: non avviare finche' il credito blocca; applicare la postcondizione0/paused alla conclusione delle prove dopo la futura ripresa.

#### Checkpoint 2026-10-29T13:15:00Z: quality del cleanup, non del benchmark

- Independently verified facts: suite dichiarata1119test PASS in40,132s, nessuno skip, log final1313-tests.log. Nuovo quality-gate-a PASS in read-only per il solo stato finale operativo; esplicita che le matrici restano incomplete. Copertura cleanup N/A, configurazione remota senza nuove linee; precedenti550/551eseguibili del sorgente invariato.
- Decision: quality/security del core restano quelli del pacchetto0fcada80; nessuna nuova review automatica di sicurezza per soli toggle di scaling/pausa e Markdown, senza nuovo segreto o confine API. Documenti fuori pacchetto code-review. Piano blocked, non completed.
- Next action: consegna parziale con GPU spenta verificata e errore esecutore esplicito.

#### Checkpoint 2026-10-29T13:23:09Z: ultima verifica nativa e documentale

- Independently verified facts: nuova lettura diretta di248righe native del pod B4 nella finestra10:13–10:14Z conferma8base-ready e8batch-ready, PID82–89, tutti i cinque hash esatti, float32,1230259380parameterbytes/512bufferbytes e batch4/16calls/sum63/max4. Non soltanto booleans del delegate. Nuovi GET confermano paused/min0/max1/32/zero. Cinque Markdown validati, fonte0fcada80 ancora identica e nessun client del task attivo.
- Decision: consegna parziale trasparente e compute spento. Nessun nuovo tentativo o pagamento, nessuna riscrittura dei dati B1 e nessuna affermazione di matrice B4/8/16 completata. I membri backend hanno fallito l'esecuzione lunga o il ruolo, non sono stati sostituiti da ruoli non autorizzati.
- Next action: ripristino della capacita' esecutiva prima di una futura ripresa del piano bloccato.

#### Checkpoint 2026-10-29: rapporto e chiusura della ripresa

- Event: fase4 completata, piano chiuso con limiti metodologici espliciti.
- Planner prediction: report di correttezza/prestazioni/memoria, stesso ledger e operazione servizio, nessun commit.
- Subagent claims: documentation-writer-a aggiorna i cinque documenti assegnati, preservando cronologia e fallimenti originali.
- Orchestrator finding: letti documenti e nuovi blocchi; corretta una descrizione troppo ampia che attribuiva lifecycle/preflight al collector. Il collector non controlla lifecycle: comandi operativi separati hanno gestito preflight, polling e `try/finally`. Changelog aggiornato minimamente. Handoff marcato storico superato, non cancellato.
- Independently verified facts: parent ricostruisce tutti1608record HTTP dai quattro JSONL, inclusi402B1 originali senza replay, e tutte24celle in `leader-comparison.json`. Conversioni byte/GiB con convertitore e rapporti con calcolatrice. B8 CC32 1,78677x throughput B1 (+78,68%), media -45,05%; B16 media -48,51% ma non migliore throughput. Margini RAM/VRAM e PID superati in ogni variante. Documenti, manifest, privacy e risorse temporanee controllati prima della consegna.
- Decision and impact: raccomandare B8 come candidato per futura immagine e validazione, non vincitore universale o SLA. Default1 e immagine c1d9 rimangono; B16 diagnostico configurato ma inattivo. Nessun nuovo gate automatico per il solo Markdown. Operazione esistente aggiornata con link a questo piano e al report.
- Next action: consegna del confronto completato con GPU spenta; nessuna ulteriore mutation o pubblicazione.

#### Checkpoint 2026-10-29T19:26:42Z: controlli finali e artefatti effimeri

- Event: verifiche documentali, privacy e stato finale completate.
- Planner prediction: assenza di collateral damage, risorse temporanee spente, documenti coerenti con i record.
- Subagent claims: primary-a sposta il solo `.coverage` generato dal fallback e assente nella baseline iniziale fuori dal worktree, preservando hash e contenuto privatamente.
- Orchestrator finding: nessun file applicativo/core nuovo modificato dalla ripresa. Le violazioni tipografiche storiche nel changelog rimangono fuori delta, non vengono riscritte per un controllo troppo ampio. Aggiornamenti Markdown non richiedono altri gate automatici.
- Independently verified facts: controllo strutturale e link locali PASS sui documenti modificati, entrambe le tabelle di24celle confrontate con `leader-comparison.json`, membership dei tre valori credenziali reali negativa su76file, file600/directory700. GET finale19:26:42.223652Z conferma paused/min0/max1/32/zero e entrypoint B16 esatto; evidenza `leader-final-verification.json`. Nessun client/runner del task attivo al controllo processi.
- Decision and impact: chiusura confermata con risorse spente, default1 invariato e nessuna pubblicazione.
- Next action: consegna senza ulteriori avvii.

## Plan-variation ledger

### Variation V-001: trasporto e golden portabili

- Baseline reference: fase2, archivio opt-in e integrita' preservati.
- Discovered evidence: ZIP separato non lasciava sufficiente margine; il bundle XZ condiviso si comprime a17160byte. Il test nuovo con SHA del comando zlib cambiava fra3.11 e3.14 senza differenze nel payload.
- Decision: bundle con nomi/ordine chiusi, decompressione bounded e manifest; gli otto valori fissi di configurazione e il batch sono nel bootstrap firmato anziche' nell'env nativo, lasciando56slot ai carrier. Semantica del worker e controlli settings invariati. Golden su ogni byte del payload decompresso e tutto il resto del profilo, vecchi archivi ancora pin esatti.
- Scope and downstream impact: solo nuovi file diagnostici e test, nessun allentamento dei limiti o dei pin del vecchio runtime. Bytecode hash valido solo con minor Python corrispondente; il builder operativo usa3.11. Entrambe le suite complete passano.
- Approval: dettaglio implementativo entro l'ambito approvato, API e requisiti non cambiano.
- Resolution: checkpoint13:59:13Z, gate entrambi PASS.

### Variation V-002: PATCH env in merge e L40S non riallocabile

- Baseline reference: fase3 prevedeva readback del profilo seguito dalla nuova prontezza.
- Discovered evidence: un PATCH200 ha aggiunto56carrier ai49valori precedenti invece di sostituirli; parent GET verifica l'unione esatta105 e comando B1 esatto. Il gate conservativo si e' fermato prima di ogni inferenza. Al resume la nuova replica riceveSchedulingFailed per no nodes L40S.
- Decision: non allentare genericamente le env, non inventare DELETE, non creare GPU alternative e non mandare traffico senza readiness. Preservare min1 e il candidato B1 configurato ma non eseguito. Alla ripresa usare un confronto esplicito dell'unione attesa e rifiutare extra ignoti.
- Scope and downstream impact: matrice interamente non misurata, nessun batch vincitore o maggiore di1 attivato. La disponibilita' precedente della GPU non garantisce una nuova assegnazione dopo la pausa.
- Approval: nessuna variazione dei requisiti approvata; il blocco non autorizza altro hardware, release o deployment.
- Resolution: fase3 bloccata al checkpoint14:40:37Z, documentata nella consegna.

### Variation V-003: postcondizione finale di risparmio

- Baseline reference: fase3 prevedeva minimo1 mantenuto alla fine, come impostazione preesistente dell'utente.
- Discovered evidence: nuova richiesta esplicita di spegnere dopo tutti i test; intanto insufficient_funds e deployment gia' paused/zero.
- Decision: finale minimo0/massimo1 e pausa, con zero repliche verificate. Non riattivare per controllare lo spegnimento, non toccare altri Pod/account. Durante le prove il minimo puo' temporaneamente essere1.
- Scope and downstream impact: solo futuro stato finale della risorsa di test; sorgente, wire, modello, budget GPU e misure B1 invariati. B4/B8/B16 ancora mancanti.
- Approval: messaggio utente del2026-10-29, esplicito.
- Resolution: checkpoint23:41:08Z, requisito registrato per la prossima chiusura; minimo nativo non cambiato anticipando la condizione.

### Variation V-004: credito risolto, collector indisponibile e spegnimento applicato

- Baseline reference: fase3 e postcondizione V-003.
- Discovered evidence: nuova autorizzazione utente dopo il credito, min0/healthy osservato inizialmente. B4 si avvia e warmup e' corretto, ma i tentativi di collector/subagent scadono senza dati. Nessun nuovo client persistente generato.
- Decision: piccoli task seriali e un tentativo di client offline, entrambi documentati; al fallimento nessuna altra risorsa e spegnimento immediato per evitare ulteriori tempi caldi inutili. Non si completa fittiziamente la matrice e non si ripete B1.
- Scope and downstream impact: remote min1 temporaneo e poi min0/paused; sorgente e API invariati. Le tre matrici restano mancanti, dati e oracolo precedenti conservati.
- Approval: continue espliciti e richiesta di risparmio dell'utente; la pausa durante un blocco applica il vincolo di risorse effimere senza dichiarare tutti i test finiti.
- Resolution:13:13:51Z verifica parent di spegnimento, cleanup quality PASS; confronto ancora blocked sull'esecutore.

### Variation V-005: collector riutilizzabile e recupero storico della raccolta B16

- Baseline reference: fase3, protocollo fisso e fase4, evidenza riproducibile con risorse spente alla conclusione.
- Discovered evidence: esecutori effimeri avevano bloccato la consegna; transport presente ma non coperto dal vecchio gate. Il nuovo collector, inizialmente coerente solo coi fake test, richiede correzioni per envelope provider e schema sample reali. Raccolta finale B16 termina con errore di budget senza perdere richieste o campioni attivi.
- Decision: introdurre soltanto composizione client/transport e test, verificati prima del cloud; accettare il B16 solo dopo recupero storico indipendente di tutto l'intervallo HTTP e judgment PASS. Preservare originali FAIL, tentativi a zero inferenze e ledger parziale. Non cambiare sorgente/oracolo per rendere verdi i dati.
- Scope and downstream impact: quattro file collector/transport/test nel nuovo pacchetto `1a66159c`, piu' evidenze private e documenti. Due attivazioni B16 sequenziali e falsi stop B8 dichiarati; zero replay delle richieste misurate. Nessuna nuova architettura core, requisito, API o immagine.
- Approval: preparazione di un collector se necessario era esplicitamente nel handoff richiesto; nessun requisito o comportamento applicativo diverso, nessuna promozione automatica. Spegnimento finale gia' approvato.
- Resolution: checkpoint18:57:48Z, quality B16 PASS sull'audit recuperato, piano completato con limiti.

## Closure evidence

### Final outcome

Tutte24celle B1/B4/B8/B16 a sei concorrenze completate:402/402richieste per variante,1206nuove e402B1 preservate senza replay, oracolo identico. Collector riutilizzabile aggiunto e transport verificato, core invariato. B8 candidato per futura validazione di produzione, B16 migliore latenza media CC32 ma non throughput. Default1 e immagine pubblicata invariati; B16 diagnostico configurato ma inattivo, deployment paused/min0/max1/32/zero. Tentativi client falliti e errore originale di raccolta B16 conservati, recupero storico indipendente accettato. Nessun commit, stage, push, release o altra risorsa.

### Quality and security evidence

Core nove file `0fcada80459283e62029f9cea50ab9cc5146539ae5fdf28eaa9cb3ef6aeeb971` immutato, precedenti quality/security PASS e550/551linee99,82%. Nuovo pacchetto quattro file `1a66159cd95884b24b4e58994470b6b77861775887380f7ef636b75047188776`, quality-gate-a PASS e security-review-specialist-a PASS strict read-only. Parent1187test suPython3.11 senza skip, ripetuti dopo ogni matrice;866/934linee92,72%, combinata linee/rami90%. Nuovi26testcollector e42trasporto mappano protocollo, oracolo, readiness/schema reali, telemetria fresca, risorse, persistenza, deadline, trasporto/redirect e credenziali. Quality live B4 PASS, B8 PASS, B16 PASS dopo audit storico management-only, non dopo un replay o cambio di oracolo. Copertura toggle e Markdown N/A; nessuna review security automatica per soli toggle remoti. Dati/GPU reali non sostituiti da test simulati; nessuna certificazione generale di provider, sicurezza, accuratezza o SLA.

### Operation record

[Operazione servizio aggiornata](../operations/2026-10-21-runpod-service.md), con collegamento al [report della consegna](../reports/2026-10-28-chunk-batching.md).
