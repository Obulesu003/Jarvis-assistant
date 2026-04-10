"""
gesture_control.py - JARVIS responds to hand gestures via webcam.
MediaPipe Hands — CPU-capable, accurate at desk distance.
Gestures: wave (wake), thumbs up (acknowledge), thumbs down (cancel), open palm (pause), fist (silence)
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)


class GestureController:
    """
    JARVIS responds to hand gestures via webcam.
    MediaPipe Hands — CPU-capable, accurate at desk distance.

    Gestures:
    - wave → wake word alternative
    - thumbs up → acknowledge / continue
    - thumbs down → cancel / stop
    - open palm → pause listening
    - fist → silence / do not disturb
    """

    GESTURES = {
        "thumbs_up": "acknowledge",
        "thumbs_down": "cancel",
        "open_palm": "pause",
        "fist": "silence",
    }

    def __init__(self, speak_func=None, hud=None):
        self._speak = speak_func
        self._hud = hud
        self._hands = None
        self._camera = None
        self._enabled = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_gesture_time = 0.0
        self._gesture_cooldown = 3.0  # seconds between gesture reactions
        self._ctx = None
        self._do_not_disturb = False

    def initialize(self):
        """Initialize MediaPipe HandLandmarker (Tasks API)."""
        try:
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            base_options = python.BaseOptions(model_asset_path="models/hand_landmarker.task")
            options = vision.HandLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO,
                num_hands=1,
                min_hand_detection_confidence=0.7,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._hands = vision.HandLandmarker.create_from_options(options)
            logger.info("[Gesture] MediaPipe HandLandmarker initialized")
        except ImportError:
            logger.warning("[Gesture] mediapipe not installed. Run: pip install mediapipe")
            self._hands = None
        except Exception as e:
            logger.warning(f"[Gesture] MediaPipe Hands unavailable: {e}")
            self._hands = None

    def start(self):
        """Start gesture recognition camera feed."""
        if not self._hands:
            return
        if self._running:
            return

        self._enabled = True
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="GestureController")
        self._thread.start()
        logger.info("[Gesture] Camera started")

    def stop(self):
        """Stop gesture recognition."""
        self._running = False
        self._enabled = False
        if self._camera:
            self._camera.release()
            self._camera = None

    def _loop(self):
        """Main camera loop using MediaPipe Tasks LIVE_STREAM mode."""
        try:
            import cv2
            from mediapipe import ImageFormat
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            # Results buffer for async callback
            self._gesture_results = []

            def on_results_callback(result, output_image, timestamp_ms):
                self._gesture_results.append(result)

            # Recreate with callback mode
            base_options = python.BaseOptions(model_asset_path="models/hand_landmarker.task")
            options = vision.HandLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.LIVE_STREAM,
                num_hands=1,
                min_hand_detection_confidence=0.7,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                result_callback=on_results_callback,
            )
            hands = vision.HandLandmarker.create_from_options(options)

            self._camera = cv2.VideoCapture(0)
            if not self._camera.isOpened():
                logger.warning("[Gesture] Camera not available")
                hands.close()
                return

            timestamp_ms = 0
            while self._running:
                ret, frame = self._camera.read()
                if not ret:
                    continue

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = vision.Image(image_format=ImageFormat.SRGB, data=rgb)
                hands.detect_async(mp_image, timestamp_ms)
                timestamp_ms += 33

                # Process results from callback buffer
                while self._gesture_results:
                    result = self._gesture_results.pop(0)
                    if result.hand_landmarks:
                        for hand in result.hand_landmarks:
                            gesture = self._classify(hand)
                            if gesture and time.time() - self._last_gesture_time > self._gesture_cooldown:
                                self._react(gesture)
                                self._last_gesture_time = time.time()

                time.sleep(0.033)

            hands.close()
        except Exception as e:
            logger.error(f"[Gesture] Camera loop error: {e}")
        finally:
            if self._camera:
                self._camera.release()

    def _classify(self, landmarks) -> str | None:
        """Classify hand pose from MediaPipe landmarks."""
        thumb_tip = landmarks.landmark[4]
        index_tip = landmarks.landmark[8]
        index_base = landmarks.landmark[5]
        middle_tip = landmarks.landmark[12]
        middle_base = landmarks.landmark[9]
        ring_tip = landmarks.landmark[16]
        ring_base = landmarks.landmark[13]
        pinky_tip = landmarks.landmark[20]
        pinky_base = landmarks.landmark[17]

        def is_extended(tip, base):
            return tip.y < base.y

        # Thumbs up: thumb up, other fingers curled
        if thumb_tip.y < landmarks.landmark[2].y and not is_extended(index_tip, index_base):
            if not is_extended(middle_tip, middle_base) and not is_extended(ring_tip, ring_base):
                return "thumbs_up"

        # Thumbs down: thumb down
        if thumb_tip.y > landmarks.landmark[2].y and not is_extended(index_tip, index_base):
            return "thumbs_down"

        # Open palm: all fingers extended
        fingers_extended = sum([
            is_extended(index_tip, index_base),
            is_extended(middle_tip, middle_base),
            is_extended(ring_tip, ring_base),
            is_extended(pinky_tip, pinky_base),
        ])
        if fingers_extended >= 3:
            return "open_palm"

        # Fist: no fingers extended
        if fingers_extended == 0 and not is_extended(thumb_tip, landmarks.landmark[2]):
            return "fist"

        return None

    def _react(self, gesture: str):
        """React to a recognized gesture."""
        action = self.GESTURES.get(gesture, "")
        logger.info(f"[Gesture] Recognized: {gesture} -> {action}")

        if action == "acknowledge":
            if self._hud:
                self._hud.set_state("listening")
            if self._speak:
                self._speak("Acknowledged, sir.")
        elif action == "pause":
            if self._hud:
                self._hud.set_state("idle")
            if self._speak:
                self._speak("Pausing. Wave to resume.")
        elif action == "silence":
            if self._speak:
                self._speak("Silence mode active.")
        elif action == "cancel":
            self.skip_current_notification()
            if self._speak:
                self._speak("Cancelled.")

    def is_do_not_disturb(self) -> bool:
        """Return current DND state."""
        return self._do_not_disturb

    def set_conversation_context(self, ctx) -> None:
        """
        Wire the ConversationContextEngine into gesture control.

        Args:
            ctx: ConversationContextEngine instance
        """
        self._ctx = ctx

    def set_do_not_disturb(self, enabled: bool) -> None:
        """
        Enable or disable proactive volunteering via gestures.

        Args:
            enabled: True = silence proactive alerts
        """
        self._do_not_disturb = enabled

    def skip_current_notification(self) -> bool:
        """
        Skip/dismiss the current proactive notification.

        Returns:
            True if a notification was skipped
        """
        if hasattr(self, "_ctx") and self._ctx:
            self._ctx.last_volunteer_at = time.time()  # Reset volunteer timer
            logger.info("[Gesture] Skipped current proactive notification")
            return True
        return False

