# Brief frontend DiddiFree - Conversations Support via DiddiComms

**Date :** 28 octobre 2026  
**Destinataire :** equipe de l'unique application frontend DiddiFree  
**API publique :** DiddiComms  
**Statut :** pret pour integration contextuelle ; support general dependant de DiddiSupport

## Objectif

Tous les signalements, messages et futurs appels Support partent du frontend
vers DiddiComms. Le frontend n'appelle jamais directement DiddiSupport ni une
route metier `/internal/`.

Il n'existe ni gateway frontend supplementaire, ni application frontend par
module. Les ecrans DiddiGo, DiddiSend et DiddiFood de l'application DiddiFree
transmettent seulement une reference vers leur ressource metier.

```text
Application DiddiFree
        |
        v
     DiddiComms
       /   \
      v     v
module metier  DiddiSupport
validation     dossier et agents
```

## Ouvrir une conversation Support

```http
POST /comms/v1/support/conversations
Authorization: Bearer <JWT utilisateur DiddiFreeID>
Idempotency-Key: <UUID genere par le frontend>
Content-Type: application/json
```

### Signalement lie a une ressource

```json
{
  "category": "payment_issue",
  "message": "Le paiement reste en attente.",
  "context": {
    "owner_service": "diddigo",
    "task_type": "ride",
    "task_id": "11111111-1111-1111-1111-111111111111"
  }
}
```

Correspondances autorisees :

| Ecran | `owner_service` | `task_type` | Identifiant |
|---|---|---|---|
| Course | `diddigo` | `ride` | `ride_id` |
| Livraison | `diddisend` | `delivery` | `delivery_id` |
| Commande Food | `diddifood` | `order` | `order_id` |

DiddiComms appelle le resolver du module et verifie que l'utilisateur figure
parmi les participants. Le frontend n'envoie jamais de `user_id`, de role, de
participant, de numero de telephone, de position GPS ou de permission.

### Demande generale

```json
{
  "category": "account_issue",
  "message": "Je ne peux pas modifier mon profil.",
  "context": null
}
```

Cette forme est implementee cote DiddiComms. Elle ne doit etre activee en
pilote qu'apres validation de la creation sans reference metier par
DiddiSupport.

### Champs

| Champ | Obligatoire | Regle |
|---|---|---|
| `category` | Non | `general` par defaut, 1 a 80 caracteres |
| `message` | Oui | 1 a 2 000 caracteres |
| `subject` | Non | 1 a 200 caracteres ; derive de la categorie si absent |
| `priority` | Non | `low`, `normal`, `high` ou `urgent` |
| `origin_report_id` | Non | Reference fonctionnelle existante, 120 caracteres maximum |
| `context` | Non | Objet complet ou `null` ; jamais partiel |

Le frontend ne doit pas permettre a l'utilisateur de choisir librement la
priorite `urgent`. Cette valeur est reservee aux parcours explicitement
approuves. Le SOS DiddiGo reste une action DiddiGo distincte.

## Reponse

```json
{
  "conversation_id": "bbbbbbbb-2222-2222-2222-bbbbbbbbbbbb",
  "support_case_id": "aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa",
  "conversation_state": "active",
  "case_status": "open",
  "owner_service": "diddigo",
  "task_type": "ride",
  "task_id": "11111111-1111-1111-1111-111111111111"
}
```

Le frontend conserve `conversation_id` pour les operations de communication.
Il n'utilise pas `support_case_id` pour appeler DiddiSupport.

## Messages

Envoyer un message :

```http
POST /comms/v1/conversations/{conversation_id}/messages
Authorization: Bearer <JWT utilisateur>
Idempotency-Key: <UUID>
```

```json
{
  "client_message_id": "<UUID stable>",
  "body": "Le probleme continue."
}
```

Relire l'historique :

```http
GET /comms/v1/conversations/{conversation_id}/messages?after_seq=0&limit=100
```

Pour une conversation Support, DiddiComms retourne uniquement les messages
`user_visible` fournis par DiddiSupport. Une note interne ne doit jamais etre
affichee, meme si elle est recue par erreur dans un evenement temps reel.

## Idempotence et reprise

- Generer une cle differente pour chaque nouvelle intention utilisateur.
- Reutiliser exactement la meme cle lors d'un retry reseau.
- Ne pas generer une nouvelle cle apres un timeout tant que le resultat de la
  tentative precedente est inconnu.
- Conserver un `client_message_id` stable pour chaque message.
- Un `409 IDEMPOTENCY_CONFLICT` impose d'arreter le retry et de journaliser le
  `X-Request-ID`.

## Erreurs a traiter

| HTTP / code | Comportement frontend |
|---|---|
| `400 IDEMPOTENCY_KEY_REQUIRED` | Corriger le client ; ne pas retenter sans cle |
| `401` | Renouveler la session DiddiFreeID |
| `404 TASK_NOT_FOUND` | Afficher que la ressource n'est plus accessible |
| `409 IDEMPOTENCY_CONFLICT` | Ne pas dupliquer ; proposer une reprise manuelle |
| `422` | Corriger le formulaire ou le contexte |
| `429` | Respecter le delai et eviter les soumissions multiples |
| `502` | Configuration interservice incorrecte ; afficher une indisponibilite |
| `503 SUPPORT_UNAVAILABLE` | Conserver le brouillon et proposer de reessayer |

Ne jamais afficher les details techniques, scopes ou noms d'hotes au client.

## Appels

Les appels entre participants d'une tache utilisent deja DiddiComms. Un appel
vers le Support n'est pas encore disponible : aucun contrat autorise ne fournit
actuellement une destination d'agent ou de centre d'appel. Le frontend ne doit
pas afficher ce bouton pour une conversation `support` avant publication de ce
contrat.

## Migration des ecrans

1. Ajouter l'appel ci-dessus dans la couche HTTP existante de l'application.
2. Brancher les boutons `Signaler un probleme` des details course, livraison et
   commande.
3. Ouvrir l'ecran de conversation avec le `conversation_id` retourne.
4. Conserver les actions metier existantes : SOS, remboursement et annulation.
5. Ne plus creer de nouvelle integration frontend vers une route de plainte
   metier lorsque le feature flag DiddiComms est actif.
6. Activer module par module avec un feature flag.

## Recette frontend minimale

- Course appartenant au passager et au chauffeur.
- Livraison appartenant au client et au coursier lorsque le contrat l'autorise.
- Commande Food apres disponibilite de son resolver DiddiComms.
- Ressource d'un autre utilisateur retournee comme introuvable.
- Double clic et retry avec la meme cle.
- Reponse visible recue en temps reel puis presente dans l'historique.
- Note interne absente de l'interface.
- Support indisponible sans perte du texte saisi.
- Conversation Support encore ouvrable apres fin de la tache metier.

## References

- `docs/DIDDISUPPORT_GATEWAY_CONTRACT.md`
- `docs/integrations/diddisupport.md`
- `docs/CONTEXT_RESOLVER_CONTRACT.md`
- `manifests/diddicomms.v1.json`
