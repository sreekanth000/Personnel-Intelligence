"""
Synthetic Source Fabric for Personal Intelligence.

Simulates what Hermes returns from external capabilities over a 30-60 day timeline.
Produces deterministic, generic, source-backed observations across 8 distinct categories:
1. personal_activity
2. communication
3. calendar_commitments
4. work_projects
5. personal_routines
6. environment_travel
7. goals
8. device_activity_signals

Every generated observation contains:
- event_id (id)
- timestamp (event_time)
- source
- source_event_id (source_id)
- event_type (observation_type)
- entities (entity_refs)
- payload (structured_data)
- provenance
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import random
from typing import Any, Dict, List, Optional, Tuple
import uuid

from personal_intelligence.core.events.models import Event, ensure_timezone_aware


@dataclass
class SyntheticObservationSpec:
    """Raw observation spec prior to Event instantiation."""
    event_id: str
    timestamp: datetime
    source: str
    source_event_id: str
    event_type: str
    entities: List[str]
    payload: Dict[str, Any]
    provenance: Dict[str, Any]
    category: str

    def to_event(self) -> Event:
        """Converts spec to a standard PI Event model."""
        return Event(
            id=self.event_id,
            timestamp=self.timestamp,
            source=self.source,
            source_id=self.source_event_id,
            observation_type=self.event_type,
            entity_refs=self.entities,
            structured_data=self.payload,
            provenance=self.provenance,
            confidence=1.0,
            summary=self.payload.get("summary", f"{self.event_type} from {self.source}"),
        )


class SyntheticSourceFabric:
    """
    Fabric that generates chronologically sorted, deterministic, source-backed
    observations simulating Hermes tool retrieval responses over 30-60 days.
    """

    CATEGORIES = (
        "personal_activity",
        "communication",
        "calendar_commitments",
        "work_projects",
        "personal_routines",
        "environment_travel",
        "goals",
        "device_activity_signals",
    )

    def __init__(
        self,
        seed: int = 42,
        days: int = 45,
        events_per_day: int = 6,
        start_time: Optional[datetime] = None,
    ) -> None:
        if days < 30:
            days = 30
        self.seed = seed
        self.days = days
        self.events_per_day = events_per_day
        self.rng = random.Random(seed)

        # Baseline start time (default 45 days before now UTC, aligned to 00:00 UTC)
        if start_time is None:
            now_utc = datetime.now(timezone.utc)
            base_date = now_utc.date() - timedelta(days=days)
            self.start_time = datetime(
                base_date.year, base_date.month, base_date.day, 8, 0, 0, tzinfo=timezone.utc
            )
        else:
            self.start_time = ensure_timezone_aware(start_time, "start_time")

    def _generate_event_id(self, category: str, index: int, timestamp: datetime) -> str:
        raw_str = f"syn-{self.seed}-{category}-{index}-{timestamp.isoformat()}"
        return f"evt-{hashlib.sha256(raw_str.encode('utf-8')).hexdigest()[:16]}"

    def _generate_source_event_id(self, source: str, category: str, index: int) -> str:
        return f"{source}-src-{self.seed}-{index:05d}"

    def generate_observations(self) -> List[Event]:
        """
        Generates a chronologically sorted list of Event objects spanning self.days.
        Guarantees all 8 categories are represented.
        """
        observations: List[SyntheticObservationSpec] = []
        total_days = self.days

        for day_idx in range(total_days):
            day_start = self.start_time + timedelta(days=day_idx)
            
            num_events = self.rng.randint(max(3, self.events_per_day - 2), self.events_per_day + 3)
            
            cats_for_day = list(self.CATEGORIES)
            self.rng.shuffle(cats_for_day)
            
            for evt_idx in range(num_events):
                category = cats_for_day[evt_idx % len(self.CATEGORIES)]
                
                hour_offset = self.rng.randint(6, 21)
                minute_offset = self.rng.randint(0, 59)
                second_offset = self.rng.randint(0, 59)
                
                evt_time = day_start.replace(
                    hour=hour_offset, minute=minute_offset, second=second_offset
                )
                
                spec = self._create_spec(category=category, day_idx=day_idx, evt_idx=evt_idx, timestamp=evt_time)
                observations.append(spec)

        observations.sort(key=lambda obs: obs.timestamp)

        events = [obs.to_event() for obs in observations]
        return events

    def _create_spec(
        self, category: str, day_idx: int, evt_idx: int, timestamp: datetime
    ) -> SyntheticObservationSpec:
        """Creates a single SyntheticObservationSpec for the specified category."""
        global_idx = day_idx * 100 + evt_idx
        
        if category == "personal_activity":
            source = "whoop"
            src_type = "health_tracker"
            event_type = "workout_completed" if evt_idx % 2 == 0 else "sleep_metrics_logged"
            entities = ["person:user", "activity:running", "metric:heart_rate"]
            summary = (
                f"Completed 45m run at average HR {145 + (day_idx % 15)} bpm (Strain: {12.4 + (day_idx % 5)})"
                if event_type == "workout_completed"
                else f"Recorded 7h {20 + (day_idx % 40)}m sleep (Recovery Score: {75 + (day_idx % 20)}%)"
            )
            evidence = {
                "duration_minutes": 45 if event_type == "workout_completed" else 440,
                "avg_heart_rate": 148,
                "strain_score": 13.1,
                "recovery_percentage": 82,
                "calories_burned": 520,
            }

        elif category == "communication":
            source = "slack" if evt_idx % 2 == 0 else "whatsapp"
            src_type = "messaging"
            event_type = "message_received"
            sender = "colleague_bob" if source == "slack" else "friend_charlie"
            entities = [f"person:{sender}", "topic:project_deploy", "channel:engineering"]
            summary = f"Message from {sender} regarding architecture milestone and release schedule"
            evidence = {
                "sender": sender,
                "channel": "engineering" if source == "slack" else "personal_chat",
                "content_snippet": "The staging build is ready for verification. Let us align at 14:00.",
                "thread_id": f"thread_{day_idx}",
            }

        elif category == "calendar_commitments":
            source = "calendar"
            src_type = "scheduling"
            event_type = "calendar_event_created"
            entities = ["person:user", "person:alice", "meeting:architecture_review"]
            summary = f"Scheduled Architecture Sync with Alice on Day {day_idx + 1}"
            evidence = {
                "title": "Quarterly Architecture Review",
                "organizer": "alice@company.com",
                "attendees": ["user@company.com", "alice@company.com", "bob@company.com"],
                "start_time": timestamp.isoformat(),
                "duration_minutes": 60,
                "location": "Virtual Room A",
            }

        elif category == "work_projects":
            source = "github" if evt_idx % 2 == 0 else "jira"
            src_type = "developer_tools"
            event_type = "code_commit_merged" if source == "github" else "issue_status_updated"
            entities = ["project:personal_intelligence", "repo:pi_core", "issue:PI-204"]
            summary = (
                f"Merged PR #{100 + day_idx}: Hardened epistemic reasoning bounds"
                if source == "github"
                else f"Jira Issue PI-{200 + day_idx} moved to IN_PROGRESS"
            )
            evidence = {
                "repository": "personal_intelligence",
                "pull_request_id": 100 + day_idx,
                "commits_count": 3,
                "issue_key": f"PI-{200 + day_idx}",
                "status": "IN_PROGRESS",
            }

        elif category == "personal_routines":
            source = "routine_tracker"
            src_type = "lifestyle"
            event_type = "routine_step_logged"
            entities = ["routine:morning_focus", "habit:meditation"]
            summary = f"Completed morning focus routine ({15 + (day_idx % 10)}m mindfulness & journaling)"
            evidence = {
                "routine_name": "Morning Focus",
                "completion_rate": 1.0,
                "streak_days": day_idx + 1,
                "notes": "Focused setup for deep work session",
            }

        elif category == "environment_travel":
            source = "weather_service" if evt_idx % 2 == 0 else "maps_gps"
            src_type = "environment"
            event_type = "environment_condition_updated" if source == "weather_service" else "location_arrival_logged"
            entities = ["location:home_office", "region:city_center"]
            summary = (
                f"Weather alert: Heavy rain & thunderstorm expected in evening (Temp {22 - (day_idx % 5)}C)"
                if source == "weather_service"
                else "Arrived at Office Workspace"
            )
            evidence = {
                "temperature_celsius": 21.5,
                "precipitation_probability": 0.85,
                "location_name": "Home Office" if source == "weather_service" else "Office HQ",
                "geofence_id": "geo_workspace_01",
            }

        elif category == "goals":
            source = "goal_tracker"
            src_type = "productivity"
            event_type = "goal_metric_updated"
            entities = ["goal:quarterly_fitness", "goal:deep_learning_mastery"]
            summary = f"Logged goal progress: 5km run milestone {day_idx % 5}/5 achieved"
            evidence = {
                "goal_id": "goal_fitness_q3",
                "metric_name": "weekly_mileage_km",
                "current_value": 25.0 + day_idx,
                "target_value": 100.0,
                "progress_percentage": min(100.0, (25.0 + day_idx) / 100.0 * 100),
            }

        else:  # device_activity_signals
            source = "device_os"
            src_type = "system_telemetry"
            event_type = "system_telemetry_logged"
            entities = ["device:macbook_pro", "system:battery"]
            summary = f"Device telemetry: Screen time {5.5 + (day_idx % 3):.1f}h, Battery level {85 - (evt_idx * 15)}%"
            evidence = {
                "screen_time_hours": 5.5,
                "battery_percentage": 85,
                "active_applications": ["VSCode", "Terminal", "Browser"],
                "wifi_ssid": "Workspace_5G",
            }

        evt_id = self._generate_event_id(category, global_idx, timestamp)
        src_evt_id = self._generate_source_event_id(source, category, global_idx)

        payload = {
            "summary": summary,
            "category": category,
            "evidence": evidence,
            "day_index": day_idx,
            "global_index": global_idx,
        }

        provenance = {
            "tool": f"hermes_fetch_{source}",
            "query": f"get_{category}_observations",
            "source_system": source,
            "source_type": src_type,
            "source_event_id": src_evt_id,
            "retrieved_at": timestamp.isoformat(),
            "confidence": 1.0,
            "provenance_chain": [f"hermes://adapters/{source}/{src_evt_id}"],
        }

        return SyntheticObservationSpec(
            event_id=evt_id,
            timestamp=timestamp,
            source=source,
            source_event_id=src_evt_id,
            event_type=event_type,
            entities=entities,
            payload=payload,
            provenance=provenance,
            category=category,
        )
