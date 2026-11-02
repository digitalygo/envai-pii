---
document_type: mycelium-plan
plan_id: 2026-10-29-copies-startup-comparison
status: completed
created_at: 2026-10-29
planner: orchestrator
baseline_version: 1
execution_owner: orchestrator
execution_started_at: 2026-10-29
last_updated_at: 2026-10-30
---

# Confronto di 8, 12 e 16 copie a B8 e tempi di avvio

## Current execution snapshot

- Status: completed, tre conteggi e startup verificati, deployment spento.
- Baseline identity: `2026-10-29-copies-startup-comparison`, versione1, baseline immutabile distinta dal precedente piano batching.
- Execution baseline: `dev` approvato, HEAD `89412bf750c2a6bf3e80fcfbb7bebd192597ef46` invariato; dirty worktree preesistente preservato, manifest iniziale165file e sorgenti diagnostici precedenti archiviati privatamente.
- Active phase: fase3 conclusa, rapporto e operazione aggiornati.
- Last verified checkpoint: 2026-10-30T01:09:57.158686Z, paused/min0/max1/32/zero, entrypoint N16/B8 e unione105env esatti; controlli di integrita', privacy e documenti PASS.
- Last successful checks: parent1233test senza skip74,308s dopo N16; delta produzione412/443linee (93,00%) e test946/949. Pacchetto `46d02491` quality PASS, quality live N8/N12/N16 PASS; runtime e archivio identici al security PASS di preparazione `2979376b`, seguiti solo da correzioni numeriche metadata/startup.
- Open blockers: nessuno per l'incarico. Cache/nodo non controllati e un solo avvio per conteggio limitano le conclusioni; errori preliminari e startup N8 partial_only originali conservati.
- Required approvals and gates: nessuna approvazione pendente; niente commit/push/release, altri deployment o modifica automatica del default1. Profilo N16/B8 conservato ma inattivo.
- Next action: nessun nuovo avvio automatico. Raccomandare8copie/B8 come compromesso candidato nel carico<=32client, non massimo fisico o SLA.

## Planner baseline

### Problem statement

L'utente chiede di provare8/12/16copie e verificare l'aumento del tempo di avvio. Il confronto precedente cambia il batch con otto copie fisse; non dimostra il massimo fisico o il numero ottimale di copie. Nuova serie a B8 fisso, stessi pesi/precisione/fixture/oracolo, con N8 fresco espressamente autorizzato come controllo. I risultati e i piani precedenti restano storici, non vengono sovrascritti.

### Research and evidence

- [Confronto batching completato](../reports/2026-10-28-chunk-batching.md): N8/B8/CC32 4,026919richieste/s, media5,974584s, p958,247637s, GPUattivita'81,17%, VRAM14,091GiB su47,384GiB. Questi margini non stimano capacita' di calcolo o massimo numero di copie.
- `runtime.py`, `gpu_runtime.py`, `gpu_monitor.py`, `batch_runtime.py`, `batch_package.py`, `gpu_profile.py`, `measure.py`, `batch_experiment.py` hanno vincoli separati sul conteggio. Solo cambiare `--workers` fallirebbe startup, barriera, emissione, parser o correlazione.
- I timestamp provider dei ready e degli eventi di lifecycle permettono una misura di avvio; l'istante di osservazione del polling include anche latenza di ingestione. Il precedente collector non conserva queste durate.
- Regole root `AGENTS.md` e `CONTRIBUTING.md`; DRC/EXP assenti. Baseline/sorgenti precedenti salvati privatamente in `/home/lorenzo/private/tmp/envai-pii-copies-startup-20261029/` prima di ogni edit.

### Hypotheses, decisions, and rationale

Task medium+ per sensibilita' del percorso diagnostico e costo cloud. Nessun nuovo algoritmo di inferenza, scheduler, dipendenza, immagine o modifica core: parametrizzare la composizione esistente mantenendo i default8 e i controlli di identita'. Un writer per responsabilita' disgiunta e correzioni seriali sono sufficienti per questo refactor meccanico; nessuna race con commit o merge. Gli archivi diagnostici cambieranno se cambiano i sorgenti inclusi: preservare il vecchio sorgente e pin dell'immagine base, ricalcolare i nuovi golden verificando integrita' e trasporto, mai falsificare i vecchi hash.

