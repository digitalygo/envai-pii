---
status: blocked
created_at: 2026-11-02
updated_at: 2026-11-02
implementation_status: verified_unchanged_8773c8689557
image_publication_status: verified_unchanged_v1_0_0_dev_8
rollout_configuration_status: verified_envai_pii_test_paused_min0
live_validation_status: blocked_provider_capacity_no_nodes_available
---

# Tentativo del 2 novembre 2026 di messa online su Verda bloccato per capacita' del provider

> [!note]
> Questo e' il resoconto storico dei tentativi 3 e 4. Il successivo tentativo 5 ha completato l'accettazione live: vedi il [report del servizio abilitato](2026-11-02-verda-n8-b8-online.md).

## Esito dei tentativi 3 e 4 e stato di sicurezza

Dopo l'istruzione del proprietario del `2026-11-02` (`"procedi, va messo online"`) sul [piano](../plans/2026-11-01-verda-n8-b8-image-scale-to-zero.md), **la messa online non e' stata raggiunta**: l'accettazione live ha chiuso con `quality-gate-b` finale **`FAIL`** per blocco di posizionamento/capacita' (indicazione di nodi non disponibili, classificazione locale `no_nodes_available`), e `envai-pii-test` e' in stato failure-safe **`paused`, `min=0`, `max=1`, `CC16`, `TTL 600` e `0` repliche (`replicas.list: []`)**. L'endpoint `https://containers.datacrunch.io/envai-pii-test` **non e' online ne' pronto**.

