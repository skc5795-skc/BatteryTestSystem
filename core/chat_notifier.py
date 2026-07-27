"""
Google Chat notification service for the Battery Test System.

The webhook URL and station settings are stored in core.config.
"""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from core.config import (
    APP_NAME,
    GOOGLE_CHAT_NOTIFICATIONS_ENABLED,
    GOOGLE_CHAT_STATION_NAME,
    GOOGLE_CHAT_TIMEOUT_SECONDS,
    GOOGLE_CHAT_WEBHOOK_URL,
)


SSL_CONTEXT = ssl.create_default_context(
    cafile=certifi.where()
)


@dataclass(frozen=True)
class ChatNotificationResult:
    success: bool
    skipped: bool = False
    error: str = ""


class GoogleChatNotifier:
    """Send Google Chat messages when battery tests start and finish."""

    def __init__(self):
        self.reset()

    def reset(self, build_id: str = ""):
        """Prepare the notifier for a new battery test."""
        self.build_id = (build_id or "").strip()
        self._start_sent = False
        self._finish_sent = False
        self._sending = False

    @staticmethod
    def _value(obj, name: str, default=""):
        try:
            value = getattr(obj, name, default)
        except Exception:
            return default
        return default if value is None else value

    @staticmethod
    def _enum_text(value, default: str = "") -> str:
        if value is None:
            return default
        return str(getattr(value, "value", value) or default)

    @staticmethod
    def _number(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _format_time(timestamp) -> str:
        try:
            if timestamp is not None:
                return datetime.fromtimestamp(
                    float(timestamp)
                ).strftime("%Y-%m-%d %I:%M:%S %p")
        except (TypeError, ValueError, OSError):
            pass

        return datetime.now().strftime(
            "%Y-%m-%d %I:%M:%S %p"
        )

    @staticmethod
    def _webhook_url() -> str:
        return (GOOGLE_CHAT_WEBHOOK_URL or "").strip()

    def _post_text(self, text: str) -> ChatNotificationResult:
        """POST a text message to the configured Google Chat webhook."""
        if not GOOGLE_CHAT_NOTIFICATIONS_ENABLED:
            return ChatNotificationResult(
                success=True,
                skipped=True,
            )

        webhook_url = self._webhook_url()
        if not webhook_url:
            return ChatNotificationResult(
                success=True,
                skipped=True,
            )

        if self._sending:
            return ChatNotificationResult(
                success=False,
                skipped=True,
                error="A notification is already being sent.",
            )

        payload = {"text": text}
        request = Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=UTF-8",
            },
            method="POST",
        )

        self._sending = True
        try:
            with urlopen(
                request,
                timeout=float(
                    GOOGLE_CHAT_TIMEOUT_SECONDS
                ),
                context=SSL_CONTEXT,
            ) as response:
                status = getattr(response, "status", 200)
                if not 200 <= int(status) < 300:
                    raise RuntimeError(
                        f"Google Chat returned HTTP {status}."
                    )

            return ChatNotificationResult(success=True)

        except HTTPError as exc:
            try:
                details = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )
            except Exception:
                details = ""

            error = f"HTTP {exc.code}: {exc.reason}"
            if details:
                error += f" — {details[:300]}"

            return ChatNotificationResult(
                success=False,
                error=error,
            )

        except URLError as exc:
            return ChatNotificationResult(
                success=False,
                error=f"Network error: {exc.reason}",
            )

        except Exception as exc:
            return ChatNotificationResult(
                success=False,
                error=str(exc),
            )

        finally:
            self._sending = False

    def send_test_started(
        self,
        session,
        *,
        force: bool = False,
    ) -> ChatNotificationResult:
        """Notify Google Chat immediately after a test starts."""
        if session is None:
            return ChatNotificationResult(
                success=False,
                error="No test session is available.",
            )

        if self._start_sent and not force:
            return ChatNotificationResult(
                success=True,
                skipped=True,
            )

        serial = str(
            self._value(
                session,
                "serial_number",
                "",
            )
            or "Unknown"
        )
        start_time = self._format_time(
            self._value(
                session,
                "start_time",
                None,
            )
        )

        message = "\n".join(
            [
                "🟢 *Battery Test Started*",
                "",
                f"*Battery SN:* {serial}",
                f"*Test Started At:* {start_time}",
            ]
        )

        result = self._post_text(message)
        if result.success and not result.skipped:
            self._start_sent = True

        return result

    def send_test_finished(
        self,
        session,
        *,
        report_saved: bool,
        report_folder: str = "",
        force: bool = False,
    ) -> ChatNotificationResult:
        """Notify Google Chat after the test stops and reports are saved."""
        if session is None:
            return ChatNotificationResult(
                success=False,
                error="No test session is available.",
            )

        if self._finish_sent and not force:
            return ChatNotificationResult(
                success=True,
                skipped=True,
            )

        serial = str(
            self._value(
                session,
                "serial_number",
                "",
            )
            or "Unknown"
        )
        measured_ah = self._number(
            self._value(
                session,
                "calculated_capacity_ah",
                0.0,
            )
        )
        test_result = self._enum_text(
            self._value(
                session,
                "result",
                None,
            ),
            "UNKNOWN",
        )

        if report_saved:
            reports_text = "CSV and PDF reports saved"
        else:
            reports_text = "CSV/PDF report save failed"

        message = "\n".join(
            [
                "✅ *Battery Test Finished*",
                "",
                f"*Battery SN:* {serial}",
                (
                    "*Measured Capacity:* "
                    f"{measured_ah:.2f} Ah"
                ),
                f"*Test Result:* {test_result}",
                f"*Reports:* {reports_text}",
            ]
        )

        result = self._post_text(message)
        if result.success and not result.skipped:
            self._finish_sent = True

        return result

    def send_test_message(self) -> ChatNotificationResult:
        """Send a simple message to verify the configured webhook."""
        message = "\n".join(
            [
                "✅ *Battery Test System webhook connected*",
                "",
                f"*Station:* {GOOGLE_CHAT_STATION_NAME}",
                f"*Application:* {APP_NAME}",
            ]
        )
        return self._post_text(message)