Una sola attivazione autorizzata per conteggio nella serie, in sequenza e con zero repliche tra profili; stop su errore serio senza replay di misure. Predire in modo conservativo risorse per il prossimo conteggio a partire dai nuovi campioni effettivi; le stime storiche del vecchio confronto B1 non sono limiti kernel o prove che N12 superi409task. Budget PID sperimentale512/guardia409, RAM/VRAM almeno20% libere, nessun tentativo deliberato di OOM. Il default applicativo batch1 non cambia.

Per startup distinguere `resume_requested`, `resume_accepted`, lifecycle provider della replica, primo/ultimo ready atteso, istante in cui il collector osserva readiness e primo warmup HTTP corretto. Calcolare separatamente attesa scheduling/container e caricamento+CUDA+warmup+barriera; non chiamare il ritardo di polling tempo di caricamento. Classificare cache solo con prova esplicita, altrimenti sconosciuta. Un avvio per conteggio e host/cache non controllati sono osservazioni, non distribuzioni o causalita' isolata.

### Planned phases

#### Phase 1: estensione offline e startup

- Objective: supportare N8/N12/N16 a B8 con identita' reale in tutti i record e startup ricostruibile.
- Planner predictions: moduli diagnostici server/package e loro test, collector/misure/guardie e test; piccolo helper startup puro. Applicazione e credenziali/trasporto invariati.
- Proposed steps: aggiungere conteggi supportati e parametri espliciti con default8, conservare schema chiuso e verificare all-N readiness/owner minimo/barriera; riusare402/81/27, persistenza e correlazione. Derivare startup da timestamp nativi e ledger client, con reason per dati mancanti. Nessun download Torch/modelli/dataset.
- Predicted verification: suite dichiarata completa, nuovi test8/12/16 e mismatch, fake eventi provider reali, sandbox bootstrap3.11, nessun test indebolito; coverage delta>=80%. Quality e security pertinenti PASS prima dell'attivazione.
- Completion criterion: profili riproducibili e tutti i gate offline indipendenti superati, archivi nei limiti provider.

#### Phase 2: serie live N8/N12/N16

- Objective: tre matrici comparabili e tre osservazioni di startup sulla sola L40S di test.
- Planner predictions: solo `envai-pii-test`, stessa immagine c1d9/port5005/health/devshm64/max1/provider32, B8 fisso e otto parametri di admission invariati per processo; aumento copie modifica aggregate admission e distribuzione.
- Proposed steps: preflight fresco, stato zero, un PATCH profilo verificato e readback bounded senza resubmit, min1 temporaneo e un resume; log completi con finestre<=55s/limit1000/split/riletture. All-N base/batch pronti e telemetria fresca, warmup escluso e matrix402. Persistenza dei raw burst prima del prossimo. Infine pausa/min0 e zero verificato nello stesso comando, anche su failure. Nessuna GPU lasciata calda durante review o attesa subagent.
- Predicted verification: 402IDcompositiunici, oracolo `ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`, fixture45174byte/63chunk, >=10campioni attivi/cella, margini e PID stabili. Startup con timestamp e limiti espliciti, cache sconosciuta se non provata. Budget per conteggio finito: startup<=600s, matrice700s, raccolta90s, cleanup180s, finestra globale1800s. Deadline applicativa60s e trasporto90s invariati.
- Completion criterion: evidenze ricostruite indipendentemente e judgment quality live PASS per ciascun conteggio, oppure blocco esatto e risorsa spenta. Nessuna sostituzione di errori con vecchi dati.

#### Phase 3: confronto e chiusura

- Objective: dire se aumentano throughput e tempo di avvio, senza promesse causali o promozioni automatiche.
- Planner predictions: nuovo report in traces, aggiornamenti compatti alla guida Verda/changelog e all'operazione servizio esistente; questo piano aggiornato soltanto dal coordinatore.
- Proposed steps: ricalcolare latenze/p95/RPS dagli stessi raw, confrontare memoria/GPU/stabilita' e durate startup, indicare benefici marginali ed eventuale peggioramento. Conservare tutti i tentativi/partial e documentare limiti di cache/host. Finale minimo0/pausa/zero, nessun nuovo default o release.
- Predicted verification: statistiche e timestamp raw controllati, conversioni con strumenti, manifest/permessi/membership credenziali, diff e risorse effimere. Markdown-only test/coverage N/A.
- Completion criterion: rapporto verificato, stato finale noto e ledger/operazione chiusi o blocco esplicito.

