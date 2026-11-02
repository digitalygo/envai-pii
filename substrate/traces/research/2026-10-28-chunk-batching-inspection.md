---
status: completed
created_at: 2026-10-28
---

# Ispezione del batching dei chunk

## Ambito

Analisi statica del percorso di inferenza, della gestione del dizionario e dei test esistenti, dopo il confronto GPU con otto modelli sulla L40S. Nessuna modifica al servizio, chiamata cloud, inferenza, esecuzione di test o nuovo benchmark. L'unico file creato e' questa ricerca.

Il checkout `dev` rimane sul commit `89412bf750c2a6bf3e80fcfbb7bebd192597ef46`, uguale al riferimento remoto verificato con `git ls-remote`. Le modifiche preesistenti sono preservate. Contributor, direttive e aspettative non sono presenti nei rispettivi percorsi.

## Sintesi

L'API v1 divide il testo in chunk, ma li presenta al modello **uno per chiamata**. Impostare soltanto un valore `batch_size` non unirebbe chiamate separate. Il primo intervento da valutare e' raggruppare i chunk dello stesso tratto non protetto, mantenendo indipendenti richieste, seed e categorie.

Il documento sintetico del benchmark contiene 6252 parole e produce esattamente 63 chunk: 62 da 120 parole e uno finale da 52. Un raggruppamento in batch da 4, 8 o 16 porterebbe rispettivamente a 16, 8 o 4 chiamate esterne alla pipeline per quel documento. Sono conteggi statici, non speedup misurati o conteggi strumentati dei kernel CUDA.

## Percorso attuale

### Chunking e chiamate al modello

- `src/app/app.py:229-230` fissa finestre di 120 parole e sovrapposizione di 20.
- `src/app/app.py:391-405` produce coppie testo/offset originale, con passo di 100 parole. Non cambia il testo all'interno della finestra.
- `src/app/app.py:237-243` costruisce la pipeline token-classification senza un parametro di batch.
- `src/app/app.py:597-600` itera i chunk e passa una lista con un solo elemento alla pipeline, tramite la corsia nativa.
- `src/app/runtime_execution.py:7-60` permette una chiamata nativa alla volta per processo. La corsia comprende l'intera invocazione della pipeline, non soltanto il forward GPU.

Otto processi offrono otto corsie indipendenti, ma non creano un batch unico fra processi o richieste. La GPU resta condivisa. Nel [test misurato B1](../reports/2026-10-28-verda-eight-model-gpu-profile.md) l'attivita' media va dal 17,65 al 77,83 percento al crescere della concorrenza; questi valori non ripartiscono il tempo fra tokenizzazione, code, forward e aggregazione.

### Dove il rilevatore puo' vedere il testo

`src/app/pii_dictionary.py:426-453` chiama il rilevatore solo sui tratti non protetti. Placeholder e valori gia' noti del seed sono esclusi. Il rilevatore suddivide ogni tratto in propri chunk e restituisce offset locali; il motore li riporta al documento originale.

Il confine iniziale piu' semplice per un batch e' quindi **un tratto della stessa analisi**, non una raccolta indiscriminata di tutti i testi arrivati al server. Nel fixture senza seed e senza placeholder iniziali il tratto e' l'intero documento; con seed o placeholder il numero di chiamate dipende anche dalla frammentazione in tratti.

## Quanti passaggi cambierebbero

Conteggi ricavati ricostruendo staticamente il fixture e verificandone lo SHA256 `97adc9b463df5728344baa30b734db39a09d24986a1c3d01ffccde3ade3e6fca`. Nessun import dell'applicazione o caricamento del modello. Il calcolatore conferma il numero di chunk e gli arrotondamenti per eccesso dei gruppi.

| Chunk per gruppo | Chiamate alla pipeline per il fixture | Stato |
| --- | --- | --- |
| 1 | 63 | Percorso attuale |
| 4 | 16 | Ipotesi da provare |
| 8 | 8 | Ipotesi da provare |
| 16 | 4 | Ipotesi da provare |

Il lavoro sui token non scompare. Un batch raggruppa input, riduce passaggi e puo' cambiare l'efficienza della GPU, ma non promette un guadagno proporzionale al numero di chiamate eliminato. Le finestre in parole non equivalgono a lunghezze uniformi in token; padding, troncamento e memoria vanno verificati.

## Tre significati diversi di batch

### Chunk della stessa analisi

E' il candidato iniziale: piu' chunk dello stesso tratto nella stessa chiamata, mantenendo la coppia chunk/offset e il controllo della deadline attorno a ciascun gruppo. Il numero di chunk forniti deve corrispondere al numero di risultati restituiti, anche quando ogni chunk ha zero entita'. Non basta usare `zip` e ignorare una cardinalita' errata, altrimenti parti del documento potrebbero restare non analizzate.

### Piu' file nella stessa richiesta

`anonymize_batch`, in `src/app/pii_dictionary.py:665-705`, non e' batching GPU. Prepara gli input e riserva gli ID, poi li processa in ordine con una sola mappa request-local. Le allocazioni del primo input diventano valori noti nei successivi. Parallelizzare tutti i file prima di questa sequenza puo' cambiare protezione del testo, etichette e ID.

`src/app/guardrail_api.py:413-452` usa questa funzione per i multipart. Il nome non dimostra che il modello riceva piu' chunk nello stesso forward.

### Richieste indipendenti

Non esiste un aggregatore fra richieste. Aggiungerlo richiederebbe uno scheduler con identita' della richiesta, scadenza, selezione delle categorie, gestione del seed e associazione dei risultati. Sarebbe un cambiamento separato, con conseguenze su latenza e isolamento. Non e' necessario per il primo confronto sui chunk.

