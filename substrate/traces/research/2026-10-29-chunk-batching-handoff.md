---
status: completed
created_at: 2026-10-29
updated_at: 2026-10-29
purpose: handoff
execution_status: completed_superseded
last_native_verification: 2026-10-29T19:26:42.223652+00:00
---

# Handoff del batching: documento storico completato e superato

## Stato attuale: completato e superato (2026-10-29T18:57:48Z)

Questo documento di handoff (redatto al checkpoint intermedio delle `13:23:09Z`) e' **completato e superato**. Il corpo originale qui sotto viene conservato integralmente come traccia storica. Per i risultati completi e lo stato corrente fare riferimento al [report finale sul chunk batching](../reports/2026-10-28-chunk-batching.md), alla [guida del parametro](../../../docs/chunk-batching.md), alla [guida del servizio Verda](../../../docs/verda-service.md) e al [record operativo](../operations/2026-10-21-runpod-service.md).

Sintesi del completamento verificato:

- **Modulo collector e transport riutilizzabile (nessuna CLI):** implementato il pacchetto di 4 file (`tools/verda_model_experiment/batch_experiment.py`, `tools/verda_model_experiment/transport.py`, `tests/test_verda_batch_experiment.py`, `tests/test_verda_transport.py`, manifesto SHA256 `1a66159cd95884b24b4e58994470b6b77861775887380f7ef636b75047188776`) mantenendo invariato il pacchetto core di 9 file (`0fcada80459283e62029f9cea50ab9cc5146539ae5fdf28eaa9cb3ef6aeeb971`, copertura `550/551`, `99,82%`). Suite indipendente: **1187 test superati, zero skip** (`59,068 s` dopo `B16`); copertura statement sui nuovi moduli `866/934` (`92,72%`, collector `564/627` `89,95%` linee e `86%` combinata, transport `302/307` `98,37%` linee, combinata complessiva `90%`); gate di qualita' e sicurezza superati.
- **Confronto 4x6 completato (`B1`, `B4`, `B8`, `B16` x `CC1, 2, 4, 8, 16, 32`):** tutte le 24 celle hanno completato `402/402` richieste HTTP `200` validate per batch (`1206` nuove richieste su `B4`, `B8` e `B16` piu' le `402` richieste storiche preservate di `B1`, senza replay di `B1`, per `1608` righe HTTP comparabili su `81` raffiche e `27` gruppi per batch, oltre a un warmup escluso per matrice) con l'oracolo canonico esatto (`ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`).
- **Risultati a `CC32` e raccomandazione:** `B1` media `10,872464 s` / p95 `14,007766 s` / `2,253740 req/s`; `B4` media `6,630575 s` / p95 `9,369125 s` / `3,392860 req/s`; `B8` media `5,974584 s` (`-45,05%` vs `B1`) / p95 `8,247637 s` / `4,026919 req/s` (`1,78677x`, `+78,68%` vs `B1`); `B16` media `5,597851 s` (`-48,51%` vs `B1`) / p95 `8,063148 s` / `3,919794 req/s`. **`B8` (`PII_MODEL_BATCH_SIZE=8`) e' raccomandato come candidato per la validazione su immagine di produzione** (miglior throughput a `CC8`, `CC16` e `CC32` con maggiore margine VRAM rispetto a `B16`), mentre il default nel sorgente resta `1`.
- **Trasparenza operativa e audit `B16`:** sono documentati e preservati i tentativi intermedi di `B8` (`live-b8` e `live-b8-ready` prima di `live-b8-c`) e i tre tentativi di `B16` con **due attivazioni GPU sequenziali** (`live-b16-attempt1-preflight-failed`, `live-b16-attempt2-gate-failed` e `live-b16-c`). In `live-b16-c/matrix-b16/result.json` (preservato inalterato) `stop_reason` e' `gpu_log_collection_failed` per il budget finale di `30 s`, ma i `263` campioni NVML originali contenevano gia' tutti i `156` campioni attivi (inclusi tutti i `25` campioni attivi degli ultimi `24,491 s` di `CC32`); l'audit read-only del parent in `6` query `<= 55 s` (`leader-b16-audit.json`, `leader-b16-gpu-correlation.json`) ha recuperato `268` campioni NVML e `1070` base aggiungendo `5` campioni inattivi per la correlazione e confermando statistiche attive identiche.
- **Stato finale del deployment:** dopo il cleanup delle `18:51:00.242Z`, la lettura nativa indipendente del parent alle **`2026-10-29T18:57:48.974474+00:00`** conferma `status: "paused"`, `min_replica_count: 0`, `max_replica_count: 1`, `concurrent_requests_per_replica: 32` e `replicas.list: []` (compute spento per questo deployment di test, senza dichiarare fatturazione zero globale per l'account; l'overlay diagnostico `B16` resta configurato ma inattivo). Evidenze private in `/home/lorenzo/private/tmp/envai-pii-batching-resume-20261029/`.

Verifica nativa finale read-only alle `2026-10-29T19:26:42.223652+00:00`: confermati paused/min0/max1/concorrenza32, zero repliche ed entrypoint B16 esatto, senza nuovo traffico di inferenza. Evidenza privata `leader-final-verification.json`.

## Da leggere prima di riprendere (snapshot storico delle 13:23:09Z)

Il batching intra-documento e' gia' implementato e verificato nel sorgente. **Non va implementato da zero.** Mancano le matrici GPU dei batch 4/8/16 e il confronto con B1.

La GPU di test e' **spenta**: ultimo controllo nativo `paused`, minimo 0, massimo 1, concorrenza 32 e zero repliche. Non riaccenderla finche' non esiste un esecutore/collector funzionante. Il credito e' stato risolto; il blocco rimasto e' nei subagent.

Questo handoff riporta evidenze gia' verificate. Non avvia test, non modifica configurazioni e non sostituisce il piano esistente. Nella nuova chat rileggere lo stato reale prima di agire.

## Stato del lavoro

| Parte | Stato |
| --- | --- |
| Batching 1/4/8/16 nel sorgente | Implementato, default 1 |
| Test locali | 1119 superati, nessuno skip |
| Copertura del delta | 550/551 linee, 99,82% |
| Quality e security del sorgente | PASS sul pacchetto congelato |
| B1 su L40S con otto modelli | 402/402 richieste valide, audit GPU completato |
| B4 su L40S con otto modelli | Avvio e un warmup corretti, matrice non eseguita |
| B8 e B16 | Mai attivati, nessuna matrice |
| Collector/CLI riutilizzabile | Non creato |
| Spegnimento del tentativo | Applicato e verificato |
| Commit, push, release o nuova immagine | Nessuno |

Il warmup B4 non e' un benchmark: non dimostra uno speedup e non permette di scegliere un batch vincitore.

## Checkout e sorgente da preservare

- Repository: `/home/lorenzo/Documents/github-digitalygo/envai-pii`.
- Branch `dev`, esplicitamente approvato dall'utente; HEAD `89412bf750c2a6bf3e80fcfbb7bebd192597ef46`. Ultimo pull fast-forward sincronizzato.
- Il default remoto e' `main`. Applicare il controllo branch previsto dalla propria role skill, tenendo presente l'approvazione precedente.
- Worktree sporco, con molto lavoro precedente anche non relativo a questa ripresa. Non resettare, fare stash o ripristini globali e non attribuire tutti i file al prossimo task.
- Sono modificati documenti e test, anche upstream-auth; esistono strumenti Verda e trace non tracciati. Prima di intervenire verificare status/diff.
- `AGENTS.md` e `CONTRIBUTING.md` root presenti. `.github/CONTRIBUTING.md`, `substrate/directives/` e `substrate/expectations/` assenti all'ultimo controllo.

Pacchetto dei nove file verificati, ancora invariato all'ultimo controllo:

```text
0fcada80459283e62029f9cea50ab9cc5146539ae5fdf28eaa9cb3ef6aeeb971
```

Comprende:

- `src/app/app.py` e `src/app/model_batching.py`.
- `tests/test_guardrail_api.py`, `tests/test_guardrail_categories.py`, `tests/test_model_batching.py`.
- `tools/verda_model_experiment/batch_package.py` e `batch_runtime.py`.
- `tests/test_verda_batch_package.py` e `tests/test_verda_batch_runtime.py`.

Gli hash individuali e l'algoritmo sono nel [record locale di revisione](../status/2026-10-28-chunk-batching-review-package.md). La directory status e' gitignored: disponibile su questo checkout, non garantita in un clone nuovo.

### Comportamento gia' implementato

`src/app/model_batching.py` risolve `PII_MODEL_BATCH_SIZE` una volta all'avvio: 1/4/8/16 dopo trim, fallback 1. Il client non puo' sceglierlo.

`src/app/app.py:584`, `_guardrail_detect`, raggruppa i chunk di una sola invocazione del detector. Il confine e' un tratto non protetto dello stesso documento, non richieste o file diversi. Chunking da 120 parole e overlap 20 invariati. Ogni gruppo usa la corsia nativa e controlli cooperativi della deadline prima/dopo; un forward in corso non viene interrotto.

B1 conserva il comportamento precedente. Batch maggiori verificano cardinalita', righe vuote, coda incompleta, indici locali interi e score finiti, fallendo chiuso su risultati malformati. Offset, merge, categorie, seed, placeholder e ordine dei file rimangono invariati. Il legacy `detect_model` non cambia.

Advisory non bloccante: il helper di grouping chiamato direttamente con bool/float non applica sempre il fallback; il percorso server produce solo int supportati. Non e' il blocco del benchmark. Non cambiare ora il core senza motivo e senza rifare i gate.

### Immagine e overlay diagnostico

L'immagine pubblicata **non contiene il nuovo adapter**:

```text
ghcr.io/digitalygo/envai-pii@sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714
```

Il test usa l'overlay diagnostico gia' verificato, non una nuova release. Impostare una variabile nell'immagine vecchia, da sola, non basta. Non modificare i pin del file base per fingere che contenga il nuovo codice.

`batch_package.py:428`, `build_batch_gpu_profile(run_id, batch_size)`, costruisce il profilo. Identificativi gia' usati: `verda-20261028-batch1`, `verda-20261028-batch4`, `verda-20261028-batch8`, `verda-20261028-batch16`. La data vecchia non e' un errore; cambiarla modifica il comando atteso.

| Identita' | SHA256 |
| --- | --- |
| File app di base nell'immagine | `b0ec5163cd0d9eee05922d4b80718eb26abc762b0612935e1f1ad8275dc3848e` |
| Helper nuovo | `31a9d653891e401e86f2c110311bba2417dee5c2450c4081c55bee88e328424d` |
| Frammento detector | `1a0f57a3e4563e8f66b245d38db175f5c368238a53334176c4cd49045e16477e` |
| Bytecode detector | `0a16342e7c87a5053c5f2a74579ba3be9c7a3f5f3964f1afde059b13518d1953` |
| Manifest overlay | `a7e71ece5e05307ff9a40f74b1b7542616ad5c733d983628767933d5210d7684` |
| Archivio diagnostico | `c4eea72b82406fe5025bd4abf51bef958077f12108dd49c2bc20f6ae35a6d12a` |

Archivio di 17160 byte, 55 argomenti e 56 carrier env, ogni valore <=253 byte. Il builder operativo deve essere **Python 3.11 come l'immagine**: il hash del bytecode dipende dal minor Python. Tutti gli otto worker devono attestare separatamente base e overlay.

## Deployment e requisito di risparmio

- Unica risorsa autorizzata: Verda `envai-pii-test`, container `envai-pii-test-0`.
- Una sola L40S alla volta, otto modelli, float32, stesso modello e stessi pesi.
- Ultimo controllo nativo: **2026-10-29T13:23:09Z, paused, minimo 0/massimo 1/concorrenza 32, `replicas.list=[]`**.
- B4 resta configurato nell'entrypoint, ma e' inattivo. Pod e PID del vecchio warmup sono storici.
- Porta 5005, probe `/health`, devshm `size_in_mb=64` e 105 env note.
- L'utente vuole **minimo 0, pausa e zero repliche verificate alla fine**, anche se il tentativo si interrompe. Minimo 1 puo' essere temporaneo durante le prove.
- Preparare e verificare il collector offline prima di pagare una GPU calda. Non creare altri deployment o hardware e non lasciarla accesa in attesa del subagent.
- Non sono state controllate o modificate altre risorse dell'account: zero compute di questo deployment non significa fattura globale zero.

## Dati B1 da conservare

La matrice valida e' nei file privati `resume1818-b1-*`, finestra `2026-10-28T18:37:31.379614Z–18:42:29.808810Z`: 81 raffiche, 27 gruppi e 402 ID compositi unici, tutti 200 con oracolo esatto. **Non ripetere B1.**

A concorrenza 32: media 10,872 s, p95 14,008 s e 2,254 successi/s. La [tabella completa](../reports/2026-10-28-chunk-batching.md) resta il riferimento. Nodo, momento e distribuzione delle connessioni possono cambiare nei test successivi: dichiarare questi limiti.

Il parent ha auditato 302 record NVML, 279 attivi, 1192 samples base e otto PID stabili. Non esiste un JSONL locale completo di quei campioni GPU B1: l'audit e i digest sono documentati, ma la riproducibilita' futura dipende anche dalla retention provider di 7 giorni. Non inventare l'archivio mancante.

Oracolo canonicale invariabile:

```text
ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40
```

Corpo: `fixture.FIXTURE_BODY`, 45174 byte, SHA256 `d2a274f2ab87b0d3d71f2b9be595350e5a9ce0c919f11a7eea12a2d168d33b59`; testo da 63 chunk. Canonicalizzazione risposta: JSON con chiavi ordinate, separatori compatti, `ensure_ascii=False`, SHA256 UTF-8. Non cambiare il riferimento per fare passare una differenza.

## Lavoro residuo, in ordine

1. Verificare offline che l'esecutore funzioni. La disponibilita' dei subagent va ricontrollata nella nuova chat; gli errori precedenti non sono un'esclusione permanente dei modelli. Non accendere prima la GPU.
2. Preparare, se serve, un collector piccolo e riutilizzabile. **Non esiste** `tools/verda_model_experiment/batch_experiment.py`, ne' il relativo test. I client effimeri sono stati rimossi: non cercare di importarli o ricostruire un framework monolitico. Riutilizzare i moduli sotto.
3. Fare un preflight fresco: deployment, immagine, hardware, entrypoint, env, scaling e stato effettivo. Nessuna misura senza tutti gli otto worker pronti e batch effettivo attestato.
4. Completare B4. Derivare nuovi PID/owner dai nuovi ready, non fissare gli 82–89 storici. Riconfermare l'oracolo con warmup escluso, poi misurare.
5. Eseguire B8 e B16 solo se passano oracolo e margini. Per cambiare profilo: pausa, attendere zero repliche, un PATCH entrypoint-only, readback esatto, una ripresa, attestazione e warmup. Mai due GPU allocate insieme.
6. Confrontare correttezza, media/p95/RPS, GPU/memory controller, RAM/VRAM e stabilita'. Il warmup B4 da 1,36 s non va confrontato con la media B1 come se fosse una matrice.
7. Concludere o riportare il blocco esatto; sempre minimo 0/pausa/zero verificato. Aggiornare lo stesso piano e rapporto. Non dichiarare completate le matrici mancanti o scegliere un vincitore prima dei risultati.

### Matrice e helper esistenti

`gpu_profile.py:263`, `run_gpu_profile`, produce gia' il protocollo fisso; non riscriverlo.

| case_index | Concorrenza | Gruppi | Raffiche per gruppo | Richieste |
| --- | --- | --- | --- | --- |
| 1 | 1 | 10 | 3 | 30 |
| 2 | 2 | 6 | 3 | 36 |
| 3 | 4 | 4 | 3 | 48 |
| 4 | 8 | 4 | 3 | 96 |
| 5 | 16 | 2 | 3 | 96 |
| 6 | 32 | 1 | 3 | 96 |

Per batch: 402 richieste, 81 raffiche, 27 gruppi; warmup esclusi. Trasporto 90 s, budget applicativo 60 s invariato, deadline matrice 700 s e budget globale finito. Persistenza del record grezzo di ogni raffica prima di proseguire, senza corpo o delta. Stop al primo errore serio, mismatch, churn o margine insufficiente; niente replay di richieste gia' misurate.

Moduli da riutilizzare:

- `gpu_profile.py:263`: `run_gpu_profile`, sender/validator/persist/safety_check iniettati.
- `gpu_profile.py:555`: `correlate_gpu_profile`, finestre di trasporto effettive.
- `measure.py:208`: `summarize_rounds`, tre burst di un gruppo.
- `gpu_monitor.py`: parsing e validazione chiusa NVML.
- `resources.py:8`: `evaluate_resource_guard`.
- `batch_runtime.py:463`: hook di warmup/attestazione e barriera delle otto copie.

`case['latency']` non contiene gia' media/p95/RPS globali. Derivare i numeri dai record: per il confronto B1 il denominatore di processing e' la somma dei `group_elapsed_seconds` delle raffiche. Durate valide per media/p95, p95 nearest-rank.

Almeno 20% di RAM e VRAM libera, otto worker stabili. Il leaf pids.max osservato era unbounded (`None`, motivo `limit_unavailable`); budget sperimentale 512/guardia 409, non quota provider. Un valore assente con motivo ignoto non e' automaticamente unbounded.

Almeno 10 campioni attivi per cella per statistiche quantitative. Missing non e' zero; zero numerico puo' essere reale. Escludere warmup/idle e riportare copertura. Salvare questa volta i JSONL dei campioni validi e la correlazione, non soltanto il riepilogo.

## Accesso e trappole del client

- OAuth: `https://api.verda.com/v1/oauth2/token`, client credentials.
- Management: `https://api.verda.com/v1/container-deployments/envai-pii-test`.
- Inferenza: `https://containers.datacrunch.io/envai-pii-test/api/v1/analyses`.
- Credenziali locali: `/home/lorenzo/Documents/.secrets/verda.json`, valori solo in memoria. Management usa OAuth; inferenza usa la chiave separata `inference_api_key`, non il client secret.
- PATCH `/scaling` puo' cambiare il solo `min_replica_count`; confrontare poi gli altri campi. POST `/pause` e `/resume` sono controlli distinti.
- Contratto API selezionato disponibile anche in `/home/lorenzo/private/tmp/envai-pii-verda-replicas-20261027/600JSONprovider-contract.json`.

Errori gia' incontrati, da non ripetere:

- case_index non e' concorrenza: indici 1..6, non 1/2/4/8/16/32. Il primo riepilogo B1 era un falso FAIL del client.
- Usare un solo `/v1` nell'URL, evitando un SDK che aggiunga un secondo prefisso.
- `/status` restituisce un enum, per esempio `{"status":"paused"}`; niente booleano `paused=false`. `updating` puo' coesistere con una replica running e worker pronti.
- `/replicas` ha `list`; `/logs` e `/system-logs` sono liste al primo livello.
- Il GET dell'immagine restituisce un oggetto con campo `image`, non necessariamente una stringa.
- Un readback puo' essere stale: bounded polling dopo un PATCH riuscito, senza reinviarlo a ogni lettura vecchia.
- Le env sono 105, non 56: unione di 49 voci del vecchio profilo GPU e 56 carrier nuovi. Verificare nomi, tipi e valori dell'intera unione e rifiutare extra ignoti. I carrier sono identici fra batch; cambiare solo l'entrypoint quando basta. Non inventare DELETE o reset env.
- Servono 8 ready base e 8 ready batch, stesso nuovo insieme PID, hash esatti, batch effettivo e owner NVML minimo PID vivo. Non basta `/health` o un solo POST riuscito.
- Per i log usare pod esatto, start/end UTC <=55 s, limit 1000, order asc; suddividere se il limite viene raggiunto. Rileggere per ritardi d'ingestione e deduplicare. Evitare il solo `search_text`/`since` e cursori forward-only.
- Lo schema NVML e' chiuso: `_timestamp`/`_replica` vanno tenuti separati dal record passato al validator.
- Niente retry di resume rifiutati o errori finanziari: non autorizzano pagamenti o altro hardware. Stock L40S non garantito dopo la pausa.

Non disabilitare TLS, seguire redirect con bearer o salvare header, payload, dictionary_delta, carrier o UUID GPU grezzi. Artifact privati 600 in directory 700, dati solo sintetici. Nessuna nuova chiave persistente, release o pagamento automatico.

## Evidenze locali e verifiche

Directory privata: `/home/lorenzo/private/tmp/envai-pii-batching-20261028/`.

- `resume1818-b1-bursts.jsonl`: 81 raffiche originali, da preservare.
- `resume1818-b1-result.json`: risultato; per correlare ricostruire `bursts` dal JSONL.
- `resume1818-b1-summary.json`: contiene anche il falso FAIL del verificatore, non un fallimento dei 402 record validi.
- `c0950-b4-readiness.json`, `c0950-b4-warmup.json`, `c0950-b4-final.json`: avvio e warmup, non matrice.
- `stop1130-final.json`: pausa 201/minimo 0 PATCH 200 e zero repliche alle 11:46:04Z.
- `final1313-tests.log`: ultimo run locale, 1119 PASS senza skip.
- `leader-final-coverage.json`: copertura del sorgente.

Non esistono risultati `complete1017-*`, `batch_experiment.py` o il suo test. I tentativi non li hanno prodotti.

Interprete gia' usato, da verificare ancora presente:

```bash
/tmp/envai-pii-gpu-replicas-20261026/.venv/bin/python -m unittest discover -v tests
```

Anche il precedente run Python 3.14 e' passato, ma il venv temporaneo e' stato rimosso. Non scaricare Torch, modelli o dataset per i test CPU. Se viene aggiunto il collector, mapparne il delta ai test, coprirlo almeno all'80% e rifare i gate applicabili: il vecchio PASS non copre nuovo codice. Non indebolire test/oracoli e non aggiungere commenti nel nuovo Python.

## Documenti da leggere

1. [Piano vivente e ledger](../plans/2026-10-28-chunk-batching.md): riprendere questo, senza piano parallelo o riscrittura del baseline.
2. [Report completo](../reports/2026-10-28-chunk-batching.md): dati B1, timeline e limiti.
3. [Guida del parametro](../../../docs/chunk-batching.md).
4. [Guida Verda](../../../docs/verda-service.md).
5. [Ricerca iniziale](2026-10-28-chunk-batching-inspection.md).
6. [Operazione servizio](../operations/2026-10-21-runpod-service.md): storia ampia, distinguere sezioni storiche da stato finale.

Guasti osservati in questa sessione: A risposta vuota/provider error; B alcuni client difettosi e rifiuto del ruolo operativo; C `UpstreamIdleTimeout` sui task lunghi, mentre avvio e cleanup brevi riuscivano. Non sono una prova di indisponibilita' permanente nella nuova chat. Non cambiare manualmente agenti o usare ruoli non ammessi per aggirare le regole.

## Prompt per la nuova chat

```text
Leggi substrate/traces/research/2026-10-29-chunk-batching-handoff.md e riprendi lo stesso piano. Il batching nel sorgente e' gia' implementato: completa solo le matrici B4/B8/B16 e il confronto con il B1 conservato, senza ripetere B1. Prima verifica offline che esecutore e collector funzionino. Non lasciare la GPU accesa durante i blocchi. Alla fine, anche su errore, minimo 0, pausa e zero repliche verificate sul solo deployment di test. Non fare commit, push o pubblicazioni senza richiesta.
```

## Verifica di questo handoff

Sintesi di piano, report, sorgenti localizzati e verifiche native/codice gia' effettuate dal parent. Revisioni quality/security precedenti e quality del solo cleanup restano limitate ai rispettivi perimetri. Per questo handoff sono stati riletti report, regole e manifest, controllati status/diff, percorsi e sincronizzazione dev. Nessuna nuova mutation o prova GPU. Test e copertura del solo nuovo Markdown: N/A.
