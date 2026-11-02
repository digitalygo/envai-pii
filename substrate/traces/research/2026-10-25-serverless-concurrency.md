---
status: completed
created_at: 2026-10-25
---

# Repliche del modello e concorrenza Serverless

## Ambito

Risposta alla domanda se più copie del modello sulla stessa GPU permettano più di quattro richieste senza aumentare la latenza. L'utente indica Serverless con scale-to-zero come direzione futura, non autorizza una distribuzione o una modifica del Pod in questa richiesta. Sono state consultate le fonti ufficiali il 2026-10-25. Nessun codice, configurazione, credenziale o risorsa cloud modificati; nessun nuovo test di carico eseguito.

## Sintesi

Repliche sulla stessa GPU possono aumentare il throughput se permettono di utilizzare meglio risorse oggi non sfruttate, ma non moltiplicano potenza di calcolo o banda. Non dimostrano latenza invariata e non rimuovono da sole i limiti del servizio. Per superare la concorrenza complessiva di un singolo worker, Serverless offre anche lo scale-out su ulteriori allocazioni GPU, con costi e tempi di avvio distinti. Il punto iniziale raccomandato è una copia per worker e un budget prudente per worker, da verificare sull'ambiente Serverless, non molte copie ipotizzate sulla sola base della VRAM nominale.

## Stato verificato del servizio

- `src/app/gunicorn_config.py:11-18`: un processo Gunicorn, thread gthread e nessun preload.
- `src/app/runtime_execution.py:7-14,78-79`: una corsia nativa con un solo proprietario per il modello e una separata per i PDF, per processo.
- `src/app/app.py:582-600`: il rilevamento v1 invia un chunk per chiamata alla corsia del modello; chunking a 120 parole con sovrapposizione di 20 (`app.py:228-230`).
- `src/app/request_admission.py`: quattro analisi attive e quattro in coda sono limiti di ammissione HTTP, non quattro forward GPU simultanei né un limite hardware intrinseco.
- Il [benchmark a caldo](../../../docs/runpod-load-pricing.md) non ha confrontato più copie del modello. Non misura VRAM allocata in byte né cold start Serverless. I campioni di utilizzo GPU non dimostrano capacità inutilizzata disponibile senza contesa.
- La v1 è stateless; cache documenti e preferenze legacy sono locali al processo. Repliche o worker effimeri non rendono tali stati automaticamente condivisi.

Questi punti sono stati incrociati con locator e analyzer read-only. I provider primari già indisponibili sono stati esclusi secondo il protocollo di sessione.

## Tre topologie diverse

| Topologia | Cosa cambia | Limite principale |
| --- | --- | --- |
| Più pesi caricati, stessa corsia attuale | Aumenta la memoria occupata | Nessun nuovo instradamento o parallelismo effettivo |
| Più processi/repliche sulla stessa GPU | Corsie e contesti separati, possibile sovrapposizione del lavoro CPU/GPU | Calcolo e banda GPU condivisi; pesi, contesti e memoria di lavoro aggiuntivi; benefici da misurare |
| Più worker Serverless con GPU assegnate | Capacità distribuita su allocazioni GPU distinte | Più secondi GPU fatturati, disponibilità e avvio dei worker |

PyTorch documenta che le operazioni nello stesso stream sono ordinate; stream differenti possono sovrapporre operazioni, ma richiedono sincronizzazione e gestione della vita dei tensori. Ciò non rende automaticamente sicura l'esecuzione concorrente dell'attuale pipeline in thread diversi. Le proprietà della libreria, dei kernel e dei risultati per richiesta vanno conservate.

Un'alternativa da confrontare è il microbatching di chunk sulla stessa copia, con attribuzione dei risultati e deadline per richiesta. Può sfruttare meglio la GPU senza duplicare tutti i pesi, ma introduce memoria di attivazione e possibili attese di raccolta del batch. Non è implementato né misurato in questo servizio.

## Conseguenze della scelta Serverless