L'ultima verifica solo management del parent alle `2026-11-02T14:14:30.270906+00:00` conferma `paused/0/min=0/max=1/CC16/TTL600` senza chiamate all'endpoint ne' quinto `resume`. Lo zero failure-safe non e' scale-to-zero naturale. I test offline non sono prova runtime (`0/7` sonde salute/auth, `0/72` benchmark `CC8`/`CC16`, nessun RPS sull'immagine ordinaria). La prova nativa del `2026-11-01` (`8` worker `PID 202..209` su `cuda:0` in `float32` a `B8` e `POST /api/v1/analyses` a freddo `HTTP 200` in `35,746288 s`, oracolo `ddda56ee9282f89ecc09aac2e33ae632e97a93e45105bb6da3a294b9d9755f40`) resta storico valido nel [report del 2026-11-01](2026-11-01-verda-n8-b8-ordinary-image-rollout.md). Vedi [guida Verda](../../../docs/verda-service.md), [avvio worker GPU](../../../docs/gpu-worker-startup.md), [batching](../../../docs/chunk-batching.md), [CI e GHCR](../../../docs/ci-release.md) e [operazione](../operations/2026-10-21-runpod-service.md).

## Identita' invariata di sorgente, immagine e deployment

Sorgente, test, modello (`v1.5.0`, `float32`), pin (`torch==2.13.0+cu126`), auth (`PII_AUTH_MODE=upstream`), default (`1`/`1`) e oracolo sono invariati; `dev` resta a `HEAD` `8773c86895577c6040c2cbc6fd2438bfea7d7ef8` senza nuovi commit, build o release dopo `v1.0.0-dev.8`:

- **Immagine:** `ghcr.io/digitalygo/envai-pii@sha256:9d7a579b45513a0ae6de01298e7312e3f849fdef98c84ccc6238541a345c6f53` (`1.0.0-dev.8`).
- **Deployment `envai-pii-test`:** `1` `L40S` (`size=1`), `entrypoint_overrides.enabled=false` (`0` carrier), `11` env ordinarie (`N8 / B8`, `PII_VERIFY_MODEL_STARTUP=1`, `PII_AUTH_MODE=upstream`, timeout `60`, admission `16/32/30`, thread `1`), scaling `min=0`, `max=1`, `CC16`, `TTL 600`.

## Correzioni del client privato, test offline e gate pre-live

Codice ed evidenze del `2026-11-02` sono solo in `/home/lorenzo/private/tmp/envai-pii-n8-b8-online-20261102/` (sorgente, API e test del repository invariati; client privati modificati con `62` test privati; evidenze congelate e preservate):

1. **Client iniziale (`client/`, `3d29948c81ede79978a367d50bb205e5171755a2cb345d79d115384d2cb0da61`, `review-package.json` `2b0ab6ed`):** lettura `id`/`status`/`started_at` (`running` minuscolo), separazione ID gestione e pod log nativi, metadati sanitizzati salvati prima degli errori, auth parziale, benchmark limitato con fasi reali nei test E2E fake e convergenza `initializing`/`image_pulling` entro `600 s` prima di `healthy` + `running` post-ready. `security-review-specialist-a` **`PASS`** mirato sul pacchetto iniziale `ed53fd98` (`60` test, `309/309`); dopo la convergenza di avvio, `quality-gate-b` finale **`PASS`** su `2b0ab6ed` (`62` test `PASS` in `1,171 s`, `313/313`, `100%`). Nessuna revisione di sicurezza del pacchetto finale a `62` test: cambiano solo convergenza, contatore e guardia sul percorso, senza nuova superficie rilevante; i rilievi mirati precedenti restano invariati.
2. **Recupero su 5 linee (`client-recovery/` vs `baseline-recovery/`, client `821a29b5dce738b247a73b7f10158e427dff4ef9bc07af8638ff17fd40a5d51f`, test `fe27385ba94865503fd0b720e47c8a95ea1f425a0479c6411bdd844e50cc3724`, pacchetto `82d817f8e0b2f79567c7972cddd311e6db0cdfeb4a2969ea5bf2e348d786cc50`):** `client/` e `live/` congelati; modificate `5` linee (percorso output/profilo, contatore `3 -> 4` e rimozione di `unavailable` dai soli terminali di startup mentre `error`/`terminating` restano fallimenti, attendendo `healthy`/`updating` + `running` + `8` `PII_WORKER_READY` stessa coorte entro `600 s`). Parent: root `1246` `PASS` (`75,457 s`), privati `62` `PASS` (`1,228 s`, inclusi E2E `unavailable -> healthy` e timeout `unavailable` perpetuo con cleanup), `5/5` linee (`100%`) ed entrambi i rami/archi. `quality-gate-b` pre-live **`PASS`** (`82d817f8`, `62` test, `5/5` linee); nessuna nuova superficie di sicurezza. L'accettazione live finale e' `quality-gate-b` **`FAIL`**: prontezza non raggiunta e controlli live residui non eseguiti per il blocco di scheduling.

## Evidenza dei tentativi 3 e 4 del 2 novembre 2026

Il contatore `3 -> 4` conta i **tentativi**, non quattro GPU fisiche (solo i due del `2026-11-01` hanno GPU fisica provata; i due del `2026-11-02` non hanno allocazione provata). Dopo il tentativo `3`, il leader ha comunicato un singolo recupero controllato nell'ambito dell'istruzione ampia esistente (senza nuovo messaggio di approvazione fittizio). Il testo del callback su una cartella gia' popolata non prova alcun rogue writer (`1` `PID` `1553851` nel journal, `0` client attivi in `ps` del parent).

| Voce | Tentativo 3 (`live/`, client iniziale) | Tentativo 4 (`live-recovery/`, client corretto, `PID 1553851`) |
| --- | --- | --- |
| `POST /resume` | `2026-11-02T09:12:57.748584Z` | Avvio `09:48:50.465365Z`; singolo `resume` `09:48:51.553130Z` (`1` invocazione) |
| Replica `/replicas` | `envai-pii-test-5c77d7d87d-744c8`, `started_at: 09:13:20.000Z`, `unavailable`, `initializing` | `envai-pii-test-5c77d7d87d-sh6xs`, `started_at: 09:49:11Z`, `unavailable` / `initializing` |
| Stop | **Guardia operatore (non app):** `09:13:20.925685Z` `unavailable` terminale (`replica_not_active`); pausa effettiva `09:13:21.123851Z`; causa iniziale non classificata | **Errore reale provider:** `09:50:13.084453Z` (`~62 s`) deployment `unhealthy` e replica `error`; stop `09:50:13.773799Z` (`status_unhealthy`) |
| `POST` a freddo | `1` schedulato da `main()`, esito non persistito (ne' `0` inviati ne' mismatch) | `1` schedulato da `main()`, invio/esito `unknown` non persistito (smentita nota su zero POST) |
| Log, auth, bench | `0` `PII_WORKER_READY` provati, `0/7` auth, `0/72` benchmark | `0` righe log container su query complete non troncate (avvio `unknown`, non non-avvio provato); `0/7` auth, `0/72` benchmark |
| Cleanup | `paused`, `min=0`, `0` repliche alle `09:13:31.968453Z` | `pause` `09:50:13.941839Z`, `min=0` `09:50:14.118015Z`, confermato `09:51:17.816186Z` |

## Diagnosi dai log di sistema e prossima decisione

La diagnosi read-only `/home/lorenzo/private/tmp/envai-pii-n8-b8-online-20261102/newroot/diagnosis-recovery/management-diagnosis.json` (`412c6c8612ccb74cee23ce5f362b544575000a681daf5b8dd7d99b3e45f27c9f`, soli `GET` gestione + `POST` OAuth) e la lettura nativa in memoria del parent (`09:48:45Z..09:49:34.999999Z`, `4` righe non troncate, `8c6c4abf8f2c2e6b8cb1fc25d573beb11d1982df781480607fda1ebae0fdeb06`) mostrano un'indicazione di nodi non disponibili (classificazione locale `no_nodes_available`, non un codice formale del provider) per `sh6xs` alle `09:49:14.721376Z` (`count: 4` prima di `unhealthy`, piu' `count: 1` alle `09:51:07.142283Z` post-cleanup). L'etichetta `no_nodes_available` e' una classificazione locale del parser (`reason`/`level` `unknown`). Per `744c8` compare `count: 2` alle `09:13:26.760998Z`, dopo la pausa effettiva (`09:13:21.123851Z`; lo stop operatore era `09:13:20.925685Z`): non prova che la guardia iniziale sia scattata per capacita'. La causa di posizionamento/scheduling del tentativo `4` e' fortemente supportata; restano `unknown` vincoli di quota, pool GPU, stock globale `L40S`, nodo fisico, avvio container e image pull. Non emerge una prova di guasto CUDA, del modello o dell'immagine; non si dichiara fatturazione zero globale.

Per procedere occorre **il ripristino di capacita'/posizionamento lato provider** oppure **una decisione del proprietario su cambio GPU o profilo** (niente loop di unpause, `min=1` forzato, bypass guardie o cambio oracolo).
