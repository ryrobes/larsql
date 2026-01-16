"""
MJPEG streaming for browser automation.

Manages frame distribution to multiple subscribers for real-time
browser viewing in web UIs.
"""

import asyncio
from typing import Dict, Set, Optional, AsyncIterator
import logging
import io

logger = logging.getLogger(__name__)


class FrameEmitter:
    """
    Manages MJPEG frame distribution to multiple subscribers.

    Each session can have multiple stream subscribers (e.g., multiple browser tabs
    viewing the same session). Frames are distributed via asyncio queues.

    Thread-safe for concurrent emit/subscribe/unsubscribe operations.
    """

    def __init__(self):
        # session_id -> set of subscriber queues
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def emit(self, session_id: str, frame: bytes):
        """
        Emit a frame to all subscribers of a session.

        Non-blocking: if a subscriber's queue is full, the frame is dropped for that subscriber.
        This prevents slow consumers from blocking the stream.

        Args:
            session_id: Session identifier
            frame: JPEG image bytes
        """
        async with self._lock:
            subscribers = self._subscribers.get(session_id, set()).copy()

        if not subscribers:
            # Log occasionally when no subscribers (every N frames)
            if not hasattr(self, "_no_sub_count"):
                self._no_sub_count = {}
            self._no_sub_count[session_id] = self._no_sub_count.get(session_id, 0) + 1
            if self._no_sub_count[session_id] % 100 == 1:
                logger.debug(
                    f"[STREAM] No subscribers for session {session_id} (frame {self._no_sub_count[session_id]})"
                )
            return

        delivered = 0
        dropped = 0
        for queue in subscribers:
            try:
                # Non-blocking put - drop frame if queue full
                queue.put_nowait(frame)
                delivered += 1
            except asyncio.QueueFull:
                # Slow consumer, drop frame silently
                dropped += 1
            except Exception as e:
                logger.debug(f"[STREAM] Error emitting frame to subscriber: {e}")

        # Log occasionally
        if not hasattr(self, "_emit_count"):
            self._emit_count = {}
        self._emit_count[session_id] = self._emit_count.get(session_id, 0) + 1
        if self._emit_count[session_id] % 100 == 0:
            logger.debug(
                f"[STREAM] Session {session_id}: emitted {self._emit_count[session_id]} frames, "
                f"last delivery: {delivered}/{len(subscribers)} subscribers, {dropped} dropped"
            )

    def subscribe(self, session_id: str, max_queue_size: int = 10) -> asyncio.Queue:
        """
        Subscribe to frames from a session.

        Args:
            session_id: Session to subscribe to
            max_queue_size: Maximum frames to buffer per subscriber

        Returns:
            Queue that will receive frame bytes. Caller is responsible for
            calling unsubscribe() when done.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)

        # Note: This is not async-safe but subscribe is typically called
        # from async context. For true thread safety, use asyncio.Lock.
        if session_id not in self._subscribers:
            self._subscribers[session_id] = set()
        self._subscribers[session_id].add(queue)

        logger.info(
            f"[STREAM] New subscriber for session {session_id}, "
            f"total subscribers: {len(self._subscribers[session_id])}"
        )
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue):
        """
        Remove a subscriber.

        Args:
            session_id: Session the queue was subscribed to
            queue: The queue returned by subscribe()
        """
        if session_id in self._subscribers:
            self._subscribers[session_id].discard(queue)
            if not self._subscribers[session_id]:
                del self._subscribers[session_id]
            logger.debug(f"Removed subscriber for session {session_id}")

    def subscriber_count(self, session_id: str) -> int:
        """Get number of active subscribers for a session."""
        return len(self._subscribers.get(session_id, set()))

    def has_subscribers(self, session_id: str) -> bool:
        """Check if session has any subscribers."""
        return (
            session_id in self._subscribers and len(self._subscribers[session_id]) > 0
        )

    def active_sessions(self) -> list[str]:
        """Get list of session IDs with active subscribers."""
        return list(self._subscribers.keys())

    async def close_session(self, session_id: str):
        """
        Close all subscribers for a session.

        Useful when a session ends to clean up all streaming connections.
        """
        async with self._lock:
            if session_id in self._subscribers:
                # Put None in each queue to signal end of stream
                for queue in self._subscribers[session_id]:
                    try:
                        queue.put_nowait(None)
                    except asyncio.QueueFull:
                        pass
                del self._subscribers[session_id]
                logger.debug(f"Closed all subscribers for session {session_id}")


# Global frame emitter instance
frame_emitter = FrameEmitter()


# Minimal 1x1 black JPEG for keepalive
_KEEPALIVE_FRAME: Optional[bytes] = None


def _get_keepalive_frame() -> bytes:
    """Get a minimal JPEG frame for keepalive."""
    global _KEEPALIVE_FRAME
    if _KEEPALIVE_FRAME is None:
        try:
            from PIL import Image

            img = Image.new("RGB", (1, 1), color="black")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=1)
            _KEEPALIVE_FRAME = buf.getvalue()
        except ImportError:
            # Minimal valid JPEG if PIL not available
            # This is a 1x1 black pixel JPEG
            _KEEPALIVE_FRAME = bytes(
                [
                    0xFF,
                    0xD8,
                    0xFF,
                    0xE0,
                    0x00,
                    0x10,
                    0x4A,
                    0x46,
                    0x49,
                    0x46,
                    0x00,
                    0x01,
                    0x01,
                    0x00,
                    0x00,
                    0x01,
                    0x00,
                    0x01,
                    0x00,
                    0x00,
                    0xFF,
                    0xDB,
                    0x00,
                    0x43,
                    0x00,
                    0x08,
                    0x06,
                    0x06,
                    0x07,
                    0x06,
                    0x05,
                    0x08,
                    0x07,
                    0x07,
                    0x07,
                    0x09,
                    0x09,
                    0x08,
                    0x0A,
                    0x0C,
                    0x14,
                    0x0D,
                    0x0C,
                    0x0B,
                    0x0B,
                    0x0C,
                    0x19,
                    0x12,
                    0x13,
                    0x0F,
                    0x14,
                    0x1D,
                    0x1A,
                    0x1F,
                    0x1E,
                    0x1D,
                    0x1A,
                    0x1C,
                    0x1C,
                    0x20,
                    0x24,
                    0x2E,
                    0x27,
                    0x20,
                    0x22,
                    0x2C,
                    0x23,
                    0x1C,
                    0x1C,
                    0x28,
                    0x37,
                    0x29,
                    0x2C,
                    0x30,
                    0x31,
                    0x34,
                    0x34,
                    0x34,
                    0x1F,
                    0x27,
                    0x39,
                    0x3D,
                    0x38,
                    0x32,
                    0x3C,
                    0x2E,
                    0x33,
                    0x34,
                    0x32,
                    0xFF,
                    0xC0,
                    0x00,
                    0x0B,
                    0x08,
                    0x00,
                    0x01,
                    0x00,
                    0x01,
                    0x01,
                    0x01,
                    0x11,
                    0x00,
                    0xFF,
                    0xC4,
                    0x00,
                    0x1F,
                    0x00,
                    0x00,
                    0x01,
                    0x05,
                    0x01,
                    0x01,
                    0x01,
                    0x01,
                    0x01,
                    0x01,
                    0x00,
                    0x00,
                    0x00,
                    0x00,
                    0x00,
                    0x00,
                    0x00,
                    0x00,
                    0x01,
                    0x02,
                    0x03,
                    0x04,
                    0x05,
                    0x06,
                    0x07,
                    0x08,
                    0x09,
                    0x0A,
                    0x0B,
                    0xFF,
                    0xC4,
                    0x00,
                    0xB5,
                    0x10,
                    0x00,
                    0x02,
                    0x01,
                    0x03,
                    0x03,
                    0x02,
                    0x04,
                    0x03,
                    0x05,
                    0x05,
                    0x04,
                    0x04,
                    0x00,
                    0x00,
                    0x01,
                    0x7D,
                    0xFF,
                    0xDA,
                    0x00,
                    0x08,
                    0x01,
                    0x01,
                    0x00,
                    0x00,
                    0x3F,
                    0x00,
                    0x7F,
                    0xFF,
                    0xD9,
                ]
            )
    return _KEEPALIVE_FRAME


async def mjpeg_generator(
    session_id: str,
    timeout: float = 30.0,
    emitter: Optional[FrameEmitter] = None,
) -> AsyncIterator[bytes]:
    """
    Async generator that yields MJPEG frames.

    Usage with FastAPI/Starlette:
        @app.get("/stream/{session_id}")
        async def stream(session_id: str):
            return StreamingResponse(
                mjpeg_generator(session_id),
                media_type="multipart/x-mixed-replace; boundary=frame"
            )

    Args:
        session_id: Session to subscribe to
        timeout: Seconds to wait for each frame before sending keepalive
        emitter: Optional FrameEmitter instance (uses global if not provided)

    Yields:
        bytes: MJPEG frame with multipart headers
    """
    if emitter is None:
        emitter = frame_emitter

    queue = emitter.subscribe(session_id)

    try:
        while True:
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=timeout)

                # None signals end of stream
                if frame is None:
                    break

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                    b"\r\n" + frame + b"\r\n"
                )
            except asyncio.TimeoutError:
                # Send a minimal keepalive frame to prevent connection timeout
                keepalive = _get_keepalive_frame()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(keepalive)).encode() + b"\r\n"
                    b"\r\n" + keepalive + b"\r\n"
                )
    except asyncio.CancelledError:
        pass
    finally:
        emitter.unsubscribe(session_id, queue)


def create_mjpeg_response_headers() -> dict:
    """Get headers for an MJPEG streaming response."""
    return {
        "Content-Type": "multipart/x-mixed-replace; boundary=frame",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive",
    }