## Execution ledger

### Ledger rules

Append-only; baseline precedente immutabile. Solo il coordinatore aggiorna il piano; claim dei subagent non equivalgono a fatti verificati.

### Phase 1 execution checkpoints

#### Checkpoint 2026-10-29: baseline e ambito validati

- Event: nuovo incarico avviato dopo il confronto batching completato.
- Planner prediction: parametri diagnostici, non nuovo motore di inferenza.
- Subagent claims: locator/analyzer individuano i vincoli count e l'assenza di una misura startup; alcune inferenze sui vecchi PID e sul divieto di modifiche non descrivono questo incarico.
- Orchestrator finding: il nuovo messaggio autorizza espressamente nuovi8/12/16 e l'estensione harness necessaria. Le vecchie stime PID B1 non possono essere usate come misura N12: i nuovi N8/B8 osservavano103task nell'intero cgroup. Conservare guardie e verificare misure reali.
- Independently verified facts: chezmoi exit0, dev sincronizzato e precedentemente approvato, baseline165file privata, vecchi sorgenti preservati. GET fresco paused/min0/max1/32/zero, L40S1, immaginec1d9 e105env. Nessun resume/inferenza.
- Decision and impact: preparazione offline su responsabilita' disgiunte, nuovi archivi attestati e gate prima del cloud; piani completati non riaperti.
- Next action: implementazione diagnostica delegata e verifica indipendente.

#### Checkpoint 2026-10-29: estensione diagnostica e startup verificati offline

- Event: fase1 completata senza avviare GPU.
- Planner prediction: parametrizzazione meccanica e helper startup, nessuna nuova architettura core.
- Subagent claims: writer-a estende server/package e aggiorna i soli golden cambiati legittimamente; writer-b estende collector/misure/guardie e helper startup. Entrambi senza cloud o credenziali. Un primo full run del server vedeva failure concorrenti, non uno stato finale accettato.
- Orchestrator finding: delta letto e confronto con vecchie copie private; immagine, core app, helper batching, fixture e trasporto invariati. Primo helper startup ipotizzava Created prima di Scheduled; native historical replay mostra Scheduled prima di Created e count2 per eventi container aggregati. Correzione delegata, test native-shaped aggiunti; questi eventi ora unknown/ambigui e le durate Gunicorn vengono distinte da caricamento puro e polling.
- Independently verified facts: parent suite1231PASS senza skip91,839s, log/coverage e delta in root privata. Produzione406/437linee e test871/874 coperte; nessun test eliminato o saltato. Native historical startup replay PASS con ancore client sintetiche dichiarate, non una nuova misura. Profili8/12/16 allB8: archivio17216byte SHA015dd46695c207a36af412bafde7e96031ccce1c5b81ae5a34726f9bbe13dcdb,56argv/56carrier253byte e8slotmargine, overlayapp/helper/hash immutati; builder3.11 obbligatorio.
- Decision and impact: quality e security PASS sul pacchetto21file `2979376b44178d5a6568c421d8a529ec86372d9282010621901e9c07fc822acf`; manifest privato `review-manifest.json`. Advisory non bloccante su runtime.PROSPECTIVE_WORKERS non usato e pin XZ dipendente da interprete; non introdurre un nuovo drift dopo i gate. Vecchi archivi non sostituiti negli artefatti, nuove checksum non spacciate per vecchie.
- Next action: primo N8 nuovo con env56 aggiornate una sola volta e vecchie49 conservate per hash iniziale, senza confrontarle con il builder GPU cambiato.

### Phase 2 execution checkpoints

#### Checkpoint 2026-10-29T23:10:17Z: PATCH N8 rifiutato prima dell'attivazione

