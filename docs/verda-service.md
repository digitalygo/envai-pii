# Guida di test per il servizio su Verda Containers

Questa guida descrive il deployment di test `envai-pii-test` creato il 2026-10-26 su Verda Containers con l'autenticazione a monte del provider. Stato finale verificato: **in pausa, zero repliche**. L'immagine e la configurazione sono pubblicate e applicate; la chiave di inferenza e' ora disponibile, ma il primo avvio ha fallito il controllo CUDA per incompatibilita' del driver esposto dall'host. Autenticazione esterna e inferenza GPU restano da collaudare. Usare solo dati sintetici finche' non arrivano le approvazioni sui dati reali.

## Confine di autenticazione

Con `PII_AUTH_MODE=upstream` il container non controlla alcun token locale. L'autenticazione del provider e' l'**unico** confine per tutte le route: analisi, impostazioni (`/settings`, `/config`) e route legacy. Nessun accesso diretto e non fidato al container deve essere possibile. Se il provider non protegge ogni route, non usare questa modalita'. Dettagli nel [contratto API](GUARDRAIL_API.md#authentication).

## Configurazione del container

| Voce | Valore |
|---|---|
| Immagine | `ghcr.io/digitalygo/envai-pii:1.0.0-dev.6` |
| Porta | `5005` |
| Probe | `GET /health` sulla porta `5005` |
| Comando | quello predefinito dell'immagine, senza override |
| `PII_AUTH_MODE` | `upstream` (valore esatto, minuscolo) |
| `PII_ANALYSIS_TIMEOUT_SECONDS` | `60` |

- Non servono `PII_API_TOKEN`, file di token o mount di segreti.
- Non passare nel container le chiavi di gestione o di inferenza del provider.
- L'immagine configurata `dev.6` e' `cu130` e richiede un driver compatibile con CUDA 13; la ricetta sorgente corrente e' `cu126` (CUDA 12.6) e non e' ancora pubblicata. Il servizio non ripiega sulla CPU.

## Scalabilita' prevista

Configurazione applicata e riletta: una L40S, minimo 0 repliche, massimo 1, concorrenza 1, scale-up dopo 10 secondi, scale-down dopo 60 secondi e TTL delle richieste 300 secondi. Il deployment e' attualmente in pausa con zero repliche, non un servizio caldo. Un successivo avvio richiede la conclusione delle verifiche di autenticazione e comporta il caricamento del modello sulla GPU.

## Credenziali

- Le credenziali dell'API cloud gestiscono i deployment e non vanno mai usate dai chiamanti.
- Un chiamante esterno ha bisogno di una **chiave API di inferenza** separata, valida per il progetto.
- Non scrivere chiavi in repository, comandi, log o documentazione.

## Verifica prevista

Lo script `src/app/smoke_cloud.py` assume il Bearer locale e un `/health` anonimo: non e' adatto alla modalita' upstream. Il collaudo ancora necessario, con soli dati sintetici, e':

1. il provider rifiuta le richieste senza chiave o con chiave non valida;
2. con una chiave valida, `/health` mostra il modello su `cuda`;
3. con una chiave valida, `POST /api/v1/analyses` risponde `200` per un JSON sintetico e per un multipart sintetico;
4. con una chiave valida, le impostazioni protette (`GET /settings`) rispondono come previsto, e senza chiave sono rifiutate dal provider.

## Risultati e limiti verificati

- [Release `v1.0.0-dev.6`](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.6), sorgente `8d8b4d583e550fd832f0d361a6702bb52552a0a4`, pubblicata dalla [pipeline immagine](https://github.com/digitalygo/envai-pii/actions/runs/40373124737). Test CI su Python 3.11, 3.13 e 3.14 superati; suite locale 899 test senza skip. Copertura del delta Python di autenticazione 24/26, 92.31%; correzione Docker OpenSSL con copertura di produzione non applicabile.
- Digest verificato del manifest: `sha256:7acfb87640edb9f81c6635c593cd8544ca92b7219b780a83f4f93b8974ef2cce`. Piattaforma `linux/amd64`, utente `app`, healthcheck conservato, label di revisione coerente, nessun opt-out incorporato nell'immagine. Scansione: zero rilievi bloccanti e 258 vulnerabilita' non corrette ignorate dalla policy, non zero vulnerabilita'.
- La prima immagine `dev.5` e' stata bloccata dal gate per OpenSSL e non e' stata distribuita. La sostitutiva installa `openssl` e `libssl3` `3.0.22-1~deb12u2`.
- La creazione ha restituito l'[endpoint dichiarato dal provider](https://containers.datacrunch.io/envai-pii-test/). Le prove senza chiave e con chiave non valida hanno ricevuto `404` testuale del provider, non risposte applicative, anziche' i `401` o `403` attesi. Questo non dimostra un bypass, ma non completa la verifica del confine di autenticazione o del routing.
- La chiave di inferenza separata e' stata fornita. Il 2026-10-26 e' stata effettuata una sola riattivazione controllata dello stesso deployment. Due chiamate `/health` con quella chiave sono scadute lato client dopo circa 120 secondi ciascuna; non e' stata ricevuta alcuna risposta applicativa. Non sono stati eseguiti inferenza, collaudo PDF o benchmark su Verda. Le credenziali Cloud API non sono state usate per l'inferenza.
- I log mostrano il pull riuscito alle `19:03:36Z`, l'avvio di Gunicorn e poi il messaggio PyTorch `The NVIDIA driver on your system is too old (found version 12080)`, seguito da `RuntimeError: CUDA is unavailable.` alle `19:03:41Z`. Il valore `12080` identifica l'API CUDA 12.8 esposta, non il numero del pacchetto driver NVIDIA. L'immagine richiede `cu130`: il modello e il percorso PDF non vengono nemmeno inizializzati. Il comportamento osservato contraddice l'assunzione di un host gia' compatibile con CUDA 13 e prevale sulle indicazioni generiche del provider.
- Dopo un solo resume e una sola pausa condizionale il deployment e' tornato **in pausa, zero repliche**. L'accettazione operativa resta **bloccata dalla compatibilita' CUDA**, non piu' dall'assenza della chiave. Nessuna immagine, configurazione, versione del modello o risorsa RunPod e' stata modificata nel tentativo.
- Stato corrente rispetto alla storia: il 2026-10-26 l'utente ha approvato e il sorgente implementa una build CUDA 12.6 con PyTorch 2.13.0 invariato (`torch==2.13.0+cu126`, [indice ufficiale cu126](https://download.pytorch.org/whl/cu126/torch/), wheel Python 3.11 `torch-2.13.0+cu126-cp311-cp311-manylinux_2_28_x86_64.whl`). La suite locale e' stata eseguita con 901 test superati, senza skip. L'immagine remota configurata resta pero' `dev.6` (`cu130`) e il deployment resta in pausa, zero repliche. Pubblicazione della nuova immagine, compatibilita' GPU su Verda e validazione dell'autenticazione sono in sospeso: non vanno date per riuscite. Il resoconto del tentativo `dev.6`, il driver `12080`, la CI e i digest sopra restano storici.

## Documentazione ufficiale del provider

- [Panoramica di Verda Containers](https://docs.verda.com/containers/overview/)
- [Scalabilita' di Verda Containers](https://docs.verda.com/containers/scaling/)
- [Credenziali API di Verda](https://docs.verda.com/welcome-to-verda/api-credentials/)
