# 2. The protocol: cards, messages, tasks, parts, artifacts

```
client                                   remote agent
  GET /.well-known/agent-card.json  ->   AgentCard {name, skills[], supportedInterfaces[], capabilities, ...}
  POST /a2a/jsonrpc  SendMessage    ->   Message {role: ROLE_USER, messageId, contextId?, parts: [Part]}
                                    <-   Task {id, contextId, status.state, history[], artifacts[]}
  POST /a2a/jsonrpc  GetTask {id}   ->   the same Task later (task store)
```

- **AgentCard** - discovery document. Skills (id, tags, input/output modes), transport bindings (`JSONRPC`,
  `HTTP+JSON`, `GRPC`) with URLs and protocol version, capabilities (streaming, push notifications), security.
- **Message** - one turn. **Part** = `text` | `data` (JSON) | `raw` bytes | `url`. We send incident state as a data part.
- **Task** - the stateful unit of work. States: `SUBMITTED → WORKING → COMPLETED | FAILED | CANCELED | REJECTED`,
  or interrupted `INPUT_REQUIRED | AUTH_REQUIRED`. The caller **branches on state**.
- **Artifact** - the output of a task (named, made of parts). Our agents return an `update` artifact = partial state.
- **contextId** groups related tasks (a conversation / an incident).

a2a-sdk 1.x is **proto-first**: types are protobuf messages, JSON on the wire is camelCase (`supportedInterfaces`),
enums are `TASK_STATE_COMPLETED`. Gotcha: data parts are `google.protobuf.Value`, so **every number is a double**.
`attempts: 0` arrives as `0.0` and an idempotency key `...:0` becomes `...:0.0`. Normalize on both sides
(`restore_ints`) or send ids as strings.
