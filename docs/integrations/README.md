# DiddiComms Integration Contracts

The canonical service manifest is `manifests/diddicomms.v1.json`. Each document
in this directory explains one peer relationship and distinguishes observed,
proposed, partial, blocked, and implemented behavior.

| Peer | Role | Status |
|---|---|---|
| DiddiFreeID | Identity provider | Partial |
| DiddiSupport | Support provider and case authority | Partial |
| DiddiAdmin | Backoffice BFF consumer | Provider implemented; adapter migration pending |
| DiddiGo | Ride task-context provider | Implemented connector |
| DiddiSend | Delivery task-context provider | Proposed |
| DiddiFood | Food-order task and Support context provider | Proposed |
| DiddiFiles | Attachment provider | Proposed |
| DiddiPay | Payment Support context provider | Proposed for DiddiComms |

Open decisions are maintained in `docs/diddiconnect/open-questions.md`.