## Perche' non basta cambiare un parametro

Il percorso v1 costruisce una lista singleton dentro il ciclo e aspetta il risultato prima di passare al chunk successivo. Il parametro della pipeline opera soltanto sugli input della singola invocazione: non puo' recuperare quelli della chiamata successiva.

Il percorso legacy `detect_model`, `src/app/app.py:408-428`, invia invece la lista completa dei chunk in una chiamata. E' un riferimento per l'associazione degli offset, ma non controlla la deadline fra i chunk e non seleziona un batch esplicito. Copiarlo senza adattamenti nel percorso v1 perderebbe controlli esistenti.

Il riferimento esplicito al batching esiste in `src/training/evaluate_targa_stress.py:108,122`: l'evaluatore passa una lista di documenti e il relativo parametro di batch. Bypassa pero' chunking, corsia e contratto HTTP. E' un esempio di API della libreria, non un'implementazione riutilizzabile tale e quale nel servizio.

## Vincoli da non perdere

- Preservare ordine, cardinalita' e offset originali, compresi Unicode, sovrapposizioni e ultimo gruppo incompleto. La fusione e' in `src/app/app.py:439-497`; non si devono cambiare chunking e batch insieme nel primo confronto.
- Mantenere il filtro delle categorie prima della fusione (`src/app/app.py:615-624`), il binder request-local (`:627-637`) e la protezione dei tratti nel motore del dizionario.
- Oggi ci sono controlli della deadline fra chunk e prima/dopo la chiamata nativa. Un gruppo piu' grande rende piu' grossolano il lavoro non interrompibile e trattiene piu' a lungo la corsia. E' una scelta di comportamento da definire esplicitamente, non un motivo per rimuovere test o aumentare il timeout.
- La VRAM libera osservata a B1 non dimostra il picco di otto copie che lavorano con B16. Bisogna mantenere margini globali e distinguere memoria per processo da totale del dispositivo.
- Un batch diverso puo' cambiare calcoli numerici e confini rilevati. L'oracolo B1, le maschere e i casi di regressione devono restare confrontabili; una differenza non va nascosta cambiando il riferimento.

## Un dettaglio del warmup

Il warmup diagnostico attuale chiama `module.detect_model(FIXTURE_TEXT)` in ogni worker (`tools/verda_model_experiment/runtime.py:604-605`). Non chiama il rilevatore v1 con una futura variante B4/B8/B16.

Una comparazione dovrebbe dimostrare che **tutti gli otto worker usano e hanno riscaldato il batch effettivo**, non soltanto che esiste un valore configurato. Un singolo POST al bilanciatore non prova il warmup di tutte le copie. Se si cambiasse solo il batch del costruttore, si potrebbe modificare il legacy/warmup lasciando ancora singleton la richiesta v1.

L'attuale pacchetto diagnostico verifica hash dei sorgenti e immagine. Una variante deve essere realmente presente nell'artefatto eseguito, con identita' e batch effettivo registrati: non basta aggiungere una variabile ignorata o disabilitare un controllo di integrita'.

## Evidenze storiche e copertura esistente

Il [vecchio sweep sulla A40](../../../docs/runpod-single-gpu-capacity.md), sezione sul batch, ha misurato B16 circa 1,88 volte B1 su una copia e un corpus sintetico diverso, chiamando direttamente il core senza HTTP. I risultati giustificano un nuovo confronto, ma non stimano il risultato della L40S con otto copie. La stima storica di circa 64 chunk riguarda quel corpus, non contraddice i 63 esatti del fixture corrente.

I test `tests/test_guardrail_api.py:152-172` verificano esplicitamente due chiamate singleton e gli offset. `:174-192` controlla l'uscita subito dopo una chiamata nativa scaduta; `:194-213` copre le forme flat/dict per un singolo chunk. Sono comportamenti da preservare o ridefinire consapevolmente, non asserzioni da indebolire per ottenere un batch.

`tests/test_pii_dictionary.py:374-440,500-542` copre ordine e riuso fra input, assenza di risultati parziali, statelessness e deadline. I test degli adapter sostituiscono `chunk_text` con esempi controllati. Una futura copertura del batching deve aggiungere casi con chunking reale, Unicode, coda incompleta, risultati vuoti/mancanti e richieste concorrenti con categorie o seed diversi.

## Valutazione

Il primo confronto sensato resta B1/B4/B8/B16 **entro la stessa analisi**, con gli stessi otto modelli, L40S, pesi, precisione e finestra del testo. Il batching fra richieste va tenuto fuori da quella prima prova.

Serve misurare separatamente attesa della corsia, preprocessing effettivo, forward e postprocessing, insieme a latenze HTTP, throughput, VRAM e contatori GPU. Il vecchio report A40 avverte che cronometrare soltanto la creazione di un generatore `preprocess` non misura la tokenizzazione completa: il dato va raccolto durante l'iterazione reale.

Questa e' un'ispezione, non un piano esecutivo o una modifica gia' applicata. Nessun nuovo test GPU e nessun batch maggiore di1 sono stati attivati. Test e copertura del nuovo delta: N/A, analisi e Markdown soltanto.

## Verifica della ricerca

Risultati incrociati con due locator, un analyzer e un pattern-finder, poi verificati direttamente sui sorgenti e sulle asserzioni citate. Alcuni riferimenti di riga e affermazioni troppo generali dei delegati sono stati corretti sulla lettura diretta: la fusione comincia alla riga439, il servizio di test ha otto copie native e le misure L40S esistono per B1, non per batch maggiori.
