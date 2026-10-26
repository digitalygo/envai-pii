# Guida di test per il servizio su Verda Containers

Questa guida descrive il deployment di test `envai-pii-test` su Verda Containers con autenticazione a monte del provider. Stato finale verificato (2026-10-26): immagine `1.0.0-dev.7` (`cu126`) distribuita, **GPU provata, `HEALTHY`, non in pausa, zero repliche** dopo scale-down naturale. Usare solo dati sintetici finche' non arrivano le approvazioni sui dati reali.

## Stato corrente

| Voce | Valore |
|---|---|
| Stato provider | `HEALTHY`, non in pausa, 0 repliche |
| Immagine distribuita | `ghcr.io/digitalygo/envai-pii@sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714` (`1.0.0-dev.7`) |
| Sorgente | `4c4db76ee1712283ba8f5778da70871b2b43e169`, tag `1.0.0-dev.7`, [pubblicazione 40402660173](https://github.com/digitalygo/envai-pii/actions/runs/40402660173) riuscita |
| Stack GPU | `torch==2.13.0+cu126` (CUDA 12.6), modello v1.5.0 invariato |
| Endpoint | [Endpoint HTTP Verda](https://containers.datacrunch.io/envai-pii-test/) |

Il prossimo invio di una richiesta puo' causare un cold start di una GPU. Al momento non c'e' alcuna GPU calda; non si afferma che ogni costo possibile sia zero.

## Come chiamare il servizio

- URL base: `https://containers.datacrunch.io/envai-pii-test/`.
- Analisi: `POST https://containers.datacrunch.io/envai-pii-test/api/v1/analyses`.
- Salute: `GET https://containers.datacrunch.io/envai-pii-test/health`.
- Autenticazione: header `Authorization: Bearer <chiave di inferenza Verda>`. La chiave e' una **chiave di inferenza dedicata**, non il client secret dell'API cloud. Configurarla nel client HTTP o in un gestore di segreti, senza inserirla negli URL, nei comandi o negli argomenti dei processi.
- Contratti e formati delle richieste: [contratto API](GUARDRAIL_API.md).

Nel client HTTP selezionare l'autenticazione Bearer e inviare un corpo JSON sintetico, per esempio:

```json
{"text":"Contatto sintetico: prova@example.com","categories":["EMAIL"]}
```

## Confine di autenticazione

Con `PII_AUTH_MODE=upstream` il container non controlla alcun token locale. L'autenticazione del provider e' l'**unico** confine per tutte le route: analisi, impostazioni (`/settings`, `/config`) e route legacy. Nessun accesso diretto e non fidato al container deve essere possibile. Se il provider non protegge ogni route, non usare questa modalita'. Dettagli nel [contratto API](GUARDRAIL_API.md#authentication).

Il provider risponde `404` testuale di 19 byte (identico per tutte le route) alle richieste senza chiave o con chiave non valida. E' il rifiuto osservato del provider, non un difetto di routing; i `404` delle route applicative sconosciute hanno corpo diverso.

## Configurazione del container

| Voce | Valore |
|---|---|
| Immagine | `ghcr.io/digitalygo/envai-pii@sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714` |
| Porta | `5005` |
| Probe | `GET /health` sulla porta `5005` |
| Comando | quello predefinito dell'immagine, senza override |
| `PII_AUTH_MODE` | `upstream` (valore esatto, minuscolo) |
| `PII_ANALYSIS_TIMEOUT_SECONDS` | `60` |

- Non servono `PII_API_TOKEN`, file di token o mount di segreti, e nessuna chiave del provider e' passata nel container.
- Il passaggio a `dev.7` e' stato un solo PATCH `200` che ha cambiato solo l'immagine; tutti gli altri parametri sono invariati.
- Il servizio non ripiega sulla CPU.

## Scalabilita'

Una L40S, minimo 0 repliche, massimo 1, concorrenza 1, scale-up dopo 10 secondi, scale-down configurato a 60 secondi (non garantito esattamente 60) e TTL delle richieste 300 secondi. Dopo l'ultimo traffico alle `22:17:08.419Z`, `ReplicaDeleted`/`ScaledToZero` e' avvenuto alle `22:19:14Z` (circa 125,6 secondi), con stato verificato indipendentemente `HEALTHY`, non in pausa, 0 repliche.

Cold start osservato (indicativo, non SLA ne' benchmark): primo avvio con download dell'immagine 237,8 secondi; avvio successivo con immagine in cache 37,7 secondi. Sono tempi complessivi di prontezza, non misure isolate del solo download.

## Credenziali

- Le credenziali dell'API cloud gestiscono i deployment e non vanno mai usate dai chiamanti.
- Un chiamante esterno ha bisogno della **chiave API di inferenza** separata, valida per il progetto.
- Non scrivere chiavi in repository, comandi, log o documentazione.

## Risultati e limiti verificati

Lo script `src/app/smoke_cloud.py` assume il Bearer locale e un `/health` anonimo: non e' adatto alla modalita' upstream. Collaudo con soli dati sintetici:

1. salute GPU reale con chiave valida: superata;
2. JSON con email, riuso del seed, TXT e guardrail testo/PDF mascherati, route legacy `analyze` e `preview/pdf`: tutti `200`;
3. il leader ha verificato in modo indipendente una vera maschera JSON, l'esatto delta e `no-store`: superato;
4. 30 sonde negative (mancanza o invalidita' della chiave) su 15 route: tutte `404` testuale del provider di 19 byte; con chiave valida le stesse route note rispondono `200`;
5. tre contrasti su route sconosciute e `healthz` `200`: superati;
6. scale-down naturale a zero: superato.

La prima esecuzione `cu126` si era fermata perche' il client di verifica classificava come errore un `404` atteso per un documento mancante; era un difetto del client, non dell'app. Una chiusura esplicitamente limitata ha corretto le attese per route e ha superato tutti i controlli sopra.

Limiti: nessuna certificazione di accuratezza, GDPR, anonimizzazione completa dei PDF o capacita'. Le revisioni di sorgente e configurazione e il giudizio di sicurezza mirato sulle evidenze live sono superati per il perimetro testato. Non e' un penetration test o una verifica esaustiva dell'infrastruttura del provider.

## Immagine e CI

- Test CI su Python 3.11, 3.13 e 3.14 superati; 901 test locali. Scansione: zero rilievi bloccanti e 287 vulnerabilita' non corrette ignorate dalla policy, non zero vulnerabilita'.
- Copertura di produzione non applicabile (solo packaging e configurazione). Nessun nuovo codice applicativo.
- Manifest `sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714`, configurazione `sha256:feb376bc156db28f44f81a3864fcb3c98a9391daa33f1908e34c85061b5f5de0`.

## Storico

- [Release `v1.0.0-dev.6`](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.6), sorgente `8d8b4d583e550fd832f0d361a6702bb52552a0a4`, [pipeline immagine](https://github.com/digitalygo/envai-pii/actions/runs/40373124737). Test su Python 3.11, 3.13 e 3.14 superati; 899 test locali. Copertura del delta di autenticazione 24/26, 92.31%. Digest `sha256:7acfb87640edb9f81c6635c593cd8544ca92b7219b780a83f4f93b8974ef2cce`; scansione zero rilievi bloccanti e 258 vulnerabilita' non corrette ignorate.
- La prima immagine `dev.5` e' stata bloccata dal gate per OpenSSL e non e' stata distribuita; la sostitutiva installa `openssl` e `libssl3` `3.0.22-1~deb12u2`.
- Storico, non piu' corrente: la creazione aveva restituito l'endpoint dichiarato dal provider e le prove senza chiave davano `404` testuale; allora non era chiaro se fosse routing. Ora e' il rifiuto osservato del provider (vedi sopra).
- Storico `dev.6` (`cu130`): una sola riattivazione controllata ha scaricato l'immagine (pull alle `19:03:36Z`), poi `The NVIDIA driver on your system is too old (found version 12080)` e `RuntimeError: CUDA is unavailable.` alle `19:03:41Z`. `12080` indica l'API CUDA 12.8 esposta dall'host. Due chiamate `/health` sono scadute lato client dopo circa 120 secondi; il deployment e' tornato in pausa. Questo ha motivato il passaggio a `cu126`.
- Storico: le voci sull'immagine `dev.6` configurata e sul PATCH non ancora applicato erano valide solo prima del passaggio a `dev.7`.

## Documentazione ufficiale del provider

- [Panoramica di Verda Containers](https://docs.verda.com/containers/overview/)
- [Scalabilita' di Verda Containers](https://docs.verda.com/containers/scaling/)
- [Credenziali API di Verda](https://docs.verda.com/welcome-to-verda/api-credentials/)
