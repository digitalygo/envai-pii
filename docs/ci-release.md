# Automazione CI, release e pubblicazione GHCR

Questa guida descrive il bundle CI del repository `digitalygo/envai-pii`: suite di test su GitHub Actions, release semantiche automatiche da Conventional Commits, build e pubblicazione su GitHub Container Registry (GHCR) dell'immagine GPU `Dockerfile.gpu` con scansione remota Trivy sul digest, trigger manuale di build e aggiornamenti settimanali con Renovate.

> [!warning]
> **Stato operativo**: i workflow e gli helper Python sono presenti nel branch `feature/runpod-service`, non ancora pubblicato sul remoto. L'esecuzione end-to-end sui runner hosted di GitHub Actions, il primo rilascio su GitHub, il push su GHCR e il pull da RunPod richiedono la configurazione dei segreti e l'attivazione manuale descritta in fondo a questa guida. Nessuna di queste operazioni live viene dichiarata completata qui.

## Stato verificato del repository

Al momento della stesura sono stati verificati i seguenti dettagli di configurazione:

- **Visibilita' e Actions**: il repository `digitalygo/envai-pii` e' pubblico, con GitHub Actions abilitato e permessi predefiniti del `GITHUB_TOKEN` impostati in sola lettura (`contents: read`).
- **Branch e release**: sul remoto esistono attualmente solo `main` e `feature/teams-pii-integration`; il branch locale `feature/runpod-service` non e' ancora stato pushato. Non esistono tag o release GitHub pubblicate.
- **Segreti e CODEOWNERS**: non risultano segreti configurati a livello di repository (eventuali segreti ereditati dall'organizzazione non sono verificabili senza visibilita' admin). I proprietari `@lorenzocamporesi` e `@lucanori` in `.github/CODEOWNERS` sono account GitHub validi.
- **Immagine runtime invariata**: `Dockerfile.gpu`, `Dockerfile`, `src/app/requirements-gpu.txt` e il codice runtime non sono stati modificati da questa configurazione CI.

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

5. **Nessun deploy automatico su RunPod**: il workflow pubblica l'immagine su GHCR ma non avvia ne' aggiorna Pod su RunPod. La compatibilita' con driver host CUDA 13+ e l'inferenza reale su GPU NVIDIA restano da validare sul Pod secondo [`docs/runpod-service.md`](runpod-service.md).

## Segreti, permessi GHCR e integrazioni opzionali

La pipeline separa i permessi di rilascio Git da quelli di pubblicazione sul registro container e dalle notifiche:

### 1. Segreto obbligatorio `RELEASE_TOKEN`

`RELEASE_TOKEN` non e' attualmente presente tra i segreti del repository e **deve essere configurato dall'utente** in `Settings -> Secrets and variables -> Actions` (oppure reso disponibile come segreto di organizzazione con accesso concesso a `envai-pii`).

- **Perche' serve**: le release e i commit creati con il `GITHUB_TOKEN` predefinito non innescano altri workflow GitHub Actions (`docker-publish.yml` dopo `release.yml`, oppure `release.yml` dopo `trigger-build.yml`).
- **Tipo e permessi consigliati**: creare un **Fine-grained Personal Access Token** dedicato, limitato al solo repository `digitalygo/envai-pii`, con permessi Repository **Contents: Read and write** e **Metadata: Read-only**. Questo copre sia la creazione di tag e release in `release.yml` sia il commit vuoto in `trigger-build.yml`.
- **Regole sui rami**: se `main`, `alpha` o `beta` usano branch protection o ruleset, l'utente a cui appartiene `RELEASE_TOKEN` deve avere il permesso di fare push sul ramo quando si usa `trigger-build.yml`. Il ramo `dev` non richiede branch protection.
- **Igiene dei segreti**: non incollare mai il token in chat, commit o file; non riutilizzare il token personale gia' salvato nella CLI locale.

### 2. Permessi di pubblicazione e visibilita' del pacchetto GHCR

La pubblicazione su `ghcr.io/digitalygo/envai-pii` usa i permessi integrati del workflow:

