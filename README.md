# Kestra FastAPI Wrapper

A FastAPI wrapper around the Kestra SDK for managing Airbyte sync flows — create, update, enable, disable, delete flows, trigger executions, and query execution history.

---

## Environment Variables

Create a `.env` file in the project root with the following variables:

| Variable | Description | Example |
|---|---|---|
| `KESTRA_HOST` | Kestra server URL with port | `http://34.166.177.253:8080` |
| `KESTRA_USERNAME` | Kestra login username | `admin` |
| `KESTRA_PASSWORD` | Kestra login password | `yourpassword` |
| `AIRBYTE_HOST` | Airbyte internal service URL | `http://airbyte-airbyte-server-svc.airbyte.svc.cluster.local:8001` |
| `AIRBYTE_USERNAME` | Airbyte login username | `airbyte` |
| `AIRBYTE_PASSWORD` | Airbyte login password | `yourpassword` |

> **Note:** `AIRBYTE_HOST` is a Kubernetes internal cluster DNS URL. Kestra must be deployed inside the same cluster for this to resolve correctly.

---

## Running the API

```bash
fastapi dev main.py
```

Interactive docs available at `http://127.0.0.1:8000/docs`

---

## Constants

| Constant | Value | Description |
|---|---|---|
| `KESTRA_TENANT` | `"main"` | Fixed tenant for OSS Kestra. Multi-tenancy is an Enterprise feature only. |

---

## Request Schemas

### `CreateFlowRequest`

Used for creating a new flow.

| Field | Type | Required | Validation | Description |
|---|---|---|---|---|
| `flow_id` | `str` | Yes | `^[a-zA-Z0-9][a-zA-Z0-9_.-]*` | Unique flow identifier. No spaces. |
| `namespace` | `str` | Yes | `^[a-z0-9][a-z0-9_.-]*` (lowercase only) | Kestra namespace (maps to tenant ID). |
| `connector_id` | `str` | Yes | `^[a-zA-Z0-9][a-zA-Z0-9_.-]*` | Airbyte connection UUID. |
| `hour` | `int` | Yes | `0–23` | Hour of day (Cairo timezone) to schedule the daily sync. |

---

### `UpdateFlowRequest`

Used for updating the schedule of an existing flow. The `connector_id` is preserved automatically from the existing flow definition.

| Field | Type | Required | Validation | Description |
|---|---|---|---|---|
| `flow_id` | `str` | Yes | `^[a-zA-Z0-9][a-zA-Z0-9_.-]*` | ID of the flow to update. |
| `namespace` | `str` | Yes | Lowercase only | Namespace the flow belongs to. |
| `hour` | `int` | Yes | `0–23` | New hour of day for the schedule. |

---

### `FlowIdentifier`

Used for enable, disable, delete, and execution endpoints.

| Field | Type | Required | Description |
|---|---|---|---|
| `flow_id` | `str` | Yes | ID of the target flow. |
| `namespace` | `str` | Yes | Namespace the flow belongs to. |

---

## Endpoints

### Health

#### `GET /health`
Checks connectivity and authentication to Kestra.

**Response:**
```json
{ "status": "ok", "kestra": "reachable" }
```

**Errors:**
| Code | Reason |
|---|---|
| `503` | Kestra unreachable — connection refused |
| `503` | Kestra unreachable — timed out |
| `503` | Kestra reachable but auth failed |

---

### Flows

#### `POST /flows/create`
Creates a new Kestra flow with an Airbyte sync task and a daily cron schedule.

**Body:** `CreateFlowRequest`

**Response:**
```json
{ "status": "created", "flow": { ... } }
```

---

#### `POST /flows/update`
Updates the cron schedule hour of an existing flow. Automatically preserves the existing `connector_id`.

**Body:** `UpdateFlowRequest`

**Response:**
```json
{ "status": "flow_updated", "flow": { ... } }
```

---

#### `POST /flows/enable`
Enables a disabled flow so it can be triggered.

**Body:** `FlowIdentifier`

**Response:**
```json
{ "status": "flow_enabled", "flow": { ... } }
```

