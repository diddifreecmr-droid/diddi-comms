# Tests staging DiddiComms et DiddiSupport

Ces tests appellent uniquement les interfaces deployees. Ils n'importent aucun
code et ne lisent aucun fichier du depot DiddiSupport.

Services cibles par defaut :

- DiddiComms : `https://diddi-comm-staging.diddifree.com`
- DiddiSupport : `http://support-backend-staging.diddifree.com`

## Smoke et contrat OpenAPI

PowerShell :

```powershell
$env:RUN_STAGING_SMOKE_TESTS = "1"
pytest tests/staging/test_diddicomms_diddisupport_staging.py -m staging -v
```

Ce niveau verifie la disponibilite des deux services et la presence des routes
HTTP du contrat. Il ne cree aucune donnee.

Les URLs sont surchargeables avec `DIDDICOMMS_STAGING_BASE_URL` et
`DIDDISUPPORT_STAGING_BASE_URL`. `STAGING_HTTP_TIMEOUT_SECONDS` controle le
timeout HTTP.

## Parcours reel en ecriture

Le parcours d'ecriture passe exclusivement par DiddiComms. DiddiComms appelle
ensuite DiddiSupport avec son identite de service configuree dans le staging.
Le test cree un vrai dossier Support et deux messages, il demande donc un
opt-in distinct :

```powershell
$env:RUN_STAGING_SMOKE_TESTS = "1"
$env:RUN_STAGING_WRITE_TESTS = "1"
$env:DIDDICOMMS_STAGING_USER_TOKEN = "<jwt-utilisateur-staging>"
pytest tests/staging/test_diddicomms_diddisupport_staging.py -m staging -v
```

Le frontend et ce test ne doivent jamais appeler les routes `/internal/` de
DiddiSupport. Ces routes sont verifiees via OpenAPI ; leur authentification et
leur utilisation effective restent sous la responsabilite de DiddiComms.

Le flux Redis `diddisupport.events` n'est pas public par HTTP. Sa certification
doit etre executee depuis l'environnement de staging disposant de
`SUPPORT_EVENTS_REDIS_URL`, avec le worker DiddiComms et son consumer group.
