# OpenTelemetry Observability Implementation Report
## Distributed Tracing, Metrics, and Log Correlation in Village Pond Planning System

**Course:** Distributed Systems & Cloud Computing / Geospatial Engineering Capstone  
**Author:** Sunil Kumar (Roll No: 12342170)  
**Department:** Department of Computer Science and Engineering  
**Institution:** Indian Institute of Technology Bhilai (IIT Bhilai)  
**Date:** October 2026  

---

## 1. Executive Summary & Objective

In modern backend and distributed architectures, understanding runtime behavior, diagnosing latency bottlenecks, and triaging intermittent failures cannot rely on static print statements or unstructured log files. **OpenTelemetry (OTel)** is the Cloud Native Computing Foundation (CNCF) industry-standard, vendor-agnostic observability framework designed to collect, process, and export **telemetry data (Traces, Metrics, and Logs)**.

The objective of this assignment is to instrument the existing **Village Pond Planning System** (FastAPI backend and geospatial hydrology processing pipeline) with OpenTelemetry. Specifically, the implementation:
1. Instruments HTTP request lifecycles and business logic with **Distributed Traces** exported to **Jaeger** via **OTLP (OpenTelemetry Protocol)**.
2. Creates fine-grained domain sub-spans capturing Digital Elevation Model (DEM) construction, D8 flow direction, BFS catchment delineation, and SCS-CN runoff volume estimation.
3. Exposes real-time **Prometheus Application Metrics** (`/metrics`) tracking request counts, processing duration histograms, and calculated hydrological quantities.
4. Implements **Trace-Log Correlation**, ensuring every backend log record is automatically injected with its active `trace_id` and `span_id`.

---

## 2. Tools, Libraries, and Backend Services Used

| Component / Tool | Version | Role in Architecture |
| :--- | :--- | :--- |
| **`opentelemetry-api`** | `1.45.1` | Core OpenTelemetry interfaces and telemetry abstractions. |
| **`opentelemetry-sdk`** | `1.45.1` | Concrete TracerProvider, BatchSpanProcessor, and Span lifecycle engine. |
| **`opentelemetry-instrumentation-fastapi`** | `0.66b1` | Automatic ASGI middleware capturing incoming HTTP spans. |
| **`opentelemetry-exporter-otlp-proto-grpc`** | `1.45.1` | High-performance gRPC client streaming OTLP traces to Jaeger. |
| **`prometheus-client`** | `0.22.1` | Standard Prometheus metric exposition (`/metrics`). |
| **Jaeger All-in-One** | `v1.60.0` | Production-grade tracing collector, in-memory query engine, and flamegraph Web UI (`:16686`). |
| **FastAPI & Uvicorn** | `0.119.0` | Asynchronous ASGI Web framework serving endpoints on port `3000`. |
| **OpenTelemetry Dashboard** | `v2.0` | Custom live in-memory telemetry inspection dashboard (`/telemetry/dashboard`). |

---

## 3. Architecture & Implementation Details

```
 [ Client / Map Interface ]
            │ (HTTP POST /analyzeContour)
            ▼
┌────────────────────────────────────────────────────────────────────────┐
│  FastAPI Backend (village-pond-planning-service)                        │
│                                                                        │
│  FastAPIInstrumentor (Root Span: POST /analyzeContour)                │
│    │                                                                   │
│    ├── Span 1: kml.parse_contours                                      │
│    ├── Span 2: terrain.boundary_filtering (Shapely prep)               │
│    ├── Span 3: terrain.build_elevation_grid (Scipy 2m DEM)             │
│    ├── Span 4: pond.pick_optimal_location (Local minima detection)      │
│    ├── Span 5: hydrology.compute_d8_flow_and_catchment (D8 + BFS)     │
│    ├── Span 6: external.fetch_annual_rainfall (Open-Meteo Client)      │
│    └── Span 7: hydrology.estimate_water_volume_scs_cn (SCS-CN Model)   │
│                                                                        │
│  Prometheus Metrics Provider       OTel Log Formatter                  │
│  (Counter, Histograms, Gauge)      [trace_id=... span_id=...]          │
└────────────────────────────────────┬───────────────────────────────────┘
            │                        │
     OTLP gRPC (Port 4317)     Scrape (/metrics)
            ▼                        ▼
┌───────────────────────┐  ┌──────────────────────────────────┐
│   Jaeger UI (:16686)  │  │  Prometheus Metrics Endpoint     │
│ (Traces & Flamegraph) │  │  (/metrics on Port 3000)         │
└───────────────────────┘  └──────────────────────────────────┘
```

