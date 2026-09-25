# Privacy Architecture — Rapid Tracker

## Overview

Rapid Tracker processes camera data from public transport buses to generate
operational intelligence. This document describes the privacy-by-design
architecture that ensures passenger data is handled responsibly.

## Core Principle

**Camera → AI Processing → Event Metadata → Control Centre**

Raw camera frames are processed in real-time and discarded. Only structured
event metadata is persisted. No raw video footage is stored.

## Data Flow

```
┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   CAMERA    │───▶│  AI PROCESSING   │───▶│  EVENT METADATA │
│   (Input)   │    │  (In-Memory)     │    │  (Structured)   │
└─────────────┘    └──────────────────┘    └─────────────────┘
       │                    │                       │
       ▼                    ▼                       ▼
  Frame Capture      Detection + Analysis     Persist to SQLite
       │                    │                       │
       ▼                    ▼                       ▼
   DISCARD            DISCARD FRAME           CONTROL CENTRE
   After              After Processing        (No Raw Video
   Inference                                  Retained)
```

## What We Store

| Data Type | Stored? | Retention | Purpose |
|-----------|---------|-----------|---------|
| Camera frames | **NO** | Discarded after inference | Real-time processing only |
| Face images | **NO** | Never stored | Privacy protection |
| Passenger photos | **NO** | Never stored | Privacy protection |
| Event metadata | **YES** | 30 days | Operational intelligence |
| GPS coordinates | **YES** | 30 days | Location tracking for incidents |
| Detection type | **YES** | 30 days | Incident classification |
| Confidence scores | **YES** | 30 days | AI explainability |
| Vehicle telemetry | **YES** | 30 days | Health monitoring |

## What We Process (But Don't Store)

| Processing | Method | Data Retained |
|-----------|--------|---------------|
| Driver drowsiness | MediaPipe face mesh (EAR/MAR/head pose) | Event: "DROWSY" + severity |
| Pothole detection | YOLO model + contour fallback | Event: "POTHOLE" + GPS + confidence |
| Cabin hazard | YOLOv8n (fire/smoke) | Event: "CABIN_FIRE" or "CABIN_SMOKE" |
| Cabin occupancy | Heuristic grid density | Aggregate count only (no faces) |
| Road defects | YOLO model + GPS | Event: "ROAD_DEFECT" + GPS |

## Privacy Controls

### Feature Toggles
- `privacy_mode`: When enabled, ensures all processing is metadata-only
- `camera_driver`: Controls driver camera access
- `camera_cabin`: Controls cabin camera access

### Data Minimization
- Frames are consumed then discarded immediately
- No image buffers are persisted to disk
- No facial recognition or identification
- No passenger counting that stores individual images

### Access Control
- All API endpoints require authentication (Bearer token)
- Role-based access: operator < supervisor < admin
- Camera controls require authentication
- Event data is read-only for operators

## Compliance Notes

- **No biometric data storage**: Face mesh landmarks are used for
  real-time drowsiness detection only; no facial templates are stored.
- **No passenger identification**: Occupancy counting uses aggregate
  density estimation, not individual tracking.
- **Data retention**: Event metadata is retained for 30 days for
  operational analytics and incident investigation.
- **Transparency**: The control centre dashboard shows what data is
  being collected and processed.

## Architecture Diagram

```
Bus Camera System
    │
    ├── Driver Camera ──▶ DDS Engine ──▶ Event: DRIVER_DROWSINESS
    │   (Real-time)      (MediaPipe)     (No face images stored)
    │
    ├── Cabin Camera ──▶ Occupancy ──▶ Event: OVERCROWDING
    │   (Real-time)      (Heuristic)    (Aggregate count only)
    │
    └── Road Camera ──▶ Pothole ──▶ Event: POTHOLE
        (Real-time)      (YOLO)      (No road images stored)
                                   
All processing happens in-memory.
Only structured events reach persistence.
```

## Verification

To verify privacy compliance:
1. Check `persistence.py` — no image/blob columns in any table
2. Check `camera_manager.py` — frames are processed and discarded
3. Check `occupancy.py` — explicit "frames consumed then discarded" comment
4. Check database schema — only text/numeric fields, no binary data
