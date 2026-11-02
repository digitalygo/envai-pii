---
status: completed
created_at: 2026-10-30
---

# Riepilogo consolidato dei benchmark GPU su Verda

Questo documento trascrive in un unico punto le tabelle dei tre report di origine, senza nuove misure e senza nuove decisioni di processo. I valori e le note dettagliate restano nei report originali:

- [Confronto delle copie del modello su Verda](2026-10-27-verda-model-copies.md), serie storica N1, N2, N4 e N8 con batch B1.
- [Report sul chunk batching](2026-10-28-chunk-batching.md), serie B1, B4, B8 e B16 con 8 copie.
- [Confronto di 8, 12 e 16 copie e tempi di avvio](2026-10-30-copy-count-startup.md), serie più recente con B8.

## Condizioni comuni e definizioni

Tutte le serie usano lo stesso documento sintetico da 45000 caratteri, diviso in 63 chunk, su una singola GPU L40S con modello in `float32`. Le serie usano allocazioni di pod distinte. Host fisico e stato della cache non sono stati controllati e potrebbero differire: il confronto è sulla stessa fixture e sulla stessa classe di GPU, non sullo stesso chip.

Tre leve diverse vengono confrontate e non vanno confuse:

- Le copie del modello sono processi Gunicorn indipendenti, ognuno con la propria copia del modello (N).
- Il batching dei chunk indica quanti dei 63 chunk di una richiesta entrano in una singola chiamata del modello (B).
- Le richieste contemporanee sono la concorrenza dei client HTTP (CC), cioè richieste in volo verso il servizio. Le richieste in volo possono mettersi in coda e non equivalgono a forward GPU paralleli.

Come sono calcolate le metriche:

- Le richieste al secondo sono i successi divisi per la somma dei tempi trascorsi delle raffiche. Non sono un obiettivo fisso di 4 richieste al secondo.
- La media è la media aritmetica delle durate delle singole richieste valide con successo. Solo il P95 usa il metodo nearest-rank sulle stesse richieste.
- Warmup, avvio e setup sono esclusi dalle statistiche HTTP di prestazione. Le misure di avvio, invece, includono il warmup.

## Serie più recente: 8, 12 e 16 copie con B8

Le 18 righe hanno N pari a 8, 12 e 16, batch B8 e concorrenza 1, 2, 4, 8, 16 e 32. Ogni matrice conta 30, 36, 48, 96, 96 e 96 richieste per concorrenza crescente, cioè 402 per configurazione del numero di copie, e tutte sono valide. I valori hanno la precisione a sei decimali delle sorgenti e la GPU media ha due decimali.

| Copie | Richieste contemporanee | Valide/totali | Richieste/s | Media (s) | P95 (s) | GPU media (%) |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | 1 | 30/30 | 1,048514 | 0,953667 | 1,011292 | 14,11 |
| 8 | 2 | 36/36 | 1,607647 | 1,199689 | 1,699316 | 24,36 |
| 8 | 4 | 48/48 | 2,446722 | 1,388004 | 2,321551 | 50,50 |
| 8 | 8 | 96/96 | 3,191351 | 1,942580 | 2,611637 | 64,33 |
| 8 | 16 | 96/96 | 3,675123 | 3,301515 | 4,466162 | 77,67 |
| 8 | 32 | 96/96 | 3,861909 | 5,971478 | 8,015375 | 80,33 |
| 12 | 1 | 30/30 | 1,042989 | 0,958725 | 1,023696 | 17,45 |
| 12 | 2 | 36/36 | 1,825990 | 1,069414 | 1,672388 | 22,76 |
| 12 | 4 | 48/48 | 2,690256 | 1,266211 | 1,809993 | 63,00 |
| 12 | 8 | 96/96 | 3,203094 | 1,907168 | 2,641978 | 54,60 |
| 12 | 16 | 96/96 | 3,602240 | 3,193339 | 4,570446 | 69,15 |
| 12 | 32 | 96/96 | 4,001195 | 5,793653 | 7,899093 | 78,87 |
| 16 | 1 | 30/30 | 1,039364 | 0,962062 | 1,042491 | 14,55 |
| 16 | 2 | 36/36 | 1,787479 | 1,087959 | 1,613176 | 34,71 |
| 16 | 4 | 48/48 | 2,630602 | 1,296024 | 1,778420 | 47,35 |
| 16 | 8 | 96/96 | 3,146939 | 1,899778 | 2,814650 | 54,38 |
| 16 | 16 | 96/96 | 3,726926 | 3,151280 | 4,402871 | 64,30 |
| 16 | 32 | 96/96 | 3,818058 | 5,637245 | 8,197978 | 71,54 |

