# Brief DiddiSupport - Conversations Support ouvertes par DiddiComms

**Date :** 28 octobre 2026  
**Destinataire :** equipe DiddiSupport  
**Demandeur technique :** DiddiComms  
**Statut :** integration contextuelle existante ; support general a completer

## Resultat attendu

L'application frontend DiddiFree appelle uniquement DiddiComms pour ouvrir une
conversation Support. DiddiComms authentifie l'utilisateur, valide une
eventuelle ressource metier, puis cree le dossier autoritatif dans
DiddiSupport.

DiddiSupport reste proprietaire du dossier, de son statut, de sa priorite, de
l'assignation, des notes internes et des actions des agents. DiddiComms reste
proprietaire du transport et de l'exposition des messages visibles.

## Appel entrant existant

```http
POST /support/v1/internal/cases
Authorization: Bearer <JWT service DiddiFreeID>
X-Client-ID: <client DiddiComms provisionne>
X-Request-ID: <correlation>
Idempotency-Key: <cle stable>
Content-Type: application/json
```

Identite attendue :

```text
aud=diddi-support
sub=service:diddicomms
role=service
token_type=service
status=active
scope contient diddi-support:cases:create
client_id identique a X-Client-ID
```

### Dossier contextuel

```json
{
  "origin_service": "diddigo",
  "resource_type": "ride",
  "resource_id": "11111111-1111-1111-1111-111111111111",
  "origin_report_id": "support-conversation-123",
  "reporter_user_id": "22222222-2222-2222-2222-222222222222",
  "category": "payment_issue",
  "subject": "Payment issue",
  "priority": "normal"
}
```

Le comportement actuel est conserve. DiddiSupport peut ensuite obtenir le
contexte expurge du module proprietaire selon `diddi.context.v1`.

### Dossier general a prendre en charge

DiddiComms envoie le meme contrat sans les trois champs de ressource :

```json
{
  "origin_report_id": "general-support-123",
  "reporter_user_id": "22222222-2222-2222-2222-222222222222",
  "category": "account_issue",
  "subject": "Account issue",
  "priority": "normal"
}
```

DiddiSupport doit accepter exactement deux formes :

1. `origin_service`, `resource_type` et `resource_id` tous presents ;
2. les trois champs absents pour une demande generale.

Toute combinaison partielle doit retourner `422 SUPPORT_RESOURCE_REFERENCE_INCOMPLETE`.
Une demande generale ne declenche aucun appel vers un module metier.

## Reponse requise

```http
HTTP/1.1 201 Created
```

```json
{
  "case_id": "aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa",
  "status": "open",
  "created_at": "2026-10-28T10:00:00Z"
}
```

Une reprise avec la meme cle et le meme contenu retourne le meme `case_id`.
La meme cle avec un contenu different retourne `409 IDEMPOTENCY_CONFLICT`.

## Premier message et messages suivants

Apres creation du dossier, DiddiComms transmet le premier message puis les
messages suivants avec :

```http
POST /support/v1/internal/cases/{case_id}/messages
Authorization: Bearer <JWT service>
X-Client-ID: <client DiddiComms>
X-Request-ID: <correlation>
Idempotency-Key: <client_message_id stable>
```

```json
{
  "reporter_user_id": "22222222-2222-2222-2222-222222222222",
  "body": "Le probleme continue."
}
```

DiddiSupport verifie que `reporter_user_id` est bien le demandeur du dossier.
La reponse doit indiquer `visibility=user_visible` et retourner un
`message_id` stable.

La lecture utilise :

```http
GET /support/v1/internal/cases/{case_id}/messages
```

Cette route ne doit jamais retourner une note interne.

## Evenements Redis vers DiddiComms

Stream : `diddisupport.events`  
Format : un champ Redis `event` contenant l'enveloppe JSON complete.  
Livraison : au moins une fois, avec `event_id` stable.

Evenements attendus :

```text
support.case.message.created.v1
support.case.updated.v1
support.case.assigned.v1
support.case.resolved.v1
```

Pour un message :

```json
{
  "event_id": "<uuid>",
  "event_type": "support.case.message.created.v1",
  "aggregate_id": "<case_id>",
  "aggregate_version": 4,
  "occurred_at": "2026-10-28T10:05:00Z",
  "payload": {
    "case_id": "<case_id>",
    "message_id": "<message_id>",
    "visibility": "user_visible"
  }
}
```

Le corps du message ne doit pas etre copie dans l'evenement. DiddiComms relit
l'historique autoritatif. Une note `internal_note` peut etre publiee pour la
synchronisation de version, mais DiddiComms ne la transmet pas au frontend.

## Ce que DiddiSupport ne doit pas faire

- Exposer directement ses routes internes au frontend.
- Creer une seconde conversation utilisateur hors DiddiComms.
- Envoyer les notes internes dans les lectures visibles.
- Faire confiance au seul `reporter_user_id` pour un dossier contextuel : le
  contexte et l'autorisation ont deja ete controles par DiddiComms, mais
  DiddiSupport conserve ses controles de coherence.
- Inclure telephone, GPS, KYC, secret ou detail fournisseur de paiement dans
  les evenements.

## Observabilite

Journaliser sans corps de message :

- `request_id`, `event_id`, `case_id`, `conversation_id` si disponible ;
- service appelant et client provisionne ;
- resultat d'idempotence ;
- categorie et statut, sans contenu utilisateur ;
- latence de creation et d'emission Redis.

Metriques minimales : creations, reprises idempotentes, conflits, messages,
notes internes, erreurs d'authentification, erreurs de publication et lag du
consumer group DiddiComms.

## Tests d'acceptation demandes

- Creation contextuelle visible dans DiddiComms.
- Creation generale sans reference metier.
- Reference partielle rejetee.
- Cle identique et contenu identique sans doublon.
- Cle identique et contenu different en `409`.
- Message utilisateur visible.
- Reponse agent visible.
- Note interne invisible.
- Doublon Redis ignore par DiddiComms.
- Dossier resolu rendant la conversation DiddiComms non modifiable.
- JWT, audience, client ou scope incorrects rejetes.

## Definition de fini

L'integration est prete lorsque le support general passe le test contractuel,
les evenements sont publies sur le port Redis provisionne, le consumer group
`diddicomms` ne presente pas de lag durable, et aucune note interne n'apparait
dans l'API DiddiComms.

## References DiddiComms

- `docs/DIDDISUPPORT_GATEWAY_CONTRACT.md`
- `docs/integrations/diddisupport.md`
- `docs/frontend/DIDDICOMMS_FRONTEND_SUPPORT_BRIEF_2026-10-28.md`
- `manifests/diddicomms.v1.json`
