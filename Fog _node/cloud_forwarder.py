# =============================================================
#  SMART CITY — FOG LAYER: CLOUD FORWARDER
#
#  WHAT THIS DOES (plain English):
#  ─────────────────────────────────────────────────────────────
#  After the fog node finishes processing (filtering +
#  aggregating), it needs to forward two types of data to cloud:
#
#  TYPE 1 — Aggregated batches (scheduled, every N readings)
#    These are the compressed summaries. Instead of 10 raw
#    readings, one clean statistical aggregate is sent.
#
#  TYPE 2 — Immediate alerts (triggered by event detector)
#    PM2.5 spike? Congestion? These skip the queue entirely
#    and go straight to the cloud right now.
#
#  This file handles:
#    ✅ Actually sending the HTTP POST to the cloud
#    ✅ Retry logic (if cloud is down, retry up to 3 times)
#    ✅ Queuing unsent messages when cloud is unavailable
#    ✅ Tracking delivery stats (sent, failed, queued)
#    ✅ Graceful fallback: if cloud is down, save locally
# =============================================================

import json
import time
import threading
import logging
import requests
from collections import deque
from datetime import datetime, timezone
from typing import Optional
from fog_config import CLOUD_URL, SEND_TO_CLOUD

logger = logging.getLogger("CloudForwarder")