### 3.1 Distributed Tracing & Span Hierarchy
When a contour map or land parcel boundary is submitted to `/analyzeContour`, OpenTelemetry initiates a hierarchical trace tree:
- **Root Span**: `POST /analyzeContour` (captured automatically by `FastAPIInstrumentor`).
- **Domain Child Spans** (explicitly instrumented via `tracer.start_as_current_span`):
  1. `kml.parse_contours`: Measures time taken to parse XML/KML MultiGeometries. Sets attributes `kml.filename` and `kml.parsed_contour_count`.
  2. `terrain.boundary_filtering`: Measures Shapely prepared polygon spatial filtering. Sets bounding box bounds (`boundary.min_lon`, `boundary.max_lat`, etc.).
  3. `terrain.build_elevation_grid`: Traces Scipy cubic interpolation converting contour lines into a 2D matrix. Sets `dem.grid_rows`, `dem.grid_cols`, and elevation extremes (`dem.min_elevation_m`, `dem.max_elevation_m`).
  4. `pond.pick_optimal_location`: Traces the 8-connected local minima search algorithm. Records `pond.latitude`, `pond.longitude`, and `pond.elevation_m`.
  5. `hydrology.compute_d8_flow_and_catchment`: Traces steepest downward slope D8 calculations and upstream BFS traversal. Records `catchment.cell_count` and `catchment.area_hectares`.
  6. `external.fetch_annual_rainfall`: Traces outbound HTTP calls to Open-Meteo weather archives. Records `rainfall.annual_mm`.
  7. `hydrology.estimate_water_volume_scs_cn`: Traces the Soil Conservation Service Curve Number calculations. Records `scs_cn.curve_number`, `scs_cn.runoff_depth_mm`, and `scs_cn.expected_volume_m3`.

### 3.2 Application Metrics
The application instruments four key metric primitives exposed via `/metrics`:
- **`pond_analysis_requests_total`** *(Counter)*: Total number of requests processed, partitioned by labels `{status="success|error", input_type="kml_file|freehand_boundary"}`.
- **`pond_analysis_duration_seconds`** *(Histogram)*: End-to-end processing latency distribution with granular buckets (`0.05s`, `0.1s`, `0.2s`, `0.5s`, `1.0s`, `2.0s`, `5.0s`, `10.0s`).
- **`catchment_area_hectares`** *(Histogram)*: Distribution of catchment areas delineated.
- **`expected_water_volume_cubic_meters`** *(Histogram)*: Distribution of harvestable water volumes estimated.
- **`active_pond_analysis_requests`** *(Gauge)*: Real-time count of concurrent analysis jobs in flight.

### 3.3 Trace-Log Correlation
Logs are configured with a custom `OTelLogFormatter` that queries `trace.get_current_span().get_span_context()`. Every log line emitted during request execution is automatically tagged with the current `trace_id` and `span_id`:
```
[2026-10-16 12:49:58,231] [INFO] [trace_id=6e76b9c7d878fde72b211e0bb4a145c5 span_id=98453d4339b01e1f] [pondplan.telemetry]: Optimal pond located at (21.2499, 81.2899) with elevation 267.0m
```
This enables an operator viewing a log line in production to copy the `trace_id` and instantly inspect the corresponding flamegraph in Jaeger.

---

## 4. Verification, Execution, and Evidence

The OpenTelemetry stack was executed and verified using the automated test suite `test_telemetry.py` and live HTTP calls against the running application.

### Screenshot 1: Jaeger UI — Trace Search & Service Overview
*(URL: `http://localhost:16686/search?service=village-pond-planning-service`)*

- **What it demonstrates**: Demonstrates that the Jaeger Collector is receiving live traces streamed over OTLP gRPC (`port 4317`) from the `village-pond-planning-service`. Multiple operations are visible, showing total execution duration (e.g., `1.99s` for freehand boundary analysis, `2.08s` for full 1m KML contour analysis), number of spans (12 spans per trace), and timestamps.

### Screenshot 2: Jaeger UI — Detailed Flamegraph & Span Hierarchy
*(URL: `http://localhost:16686/trace/6e76b9c7d878fde72b211e0bb4a145c5`)*

