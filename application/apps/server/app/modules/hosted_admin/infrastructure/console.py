"""Bounded inventory reads and disposable asynchronous observations, never business reads."""

from concurrent.futures import ThreadPoolExecutor
import threading

from app.modules.hosted_admin.application.contracts import AdminError
from app.modules.hosted_admin.application.console import (
    AccessObservation,
    RuntimeObservation,
    RecoveryObservation,
    TunnelObservation,
    DiscrepancyObservation,
    RegisteredOperator,
    ConsoleInventory,
)
from app.modules.hosted_admin.application.qualification import CapacitySnapshot

PAGE_SIZE = 50
REFRESH_SECONDS = 30
STALE_SECONDS = 60
MODELS = {
    "capacity": CapacitySnapshot,
    "tunnel": TunnelObservation,
    "discrepancies": DiscrepancyObservation,
    "access": AccessObservation,
    "runtime": RuntimeObservation,
    "recovery": RecoveryObservation,
}


class ConsoleReads:
    def __init__(self, store, inventory: ConsoleInventory):
        self.store, self.inventory = store, inventory
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="admin-observation")
        self.slots = threading.BoundedSemaphore(8)
        self.lock = threading.Lock()
        self.cache = {}

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def handle(self, request, identity, setups=None):
        if request.method == "console_qualification":
            return self.qualification()
        if request.method == "console_operation":
            return self.operation(request.operation_id, identity)
        records = [RegisteredOperator.model_validate(item) for item in self.inventory.records()]
        if len(records) > 1000 or len({item.key for item in records}) != len(records):
            raise AdminError("admin_inventory_invalid", 503)
        records.sort(key=lambda item: item.key)
        setups = setups or {}
        records = [
            item.model_copy(
                update={"name": setups[item.key]["name"], "setup_id": setups[item.key]["id"]}
            )
            if item.key in setups
            else item
            for item in records
        ]
        if request.method == "console_directory":
            page = records[request.offset : request.offset + PAGE_SIZE]
            return {
                "items": [
                    item.model_dump()
                    | {
                        "access": self.cached("access", item.key),
                        "runtime": self.cached("runtime", item.key),
                        "recovery": self.cached("recovery", item.key),
                    }
                    for item in page
                ],
                "total": len(records),
                "offset": request.offset,
                "next": request.offset + PAGE_SIZE
                if request.offset + PAGE_SIZE < len(records)
                else None,
            }
        if request.instance is not None and request.instance not in {item.key for item in records}:
            raise AdminError("admin_instance_not_found", 404)
        if request.method == "console_record":
            return {
                "items": [item.model_dump() for item in records if item.key == request.instance]
            }
        return self.observation(request.section, request.instance)

    def cached(self, section, instance):
        with self.lock:
            prior = dict(self.cache.get((section, instance), {}))
        state = "unknown" if not prior.get("data") else "available"
        if prior.get("data") and (
            prior.get("failed") or self.store.clock() - prior["observed"] >= STALE_SECONDS
        ):
            state = "stale"
        return prior | {"state": state}

    def observation(self, section, instance):
        key, now = (section, instance), self.store.clock()
        with self.lock:
            prior = self.cache.setdefault(
                key, {"data": None, "observed": None, "attempted": None, "refreshing": False}
            )
            if (
                not prior["refreshing"]
                and (prior["attempted"] is None or now - prior["attempted"] >= REFRESH_SECONDS)
                and self.slots.acquire(blocking=False)
            ):
                prior.update(refreshing=True, attempted=now)
                self.executor.submit(self._collect, key)
            state = "unknown" if prior["data"] is None else "available"
            if prior["data"] is not None and (
                prior.get("failed") or now - prior["observed"] >= STALE_SECONDS
            ):
                state = "stale"
            return dict(prior) | {"state": state}

    def _collect(self, key):
        section, instance = key
        try:
            value = MODELS[section].model_validate(self.inventory.observe(section, instance))
            # Closed projection prevents paths/credentials from reaching the unprivileged listener.
            data = value.model_dump(mode="json")
            if section == "capacity":
                data = {
                    name: data[name]
                    for name in (
                        "environment_hash",
                        "observed",
                        "release",
                        "profile",
                        "memory_total",
                        "memory_committed",
                        "disk_total",
                        "disk_free",
                        "disk_committed",
                        "inventory_clear",
                        "active_count",
                    )
                }
            observed = value.observed if section == "capacity" else self.store.clock()
            if not 0 <= self.store.clock() - observed < STALE_SECONDS:
                raise AdminError("admin_observation_stale", 503)
            with self.lock:
                self.cache[key].update(data=data, observed=observed, failed=False)
        except Exception:
            # Keep the last verified projection, never exception text or private locators.
            with self.lock:
                self.cache[key]["failed"] = True
        finally:
            with self.lock:
                self.cache[key]["refreshing"] = False
            self.slots.release()

    def qualification(self):
        with self.store.transaction() as connection:
            capacity = connection.execute(
                "SELECT ceiling,revision,environment_hash FROM capacity WHERE id=1"
            ).fetchone()
            plans = connection.execute(
                "SELECT id,state,revision,created FROM qualification ORDER BY created DESC,id DESC LIMIT 20"
            ).fetchall()
            evidence = connection.execute(
                "SELECT qualification_id,kind,observed,expires,passed FROM qualification_evidence "
                "WHERE qualification_id IN (SELECT id FROM qualification ORDER BY created DESC,id DESC LIMIT 20) "
                "ORDER BY observed DESC,rowid DESC LIMIT 200"
            ).fetchall()
        return {
            "capacity": dict(capacity) if capacity else None,
            "plans": [dict(row) for row in plans],
            "evidence": [dict(row) for row in evidence],
            "evidence_limit": 200,
        }

    def operation(self, identifier, identity):
        from app.modules.hosted_admin.infrastructure.operations import OperationEngine

        result = OperationEngine(self.store).get(identifier, identity["id"])
        with self.store.transaction() as connection:
            events = connection.execute(
                "SELECT action,recorded FROM operation_audit WHERE operation_id=? ORDER BY sequence DESC LIMIT 100",
                (identifier,),
            ).fetchall()
            row = connection.execute(
                "SELECT identity,payload FROM operation WHERE id=?", (identifier,)
            ).fetchone()
        import json

        payload = json.loads(row["payload"])
        return result | {
            "actor": row["identity"],
            "reason": payload["reason"],
            "events": [dict(row) for row in events],
        }