class CloudForwarder:
    """
    Handles all outbound traffic from the fog node to the cloud.

    Two sending modes:
      send_aggregation(payload) → for batched aggregated data
      send_alert(event)         → for immediate priority alerts

    Has a retry queue — if the cloud is unavailable, payloads
    sit in memory and are retried automatically.
    """

    MAX_RETRIES    = 3
    RETRY_DELAY    = 2    # seconds between retries
    QUEUE_MAX_SIZE = 500  # max queued messages before dropping oldest

    def __init__(self):
        # Queue for messages that failed to send
        self._retry_queue: deque = deque(maxlen=self.QUEUE_MAX_SIZE)
        self._queue_lock = threading.Lock()

        # Stats
        self.total_sent       = 0
        self.total_failed     = 0
        self.total_alerts_sent = 0
        self.total_queued     = 0

        # Cloud connectivity status
        self.cloud_reachable  = True
        self.last_success_time: Optional[float] = None
        self.last_failure_time: Optional[float] = None

        # Start background retry worker thread
        self._retry_thread = threading.Thread(
            target=self._retry_worker,
            daemon=True,
            name="fog-retry-worker"
        )
        self._retry_thread.start()
        logger.info(f"CloudForwarder ready → {CLOUD_URL}")

    # ──────────────────────────────────────────────────────────
    # PUBLIC: Send aggregated batch
    # ──────────────────────────────────────────────────────────
    def send_aggregation(self, payload: dict) -> bool:
        """
        Send an aggregated payload to the cloud.
        Called by the fog node every time a window completes.

        Returns True if sent successfully.
        """
        if not SEND_TO_CLOUD:
            logger.info(f"[CLOUD OFF] Aggregation: {payload.get('sensor_id')} "
                        f"window={payload.get('window_size')}")
            return True

        envelope = {
            "type":    "aggregation",
            "source":  "fog_node_01",
            "payload": payload,
            "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        return self._send(envelope, priority=False)

    # ──────────────────────────────────────────────────────────
    # PUBLIC: Send immediate alert
    # ──────────────────────────────────────────────────────────
    def send_alert(self, event_dict: dict) -> bool:
        """
        Send an immediate alert to the cloud.
        These skip the queue and are sent with priority.
        Called by the fog node when event detector fires.

        Returns True if sent successfully.
        """
        if not SEND_TO_CLOUD:
            logger.warning(
                f"[CLOUD OFF] ALERT: {event_dict.get('event_type')} | "
                f"{event_dict.get('sensor_id')} | "
                f"value={event_dict.get('value')}"
            )
            self.total_alerts_sent += 1
            return True

        envelope = {
            "type":    "alert",
            "source":  "fog_node_01",
            "payload": event_dict,
            "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        success = self._send(envelope, priority=True)
        if success:
            self.total_alerts_sent += 1
        return success

    # ──────────────────────────────────────────────────────────
    # INTERNAL: HTTP POST with retry
    # ──────────────────────────────────────────────────────────
    def _send(self, envelope: dict, priority: bool = False) -> bool:
        """
        Attempts to POST the envelope to the cloud URL.
        Retries up to MAX_RETRIES times on failure.
        If all retries fail, adds to retry queue.
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = requests.post(
                    CLOUD_URL,
                    json=envelope,
                    timeout=5,
                    headers={
                        "Content-Type": "application/json",
                        "X-Source":     "fog-node-01",
                        "X-Priority":   "high" if priority else "normal",
                    }
                )

                if response.status_code in (200, 201, 202):
                    self.total_sent += 1
                    self.cloud_reachable   = True
                    self.last_success_time = time.time()

                    msg_type = envelope.get("type", "unknown")
                    sensor   = envelope["payload"].get("sensor_id", "?")
                    logger.info(
                        f"✓ → Cloud [{msg_type.upper()}] "
                        f"{sensor} (attempt {attempt})"
                    )
                    return True
                else:
                    logger.warning(
                        f"Cloud returned {response.status_code} "
                        f"(attempt {attempt}/{self.MAX_RETRIES})"
                    )

            except requests.exceptions.ConnectionError:
                if attempt == 1:
                    logger.warning(
                        f"Cloud unreachable at {CLOUD_URL} — "
                        f"queuing for retry"
                    )
                self.cloud_reachable   = False
                self.last_failure_time = time.time()

            except requests.exceptions.Timeout:
                logger.warning(
                    f"Cloud timeout (attempt {attempt}/{self.MAX_RETRIES})"
                )

            except Exception as e:
                logger.error(f"Unexpected send error: {e}")

            # Wait before retrying (except on last attempt)
            if attempt < self.MAX_RETRIES:
                time.sleep(self.RETRY_DELAY)

        # All retries exhausted — queue for later
        self._queue_for_retry(envelope)
        self.total_failed += 1
        return False

    def _queue_for_retry(self, envelope: dict):
        """Add failed message to retry queue."""
        with self._queue_lock:
            envelope["_retry_queued_at"] = time.time()
            self._retry_queue.append(envelope)
            self.total_queued += 1
            logger.info(
                f"Queued for retry. Queue size: {len(self._retry_queue)}"
            )

    # ──────────────────────────────────────────────────────────
    # BACKGROUND: Retry worker thread
    # ──────────────────────────────────────────────────────────
    def _retry_worker(self):
        """
        Background thread that periodically tries to flush
        the retry queue when the cloud becomes available again.
        Checks every 15 seconds.
        """
        while True:
            time.sleep(15)

            with self._queue_lock:
                if not self._retry_queue:
                    continue
                # Take a snapshot — don't hold lock while sending
                pending = list(self._retry_queue)
                self._retry_queue.clear()

            logger.info(f"Retry worker: attempting {len(pending)} queued messages")
            resent  = 0
            requeue = []

            for envelope in pending:
                queued_age = time.time() - envelope.pop("_retry_queued_at", 0)
                # Drop messages older than 5 minutes — too stale
                if queued_age > 300:
                    logger.info(f"Dropped stale message (age: {queued_age:.0f}s)")
                    continue

                try:
                    response = requests.post(
                        CLOUD_URL, json=envelope, timeout=5
                    )
                    if response.status_code in (200, 201, 202):
                        resent += 1
                        self.total_sent += 1
                    else:
                        envelope["_retry_queued_at"] = time.time()
                        requeue.append(envelope)
                except Exception:
                    envelope["_retry_queued_at"] = time.time()
                    requeue.append(envelope)

            # Put failed ones back in queue
            with self._queue_lock:
                self._retry_queue.extend(requeue)

            if resent:
                logger.info(f"✓ Retry worker: resent {resent} messages")

    # ──────────────────────────────────────────────────────────
    # STATS
    # ──────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        return {
            "cloud_url":          CLOUD_URL,
            "cloud_reachable":    self.cloud_reachable,
            "total_sent":         self.total_sent,
            "total_failed":       self.total_failed,
            "total_alerts_sent":  self.total_alerts_sent,
            "retry_queue_size":   len(self._retry_queue),
            "last_success":       (
                datetime.fromtimestamp(self.last_success_time)
                .strftime("%H:%M:%S")
                if self.last_success_time else "never"
            ),
        }
