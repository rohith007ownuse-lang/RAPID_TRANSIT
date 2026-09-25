"""
fatigue_engine.py
The only module that reads eye + mouth + head-pose signals together
and decides an overall drowsiness status.

This system does NOT perform automatic braking on the bus. Drowsiness and
face-loss events are reported as a *recommendation* to the Control Centre,
which decides on any intervention after human safety review. Braking is a
Control Centre decision, not an automatic onboard action.

Statuses reported per frame:
  - NORMAL               : face present + eyes open
  - EYES CLOSED          : eyes closed but below the drowsiness duration
  - DROWSINESS WARNING   : eyes continuously closed, timer running
  - DROWSINESS DETECTED  : eyes closed beyond the drowsiness duration
  - HEAD NOD DETECTED    : sustained downward head deviation
  - HEAD POSE ALERT      : sustained head-pose deviation

A "brake_recommended" field is populated when the system would historically
have braked (eyelid closure or face loss beyond safety thresholds), but no
automatic command is sent to the vehicle. The Control Centre decides.
"""

import time
from collections import deque

from bus_node.detectors.eye_detection import calculate_avg_ear
from bus_node.detectors.mouth_detection import calculate_mar
from bus_node.detectors.head_pose import get_head_pose, HeadPoseTracker
from bus_node.core.severity import severity_for
from bus_node.utils.config_manager import get_config


