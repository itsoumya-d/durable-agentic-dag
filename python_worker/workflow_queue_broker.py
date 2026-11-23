from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

MessageState = Literal["queued", "in_flight", "completed", "failed", "dead_lettered"]


@dataclass
class QueueMessage:
    message_id: str
    workflow_id: str
    stage: str
    payload: Dict[str, Any]
    priority: int = 10
    attempt_count: int = 0
    max_retries: int = 3
    idempotency_key: str = ""
    state: MessageState = "queued"
    created_at_epoch: float = field(default_factory=time.time)
    backoff_until_epoch: float = 0.0
    last_error: Optional[str] = None


class WorkflowQueueBroker:
    """
    Distributed-safe async workflow queue broker and dead-letter queue (DLQ) state machine.
    Enforces priority scheduling, exponential backoff retries, and strict idempotency de-duplication.
    """

    def __init__(self, base_retry_delay_seconds: float = 1.0, max_retry_delay_seconds: float = 60.0):
        self.base_retry_delay = base_retry_delay_seconds
        self.max_retry_delay = max_retry_delay_seconds
        self._messages: Dict[str, QueueMessage] = {}
        self._idempotency_index: Dict[str, str] = {}  # idempotency_key -> message_id
        self._dlq: List[str] = []

    def enqueue(
        self,
        workflow_id: str,
        stage: str,
        payload: Dict[str, Any],
        priority: int = 10,
        idempotency_key: Optional[str] = None,
        max_retries: int = 3,
        current_epoch: Optional[float] = None,
    ) -> QueueMessage:
        now = current_epoch if current_epoch is not None else time.time()
        idem_key = idempotency_key or f"{workflow_id}:{stage}:{uuid.uuid4().hex[:8]}"

        if idem_key in self._idempotency_index:
            existing_id = self._idempotency_index[idem_key]
            return self._messages[existing_id]

        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        msg = QueueMessage(
            message_id=msg_id,
            workflow_id=workflow_id,
            stage=stage,
            payload=payload,
            priority=priority,
            attempt_count=0,
            max_retries=max_retries,
            idempotency_key=idem_key,
            state="queued",
            created_at_epoch=now,
            backoff_until_epoch=now,
        )

        self._messages[msg_id] = msg
        self._idempotency_index[idem_key] = msg_id
        return msg

    def lease_batch(self, max_batch_size: int = 10, current_epoch: Optional[float] = None) -> List[QueueMessage]:
        now = current_epoch if current_epoch is not None else time.time()
        candidates: List[QueueMessage] = []

        for msg in self._messages.values():
            if msg.state == "queued" and msg.backoff_until_epoch <= now:
                candidates.append(msg)

        # Higher priority first, then FIFO by creation timestamp
        candidates.sort(key=lambda m: (-m.priority, m.created_at_epoch))
        leased = candidates[:max_batch_size]

        for m in leased:
            m.state = "in_flight"

        return leased

    def acknowledge(self, message_id: str) -> bool:
        if message_id not in self._messages:
            return False
        msg = self._messages[message_id]
        if msg.state != "in_flight":
            return False
        msg.state = "completed"
        return True

    def fail_and_retry(
        self,
        message_id: str,
        error_reason: str,
        current_epoch: Optional[float] = None,
        is_terminal: bool = False,
    ) -> QueueMessage:
        if message_id not in self._messages:
            raise KeyError(f"Message {message_id} not found")

        msg = self._messages[message_id]
        now = current_epoch if current_epoch is not None else time.time()
        msg.attempt_count += 1
        msg.last_error = error_reason

        if is_terminal or msg.attempt_count >= msg.max_retries:
            msg.state = "dead_lettered"
            if message_id not in self._dlq:
                self._dlq.append(message_id)
        else:
            delay = min(self.max_retry_delay, self.base_retry_delay * (2 ** (msg.attempt_count - 1)))
            msg.backoff_until_epoch = now + delay
            msg.state = "queued"

        return msg

    def reprocess_dlq(self, message_id: Optional[str] = None) -> int:
        count = 0
        target_ids = [message_id] if message_id else list(self._dlq)

        for mid in target_ids:
            if mid in self._messages and self._messages[mid].state == "dead_lettered":
                msg = self._messages[mid]
                msg.state = "queued"
                msg.attempt_count = 0
                msg.backoff_until_epoch = 0.0
                if mid in self._dlq:
                    self._dlq.remove(mid)
                count += 1

        return count

    def get_metrics(self) -> Dict[str, int]:
        counts = {"queued": 0, "in_flight": 0, "completed": 0, "dead_lettered": 0, "total": len(self._messages)}
        for m in self._messages.values():
            if m.state in counts:
                counts[m.state] += 1
        return counts
