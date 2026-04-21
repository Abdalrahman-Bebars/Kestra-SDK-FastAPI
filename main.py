from kestrapy import KestraClient, Configuration
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv
from kestrapy.exceptions import (
    UnauthorizedException,
    NotFoundException,
    UnprocessableEntityException,
    ApiException
)
import os
import re
import requests

load_dotenv()

# --- Configuration ---
configuration = Configuration()
configuration.host = os.getenv("KESTRA_HOST")
configuration.username = os.getenv("KESTRA_USERNAME")
configuration.password = os.getenv("KESTRA_PASSWORD")

client = KestraClient(configuration)
KESTRA_TENANT = "main"

app = FastAPI()


# --- Request Models ---
class CreateFlowRequest(BaseModel):
    flow_id: str
    namespace: str
    connector_id: str
    hour: int
    # cron is fixed in this example, but could be made dynamic if needed

    @field_validator("flow_id", "namespace", "connector_id", "hour")
    @classmethod
    def valid_kestra_id(cls, v, info):
        if info.field_name == "namespace":
            if not re.match(r'^[a-z0-9][a-z0-9_.\-]*$', v):
                raise ValueError("Namespace must be lowercase: ^[a-z0-9][a-z0-9_.-]*")
        
        elif info.field_name == "hour":
            if not (0 <= v <= 23):
                raise ValueError("Hour must be between 0 and 23")

        else:
            if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$', v):
                raise ValueError("Must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]* (no spaces or special characters)")
        return v

class UpdateFlowRequest(BaseModel):
    flow_id: str
    namespace: str
    hour: int
    @field_validator("flow_id", "namespace", "hour")
    @classmethod
    def valid_kestra_id(cls, v, info):
        if info.field_name == "namespace":
            if not re.match(r'^[a-z0-9][a-z0-9_.\-]*$', v):
                raise ValueError("Namespace must be lowercase: ^[a-z0-9][a-z0-9_.-]*")
        elif info.field_name == "hour":
            if not (0 <= v <= 23):
                raise ValueError("Hour must be between 0 and 23")
        else:
            if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$', v):
                raise ValueError("Must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]* (no spaces or special characters)")
        return v

class FlowIdentifier(BaseModel):
    flow_id: str
    namespace: str

    @classmethod
    def valid_kestra_id(cls, v, info):
        if info.field_name == "namespace":
            if not re.match(r'^[a-z0-9][a-z0-9_.\-]*$', v):
                raise ValueError("Namespace must be lowercase: ^[a-z0-9][a-z0-9_.-]*")
        else:
            if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$', v):
                raise ValueError("Must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]* (no spaces or special characters)")
        return v


# --- Exception Handler ---
def handle_kestra_exception(e: Exception, context: str = ""):
    if isinstance(e, UnauthorizedException):
        raise HTTPException(status_code=401, detail="Kestra auth failed — check credentials")

    if isinstance(e, NotFoundException):
        raise HTTPException(status_code=404, detail="Flow or namespace not found")

    # Catch 409 Illegal State explicitly
    if isinstance(e, ApiException) and e.status == 409:
        body = str(e).lower()
        if "disabled" in body:
            raise HTTPException(status_code=409, detail="Flow is disabled — enable it before executing")
        if "already exists" in body:
            raise HTTPException(status_code=409, detail="Flow already exists — use /flows/update to modify it")
        if "already enabled" in body:
            raise HTTPException(status_code=409, detail="Flow is already enabled")
        if "already disabled" in body:
            raise HTTPException(status_code=409, detail="Flow is already disabled")
        raise HTTPException(status_code=409, detail=f"Illegal state: {e}")

    if isinstance(e, UnprocessableEntityException):
        body = str(e).lower()

        if context == "create":
            if "already exists" in body:
                raise HTTPException(status_code=409, detail="Flow already exists — use /flows/update to modify it")
            raise HTTPException(status_code=422, detail=f"Invalid flow definition: {e}")

        if context == "update":
            if "not found" in body:
                raise HTTPException(status_code=404, detail="Flow not found — use /flows to create it first")
            raise HTTPException(status_code=422, detail=f"Invalid flow definition: {e}")

        if context == "enable":
            if "already enabled" in body or "enabled" in body:
                raise HTTPException(status_code=409, detail="Flow is already enabled")
            if "not found" in body:
                raise HTTPException(status_code=404, detail="Flow not found")
            raise HTTPException(status_code=422, detail=f"Cannot enable flow: {e}")

        if context == "disable":
            if "already disabled" in body or "disabled" in body:
                raise HTTPException(status_code=409, detail="Flow is already disabled")
            if "not found" in body:
                raise HTTPException(status_code=404, detail="Flow not found")
            raise HTTPException(status_code=422, detail=f"Cannot disable flow: {e}")

        if context == "delete":
            if "not found" in body:
                raise HTTPException(status_code=404, detail="Flow not found — already deleted?")
            raise HTTPException(status_code=422, detail=f"Cannot delete flow: {e}")

        if context == "execute":
            if "not found" in body:
                raise HTTPException(status_code=404, detail="Flow not found — create it first")
            if "disabled" in body:
                raise HTTPException(status_code=409, detail="Flow is disabled — enable it before executing")
            raise HTTPException(status_code=422, detail=f"Cannot execute flow: {e}")

        raise HTTPException(status_code=422, detail=f"Unprocessable entity: {e}")

    raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