class FatigueEngine:
    def __init__(self, ear_threshold, mar_threshold, baseline_pitch,
                 eye_closed_duration=None, yawn_duration=None,
                 head_pitch_drop=None, head_nod_duration=None,
                 head_pose_alert_deviation=None, head_pose_alert_duration=None,
                 perclos_window=None, perclos_threshold=None, perclos_min_samples=None,
                 emergency_stop_threshold=None, face_loss_stop_threshold=None):

        # Load facial/detection settings from config (editable in
        # config/system_config.json under "detection"). Constructor args
        # (e.g. calibrated EAR/MAR from main.py) override the config.
        self.config = get_config()

        if ear_threshold is None:
            ear_threshold = self.config.get('detection.ear_threshold', 0.23)
        if mar_threshold is None:
            mar_threshold = self.config.get('detection.mar_threshold', 0.40)
        if eye_closed_duration is None:
            eye_closed_duration = self.config.get('detection.eye_closed_duration', 1.3)
        if yawn_duration is None:
            yawn_duration = self.config.get('detection.yawn_duration', 1.0)
        if head_pitch_drop is None:
            head_pitch_drop = self.config.get('detection.head_pitch_threshold', 15.0)
        if head_nod_duration is None:
            head_nod_duration = self.config.get('detection.head_pose_duration', 1.3)
        if head_pose_alert_deviation is None:
            head_pose_alert_deviation = self.config.get('detection.head_pose_alert_deviation', 15.0)
        if head_pose_alert_duration is None:
            head_pose_alert_duration = self.config.get('detection.head_pose_alert_duration', 2.5)
        if perclos_window is None:
            perclos_window = self.config.get('detection.perclos_window', 60.0)
        if perclos_threshold is None:
            perclos_threshold = self.config.get('detection.perclos_threshold', 0.15)
        if perclos_min_samples is None:
            perclos_min_samples = self.config.get('detection.perclos_min_samples', 30)

        self.EAR_THRESHOLD = ear_threshold
        self.MAR_THRESHOLD = mar_threshold
        self.eye_closed_duration = eye_closed_duration
        self.yawn_duration = yawn_duration

        self.nod_tracker = HeadPoseTracker(
            baseline_pitch=baseline_pitch,
            deviation_threshold=head_pitch_drop,
            duration_threshold=head_nod_duration,
            direction="down"
        )
        self.pose_alert_tracker = HeadPoseTracker(
            baseline_pitch=baseline_pitch,
            deviation_threshold=head_pose_alert_deviation,
            duration_threshold=head_pose_alert_duration,
            direction="both"
        )

        self.eye_closed_start = None
        self.last_eye_closed_duration = 0.0
        self.mouth_open_start = None
        self.yawn_detected = False
        self.yawn_counter = 0

        self.perclos_window = perclos_window
        self.perclos_threshold = perclos_threshold
        self.perclos_min_samples = perclos_min_samples
        self.perclos_history = deque()

        self.drowsy_active = False
        self.drowsy_episode_start = None
        self.total_drowsy_episodes = 0
        self.total_drowsy_time = 0.0
        self.max_closed_time = 0.0
        self.ear_sum = 0.0
        self.ear_count = 0

        self.last_ear = 0.0
        self.last_mar = 0.0
        self.last_pitch = baseline_pitch
        self.last_perclos = 0.0

        # ---- Brake recommendation layer ----
        # This system does NOT brake automatically. It only evaluates whether
        # an intervention *would* historically have been warranted and reports
        # a recommendation ("brake_recommended") to the Control Centre. The
        # Control Centre decides, after human safety review, whether to act.

        # Continuous eye closure beyond this threshold flags a brake recommendation.
        if emergency_stop_threshold is None:
            emergency_stop_threshold = self.config.get(
                'hardware.emergency_stop_threshold', 8.0)
        self.emergency_stop_threshold = float(emergency_stop_threshold)

        # Face-loss threshold: continuous time the face may be missing before a
        # brake recommendation is raised (default 2.0s).
        if face_loss_stop_threshold is None:
            face_loss_stop_threshold = self.config.get(
                'hardware.face_loss_stop_threshold', 2.0)
        self.face_loss_stop_threshold = float(face_loss_stop_threshold)

        # Recommendation flags (no automatic action is taken on the bus).
        self.brake_recommended = False
        self.brake_recommend_reason = None
        self.total_brake_recommendations = 0
        self.total_face_loss_recommendations = 0

        # Face-loss timing (continuous, resets when face is detected again).
        self.face_lost_start = None
        self.face_lost_time = 0.0

    def process_frame(self, landmarks, frame_w, frame_h):
        now = time.time()

        ear = calculate_avg_ear(landmarks)
        mar = calculate_mar(landmarks)

        self.ear_sum += ear
        self.ear_count += 1

        pose = get_head_pose(landmarks, frame_w, frame_h)
        pitch = pose[0] if pose is not None else self.nod_tracker.baseline_pitch
        nod_duration, head_nod_detected, nod_deviation = self.nod_tracker.update(pitch)
        pose_alert_duration, head_pose_alert, pose_deviation = self.pose_alert_tracker.update(pitch)

        yawn_event = False
        if mar > self.MAR_THRESHOLD:
            if self.mouth_open_start is None:
                self.mouth_open_start = now
            mouth_duration = now - self.mouth_open_start
            if mouth_duration >= self.yawn_duration and not self.yawn_detected:
                self.yawn_counter += 1
                self.yawn_detected = True
                yawn_event = True
        else:
            self.mouth_open_start = None
            self.yawn_detected = False

        is_closed = ear < self.EAR_THRESHOLD
        eye_closed_event = False
        eye_reopened_event = False

        if is_closed:
            if self.eye_closed_start is None:
                self.eye_closed_start = now
                eye_closed_event = True
            closed_time = now - self.eye_closed_start
            self.last_eye_closed_duration = closed_time
            self.max_closed_time = max(self.max_closed_time, closed_time)
        else:
            if self.eye_closed_start is not None:
                eye_reopened_event = True
            self.eye_closed_start = None
            closed_time = 0.0

        self.perclos_history.append((now, is_closed))
        while self.perclos_history and now - self.perclos_history[0][0] > self.perclos_window:
            self.perclos_history.popleft()

        if len(self.perclos_history) >= self.perclos_min_samples:
            closed_count = sum(1 for _, c in self.perclos_history if c)
            perclos = closed_count / len(self.perclos_history)
        else:
            perclos = 0.0

        self.last_ear = ear
        self.last_mar = mar
        self.last_pitch = pitch
        self.last_perclos = perclos

        drowsy_start_event = False
        drowsy_end_event = False
        DROWSY_STATUSES = ("DROWSINESS DETECTED", "DROWSINESS DETECTED (PERCLOS)")

        # ---- Status determination (unchanged detection logic) ----
        if closed_time >= self.eye_closed_duration:
            status = "DROWSINESS DETECTED"
            if not self.drowsy_active:
                self.drowsy_active = True
                self.drowsy_episode_start = now
                self.total_drowsy_episodes += 1
                drowsy_start_event = True
        elif perclos >= self.perclos_threshold:
            status = "DROWSINESS DETECTED (PERCLOS)"
            if not self.drowsy_active:
                self.drowsy_active = True
                self.drowsy_episode_start = now
                self.total_drowsy_episodes += 1
                drowsy_start_event = True
        elif head_pose_alert:
            status = "HEAD POSE ALERT"
        elif head_nod_detected:
            status = "HEAD NOD DETECTED"
        elif is_closed:
            status = "EYES CLOSED"
        else:
            status = "NORMAL"

        if status not in DROWSY_STATUSES and self.drowsy_active:
            drowsy_duration = now - self.drowsy_episode_start
            self.total_drowsy_time += drowsy_duration
            self.drowsy_active = False
            drowsy_end_event = True

        # ---- Brake recommendation ----
        # Face is present in this frame, so the face-loss timer resets.
        self.face_lost_start = None
        self.face_lost_time = 0.0

        # No automatic braking here. Evaluate whether an intervention would
        # historically have been warranted, and report it as a recommendation
        # for the Control Centre to act on after human safety review.
        hw_state = "NORMAL"
        stop_triggered_event = False
        stop_released_event = False

        if is_closed and closed_time >= self.emergency_stop_threshold:
            # Continuous eye closure beyond the safety threshold.
            if not self.brake_recommended:
                self.brake_recommended = True
                self.brake_recommend_reason = "eye_closure"
                self.total_brake_recommendations += 1
                stop_triggered_event = True
            hw_state = "DROWSINESS_WARNING"
        elif is_closed and closed_time > 0:
            # Eyes closed, timer running but not at the threshold yet.
            hw_state = "DROWSINESS_WARNING"
        else:
            # Eyes open - clear any prior recommendation for eye closure.
            if self.brake_recommended and self.brake_recommend_reason == "eye_closure":
                self.brake_recommended = False
                self.brake_recommend_reason = None
                stop_released_event = True
            hw_state = "NORMAL"

        # ---- Compute drowsiness percent for the dashboard (unchanged) ----
        closed_ratio = min(1.0, closed_time / self.eye_closed_duration) if self.eye_closed_duration else 0.0
        perclos_ratio = min(1.0, perclos / self.perclos_threshold) if self.perclos_threshold else 0.0
        drowsy_percent = round(100 * max(closed_ratio, perclos_ratio))

        return {
            "ear": ear, "mar": mar, "pitch": pitch,
            "closed_time": closed_time, "perclos": perclos,
            "nod_duration": nod_duration, "nod_deviation": nod_deviation,
            "pose_alert_duration": pose_alert_duration, "pose_deviation": pose_deviation,
            "status": status, "severity": severity_for(status),
            "drowsy_percent": drowsy_percent,
            "yawn_counter": self.yawn_counter, "yawn_event": yawn_event,
            "eye_closed_event": eye_closed_event, "eye_reopened_event": eye_reopened_event,
            "eye_reopened_duration": self.last_eye_closed_duration,
            "drowsy_start_event": drowsy_start_event, "drowsy_end_event": drowsy_end_event,
            # Driver recommendation state (no automatic action is taken on the bus)
            "hardware_state": hw_state,
            "brake_recommended": self.brake_recommended,
            "brake_recommend_reason": self.brake_recommend_reason,
            "face_lost_time": self.face_lost_time,
            "stop_triggered_event": stop_triggered_event,
            "stop_released_event": stop_released_event,
            "total_brake_recommendations": self.total_brake_recommendations,
            "total_face_loss_recommendations": self.total_face_loss_recommendations,
        }

    def handle_face_lost(self):
        drowsy_end_event = False
        eye_reopened_event = self.eye_closed_start is not None
        now = time.time()

        if self.drowsy_active:
            drowsy_duration = now - self.drowsy_episode_start
            self.total_drowsy_time += drowsy_duration
            self.drowsy_active = False
            drowsy_end_event = True

        self.eye_closed_start = None
        self.mouth_open_start = None

        # ---- Face-loss timing ----
        # Continuous time the face has been missing. A brief <2s glitch
        # does not raise a recommendation; the timer continues and only
        # flags after crossing the threshold.
        if self.face_lost_start is None:
            self.face_lost_start = now
        self.face_lost_time = now - self.face_lost_start

        # ---- Face-loss brake recommendation ----
        # Face missing for >= face_loss_stop_threshold -> raise a brake
        # recommendation for the Control Centre. No automatic action is sent.
        stop_triggered_event = False
        hw_state = "DROWSINESS_WARNING" if self.brake_recommended else "NORMAL"

        if not self.brake_recommended and \
                self.face_lost_time >= self.face_loss_stop_threshold:
            self.brake_recommended = True
            self.brake_recommend_reason = "face_loss"
            self.total_brake_recommendations += 1
            self.total_face_loss_recommendations += 1
            stop_triggered_event = True

        return {
            "ear": self.last_ear, "mar": self.last_mar, "pitch": self.last_pitch,
            "closed_time": 0.0, "perclos": self.last_perclos,
            "nod_duration": 0.0, "nod_deviation": 0.0,
            "pose_alert_duration": 0.0, "pose_deviation": 0.0,
            "status": "NO FACE", "severity": severity_for("NO FACE"),
            "drowsy_percent": 0,
            "yawn_counter": self.yawn_counter, "yawn_event": False,
            "eye_closed_event": False, "eye_reopened_event": eye_reopened_event,
            "eye_reopened_duration": self.last_eye_closed_duration,
            "drowsy_start_event": False, "drowsy_end_event": drowsy_end_event,
            "hardware_state": hw_state,
            "brake_recommended": self.brake_recommended,
            "brake_recommend_reason": self.brake_recommend_reason,
            "face_lost_time": self.face_lost_time,
            "stop_triggered_event": stop_triggered_event,
            "stop_released_event": False,
            "total_brake_recommendations": self.total_brake_recommendations,
            "total_face_loss_recommendations": self.total_face_loss_recommendations,
        }

    def clear_brake_recommendation(self):
        """
        Clear the current brake recommendation. This can be called by the
        Control Centre after a human safety review, or locally by the bus
        operator. No vehicle command is sent; braking decisions belong to the
        Control Centre.
        """
        was_recommended = self.brake_recommended
        self.brake_recommended = False
        self.brake_recommend_reason = None
        return was_recommended

    def reset(self):
        self.eye_closed_start = None
        self.last_eye_closed_duration = 0.0
        self.mouth_open_start = None
        self.face_lost_start = None
        self.face_lost_time = 0.0
        self.yawn_detected = False
        self.yawn_counter = 0
        self.perclos_history.clear()
        self.drowsy_active = False
        self.drowsy_episode_start = None
        self.total_drowsy_episodes = 0
        self.total_drowsy_time = 0.0
        self.max_closed_time = 0.0
        self.ear_sum = 0.0
        self.ear_count = 0
        self.last_ear = 0.0
        self.last_mar = 0.0
        self.last_perclos = 0.0
        self.nod_tracker.reset()
        self.pose_alert_tracker.reset()
        self.clear_brake_recommendation()

    def summary(self, session_duration):
        avg_ear = (self.ear_sum / self.ear_count) if self.ear_count > 0 else 0.0
        return {
            "duration_seconds": session_duration,
            "yawns": self.yawn_counter,
            "drowsy_episodes": self.total_drowsy_episodes,
            "drowsy_time_seconds": self.total_drowsy_time,
            "max_closed_time": self.max_closed_time,
            "brake_recommendations": self.total_brake_recommendations,
            "face_loss_recommendations": self.total_face_loss_recommendations,
            "avg_ear": avg_ear,
        }
