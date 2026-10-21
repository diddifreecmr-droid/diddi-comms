# Bootstrap Manifests

These manifests are the shared starting point for module adoption. They are not
runtime discovery documents and must not be fetched dynamically by production
services.

These three files cover business-owner context providers only. The complete
DiddiComms service and its Support, Admin, Identity, Files, and Pay connections
are declared in `manifests/diddicomms.v1.json` and documented under
`docs/integrations/`. Their absence from this bootstrap directory does not mean
those integrations are complete or out of scope.

Each owner team must review its file, replace draft state policies, confirm
privacy fields, and commit the approved document into its own repository at:

```text
docs/integrations/diddiconnect.module.v1.json
```

The owner-repository copy becomes authoritative after provider tests, consumer
tests, and the staging smoke test pass. The central copy can then be updated as
the ecosystem catalog.

| Module | Task context | Support context | Manifest adoption |
|---|---|---|---|
| DiddiGo | Implemented in code | Implemented in code | Proposed |
| DiddiSend | Proposed | Implemented in code | Proposed |
| DiddiFood | Proposed | Proposed | Proposed |