# --- Health Check ---

@app.get("/health")
def health():
    try:
        host = os.getenv("KESTRA_HOST")
        response = requests.get(
            f"{host}/api/v1/flows",
            auth=(os.getenv("KESTRA_USERNAME"), os.getenv("KESTRA_PASSWORD")),
            timeout=5
        )
        if response.status_code == 401:
            raise HTTPException(status_code=503, detail="Kestra reachable but auth failed")
        return {"status": "ok", "kestra": "reachable"}
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Kestra unreachable — connection refused")
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=503, detail="Kestra unreachable — timed out")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Unexpected error: {e}")


# --- Endpoints ---
@app.post("/flows/create")
def create_flow(request: CreateFlowRequest):
    body = f"""id: {request.flow_id}
namespace: {request.namespace}

tasks:
  - id: sync
    type: io.kestra.plugin.airbyte.connections.Sync
    url: {os.getenv("AIRBYTE_HOST")}
    connectionId: {request.connector_id}
    username: {os.getenv("AIRBYTE_USERNAME")}
    password: {os.getenv("AIRBYTE_PASSWORD")}

triggers:
  - id: daily_schedule
    type: io.kestra.plugin.core.trigger.Schedule
    cron: "0 {request.hour} * * *"
    timezone: Africa/Cairo
"""
    try:
        api_response = client.flows.create_flow(KESTRA_TENANT, body)
        return {"status": "created", "flow": api_response}
    except Exception as e:
        handle_kestra_exception(e, context="create")


@app.post("/flows/update")
def update_flow(request: UpdateFlowRequest):
    try:
        # Fetch existing flow to extract connector_id
        existing = client.flows.flow(
            tenant=KESTRA_TENANT,
            namespace=request.namespace,
            id=request.flow_id,
            source=True,
            allow_deleted=False
        )

        # Parse connector_id from existing flow source
        import yaml
        flow_dict = yaml.safe_load(existing.source)
        connector_id = flow_dict["tasks"][0]["connectionId"]

    except Exception as e:
        handle_kestra_exception(e, context="update")

    body = f"""id: {request.flow_id}
namespace: {request.namespace}

tasks:
  - id: sync
    type: io.kestra.plugin.airbyte.connections.Sync
    url: {os.getenv("AIRBYTE_HOST")}
    connectionId: {connector_id}
    username: {os.getenv("AIRBYTE_USERNAME")}
    password: {os.getenv("AIRBYTE_PASSWORD")}

triggers:
  - id: daily_schedule
    type: io.kestra.plugin.core.trigger.Schedule
    cron: "0 {request.hour} * * *"
    timezone: Africa/Cairo
"""
    try:
        api_response = client.flows.update_flow(
            tenant=KESTRA_TENANT,
            namespace=request.namespace,
            id=request.flow_id,
            body=body
        )
        return {"status": "flow_updated", "flow": api_response}
    except Exception as e:
        handle_kestra_exception(e, context="update")


@app.post("/flows/enable")
def enable_flow(request: FlowIdentifier):
    try:
        api_response = client.flows.enable_flows_by_ids(
            tenant=KESTRA_TENANT,
            id_with_namespace=[{"id": request.flow_id, "namespace": request.namespace}]
        )
        return {"status": "flow_enabled", "flow": api_response}
    except Exception as e:
        handle_kestra_exception(e, context="enable")


