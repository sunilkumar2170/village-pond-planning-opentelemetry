# AI-Based Village Pond Planning System with OpenTelemetry Observability

[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Tracing%20%7C%20Metrics%20%7C%20Logs-blue.svg)](https://opentelemetry.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-green.svg)](https://fastapi.tiangolo.com/)
[![Jaeger](https://img.shields.io/badge/Jaeger-All--in--One%20v1.60-orange.svg)](https://www.jaegertracing.io/)
[![Prometheus](https://img.shields.io/badge/Prometheus-Metrics%20Format-red.svg)](https://prometheus.io/)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)

**Author:** Sunil Kumar  
**Roll Number:** 12342170  
**Course:** CSD Lab 8 — OpenTelemetry Observability Implementation  
**Affiliation:** Indian Institute of Technology Bhilai (IIT Bhilai)  

---

## 📌 Project Overview

The **Village Pond Planning System** is a geospatial civil-engineering platform developed to assist rural planners in identifying optimal rainwater harvesting locations and calculating contributing catchment volumes.

In this project, the monolithic geospatial pipeline was enhanced with **full three-pillar observability (Traces, Metrics, Logs)** using the official **OpenTelemetry (OTel) Python SDK**, **Jaeger**, and **Prometheus**.

---

## 🏗️ Observability Architecture

```
                                  [ Client Request ]
                                (POST /analyzeContour)
                                          │
                                          ▼
                     ┌─────────────────────────────────────────┐
                     │         FastAPI Backend Engine          │
                     │  (Root Span: process_contour_file)      │
                     └────────────────────┬────────────────────┘
                                          │
       ┌──────────────────────────────────┴──────────────────────────────────┐
       │                                                                     │
       ▼ (Sequential Child Spans)                                            ▼ (Telemetry Engine)
  1. kml.parse_contours                                             ┌─────────────────┐
  2. terrain.boundary_filtering                                     │ OpenTelemetry   │
  3. terrain.build_elevation_grid                                   │ Python SDK      │
  4. pond.pick_optimal_location                                     │ - TracerProvider│
  5. hydrology.compute_d8_flow_and_catchment                        │ - BatchProcessor│
  6. external.fetch_annual_rainfall                                 │ - OTelFormatter │
  7. hydrology.estimate_water_volume_scs_cn                         └────────┬────────┘
                                                                             │
             ┌───────────────────────┬───────────────────────┬───────────────┴───────────────┐
             ▼                       ▼                       ▼                               ▼
    [ Jaeger Collector ]    [ Prometheus Metrics ]   [ Trace-Correlated Logs ]    [ In-Memory Dashboard ]
     OTLP gRPC (:4317)       Endpoint: /metrics       TraceID & SpanID injected    Buffer: /telemetry/dashboard
```

---

## 🔍 Key Observability Features

### 1. Granular Domain Tracing (7 Child Spans)
Monolithic request execution is broken into 7 sequential domain child spans with semantic domain attributes:
* `kml.parse_contours`: Geometry vertices count, contour levels parsed.
* `terrain.boundary_filtering`: Shapely polygon containment validation.
* `terrain.build_elevation_grid`: SciPy Delaunay triangulation & DEM interpolation bounds.
* `pond.pick_optimal_location`: Topographic local depression coordinates (`lat`, `lon`, `elevation_m`).
* `hydrology.compute_d8_flow_and_catchment`: D8 steepest-slope routing & BFS catchment delineation (`area_hectares`, `cell_count`).
* `external.fetch_annual_rainfall`: External Open-Meteo meteorological API latency and precipitation retrieval.
* `hydrology.estimate_water_volume_scs_cn`: SCS Curve Number runoff depth ($mm$) and expected harvestable volume ($m^3$).

### 2. Standardized Prometheus Metrics (`/metrics`)
* `pond_analysis_requests_total`: Counter tracking total processed requests labeled by `input_type` (`kml_file` vs `freehand_boundary`) and `status` (`success` vs `error`).
* `pond_analysis_duration_seconds`: Histogram measuring execution latency distribution ($0.05s$ to $10s$).
* `catchment_area_hectares`: Histogram tracking delineated watershed area distribution.
* `expected_water_volume_cubic_meters`: KPI gauge aggregating total calculated water storage potential.
* `active_pond_analysis_requests`: In-flight gauge monitoring concurrent computations.

### 3. Deterministic Trace-Log Correlation
A custom `OTelLogFormatter` dynamically inspects the thread-local span context via `trace.get_current_span().get_span_context()`, injecting the 32-character hexadecimal `trace_id` and 16-character `span_id` directly into each log record:
```text
2026-10-16 19:42:15,102 [INFO] [trace_id=90a2543b0f0b5f1ab3928c30fe1a6da5 span_id=314b9c1d0a5e8f22] pond.pick_optimal_location: Optimal pond located at (21.2499, 81.2899) with elevation 267.0m
```

### 4. Custom Live In-Memory Telemetry Dashboard
An embedded real-time telemetry dashboard accessible at `/telemetry/dashboard` providing:
* Active spans count, processor status, and recent trace ring buffer.
* Live microsecond timing waterfall view.
* Instant attribute inspection without requiring external UI tools.

---

## 🌐 Remote Evaluation Deployment (`10.1.75.53`)

The stack is deployed on the IIT Bhilai evaluation server with the following endpoints:

| Service / Endpoint | Port / Access | Status | Description |
|---|---|---|---|
| **Backend REST API** | `http://10.1.75.53:3213/` | `200 OK` | Main API service metadata & endpoints |
| **Health Check** | `http://10.1.75.53:3213/health` | `200 OK` | `{"status":"online", "telemetry":"active"}` |
| **Prometheus Metrics** | `http://10.1.75.53:3213/metrics` | `200 OK` | Prometheus scrape endpoint |
| **Live OTel Dashboard** | `http://10.1.75.53:3213/telemetry/dashboard` | `200 OK` | Real-time in-memory spans UI |
| **Trace Correlated Logs**| `http://10.1.75.53:3213/telemetry/logs` | `200 OK` | Colorized log viewer with TraceID |
| **Frontend Web Interface** | `http://10.1.75.53:4213/` | `200 OK` | Production React map interface |
| **SSH Terminal Access** | `ssh -p 6213 student@10.1.75.53` | `Active` | Remote container shell (Password authenticated) |

---

## 🚀 Local Installation & Quick Start

### 1. Clone Repository & Setup Virtual Environment
```bash
git clone https://github.com/sunilkumar2170/village-pond-planning-opentelemetry.git
cd village-pond-planning-opentelemetry
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Start Jaeger All-in-One Daemon
Download and run the Jaeger binary (or via Docker):
```bash
# Docker:
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  -p 4318:4318 \
  jaegertracing/all-in-one:1.60
```

### 3. Launch the Backend Service
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --reload
```

### 4. Trigger Analysis & Inspect Telemetry
```bash
curl -X POST "http://localhost:3000/analyzeContour" \
  -F "contour_map=@contours_1m.kml"
```
* **Jaeger Traces:** Open `http://localhost:16686` and search for service `village-pond-planning-service`.
* **Prometheus Metrics:** Open `http://localhost:3000/metrics`.
* **In-Memory Dashboard:** Open `http://localhost:3000/telemetry/dashboard`.
* **Live Correlated Logs:** Open `http://localhost:3000/telemetry/logs`.

---

## 📂 Core Repository Structure

```
├── main.py                     # FastAPI backend with 7 OTel child spans & metrics
├── telemetry.py                # OpenTelemetry setup (TracerProvider, Exporters, Formatter)
├── models.py                   # Pydantic schemas for requests and responses
├── terrain_processor.py        # Delaunay triangulation & elevation grid generation
├── catchment_analyzer.py       # D8 flow routing, local minima & BFS catchment tracing
├── kml_parser.py               # Spatial KML/KMZ geometry parser
├── rainfall_service.py         # Open-Meteo & NASA POWER meteorological yield retrieval
├── contours_1m.kml             # Sample 1-meter elevation contour dataset
├── requirements.txt            # Python dependencies (FastAPI, OTel SDK, Prometheus)
├── main.tex                    # LaTeX source code for the lab evaluation report
├── OPENTELEMETRY_REPORT.tex    # Standalone mirror of the LaTeX report
├── README.md                   # Technical documentation and setup guide
└── pondplan/                   # React + TypeScript frontend web interface
```

---

## 📜 Academic Integrity & AI Usage Declaration

> *AI was used to understand OpenTelemetry concepts, assist with code implementation and debugging, and improve the technical documentation.*
