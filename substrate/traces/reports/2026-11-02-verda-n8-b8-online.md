---
status: completed
created_at: 2026-11-02
live_validation_status: passed
---

# Servizio Verda N8 e B8 abilitato con scale-to-zero

## Esito

Il nuovo tentativo richiesto dall'utente ha superato l'accettazione live. `envai-pii-test` e' abilitato, non in pausa, con una L40S al massimo e zero repliche quando inattivo. L'ultima verifica indipendente solo management alle `2026-11-02T15:53:25.769351+00:00` conferma `healthy`, `replicas.list=[]`, profilo e immagine invariati.

- Immagine ordinaria `v1.0.0-dev.8`: `ghcr.io/digitalygo/envai-pii@sha256:9d7a579b45513a0ae6de01298e7312e3f849fdef98c84ccc6238541a345c6f53`.
- Configurazione: L40S x1, N8/B8, verifica startup attiva, auth upstream, 11 env, nessun override diagnostico, `/health`:5005.
- Scaling: min 0/max 1, concorrenza 16, TTL 600 s, ritardi up/down 10/60 s.
- Una sola mutation, `resume`; nessuna pausa finale, cambio GPU, modifica applicativa, nuova immagine o release.
- Tentativo conservativo numero 5, non cinque GPU fisiche. Tutte le evidenze precedenti sono preservate.

## Prove live

| Controllo | Risultato |
| --- | --- |
| Resume accettato | `15:26:30.778837Z` |
| Pod e id management | `envai-pii-test-5c77d7d87d-9shc7`, uguaglianza osservata tra i due identificativi |
| Worker | 8 PID distinti, 202..209, stessa coorte boot/ready, `cuda:0`, `float32` |
| Batching reale per worker | 63 chunk, 8 chiamate, somma input 63, massimo 8, coda 7 |
| Gunicorn listening | `15:26:56.588074211Z` |
| Ultimo worker pronto | `15:27:10.180128416Z` |
| Prima analisi a freddo | HTTP 200, circa 39,015 s, 45746 byte wire |
| Salute autenticata | HTTP 200, CUDA e modello caricati, `Cache-Control: no-store` |
| Contrasti auth | 6/6 rifiutati con HTTP 404 del provider su health, analisi e settings, chiave assente o errata |
| Benchmark | 72/72 HTTP 200 canonici, nessun retry o errore |
| Scale-to-zero | Evento nativo `ScaledToZero` alle `15:29:52Z`, senza pausa |
| Due osservazioni zero | `15:30:01.953943Z` e `15:30:09.068351Z`, distanti 7,114408 s, deployment healthy |

La prima risposta puo' precedere il ready dell'ultimo worker: il collettore attende comunque l'intera coorte prima delle prove successive. Il controllo di salute da solo non viene usato per dimostrare otto modelli.

Il corpo sintetico inviato e' identico alle serie precedenti: 45000 code point, 45174 byte, SHA-256 `d2a274f2ab87b0d3d71f2b9be595350e5a9ce0c919f11a7eea12a2d168d33b59`. Prima risposta e tutte le 72 misure coincidono con l'oracolo canonico invariato `ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`. I sei rifiuti hanno lunghezza 19 e SHA-256 del body standard del provider `404 page not found\n`; nessun body e' conservato.

## Misure del profilo ordinario

| Concorrenza | Raffiche | Risposte valide | Media (s) | P95 (s) | Richieste/s |
| --- | --- | --- | --- | --- | --- |
| 8 | 3 | 24/24 | 1,870068 | 2,373021 | 3,374888 |
| 16 | 3 | 48/48 | 3,181436 | 4,755323 | 3,434938 |

Il parent ricalcola tutte le righe, media, p95 nearest-rank e throughput come risposte valide divise per la somma delle durate delle raffiche. La richiesta cold e le sette sonde auth/health sono escluse. Questi valori descrivono il fixture e questa osservazione, non capacita' massima, accuratezza o SLA.

L'ultima risposta misurata termina alle `15:28:01.176932Z`; il marcatore client di fine traffico e' `15:28:01.448762Z`, 0,271830 s dopo. La prima osservazione a zero avviene 120,777011 s dopo l'ultima risposta effettiva, oppure 120,505 s dal marcatore. Il campionamento non misura l'istante fisico esatto di spegnimento. Dopo il benchmark non sono inviate altre richieste endpoint, solo letture management.

## Verifiche e provenienza

- Suite root: 1246 PASS, nessuno skip, 78,982 s. Client privato: 62 PASS, 1,164 s; delta eseguibile 4/4 coperto al 100%. Il literal autorizzativo multilinea e' esercitato dai test del profilo e non e' uno statement separato di coverage.
- Quality-gate-b pre-live PASS sul pacchetto `8c19c4bf44c31b11a2ef4ab601c1a3c64cafaf0d23d7db5f7cc09b80602e97b8`; quality-gate-b finale di accettazione live PASS dopo le prove reali. I precedenti FAIL restano storici, non vengono cancellati o convertiti.
- Nessun nuovo delta di sicurezza applicativo: sole sostituzioni private di output, contatori e autorizzazione, con trasporto, dati persistiti e controlli gia' revisionati invariati.
- Backend-dev-b si ferma prima di agire per una classificazione errata del ruolo operativo; il fallback sequenziale backend-dev-c esegue direttamente l'unico comando gia' verificato come membro backend delegato, senza subagent annidati.
- Audit indipendente nativo: due finestre non troncate, 53 e 7 righe, tutti gli otto payload e PID verificati, nessun marker di errore nel periodo di misura; evento `ScaledToZero` riletto dal provider e stato finale confrontato su dieci campi.
- Fonte privata: `/home/lorenzo/private/tmp/envai-pii-verda-retry5-20261102/live/`, con report, passi, startup, sonde, righe benchmark, snapshot management e scale-to-zero. Solo metadati e hash, nessun segreto, risposta PII o dizionario conservato.

Sorgente `dev` invariato a `8773c86895577c6040c2cbc6fd2438bfea7d7ef8`, main non modificato e nessun nuovo commit. La chiusura documentale ha test e coverage N/A. Nessun client o risorsa locale di test lasciato attivo; zero repliche e' lo stato inattivo del servizio abilitato, non una pausa amministrativa. Pull, cache e scheduling non sono isolati e TTL 600 non costituisce SLA.

Riferimenti: [piano del rollout](../plans/2026-11-01-verda-n8-b8-image-scale-to-zero.md), [precedente blocco di scheduling](2026-11-02-verda-online-capacity-blocker.md), [guida Verda](../../../docs/verda-service.md) e [operazione esistente](../operations/2026-10-21-runpod-service.md).