- **What it demonstrates**: Shows the complete distributed trace flamegraph. The root span `POST /analyzeContour` branches into `process_contour_file`, which cleanly divides into the 7 sequential domain spans. The visual timeline clearly reveals where time is spent:
  - `external.fetch_annual_rainfall`: ~1113 ms (network latency to meteorological service).
  - `terrain.build_elevation_grid`: ~304 ms (Scipy grid interpolation).
  - `kml.parse_contours`: ~271 ms (XML spatial parsing).
  - `terrain.boundary_filtering`: ~132 ms (Shapely prepared polygon filtering).
  - `pond.pick_optimal_location`: ~112 ms (Local minima candidate evaluation).
  - `hydrology.compute_d8_flow_and_catchment`: ~28 ms (D8 matrix + BFS queue).
  - `hydrology.estimate_water_volume_scs_cn`: ~0.5 ms (Hydrological formulas).

### Screenshot 3: Jaeger UI — Span Semantic Attributes & Metadata
*(Clicking span `pond.pick_optimal_location` or `hydrology.estimate_water_volume_scs_cn`)*

- **What it demonstrates**: Shows custom domain attributes attached to spans:
  - `pond.latitude = 21.2499`
  - `pond.longitude = 81.2899`
  - `pond.elevation_m = 267.0`
  - `catchment.area_hectares = 2.65`
  - `rainfall.annual_mm = 1280.7`
  - `scs_cn.runoff_depth_mm = 1097.7`
  - `scs_cn.expected_volume_m3 = 29069.1`
  This proves that OpenTelemetry not only tracks execution timing but also contextually annotates domain-specific calculations.

### Screenshot 4: Prometheus Metrics Exposition (`/metrics`)
*(URL: `http://localhost:3000/metrics`)*

- **What it demonstrates**: Displays the raw Prometheus text-format output generated by the application. Shows counters incrementing (`pond_analysis_requests_total{input_type="freehand_boundary",status="success"} 1.0`), duration histograms recording latency distribution (`pond_analysis_duration_seconds_bucket`), and process metrics.

### Screenshot 5: Built-In OpenTelemetry Observability Dashboard
*(URL: `http://localhost:3000/telemetry/dashboard`)*

- **What it demonstrates**: Shows the in-memory telemetry dashboard built directly into the application. It summarizes total captured spans, active exporters, and displays a tabular view of all recent spans with microsecond-accurate durations and attribute tags.

### Screenshot 6: Correlated Application Logs (`otel_application.log`)
*(File: `otel_application.log`)*

- **What it demonstrates**: Displays structured log records demonstrating **Trace-Log Correlation**. Each log record carries the 32-character hexadecimal `trace_id` (e.g. `6e76b9c7d878fde72b211e0bb4a145c5`) and 16-character `span_id`.

---

## 5. Practical Value: How OpenTelemetry Helps Monitor, Debug, and Analyze

Through this implementation, OpenTelemetry provides critical operational advantages:

1. **Pinpointing Latency Bottlenecks (Amdahl's Law in Practice)**:
   - Without distributed tracing, an engineer observing a 2-second response time might assume the terrain interpolation or BFS flow algorithms are slow.
   - The Jaeger flamegraph immediately proved that **56% of total request time (1.11s out of 1.98s)** was spent waiting for the external Open-Meteo weather API call. In contrast, our local geospatial D8 and BFS algorithms took only **28 milliseconds**.
   - *Actionable Optimization*: This insight directly justified our 1.5s non-blocking timeout and caching layer for weather queries.

2. **Zero-Ambiguity Root Cause Analysis**:
   - In distributed or multi-threaded environments, logs from concurrent users get interleaved.
   - By correlating logs with `trace_id`, an engineer can filter logs by a single trace ID to view the exact chronological story of a specific transaction without noise from other concurrent users.

3. **Production SLI / SLO Monitoring with Metrics**:
   - The Prometheus `/metrics` histograms allow engineering teams to define Service Level Objectives (e.g., "95% of pond analyses must complete in under 2.5 seconds").
   - Metrics provide aggregate health trends (P95/P99 latencies, error spikes) before users report issues.

---

## 6. Conclusion

OpenTelemetry was successfully implemented and verified in the Village Pond Planning System. The solution provides end-to-end observability across the three pillars:
- **Traces** visualized in Jaeger UI with custom domain sub-spans.
- **Metrics** exported via standard Prometheus format.
- **Logs** correlated with unique trace and span identifiers.

The implementation is robust, production-ready, and delivers deep architectural insight into the performance and reliability of the geospatial hydrological engine.