- Event: primo comando operativo si ferma prima di min1/resume e qualunque inferenza; deployment resta spento.
- Planner prediction: primo PATCH del profilo invia soltanto56carrier, readback verifica unione105 con vecchie49 preservate.
- Subagent claims: primary-a costruisce erroneamente il PATCH con tutta l'unione105env, riceve400, poi finally pausa201/min0PATCH200 e zero verificato. Flag attemptedfalse nel riepilogo e' errato; ledger registra il PATCH400. Nessun dato startup o matrice.
- Orchestrator finding: errore del client, non evidenza di modello o capacita'. Il dubbio sui33332byte del body corretto non dimostra un limite provider: `PAYLOAD_LIMIT_BYTES` riguarda il bootstrap decompresso, non il JSON HTTP. Il contratto locale non dichiara un limite32768byte per questo body.
- Independently verified facts: parent ricostruisce builder corretto con56env/body33332byte, rilegge codice dei limiti e GET paused/min0/zero; vecchia definizione immutata. Artefatti falliti in `n8-b8/` preservati, nessun processo effimero rimasto.
- Decision and impact: correzione operativa bounded al fallback-b: usare esattamente il deployment_patch del builder senza sostituireenv con la union. Nessun cambio di codice/gate o limite, nessun retry finanziario/stock e nessun replay.
- Next action: un solo PATCH corretto e, se accettato e verificato, primo N8 con startup/matrice e finaleOFF.

#### Checkpoint 2026-10-30: N8 verificato e startup recuperato a GPU spenta

- Event: primo conteggio della nuova serie completato e spento, nessun replay dei dati precedenti.
- Planner prediction: controllo N8 fresco e startup distinto dal ritardo del collector.
- Subagent claims: fallback-b corregge il solo payload, PATCH56env200 e readback105convecchie49intatte; una min1/resume e una pausa/min0.402misure valide, ma helper startup si ferma su due Created/Started count1 distinti per init e main container.
- Orchestrator finding: eventi realmente distinti non possono essere scelti arbitrariamente come start del main; correzione delegata solo a helper/test: campi opzionali diventano unknown, mentre boot Gunicorn e ready restano misurabili. Server/archive e dati HTTP/GPU non cambiano. Originale partial_only conservato.
- Independently verified facts: parent ogni402IDcompositi/81raffiche/27gruppi, status/oracolo/fixture/timing e statistiche ricalcolate,211NVML/146attivi e836base ottoPID240-247 owner240,0anomalie,minimo18campioni/cella. Guardie RAM libera84,44%, VRAM70,22%,PIDmax108; pids.max finito580081 sul nodo, nonunbounded. Fullsuite1233PASS senza skip95,615s, productiondelta412/443 e test946/949. Rilettura management-only completa recupera startup senza inferenza: requested23:16:54.751Z,accepted23:16:55.077Z,lastready23:20:35.224965Z,observed23:20:47.459Z; accepted->ready220,147965s e primo boot->ready15,444970s. Fase Pulling->Pulled197s, cache ancora sconosciuta. Artifact leader-n8-startup.json e audit conservano i limiti, GET paused/min0/zero.
- Decision and impact: quality-gate-a PASS su delta completo corretto `46d02491337709447e475ebaca92e61f444bf0ae9871f638a04ffce585047a0e` e N8 con recupero. Nessuna nuova superficie security per la sola correzione numerica del lifecycle; runtime critico identico al precedente PASS. Guardia N12 da N8 nuovo PASS con2GiBmargin, budgetPID512/guardia409, stime esplicitamente non quote provider.
- Next action: N12 con nuovo runID e un solo avvio, senza riapplicare le env gia' aggiornate.

#### Checkpoint 2026-10-30: N12 verificato e spento

