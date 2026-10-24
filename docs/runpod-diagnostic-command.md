# Comando diagnostico per il Pod RunPod

Questo documento riporta un comando di sola lettura per riprodurre sul Pod il forward pass che fallisce con `500 internal_error` quando manca il compilatore C (causa radice confermata: Triton non trova un compilatore C). Non e' uno script eseguibile e non e' un file di configurazione da applicare.

Eseguirlo nel terminale del Pod RunPod, non in locale: serve la GPU del Pod e il modello integrato nell'immagine. Usa solo testo sintetico, non modifica il servizio pubblico e non contiene credenziali. Mentre gira puo' caricare una seconda copia del modello in VRAM, oltre a quella del worker Gunicorn.

```bash
cd /app/src/app
python -c 'from concurrent.futures import ThreadPoolExecutor; import app; ThreadPoolExecutor(max_workers=1).submit(app.analyze, "Contact: runpod-smoke@example.com").result(timeout=60); print("DIAGNOSTIC PASS")'
```

Con l'immagine `v1.0.0-dev.2` il comando termina con `RuntimeError: Failed to find C compiler`. Con un'immagine ricostruita che include il compilatore l'esito atteso e' `DIAGNOSTIC PASS`, da verificare sulla GPU: la presenza del compilatore non dimostra che ogni altra dipendenza funzioni.