## Serie precedente: batch B1, B4, B8 e B16 con 8 copie

Le 24 righe usano 8 copie e concorrenza 1, 2, 4, 8, 16 e 32. Ogni matrice conta 402 richieste valide su 402. Il batch sostituisce la colonna delle copie. I valori hanno la precisione a sei decimali delle sorgenti.

La riga B1 è la misura originale del 28 ottobre, conservata così com'è: non è stata rieseguita una nuova prova. Per B8 con 8 copie e concorrenza 32 esistono due valori separati e non vanno uniti né mediati: 4,026919 richieste/s nella serie precedente a B8 e 3,861909 richieste/s nel nuovo controllo fresco N8 della serie più recente.

| Batch | Richieste contemporanee | Valide/totali | Richieste/s | Media (s) | P95 (s) | GPU media (%) |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | 1 | 30/30 | 0,548491 | 1,823119 | 1,852424 | 16,11 |
| B1 | 2 | 36/36 | 1,015401 | 1,938944 | 2,028758 | 45,83 |
| B1 | 4 | 48/48 | 1,281759 | 2,574119 | 3,612551 | 64,06 |
| B1 | 8 | 96/96 | 1,662793 | 3,560389 | 5,472892 | 71,65 |
| B1 | 16 | 96/96 | 1,768621 | 6,288389 | 9,395524 | 71,59 |
| B1 | 32 | 96/96 | 2,253740 | 10,872464 | 14,007766 | 87,14 |
| B4 | 1 | 30/30 | 0,866661 | 1,153778 | 1,249313 | 11,94 |
| B4 | 2 | 36/36 | 1,640053 | 1,198030 | 1,309262 | 29,00 |
| B4 | 4 | 48/48 | 2,274139 | 1,509908 | 2,564284 | 45,05 |
| B4 | 8 | 96/96 | 2,641691 | 2,201538 | 3,488409 | 53,05 |
| B4 | 16 | 96/96 | 3,033092 | 3,735209 | 5,626851 | 63,61 |
| B4 | 32 | 96/96 | 3,392860 | 6,630575 | 9,369125 | 69,62 |
| B8 | 1 | 30/30 | 0,972887 | 1,027804 | 1,094380 | 15,03 |
| B8 | 2 | 36/36 | 1,766362 | 1,102440 | 1,622194 | 28,70 |
| B8 | 4 | 48/48 | 2,520777 | 1,341716 | 1,923248 | 43,67 |
| B8 | 8 | 96/96 | 3,124087 | 1,981459 | 2,677468 | 69,25 |
| B8 | 16 | 96/96 | 3,452352 | 3,223674 | 4,614377 | 71,00 |
| B8 | 32 | 96/96 | 4,026919 | 5,974584 | 8,247637 | 81,17 |
| B16 | 1 | 30/30 | 0,985266 | 1,014894 | 1,072646 | 12,94 |
| B16 | 2 | 36/36 | 1,609574 | 1,165427 | 1,760677 | 25,30 |
| B16 | 4 | 48/48 | 2,545938 | 1,364104 | 2,016599 | 37,39 |
| B16 | 8 | 96/96 | 3,027711 | 1,988593 | 2,751272 | 63,93 |
| B16 | 16 | 96/96 | 3,213059 | 3,550220 | 5,548307 | 60,10 |
| B16 | 32 | 96/96 | 3,919794 | 5,597851 | 8,063148 | 75,96 |