- Event: secondo conteggio completato, senza riassegnare archivi/env o ripetere N8.
- Planner prediction: matrice identica e startup all-N con nuovi PID, prima di aumentare a16.
- Subagent claims: backend-b chiede nuovamente branch confirmation senza agire; fallback-c riceve l'approvazione dev gia' presente e riusa il comando N8 con sostituzioni bounded. Un solo PATCH entrypoint, una min1/resume e una pausa/min0; zero errori, source intatto.
- Orchestrator finding: dodici copie reali, PID241-252 owner241, batch8warm8/sum63/max8. Stessi pesi/precisione/immagine/oracolo; cambia soltanto conteggio nel comando. Nessun nuovo codice o scope diverso.
- Independently verified facts: parent ogni402righe/81raffiche/27gruppi e sei statistiche ricostruite,209NVML145attivi/[29,21,16,30,26,23]campioni per cella,1238baseN12,0anomalie. Rilettura native230righe in finestre<=50s riproduce startup.json identico: accepted00:12:32.730Z,lastready00:12:58.838766Z,26,108766s; primo boot->ready17,537627s. Cache e tempi container aggregati unknown, non zero. Parent1233PASS senza skip70,298s, source `46d02491` identico e GETpaused/min0/zero.
- Decision and impact: quality N12 PASS. CC32 4,001195richieste/s, media5,793653s,p957,899093s; aumento modesto rispetto al nuovo N8, non prova di scalabilita' lineare. RAM libera76,78%, VRAM55,33%,PIDmax149. Guardia N16 da questi dati PASScon2GiBmargin,requiredGPU40,55GB<50,87GB eprojectedPID201/required252<512; stime, non misura N16.
- Next action: ultimo N16 con stesso B8 e protocollo, chiusura aGPUspenta prima del rapporto.

#### Checkpoint 2026-10-30T00:44:20Z: N16 completato e verificato

- Event: ultima matrice e ultimo startup completati, fase2 chiusa con GPU spenta.
- Planner prediction: stesso protocollo402/oracolo e startup all-N prima della chiusura.
- Subagent claims: member-c riusa il driver N12 con sostituzioni bounded di conteggio/runID/hash atteso e output; entrypoint-only una volta, min1/resume una volta e pausa/min0 una volta. Driver temporanei rimossi, nessuna modifica repository.
- Orchestrator finding: sedici copie reali, PID240-254 e256 owner240, non si presume che i PID debbano essere consecutivi. B8 fisso e fonte attestata, nessun replay o cambio automatico delle admission32/provider o dei parametri per processo.
- Independently verified facts: parent tutti1206record della serie e18celle ricostruiti; per N16402/81/27,214NVML154attivi e1705base validi,0anomalie e almeno17campioni/cella. Native353righe in due finestre non troncate riproducono startup.json identico. Accepted00:33:15.145Z,lastready00:33:41.765396Z:26,620396s; boot->ready19,868978s, Listening->ready19,874904s. RAM libera69,10%, VRAM40,45%,PID191 sotto409. Suite postN161233PASS senza skip74,308s; source46d02491 immutato, parent GET00:44:20Zpaused/min0/max1/32/zero ed entrypoint N16/B8 esatto.
- Decision and impact: quality-gate-a PASS sul solo N16; tutti i conteggi completati. CC32 N163,818058richieste/s contro N83,861909 e N124,001195, nessun aumento materiale del throughput dal raddoppio delle copie. Nessuna nuova superficie security per i soli toggle e metriche numeriche.
- Next action: rapporto comparativo e chiusura documentale, mantenendo la GPU spenta.

### Phase 3 execution checkpoints

#### Checkpoint 2026-10-30T01:09:57Z: rapporto e verifiche finali

- Event: fase3 conclusa, piano completato con limiti dichiarati.
- Planner prediction: confronto correttezza/prestazioni/memoria/startup e stato finale, senza promozioni automatiche.
- Subagent claims: documentation-writer-a aggiorna nuovo report, due guide, changelog e operazione esistente, senza edit al piano o codice.
- Orchestrator finding: documenti letti e verificati. Corretti in Markdown il prefisso carrier inventato, una cardinalita' categorie non verificata e la formulazione delle medie GPU/throughput. Vecchi report, piani e dati storici rimangono invariati.
- Independently verified facts:18celle nel rapporto corrispondono ai raw verificati; conversioni byte/GiB e rapporti con strumenti. N12 aCC32+3,60665% e N16-1,13547% sul nuovo N8; proxyListening->allready15,450720/17,542707/19,874904s, aumento N16di4,424184s/+28,63416%. Collateral check:22file baseline modificati intenzionalmente e5nuovi, HEAD e staging invariati; nessun nuovo commento Python. Markdown e link PASS, membership dei tre valori credenziali reali negativa su146file, permessi privati600/700, nessun client/driver attivo. GET01:09:57Zconferma paused/min0/max1/32/zero e N16/B8 con105env esatte,vecchie49preservate; prova `leader-final-verification.json`.
- Decision and impact: raccomandare8copie+B8 per il miglior compromesso osservato fino a32client; non affermare massimo fisico, causalita' startup isolata, soak o SLA. N8include197sdi fase provider; cache sconosciuta per tutti, quindi220scontro26s non significa che piu' copie avviino prima. Nessun gate automatico nuovo per il solo Markdown.
- Next action: consegna del risultato e link al report, nessuna nuova attivazione.