@app.post("/flows/disable")
def disable_flow(request: FlowIdentifier):
    try:
        api_response = client.flows.disable_flows_by_ids(
            tenant=KESTRA_TENANT,
            id_with_namespace=[{"id": request.flow_id, "namespace": request.namespace}]
        )
        return {"status": "flow_disabled", "flow": api_response}
    except Exception as e:
        handle_kestra_exception(e, context="disable")


@app.post("/flows/delete")
def delete_flow(request: FlowIdentifier):
    try:
        api_response = client.flows.delete_flows_by_ids(
            tenant=KESTRA_TENANT,
            id_with_namespace=[{"id": request.flow_id, "namespace": request.namespace}]
        )
        return {"status": "flow_deleted", "flow": api_response}
    except Exception as e:
        handle_kestra_exception(e, context="delete")


@app.post("/executions")
def create_execution(request: FlowIdentifier):
    try:
        # Prevent concurrent executions by checking for active states
        running = client.executions.search_executions_by_flow_id(
            tenant=KESTRA_TENANT,
            namespace=request.namespace,
            flow_id=request.flow_id,
            page=1,
            size=10
        )

        active_states = {"RUNNING", "CREATED", "RESTARTED"}
        active_executions = [
            r for r in (running.results or [])
            if r.state.current in active_states
        ]

        if active_executions:
            active = active_executions[0]
            history = active.state.histories[0] if active.state.histories else None
            return {
                "status": "skipped",
                "reason": "A concurrent execution is already running",
                "execution_id": active.id,
                "started_at": history.var_date if history else None
        }

        # Safe to trigger
        api_response = client.executions.create_execution(
            namespace=request.namespace,
            id=request.flow_id,
            tenant=KESTRA_TENANT,
            wait=False
        )
        return {"status": "execution_started", "execution": api_response}
    
    except Exception as e:
        handle_kestra_exception(e, context="execute")


import requests

@app.get("/flows/{namespace}")
def get_flows_by_namespace(namespace: str):
    if not re.match(r'^[a-z0-9][a-z0-9_.\-]*$', namespace):
        raise HTTPException(status_code=422, detail="Namespace must be lowercase: ^[a-z0-9][a-z0-9_.-]*")
    
    host = os.getenv("KESTRA_HOST")
    auth = (os.getenv("KESTRA_USERNAME"), os.getenv("KESTRA_PASSWORD"))

    try:
        api_response = client.flows.list_flows_by_namespace(
            tenant=KESTRA_TENANT,
            namespace=namespace
        )
        flows = []
        for flow in (api_response or []):
            last_execution = None
            try:
                resp = requests.get(
                    f"{host}/api/v1/{KESTRA_TENANT}/executions",
                    params={
                        "namespace": namespace,
                        "flowId": flow.id,
                        "page": 1,
                        "size": 10,  # fetch more, sort ourselves
                    },
                    auth=auth,
                    timeout=5
                )
                data = resp.json()
                if data.get("results"):
                    # Sort by startDate descending and take the last one
                    sorted_execs = sorted(
                        data["results"],
                        key=lambda x: x["state"].get("startDate", ""),
                        reverse=True
                    )
                    last = sorted_execs[0]
                    last_execution = {
                        "id": last["id"],
                        "state": last["state"]["current"],
                        "started_at": last["state"]["startDate"],
                    }
            except Exception:
                pass

            flows.append({
                "id": flow.id,
                "updated": flow.updated.isoformat() if flow.updated else None,
                "last_execution": last_execution
            })

        return {"status": "flows_found", "flows": flows}
    except Exception as e:
        handle_kestra_exception(e, context="get_flows_by_namespace")


@app.get("/executions/{namespace}/{flow_id}")
def get_execution_history(namespace: str, flow_id: str, page: int = 1, size: int = 10):
    if not re.match(r'^[a-z0-9][a-z0-9_.\-]*$', namespace):
        raise HTTPException(status_code=422, detail="Namespace must be lowercase")
    try:
        api_response = client.executions.search_executions_by_flow_id(
            tenant=KESTRA_TENANT,
            namespace=namespace,
            flow_id=flow_id,
            page=page,
            size=size
        )
        executions = [
            {
                "id": exc.id,
                "state": exc.state.current,
                "started_at": exc.state.histories[0].var_date if exc.state.histories else None,
            }
            for exc in (api_response.results or [])
        ]
        return {
            "status": "ok",
            "total": api_response.total,
            "page": page,
            "size": size,
            "executions": executions
        }
    except Exception as e:
        handle_kestra_exception(e, context="execute")