Le impostazioni ufficiali prevedono worker attivi minimi pari a zero e un limite massimo di worker. Lo scale-out aumenta le allocazioni di calcolo; non significa caricare repliche gratuite sulla GPU esistente. Un worker GPU usa normalmente una GPU assegnata, con numero configurabile.

Con zero worker pronti non si può garantire risposta immediata: può essere necessario avviare o ripristinare un worker e preparare il modello. FlashBoot riduce questi tempi, ma non garantisce la stessa latenza di un worker già caldo. Mantenere un worker attivo riduce il problema per quella capacità, ma comporta fatturazione continua.

Serverless fattura avvio del worker e caricamento del modello, esecuzione e attesa prima dello spegnimento. Il download dell'immagine o di modelli in cache normalmente avviene a worker spento e non è fatturato come compute, pur potendo aumentare l'attesa utente. Quando i worker sono effettivamente spenti non si paga il loro compute; storage e altri costi non sono necessariamente nulli. La tariffa Serverless non è quella del Pod del benchmark: i costi unitari precedenti non vanno trasferiti automaticamente.

### Tipo di endpoint

Il load balancing è il candidato iniziale più vicino all'API attuale: supporta Flask, percorsi personalizzati, multipart e risposte binarie. Supporta worker che possono non essere pronti, ma non offre la coda persistente dei job: cold start e sovraccarico richiedono backpressure e retry limitati o una coda nel backend chiamante. Vanno adattati e verificati avvio, porte, health check, autenticazione e limiti; non basta riutilizzare l'immagine senza integrazione.

I job queue-based sono un'alternativa se si accetta un contratto asincrono: buffering e retry del provider, richiesta con involucro JSON e recupero del risultato. Non sono la stessa API multipart attuale. Sono soggetti a timeout, TTL, errori e retention; non costituiscono una promessa di esecuzione sempre riuscita. Per dati personali, coda e conservazione dei risultati richiedono una valutazione dedicata. L'autenticazione del provider e la chiave applicativa restano confini distinti; non copiare una chiave di gestione nell'applicazione o nel client pubblico per aggirarli.

## Raccomandazione e verifiche mancanti

1. Progettare prima lo scale-out Serverless: modello caricato una volta per worker, minimo zero, massimo e timeout inattivo coerenti con budget e frequenza delle richieste. Il budget prudente ricavato dal Pod non è una certificazione della capacità del futuro worker.
2. Confrontare una copia attuale, una copia con microbatch e repliche in processi indipendenti prima di scegliere l'ottimizzazione sulla singola GPU. Misurare throughput, p95, VRAM allocata e costo per lavoro riuscito, non solo occupazione nominale della scheda.
3. Separare prove a caldo, scale-out e ripartenza da zero. Un requisito di latenza immediata per ogni richiesta non può essere garantito contemporaneamente allo spegnimento di tutti i worker quando il servizio è inattivo.

Nessuna configurazione proposta è stata applicata. Test e copertura N/A: sola analisi e documentazione.

## Fonti

- [Impostazioni degli endpoint Runpod](https://docs.runpod.io/serverless/endpoints/endpoint-configurations), documento aggiornato il 2026-10-15 e letto direttamente: worker minimi/massimi, GPU per worker, idle timeout e FlashBoot.
- [Load balancing Serverless](https://docs.runpod.io/serverless/load-balancing/overview), aggiornato il 2026-09-10 e letto direttamente: Flask, multipart, health check, limiti, assenza di coda e gestione dei cold start.
- [Fatturazione Serverless](https://docs.runpod.io/serverless/pricing), letta direttamente: avvio, esecuzione, attesa e storage.
- [Semantica CUDA di PyTorch](https://pytorch.org/docs/2.14/notes/cuda.html), letta direttamente: stream, ordinamento e sincronizzazione. È una fonte concettuale; non autorizza né richiede un aggiornamento del pin PyTorch del repository.
- [Handler concorrenti Runpod](https://docs.runpod.io/serverless/workers/concurrent-handler), consultato dal ricercatore: concorrenza per worker da abilitare esplicitamente, distinta dal numero di worker.