## Plan-variation ledger

### Variation V-001: disambiguazione metadata di avvio e recupero N8

- Baseline reference: fase1 startup puro e fase2 timestamp nativi/unknown espliciti.
- Discovered evidence: prima prova storica smentisce Created prima di Scheduled; primo nuovo N8 presenta eventi count1 distinti di container iniziale e principale. Scelta arbitraria dell'ultimo Started non sarebbe una misura verificata.
- Decision: correggere soltanto helper startup/test; container start resta unknown quando ambiguo, mantenere proxy Gunicorn e phase Pulling->Pulled con limiti espliciti. Recuperare N8 in sola lettura senza riavvio e senza alterare l'originale partial_only.
- Scope and downstream impact: due file non inclusi nell'archivio server; suite1233 e quality sul delta completo corretto. Security critical runtime/server/archive/trasporto invariati dal PASS precedente. Nessun cambiamento core o requirement applicativo.
- Approval: entro misure e correttezza diagnostica gia' autorizzate, non una nuova logica di prodotto.
- Resolution: N8 accettato da quality-gate-a sulla ricostruzione parent, poi N12/N16 con stesso helper.

### Variation V-002: correzione del solo payload operativo N8

- Baseline reference: fase2 PATCH del profilo con readback esatto prima del resume.
- Discovered evidence: primary-a invia105env invece56carrier e riceve400 prima di attivare qualunque GPU; nessun effetto sul profilo. Flag attemptedfalse errato nel riepilogo originale, ledger400preservato.
- Decision: fallback con esatto payload builder56env e verifica separata dell'unione105; nessun limite allentato o retry di credito/stock. N8 viene attivato e misurato una sola volta, come N12 e N16.
- Scope and downstream impact: solo comando operativo; codice, fixture, oracolo e protocollo invariati. Fallimento originale conservato, non convertito in PASS o nascosto.
- Approval: correzione interna necessaria all'incarico autorizzato, senza nuove risorse o cambi requisiti.
- Resolution: N8 quality PASS con evidenze complete e finaleOFF.

## Closure evidence

### Final outcome

Confronto nuovo N8/N12/N16 a B8 completato:402/402HTTP200/oracolo per conteggio,1206richieste misurate complessive, un warmup escluso per conteggio, nessun replay. Tutti i margini e i gate superati. Copie aggiuntive aumentano memoria e proxy di avvio senza aumento materiale del throughput nel carico testato;8/B8 resta il candidato consigliato, non un massimo fisico. Default1 e immagine pubblicata invariati, ultimo profilo diagnostico N16/B8 conservato ma inattivo, paused/min0/max1/32/zero verificato. Nessun commit, stage, push, release, pagamento, nuovo segreto o altra risorsa.

### Quality and security evidence

Source21file `46d02491337709447e475ebaca92e61f444bf0ae9871f638a04ffce585047a0e`, manifest privato; parent1233test senza skip e delta produzione412/443linee93,00%, test946/949. Quality source PASS e liveN8/N12/N16PASS, incluso recupero N8 solo-read. Security di preparazione PASS sul pacchetto `2979376b44178d5a6568c421d8a529ec86372d9282010621901e9c07fc822acf`; il delta successivo modifica solo helper/test di metriche startup, non runtime/archivio/core o confini sensibili, quindi non si dichiara una nuova review dell'intero hash46. Archivi e fonte precedenti preservati privatamente, nuovi golden reali verificati con builder3.11 e limiti253byte/64slot/margine8 invariati. Test e coverage toggle/Markdown N/A, non sostituiscono evidenze GPU/native. Nessuna certificazione generale di sicurezza, accuratezza, capacita' massima o SLA.

### Operation record

[L'operazione servizio](../operations/2026-10-21-runpod-service.md) e' aggiornata con il [report delle copie e startup](../reports/2026-10-30-copy-count-startup.md), questo piano e i risultati finali, senza duplicare il ledger.