## Serie storica: 1, 2, 4 e 8 copie con B1

Le 24 righe usano N pari a 1, 2, 4 e 8, batch B1 e concorrenza 1, 2, 4, 8, 16 e 32. I tentativi per cella sono 3, 6, 12, 24, 48 e 96 per concorrenza crescente, con due eccezioni:

- N8 con concorrenza 1 conta 6/6 successi su due attivazioni distinte, e la riga è un aggregato descrittivo.
- N1 con concorrenza 32 conta 76/96 successi: 20 risposte HTTP 429. Media e P95 riguardano solo i 76 successi.

Tutte le altre celle sono valide al 100 per cento. Questa è una serie con protocollo breve e separato: 759 tentativi, 739 validi. Le richieste al secondo hanno 3 decimali, media e P95 hanno 2 decimali, come nel report di origine.

| Copie | Richieste contemporanee | Valide/totali | Richieste/s | Media (s) | P95 (s) |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | 3/3 | 0,543 | 1,84 | 1,86 |
| 1 | 2 | 6/6 | 0,578 | 3,15 | 3,51 |
| 1 | 4 | 12/12 | 0,595 | 5,26 | 6,74 |
| 1 | 8 | 24/24 | 0,590 | 11,13 | 13,53 |
| 1 | 16 | 48/48 | 0,588 | 23,86 | 27,19 |
| 1 | 32 | 76/96 | 0,544 | 31,88 | 45,03 |
| 2 | 1 | 3/3 | 0,512 | 1,95 | 2,00 |
| 2 | 2 | 6/6 | 0,776 | 2,43 | 3,57 |
| 2 | 4 | 12/12 | 0,924 | 3,27 | 5,58 |
| 2 | 8 | 24/24 | 1,112 | 5,86 | 7,26 |
| 2 | 16 | 48/48 | 1,065 | 12,24 | 15,89 |
| 2 | 32 | 96/96 | 1,011 | 25,48 | 31,04 |
| 4 | 1 | 3/3 | 0,507 | 1,97 | 2,06 |
| 4 | 2 | 6/6 | 0,756 | 2,38 | 3,70 |
| 4 | 4 | 12/12 | 1,260 | 2,54 | 3,76 |
| 4 | 8 | 24/24 | 1,437 | 3,97 | 5,61 |
| 4 | 16 | 48/48 | 1,550 | 7,13 | 11,73 |
| 4 | 32 | 96/96 | 1,577 | 14,75 | 22,34 |
| 8 | 1 | 6/6 | 0,536 | 1,87 | 1,94 |
| 8 | 2 | 6/6 | 1,017 | 1,93 | 2,04 |
| 8 | 4 | 12/12 | 1,087 | 2,72 | 5,26 |
| 8 | 8 | 24/24 | 1,576 | 3,29 | 5,49 |
| 8 | 16 | 48/48 | 1,513 | 6,06 | 10,96 |
| 8 | 32 | 96/96 | 1,720 | 11,84 | 18,90 |

## Risorse campionate

Una riga per serie e configurazione, arrotondata a 3 decimali. La RAM è il picco del kernel su un limite di 58 GiB, la VRAM visibile sulla GPU è circa 47,38 GiB. I task sono thread e processi, non richieste. I valori della serie storica N8 e della serie con B1 differiscono: 8,787 GiB di RAM nella serie storica e 8,806 GiB nella serie successiva.