- **Nessun PAT per il push dell'immagine**: `docker-publish.yml` pubblica su GHCR usando esclusivamente il `GITHUB_TOKEN` automatico del job, che eleva i permessi a `packages: write` e `contents: read` senza modificare il default di sola lettura del repository.
- **Visibilita' del pacchetto e RunPod**: anche se il repository Git e' pubblico, un nuovo pacchetto creato su GHCR in un'organizzazione nasce di default **privato**. Non rendere pubblico il pacchetto senza approvazione esplicita: verificare la visibilita' nelle impostazioni del pacchetto GHCR. Finche' il pacchetto resta privato, RunPod richiede nella propria sezione Container Registry Auth un token separato di sola lettura (`read:packages`) per eseguire il pull dell'immagine.
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
- **Eccezioni manuali per PyTorch e Dockerfile CPU**: una `packageRule` disabilita Renovate esclusivamente per il pacchetto `torch` in `src/app/requirements-gpu.txt` (`torch==2.13.0+cu130`). Quel pin e il pin corrispondente in `Dockerfile.gpu` dipendono dall'indice wheel ufficiale PyTorch `cu130` e vanno aggiornati insieme a mano. Anche i pin `pip install` inline nel `Dockerfile` CPU non sono letti dal manager `dockerfile` (che aggiorna solo il digest dell'immagine `FROM`) e restano a gestione manuale.
- **Installazione della GitHub App**: il file di configurazione e' nel repository, ma l'accesso effettivo della GitHub App **Renovate** al repository `digitalygo/envai-pii` dipende dall'installazione a livello di organizzazione e va verificato da un amministratore.

## Procedura di bootstrap e prima attivazione

Poiche' il repository non ha ancora alcuna release ne' tag Git, il primo arrivo di questa configurazione su un ramo di rilascio (`main`, `dev`, `alpha` o `beta`) deve rispettare la regola di bootstrap per evitare di pubblicare accidentalmente una prima release sul commit che introduce la CI:

1. **Configurare `RELEASE_TOKEN`**: aggiungere il segreto `RELEASE_TOKEN` nelle impostazioni del repository (o abilitarne l'ereditarieta' dall'organizzazione) prima di fare push su un ramo di rilascio.
2. **Includere `[skip ci]` nel commit di atterraggio**: quando si unisce `feature/runpod-service` su `main` (o su `dev`), assicurarsi che il messaggio del commit finale sul ramo di rilascio contenga `[skip ci]`, per esempio:

   ```text
   ci: configure GPU releases and GHCR [skip ci]
   ```

   Attenzione: se si usa un merge commit o uno squash merge da GitHub UI, `[skip ci]` deve comparire nel messaggio del **commit di merge/squash** che atterra su `main`, non solo nei commit intermedi del branch di feature.
3. **Verificare l'assenza di release accidentali**: dopo il push su `main`, controllare nella scheda `Actions` e nella sezione `Releases` che non sia stata creata alcuna release `v1.0.0`.
4. **Avviare la prima release intenzionale**: quando si e' pronti a pubblicare `1.0.0` e la relativa immagine GPU su GHCR, aprire `Actions -> Trigger image build -> Run workflow`, selezionare il branch di rilascio (es. `main` o `dev`) e avviare il job. Nota: eseguire `Trigger image build` su un branch di lavoro come `feature/runpod-service` aggiunge il commit vuoto `chore: trigger image build` a quel branch, ma **non** avvia `release.yml` ne' `docker-publish.yml` perche' il workflow di release ascolta solo `dev`, `alpha`, `beta` e `main`.
5. **Controllare la catena live end-to-end**: prima di usare la nuova immagine su RunPod, verificare nell'ordine:
   - esecuzione verde di `Release` e creazione della release GitHub `v1.0.0` (o `v1.0.0-<canale>.1`);
   - avvio automatico di `docker-publish`, superamento del check di spazio disco (30 GiB) e push del digest su `ghcr.io/digitalygo/envai-pii`;
   - superamento della scansione remota Trivy sul digest e promozione dei tag previsti;
   - visibilita' del pacchetto GHCR e pull dell'immagine per digest (`ghcr.io/digitalygo/envai-pii@sha256:<digest>`) dal Pod RunPod, seguito dallo smoke test `src/app/smoke_cloud.py` documentato nella [guida del servizio RunPod](runpod-service.md).
