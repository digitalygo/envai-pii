# Guida di test per il servizio su Verda Containers

Questa guida descrive come provare `envai-pii` su Verda Containers con l'autenticazione a monte del provider. Stato: **in sospeso**. Il tag dell'immagine pubblicata e l'URL del deployment non sono ancora disponibili, quindi nulla qui e' stato distribuito o verificato. Usare solo dati sintetici finche' non arrivano le approvazioni sui dati reali.

## Confine di autenticazione

Con `PII_AUTH_MODE=upstream` il container non controlla alcun token locale. L'autenticazione del provider e' l'**unico** confine per tutte le route: analisi, impostazioni (`/settings`, `/config`) e route legacy. Nessun accesso diretto e non fidato al container deve essere possibile. Se il provider non protegge ogni route, non usare questa modalita'. Dettagli nel [contratto API](GUARDRAIL_API.md#authentication).

## Configurazione del container

| Voce | Valore |
|---|---|
| Immagine | tag pubblicato non ancora disponibile (in sospeso) |
| Porta | `5005` |
| Probe | `GET /health` sulla porta `5005` |
| Comando | quello predefinito dell'immagine, senza override |
| `PII_AUTH_MODE` | `upstream` (valore esatto, minuscolo) |
| `PII_ANALYSIS_TIMEOUT_SECONDS` | `60` |

- Non servono `PII_API_TOKEN`, file di token o mount di segreti.
- Non passare nel container le chiavi di gestione o di inferenza del provider.
- L'host deve esporre un driver NVIDIA compatibile con CUDA 13: il servizio non ripiega sulla CPU.

## Scalabilita' prevista

Valori pianificati, **non ancora applicati**: minimo 0 repliche, massimo 1, concorrenza 1, scale-down dopo 60 secondi. Con minimo 0 il primo avvio include il caricamento del modello su GPU: attendere `/health` prima di inviare richieste.

## Credenziali

- Le credenziali dell'API cloud gestiscono i deployment e non vanno mai usate dai chiamanti.
- Un chiamante esterno ha bisogno di una **chiave API di inferenza** separata, valida per il progetto.
- Non scrivere chiavi in repository, comandi, log o documentazione.

## Verifica prevista

Lo script `src/app/smoke_cloud.py` assume il Bearer locale e un `/health` anonimo: non e' adatto alla modalita' upstream. La verifica pianificata, con soli dati sintetici, e':

1. il provider rifiuta le richieste senza chiave o con chiave non valida;
2. con una chiave valida, `/health` mostra il modello su `cuda`;
3. con una chiave valida, `POST /api/v1/analyses` risponde `200` per un JSON sintetico e per un multipart sintetico;
4. con una chiave valida, le impostazioni protette (`GET /settings`) rispondono come previsto, e senza chiave sono rifiutate dal provider.

## Documentazione ufficiale del provider

- [Panoramica di Verda Containers](https://docs.verda.com/containers/overview/)
- [Scalabilita' di Verda Containers](https://docs.verda.com/containers/scaling/)
- [Credenziali API di Verda](https://docs.verda.com/welcome-to-verda/api-credentials/)