| Serie | Copie | Batch | VRAM max (GiB) | RAM picco kernel (GiB) | Task max |
| --- | --- | --- | --- | --- | --- |
| Più recente | 8 | B8 | 14,107 | 9,027 | 108 |
| Più recente | 12 | B8 | 21,161 | 13,468 | 149 |
| Più recente | 16 | B8 | 28,213 | 17,921 | 191 |
| Batch precedente | 8 | B1 | 13,482 | 8,806 | 102 |
| Batch precedente | 8 | B4 | 13,794 | 8,802 | 106 |
| Batch precedente | 8 | B8 | 14,091 | 8,801 | 103 |
| Batch precedente | 8 | B16 | 15,263 | 8,809 | 105 |
| Storica | 1 | B1 | 1,688 | 1,150 | 42 |
| Storica | 2 | B1 | 3,373 | 2,243 | 49 |
| Storica | 4 | B1 | 6,742 | 4,429 | 73 |
| Storica | 8 | B1 | 13,482 | 8,787 | 109 |

## Tempi di avvio

Solo la serie più recente ha misure di avvio, con una sola osservazione per numero di copie. Tutti i valori sono in secondi.

| Copie | Interno da Listening a tutte pronte | Resume accettato a ultimo log pronto | Resume accettato a pronto osservato dal client | Resume accettato a prima risposta valida HTTP | Fase di pull del provider |
| --- | --- | --- | --- | --- | --- |
| 8 | 15,450720 | 220,147965 | 232,382 | 233,481720 | 197 |
| 12 | 17,542707 | 26,108766 | 32,050 | 33,188905 | n.d. |
| 16 | 19,874904 | 26,620396 | 38,955 | 40,365413 | n.d. |

Come leggere le colonne:

- Il tempo interno da Listening a tutte pronte comprende l'inizializzazione di applicazione, modello e CUDA, il warmup e la barriera di prontezza di tutte le copie. Usa un solo orologio del pod.
- Solo la colonna da resume accettato a ultimo log pronto mescola due orologi, client e provider, e l'offset tra i due non è noto.
- Il pronto osservato dal client e la prima risposta valida HTTP usano l'orologio del client e includono il polling dei log e il warmup del gate.
- La prima risposta valida HTTP segna la fine del warmup escluso dalle statistiche, non il primo istante in cui il servizio poteva rispondere.
- Nella riga di 8 copie, la fase di pull del provider (197 secondi) è la fase tra gli eventi Pulling e Pulled. Non è solo il caricamento dei pesi del modello e non c'è garanzia sulla sua composizione esatta.
- Il valore n.d. nelle righe di 12 e 16 copie significa che l'evento iniziale Pulling non era disponibile, mentre l'evento Pulled era disponibile. Non vale 0 secondi, e lo stato della cache dell'immagine è sconosciuto in tutte e tre le corse.
- Ogni conteggio ha una sola osservazione. La differenza tra 220 e 26 secondi non dimostra che più copie si avviino più velocemente.

## Conclusione

- I 32 client HTTP testati non sono il massimo fisico dell'hardware.
- Con 8 copie e concorrenza 32, passare da B1 a B8 porta le richieste al secondo da 2,253740 a 4,026919.
- Nella serie più recente, N12 è circa +3,61 per cento rispetto al controllo N8 a concorrenza 32 e N16 non dà un guadagno materiale.
- 8 copie con B8 è solo un candidato di compromesso: nessuna promozione e nessuna nuova immagine.
- Le serie usano la stessa fixture ma allocazioni di pod distinte; host fisico e cache non sono stati controllati e potrebbero differire. Non sono uno SLA né una certificazione di accuratezza.
- Sono esclusi A40, hardware Runpod e test diretti del core, perché non sono confrontabili.
- Il totale verificato con calcolatrice è 3573 tentativi e 3553 validi. Le uniche 20 risposte HTTP 429 sono quelle della vecchia cella N1 con concorrenza 32, e il warmup è escluso.
- Telemetria di potenza, controller di memoria, audit dei campioni e dettagli operativi restano nei report originali.

## Nota di verifica

Test e copertura N/A: solo Markdown; nessun quality gate o security review automatico, nessuna nuova prova GPU. Il file contiene 66 righe di prestazioni (18 più recenti, 24 del batch e 24 storiche), 11 righe di risorse e 3 righe di avvio.
