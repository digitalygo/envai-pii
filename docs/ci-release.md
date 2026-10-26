# Automazione CI, release e pubblicazione GHCR

Questa guida descrive il bundle CI del repository `digitalygo/envai-pii`: suite di test su GitHub Actions, release semantiche automatiche da Conventional Commits, build e pubblicazione su GitHub Container Registry (GHCR) dell'immagine GPU `Dockerfile.gpu` con scansione remota Trivy sul digest, trigger manuale di build e aggiornamenti settimanali con Renovate.

> [!warning]
> **Stato operativo attuale: immagine `v1.0.0-dev.7` CUDA 12.6 distribuita su Verda, GPU provata, idle 0.** La [pipeline 40402660173](https://github.com/digitalygo/envai-pii/actions/runs/40402660173) e' riuscita per il sorgente `4c4db76ee1712283ba8f5778da70871b2b43e169` (tag `1.0.0-dev.7`), con PyTorch `2.13.0+cu126`, modello v1.5.0 invariato, 901 test su tre versioni Python e scansione `0 blocker(s), 287 unfixed ignored` (non zero vulnerabilita'). Digest distribuito `sha256:c1d9d9c089047f7c1e4b7b0815e91a12cd810c963ddb58ba1f0da1233e961714`. Il deployment Verda e' `HEALTHY`, non in pausa, con 0 repliche dopo scale-down naturale; inferenza reale e autenticazione del provider sono state verificate con dati sintetici. Dettagli in [guida Verda](verda-service.md). Nessuna certificazione di accuratezza, GDPR o capacita'.
>
> **Storico RunPod: `v1.0.0-dev.4` provata su GPU reale.** La release [`v1.0.0-dev.4`](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.4) e il [publisher docker-publish](https://github.com/digitalygo/envai-pii/actions/runs/40194544097) sono riusciti (build, scansione Trivy, promozione e verifica dei tre tag). Il gate ha riportato `0 blocker(s), 247 unfixed ignored`: residuo non zero, policy invariata, nessun segreto ne' `HIGH`/`CRITICAL` correggibile. L'immagine non e' stata applicata al Pod di test e la nuova concorrenza non e' stata provata su GPU. Il risultato su GPU reale (smoke 6 su 6 e casi PDF) appartiene a `v1.0.0-dev.3` ed e' solo storico; vedi la [guida del servizio RunPod](runpod-service.md). Le immagini `v1.0.0-dev.1` (bloccata, senza tag) e `v1.0.0-dev.2` (senza compilatore C) non sono target di deploy.

## Stato verificato del repository

Stato live rilevato durante l'attivazione sul ramo `dev`:

- **Visibilita' e Actions**: il repository `digitalygo/envai-pii` e' pubblico, con GitHub Actions abilitato e permessi predefiniti del `GITHUB_TOKEN` in sola lettura (`contents: read`).
- **Rami**: il ramo `feature/runpod-service` e' stato pubblicato (commit di bootstrap `a4525db`). Il ramo `dev` e' stato creato dallo stesso commit con `[skip ci]`, quindi non ha prodotto alcuna release iniziale. `main` e' **invariato** (`30d6f9c675e245bc8494df959adaeaa9d8de35c7`) e non e' stato promosso nessun contenuto su `main`.
- **Prima attivazione**: un commit vuoto `chore` (`766cb1af8e567e3e9b9388ef4887fbef53461975`) pushato su `dev` ha avviato la [esecuzione Release 39957892878](https://github.com/digitalygo/envai-pii/actions/runs/39957892878), conclusa con successo: 820 test superati su Python 3.11, 3.13 e 3.14 e creazione della pre-release [`v1.0.0-dev.1`](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.1) su quello SHA.
- **Segreti**: `RELEASE_TOKEN` e' **disponibile**: la CI live ha superato il controllo `Require RELEASE_TOKEN` e la pubblicazione tramite API, anche se l'elenco dei segreti del repository via CLI risulta vuoto. L'origine del token (per esempio ereditarieta' dall'organizzazione) non e' verificata e non va dedotta.
- **CODEOWNERS**: i proprietari `@lorenzocamporesi` e `@lucanori` in `.github/CODEOWNERS` sono account GitHub validi.
- **Pacchetto GHCR pubblico**: l'API di GitHub Packages riporta il pacchetto `ghcr.io/digitalygo/envai-pii` come **pubblico**, collegato al repository `digitalygo/envai-pii`. La visibilita' non e' stata modificata manualmente. Non cambiare la politica di visibilita' senza approvazione esplicita.
- **Storico: pubblicazione `v1.0.0-dev.1` fallita al gate**: l'[esecuzione docker-publish 39957975454](https://github.com/digitalygo/envai-pii/actions/runs/39957975454) ha completato build, push per digest, validazione dell'identita' dei metadati e scansione remota, poi e' fallita al gate di scansione con esattamente 2 risultati bloccanti:
  - `CVE-2026-23949` (`HIGH`, fix in `6.1.0`, `jaraco.context`, [GHSA-58pv-8j8x-9vj2](https://github.com/advisories/GHSA-58pv-8j8x-9vj2));
  - `CVE-2026-24049` (`HIGH`, fix in `0.46.2`, `wheel`, [GHSA-8rrh-rw8j-w5fx](https://github.com/advisories/GHSA-8rrh-rw8j-w5fx)).

  Il report di scansione e' stato eliminato per la politica di privacy della CI; nel report iniziale percorsi esatti e versioni installate non erano confermati. Le wheel ufficiali e la base effettiva ora confermano che `setuptools 79.0.1` vendorizza le vecchie versioni `jaraco.context 5.3.0` e `wheel 0.45.1`. L'immagine di quella corsa non ha tag (versione GHCR `1434889853`).
- **Correzione applicata**: `src/app/requirements-gpu.txt` fissa `setuptools 80.10.2` (che vendorizza `jaraco.context 6.1.0` e `wheel 0.46.3`, al posto della base `79.0.1`) e `Dockerfile.gpu` verifica queste soglie vendorizzate prima di `pip check`. Nessun bypass del gate.
- **Immagine storica disponibile (`v1.0.0-dev.4`)**: commit sorgente `0f161021b03b630ecf03556b6bf3cfe2f074cf75`; [Release 40194500271](https://github.com/digitalygo/envai-pii/actions/runs/40194500271) riuscita (test su Python 3.11, 3.13 e 3.14) con creazione della [release GitHub](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.4); [docker-publish 40194544097](https://github.com/digitalygo/envai-pii/actions/runs/40194544097) riuscito in tutti i job (build, metadati, identita' remota, scansione Trivy, promozione e verifica dei 3 tag). Digest `sha256:c71a392411ab14aed2d4b28bb8e84e5e727f32df6e24e5238b11715d3fbaf9ef`, tag `1.0.0-dev.4`, `dev` e `1.0.0-dev.4-0f161021b03b`, versione GitHub Packages `1443057951`, configurazione `sha256:5bc8d0974a646e01ad9358813a79acf02c7be52cc8e454b0612dfb309ac1bb2b`. Gate esatto `0 blocker(s), 247 unfixed ignored` con policy invariata. Verifiche indipendenti del leader: i tre tag risolvono allo stesso digest remoto; manifest grezzo validato; hash del blob di configurazione grezzo coincidente con il descrittore; `HEALTHCHECK` Docker presente nella configurazione reale (la proiezione `Buildx.Image` omette il campo specifico di Docker, non e' un difetto dell'immagine); label con versione 4 e SHA sorgente; utente non root `app`; nessuna chiave API incorporata. `main` resta `30d6f9c675e245bc8494df959adaeaa9d8de35c7`. Questa voce descrive un artefatto **pubblicato**, non distribuito. Riferimento candidato (preferire il digest): `ghcr.io/digitalygo/envai-pii@sha256:c71a392411ab14aed2d4b28bb8e84e5e727f32df6e24e5238b11715d3fbaf9ef`.
- **Immagine storica (`v1.0.0-dev.3`)**: provata su GPU reale. Dettagli: commit sorgente `4d6037bfc0c5ba8220399afe58dde968ee4b74a4` pushato su `dev`, [Release 40140407527](https://github.com/digitalygo/envai-pii/actions/runs/40140407527) riuscita e creazione della release GitHub [`v1.0.0-dev.3`](https://github.com/digitalygo/envai-pii/releases/tag/v1.0.0-dev.3); [docker-publish 40140446020](https://github.com/digitalygo/envai-pii/actions/runs/40140446020) riuscito in tutti i job, con 823 test su Python 3.11, 3.13 e 3.14. Il log di installazione mostra `gcc` 12.2.0-14+deb12u1 e `libc6-dev` 2.36-9+deb12u14 e la prova C reale (RUN #9) completata. Il gate ha riportato esattamente `scan gate passed: 0 blocker(s), 247 unfixed ignored`: il residuo non e' zero; la policy e' invariata (`HIGH`/`CRITICAL` con fix e qualunque segreto bloccano) e non ci sono segreti ne' `HIGH`/`CRITICAL` correggibili. I tag `dev`, `1.0.0-dev.3` e `1.0.0-dev.3-4d6037bfc0c5` risolvono allo stesso digest, verificato dalla CI, dall'API GitHub Packages (versione `1441208809`) e da strumenti immagine indipendenti del leader (`linux/amd64`, utente non root `app`, label revision e version corrette, nessun token incorporato; configurazione `sha256:47bea1e9e0ad1293a3029f3ede8c858d35f73fb6bc82fd2e1a546debafb1b1d3`). Il pacchetto resta pubblico, senza modifiche a visibilita' o credenziali; `main` resta `30d6f9c675e245bc8494df959adaeaa9d8de35c7`. Riferimento storico (digest): `ghcr.io/digitalygo/envai-pii@sha256:2b0324fe6e154eadc270b1accf157519abb5cac1663453579d5f76e1cf2f2f13`, oppure il tag `ghcr.io/digitalygo/envai-pii:1.0.0-dev.3`.
- **Immagine precedente (`v1.0.0-dev.2`)**: storica e non piu' target. Commit `6c9e4aeef964cf25a7ed40b0c0efaa732921b182`, [Release 39968680451](https://github.com/digitalygo/envai-pii/actions/runs/39968680451) e [docker-publish 39968768255](https://github.com/digitalygo/envai-pii/actions/runs/39968768255) riusciti (821 test), gate con 63 vulnerabilita' non corrette ignorate, versione GHCR `1435321891`, digest `a0b25f412c3b...`. Senza compilatore C: con GPU reale carica il modello e `/health` risponde `200`, ma la prima inferenza autenticata risponde `500` (`RuntimeError: Failed to find C compiler` nel driver Triton).
- **Immagine storica**: il digest di `v1.0.0-dev.1` (versione GHCR `1434889853`) resta senza tag e non e' un target di deploy.
- **Stato del Pod (storico)**: `2glj7taobhnhvg` eseguiva il digest `v1.0.0-dev.3` (un solo `PATCH` dell'immagine e un riavvio del container, GPU A40 e configurazione invariate). L'utente ha riferito in seguito di averlo fermato; lo stato attuale non e' stato interrogato e `v1.0.0-dev.4` non e' stata applicata.
- **Immagine runtime**: training, pin ML, autenticazione e modello sono invariati. `v1.0.0-dev.3` aggiunge il compilatore C a `Dockerfile.gpu`; `v1.0.0-dev.4` modifica l'ammissione delle richieste, la gestione delle operazioni native e la configurazione Gunicorn su CPU e GPU, con contratto API 0.4.0 e campi wire invariati.

## Architettura dei workflow

Il bundle CI si compone di quattro workflow coordinati:

| File | Trigger | Ruolo principale |
|---|---|---|
| `.github/workflows/tests.yml` | `push` su `main`, `pull_request`, `workflow_call` | Esegue `python -m unittest discover -v tests` su Python `3.11`, `3.13` e `3.14` installando solo i pin `flask==3.1.3` e `pymupdf==1.28.2` letti da `src/app/requirements-gpu.txt` (modello mockato, nessun download di PyTorch o pesi, e `node` gia' presente su `ubuntu-latest` per le verifiche JS dei workflow). |
| `.github/workflows/release.yml` | `push` su `dev`, `alpha`, `beta`, `main` | Chiama `tests.yml` e poi `.github/scripts/release.py` (solo libreria standard Python, senza introdurre `package.json` o semantic-release Node). Richiede `RELEASE_TOKEN`; fallisce subito se il segreto manca. |
| `.github/workflows/docker-publish.yml` | `release: [published]` | Chiama `tests.yml`, costruisce `Dockerfile.gpu` (`linux/amd64`) per l'esatto commit della release, pubblica per digest su GHCR, esegue la scansione Trivy remota sul digest, promuove i tag solo se il gate passa, invia l'eventuale dispatch Swarm e notifica kChat. |
| `.github/workflows/trigger-build.yml` | `workflow_dispatch` (selezione branch da UI) | Usa `RELEASE_TOKEN` per creare e pushare un singolo commit vuoto `chore: trigger image build` (stesso albero Git, `force: false`) sul branch scelto, senza eseguire build o test nel job. Non e' presente il trigger `repository_dispatch` `content-update` perche' il servizio non e' guidato da un CMS. |

## Modello di versionamento e canali di rilascio

Il motore `.github/scripts/release.py` calcola la versione successiva dai commit finiti sul branch a partire dall'ultima release. I tag Git hanno il prefisso `v` (per esempio `v1.0.0`), mentre i tag dell'immagine GHCR non lo hanno (`1.0.0`):

- **Numerazione dedicata del servizio**: la prima release parte da `1.0.0` su `main` (o `1.0.0-<canale>.1` sui rami di pre-release). Questa sequenza e' indipendente dalla versione storica upstream dell'app (`2.0.0`), dalla revisione del modello (`v1.5.0`) e dalla versione dello schema OpenAPI (`0.3.0`).
- **Regole Conventional Commits**:
  - `feat`: incremento **minor** (`0.1.0`).
  - `fix`, `chore`, `refactor`, `build`: incremento **patch** (`0.0.1`). `build` rilascia perche' modifica dipendenze o container distribuiti; `ci` non rilascia perche' tocca solo la pipeline.
  - `feat` o `fix` con `!` (es. `feat!:`) oppure footer `BREAKING CHANGE`: incremento **major** (`1.0.0`).
  - `ci`, `docs`, `test`, `style`, `perf` e qualunque commit contenente `[skip ci]`: **nessun rilascio**.
- **Canali**: `main` pubblica release stabili `X.Y.Z`; `dev`, `alpha` e `beta` pubblicano pre-release `X.Y.Z-<canale>.N` (es. `1.1.0-alpha.1`). Il ramo `dev` rilascia anche senza regole di branch protection.
- **Collisioni, idempotenza e recupero parziale**: se la versione calcolata esiste gia' su un commit diverso, lo script avanza automaticamente alla versione libera successiva senza fallire. Se viene rieseguito sullo stesso SHA di una release gia' esistente, termina in modo idempotente. Se una corsa precedente ha creato solo il tag Git ma non la release GitHub, il passo di recupero tenta di creare la release mancante ma non dichiara `released=true` finche' la release non risulta effettivamente osservata dalle API GitHub.

## Pubblicazione GHCR, scansione Trivy e promozione dei tag

Il workflow `docker-publish.yml` si attiva esclusivamente all'evento `release` di tipo `published` (creato con `RELEASE_TOKEN`) e opera sull'esatto SHA associato al tag della release:

1. **Verifica preflight e spazio disco**: controlla la presenza di `Dockerfile` e `Dockerfile.gpu` e la corrispondenza tra SHA dell'evento e commit del tag. Sui runner `github-hosted` (`ubuntu-24.04`, timeout job 60 minuti, cache GitHub Actions `type=gha,scope=gpu`) rimuove le directory SDK preinstallate non necessarie (`/usr/local/lib/android`, `/usr/share/dotnet`, `/opt/ghc`, `/usr/local/share/boost`) e verifica che restino almeno **30 GiB** liberi prima della build (l'immagine GPU locale occupa circa 6,14 GiB non compressi). La soglia di 30 GiB e' un controllo fail-closed con errore esplicito, non una garanzia assoluta di capienza del runner hosted.
2. **Build e push solo per digest**: costruisce `Dockerfile.gpu` per `linux/amd64` senza richiedere una GPU sul runner. Il push iniziale su `ghcr.io/digitalygo/envai-pii` avviene con `push-by-digest=true`, `oci-mediatypes=false`, `provenance: false` e `sbom: false`: l'immagine viene caricata senza alcun tag e mantiene i media type Docker v2 (preservando `HEALTHCHECK` nei metadati).
3. **Scansione di sicurezza remota obbligatoria**: prima di creare qualunque tag, `.github/scripts/registry_publish.py` valida il manifest e la configurazione remoti del digest appena caricato. Poi il container ufficiale `ghcr.io/aquasecurity/trivy:0.76.1` (fissato per digest) scansiona `ghcr.io/digitalygo/envai-pii@sha256:<digest>` direttamente dal registro (`--image-src remote`, scanner `vuln,secret`). `.github/scripts/scan_gate.py` applica il gate:

   - vulnerabilita' `HIGH` o `CRITICAL` **con fix disponibile** bloccano la pipeline;
   - vulnerabilita' senza fix disponibile vengono ignorate;
   - **qualunque segreto** rilevato o un report Trivy mancante, malformato, incompleto o riferito a un digest/config diverso blocca la pipeline.

   Se il gate fallisce, il job termina prima dello step di tagging: nessun tag nuovo viene creato e nessun tag esistente viene spostato.
4. **Promozione dei tag senza rebuild**: solo dopo il superamento del gate, `docker buildx imagetools create --prefer-index=false` copia i tag direttamente sul digest gia' scansionato e verifica che ogni tag risolva a quello stesso `sha256:<digest>`:

   - **Release stabile `X.Y.Z` (da `main`)**: `X.Y.Z`, `X.Y`, `X`, `latest`, `X.Y.Z-<short-sha12>`.
   - **Pre-release `X.Y.Z-<canale>.N` (da `dev`, `alpha`, `beta`)**: `X.Y.Z-<canale>.N`, `<canale>`, `X.Y.Z-<canale>.N-<short-sha12>` (nessun alias numerico mobile `X` o `X.Y`).

5. **Nessun deploy automatico su RunPod**: il workflow pubblica l'immagine su GHCR ma non avvia ne' aggiorna Pod su RunPod. Il requisito corrente dell'host e' un driver NVIDIA compatibile con CUDA 12.6 (ricetta `cu126`); le immagini gia' pubblicate, come `dev.6`, restano `cu130` e richiedono CUDA 13. La compatibilita' del nuovo host e l'inferenza reale su GPU NVIDIA restano da validare sul Pod secondo [`docs/runpod-service.md`](runpod-service.md).

## Segreti, permessi GHCR e integrazioni opzionali

La pipeline separa i permessi di rilascio Git da quelli di pubblicazione sul registro container e dalle notifiche:

### 1. Segreto obbligatorio `RELEASE_TOKEN`

`RELEASE_TOKEN` e' **gia' disponibile** per la CI live (verificato dal controllo `Require RELEASE_TOKEN` e dalla pubblicazione API riuscita), anche se `gh secret list` a livello di repository e' vuoto; l'origine non e' verificata. Per nuovi ambienti va configurato in `Settings -> Secrets and variables -> Actions` (oppure reso disponibile come segreto di organizzazione con accesso concesso a `envai-pii`). Non richiedere un nuovo token se quello esistente funziona.

- **Perche' serve**: le release e i commit creati con il `GITHUB_TOKEN` predefinito non innescano altri workflow GitHub Actions (`docker-publish.yml` dopo `release.yml`, oppure `release.yml` dopo `trigger-build.yml`).
- **Tipo e permessi consigliati**: creare un **Fine-grained Personal Access Token** dedicato, limitato al solo repository `digitalygo/envai-pii`, con permessi Repository **Contents: Read and write** e **Metadata: Read-only**. Questo copre sia la creazione di tag e release in `release.yml` sia il commit vuoto in `trigger-build.yml`.
- **Regole sui rami**: se `main`, `alpha` o `beta` usano branch protection o ruleset, l'utente a cui appartiene `RELEASE_TOKEN` deve avere il permesso di fare push sul ramo quando si usa `trigger-build.yml`. Il ramo `dev` non richiede branch protection.
- **Igiene dei segreti**: non incollare mai il token in chat, commit o file; non riutilizzare il token personale gia' salvato nella CLI locale.

### 2. Permessi di pubblicazione e visibilita' del pacchetto GHCR

La pubblicazione su `ghcr.io/digitalygo/envai-pii` usa i permessi integrati del workflow:

- **Nessun PAT per il push dell'immagine**: `docker-publish.yml` pubblica su GHCR usando esclusivamente il `GITHUB_TOKEN` automatico del job, che eleva i permessi a `packages: write` e `contents: read` senza modificare il default di sola lettura del repository.
- **Visibilita' del pacchetto e RunPod**: l'API di GitHub Packages riporta oggi il pacchetto come **pubblico** (misurato, non assunto privato), collegato al repository. Non modificare la visibilita' senza approvazione esplicita. Se in futuro il pacchetto diventasse privato, RunPod richiederebbe nella propria sezione Container Registry Auth un token separato di sola lettura (`read:packages`) per il pull.
- **Collegamento al repository e risoluzione errori `403`**: l'immagine include la label `org.opencontainers.image.source=https://github.com/digitalygo/envai-pii` per associare il pacchetto al repository. Se il pacchetto `ghcr.io/digitalygo/envai-pii` esiste gia' sotto l'organizzazione (per esempio da un push manuale precedente) e il job `docker-publish` fallisce con `403 Forbidden`, aprire le impostazioni del pacchetto su GitHub (`Package settings -> Manage Actions access`) e concedere al repository `envai-pii` il ruolo **Write** o **Admin**, verificando anche i permessi dei pacchetti a livello di organizzazione. Non disattivare mai la scansione o le verifiche per aggirare un errore di permesso.

### 3. Segreti e variabili opzionali (notifiche e Swarm)

Le integrazioni con kChat e con il repository Swarm sono opzionali e non bloccano il rilascio se omesse:

| Nome | Tipo | Comportamento |
|---|---|---|
| `KCHAT_WEBHOOK_URL` | Secret opzionale | Se configurato, il job `notify` (`if: always()`) invia un messaggio kChat che inizia con `✅` (successo) o `❌` (fallimento, inclusi scan gate o tagging falliti) riportando repository, tag della release, SHA del commit ed esito. Se assente, la notifica viene saltata senza far fallire il workflow. |
| `SWARM_REPOSITORY_DISPATCH_TOKEN` | Secret opzionale | Token con permesso di inviare `repository_dispatch` al repository Swarm. Usato solo dopo la verifica finale dei tag GHCR. |
| `SWARM_REPOSITORY` | Variable opzionale (`vars.SWARM_REPOSITORY`) | Repository di destinazione nel formato `<owner>/<repo>`. Quando sia il token sia la variabile sono configurati, viene inviato l'evento `renovate-run` con `source_repository`, `release_tag`, `commit_sha` e `run_id`. Se mancano o ricevono `401`/`403`/`404`, lo step viene saltato silenziosamente. |

## Aggiornamenti automatici con Renovate

Il file `.github/renovate.json` configura l'aggiornamento delle dipendenze con queste regole:

- **Pianificazione**: finestra settimanale ogni mercoledi' tra le `11:00` e le `13:00` (`Europe/Rome`, espressione `* 11-12 * * 3`), con `automerge: false`, `platformAutomerge: false`, `pinDigests: true` e revisori assegnati automaticamente da `.github/CODEOWNERS` (`@lorenzocamporesi` e `@lucanori`).
- **Manager abilitati e raggruppamento**: sono attivi solo `pip_requirements` (`requirements.txt` e `src/app/requirements-gpu.txt`), `dockerfile` (`Dockerfile` e `Dockerfile.gpu`), `docker-compose` (`docker-compose.yml`) e `github-actions` (`.github/workflows/*.yml`). Gli aggiornamenti `patch` sono raggruppati in una singola PR per ciascun manager.
- **Tipi di commit semantici**: gli aggiornamenti di `pip_requirements`, `dockerfile` e `docker-compose` usano il prefisso `build(packages): ...` (che una volta uniti su un ramo di rilascio producono una release **patch**), mentre gli aggiornamenti di `github-actions` usano `ci(github-actions): ...` (che **non** produce release).
- **Eccezioni manuali per PyTorch e Dockerfile CPU**: una `packageRule` disabilita Renovate esclusivamente per il pacchetto `torch` in `src/app/requirements-gpu.txt` (`torch==2.13.0+cu126`). Quel pin e il pin corrispondente in `Dockerfile.gpu` dipendono dall'indice wheel ufficiale PyTorch `cu126` e vanno aggiornati insieme a mano. Anche i pin `pip install` inline nel `Dockerfile` CPU non sono letti dal manager `dockerfile` (che aggiorna solo il digest dell'immagine `FROM`) e restano a gestione manuale.
- **Installazione della GitHub App**: il file di configurazione e' nel repository, ma l'accesso effettivo della GitHub App **Renovate** al repository `digitalygo/envai-pii` dipende dall'installazione a livello di organizzazione e va verificato da un amministratore.

## Procedura di bootstrap e prima attivazione

> [!note]
> Procedura storica: l'attivazione iniziale e' gia' stata eseguita sul ramo `dev` (vedi stato verificato). Resta valida come riferimento per **nuovi** rami di rilascio o nuovi deployment del bundle.

Per evitare di pubblicare accidentalmente una prima release sul commit che introduce la CI, il primo arrivo della configurazione su un ramo di rilascio senza tag (`main`, `dev`, `alpha` o `beta`) deve rispettare questa regola:

1. **Rendere disponibile `RELEASE_TOKEN`**: segreto del repository o ereditato dall'organizzazione, prima del push su un ramo di rilascio.
2. **Includere `[skip ci]` nel commit di atterraggio**, per esempio:

   ```text
   ci: configure GPU releases and GHCR [skip ci]
   ```

   Con merge commit o squash da GitHub UI, `[skip ci]` deve comparire nel messaggio del **commit di merge/squash** che atterra sul ramo, non solo nei commit intermedi.
3. **Verificare l'assenza di release accidentali** nelle schede `Actions` e `Releases`.
4. **Avviare la prima release intenzionale**. Il workflow `trigger-build.yml` non e' presente sul ramo predefinito `main`, quindi il pulsante `Run workflow` della UI non e' garantito. L'attivazione su `dev` e' avvenuta con un commit vuoto `chore` approvato, pushato direttamente su `dev`: non serve alcuna promozione su `main` ne' unire `main` per provare la pubblicazione; la release `v1.0.0-dev.1` (poi sostituita da `v1.0.0-dev.2` e `v1.0.0-dev.3`) e' partita dal ramo `dev` e `main` non e' mai stato modificato. Eseguire `Trigger image build` su un ramo di lavoro come `feature/runpod-service` aggiunge il commit vuoto `chore: trigger image build` ma **non** avvia la catena: `release.yml` ascolta solo i push su `dev`, `alpha`, `beta` e `main`, mentre `docker-publish.yml` si attiva alla pubblicazione della release.
5. **Controllare la catena live end-to-end** prima di usare l'immagine su RunPod, nell'ordine:
   - esecuzione verde di `Release` e creazione della release GitHub (`v1.0.0` oppure `v1.0.0-<canale>.1`): **completato** per `v1.0.0-dev.3` e `v1.0.0-dev.4`;
   - avvio automatico di `docker-publish`, controllo spazio disco e push del digest: **completato**;
   - build: **superata** (`docker-publish` 40140446020 per v3, 40194544097 per v4);
   - scansione remota Trivy e promozione dei tag: **superate** (tag verificati), ma con 247 vulnerabilita' non corrette ignorate (residuo non zero);
   - pull per digest dal Pod RunPod, forward reale su GPU e smoke test `src/app/smoke_cloud.py` della [guida del servizio RunPod](runpod-service.md): **superati** il 2026-10-25 sul Pod `2glj7taobhnhvg` (6 su 6, piu' casi sintetici JSON e PDF) con `v1.0.0-dev.3`, storico; per `v1.0.0-dev.4` **in sospeso**.
