from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from gdps_qi.types import UploadServerStatus


@dataclass
class UploadResult:
    local_write_ok: bool
    server_status: UploadServerStatus
    status_code: int
    response_body: str
    idempotency_key: str
    stored_path: Optional[str] = None

    @property
    def ack(self) -> bool:
        """True only when server explicitly ACKed upload."""
        return self.server_status is UploadServerStatus.ACK

    def as_dict(self) -> Dict[str, object]:
        return {
            "local_write_ok": self.local_write_ok,
            "server_status": self.server_status.value,
            "ack": self.ack,
            "status_code": self.status_code,
            "response_body": self.response_body,
            "idempotency_key": self.idempotency_key,
            "stored_path": self.stored_path,
        }


@dataclass
class ReportUploader:
    endpoint: str = ""
    pending_dir: str = "logs/quality-inspection/pending_uploads"
    _sent_keys: Dict[str, UploadResult] = field(default_factory=dict)

    def upload_batch(self, records: List[Dict[str, object]], idempotency_key: str) -> UploadResult:
        if idempotency_key in self._sent_keys:
            return self._sent_keys[idempotency_key]
        payload = {
            "idempotency_key": idempotency_key,
            "created_at": time.time(),
            "records": records,
        }
        body = json.dumps(payload, sort_keys=True)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        from pathlib import Path

        pending = Path(self.pending_dir)
        pending.mkdir(parents=True, exist_ok=True)
        path = pending / f"report_{digest}.json"
        try:
            path.write_text(body, encoding="utf-8")
            local_ok = True
        except OSError as exc:
            local_ok = False
            result = UploadResult(
                local_write_ok=False,
                server_status=UploadServerStatus.FAILED,
                status_code=-1,
                response_body=str(exc),
                idempotency_key=idempotency_key,
                stored_path=None,
            )
            self._sent_keys[idempotency_key] = result
            return result
        if not self.endpoint:
            result = UploadResult(
                local_write_ok=local_ok,
                server_status=UploadServerStatus.PENDING,
                status_code=0,
                response_body="no_endpoint_configured",
                idempotency_key=idempotency_key,
                stored_path=str(path),
            )
        else:
            result = UploadResult(
                local_write_ok=local_ok,
                server_status=UploadServerStatus.PENDING,
                status_code=501,
                response_body="endpoint_present_but_client_not_verified",
                idempotency_key=idempotency_key,
                stored_path=str(path),
            )
        self._sent_keys[idempotency_key] = result
        return result