---

#### `POST /flows/disable`
Disables a flow to prevent it from being triggered.

**Body:** `FlowIdentifier`

**Response:**
```json
{ "status": "flow_disabled", "flow": { ... } }
```

---

#### `POST /flows/delete`
Permanently deletes a flow.

**Body:** `FlowIdentifier`

**Response:**
```json
{ "status": "flow_deleted", "flow": { ... } }
```

---

#### `GET /flows/{namespace}`
Lists all flows in a namespace along with their last execution state.

**Path Params:**
| Param | Type | Description |
|---|---|---|
| `namespace` | `str` | Lowercase namespace to query. |

**Response:**
```json
{
  "status": "flows_found",
  "flows": [
    {
      "id": "GA4-SDK-test",
      "updated": "2026-04-20T16:32:55.854419+00:00",
      "last_execution": {
        "id": "6veHibTuUwcEEUGjxs0EhP",
        "state": "SUCCESS",
        "started_at": "2026-04-20T14:00:01.698100Z"
      }
    }
  ]
}
```

> `last_execution` is `null` if the flow has never been executed.

---

### Executions

#### `POST /executions`
Triggers a manual execution of a flow. Automatically checks for concurrent running executions and skips if one is already active (Airbyte connections cannot be synced concurrently).

**Body:** `FlowIdentifier`

**Response (triggered):**
```json
{ "status": "execution_started", "execution": { ... } }
```

**Response (skipped — concurrent execution):**
```json
{
  "status": "skipped",
  "reason": "A concurrent execution is already running",
  "execution_id": "6veHibTuUwcEEUGjxs0EhP",
  "started_at": "2026-04-20T14:00:01.698100Z"
}
```

---

#### `GET /executions/{namespace}/{flow_id}`
Returns paginated execution history for a specific flow.

**Path Params:**
| Param | Type | Description |
|---|---|---|
| `namespace` | `str` | Lowercase namespace. |
| `flow_id` | `str` | Flow ID to query. |

**Query Params:**
| Param | Type | Default | Description |
|---|---|---|---|
| `page` | `int` | `1` | Page number. |
| `size` | `int` | `10` | Results per page. |

**Response:**
```json
{
  "status": "ok",
  "total": 42,
  "page": 1,
  "size": 10,
  "executions": [
    {
      "id": "6veHibTuUwcEEUGjxs0EhP",
      "state": "SUCCESS",
      "started_at": "2026-04-20T14:00:01.698100Z"
    }
  ]
}
```

---

## Error Handling

All endpoints use a centralized `handle_kestra_exception()` function that maps Kestra SDK exceptions to appropriate HTTP responses.

| HTTP Code | Condition |
|---|---|
| `401` | Invalid Kestra credentials |
| `404` | Flow or namespace not found |
| `409` | Flow already exists (on create) |
| `409` | Flow is already enabled/disabled |
| `409` | Flow is disabled — cannot execute |
| `409` | Airbyte connection is inactive |
| `409` | Concurrent execution already running (skipped, not an error) |
| `422` | Invalid flow definition (bad YAML, wrong task type, etc.) |
| `500` | Unexpected error |

### Validation Rules

Input validation happens at the request model level before any call is made to Kestra:

- `flow_id` and `connector_id` must match `^[a-zA-Z0-9][a-zA-Z0-9_.-]*` — no spaces, no special characters
- `namespace` must match `^[a-z0-9][a-z0-9_.-]*` — lowercase only
- `hour` must be an integer between `0` and `23`

---

## Flow Definition Template

Every created flow follows this YAML structure:

```yaml
id: {flow_id}
namespace: {namespace}

tasks:
  - id: sync
    type: io.kestra.plugin.airbyte.connections.Sync
    url: {AIRBYTE_HOST}
    connectionId: {connector_id}
    username: {AIRBYTE_USERNAME}
    password: {AIRBYTE_PASSWORD}

triggers:
  - id: daily_schedule
    type: io.kestra.plugin.core.trigger.Schedule
    cron: "0 {hour} * * *"
    timezone: Africa/Cairo
```
