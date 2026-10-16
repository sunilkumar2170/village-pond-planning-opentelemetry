"""
OpenTelemetry Instrumentation Module for Village Pond Planning System
Provides:
  - Distributed Tracing (OTLP gRPC/HTTP exporter to Jaeger + In-Memory trace storage)
  - Application & Hydrology Metrics (Prometheus /metrics endpoint)
  - Trace-Log Correlation (Logs enriched with trace_id and span_id)
"""

import time
import json
import logging
from typing import Optional, Dict, Any, List
from collections import deque

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# =====================================================================
# 1. SERVICE RESOURCE IDENTIFIER
# =====================================================================
SERVICE_NAME = "village-pond-planning-service"
SERVICE_VERSION = "2.0.0"
RESOURCE = Resource.create({
    "service.name": SERVICE_NAME,
    "service.version": SERVICE_VERSION,
    "deployment.environment": "production",
    "system.subsystem": "geospatial-hydrology-engine"
})

# =====================================================================
# 2. IN-MEMORY SPAN STORAGE (For Live Inspection & Fallback)
# =====================================================================
MAX_SAVED_SPANS = 200
SAVED_SPANS_DEQUE: deque = deque(maxlen=MAX_SAVED_SPANS)

class MemoryAndFileSpanExporter(SpanExporter):
    """Exports spans to in-memory deque and a structured JSON log file."""
    def __init__(self, log_filepath: str = "otel_traces.log"):
        self.log_filepath = log_filepath

    def export(self, spans: List[ReadableSpan]) -> SpanExportResult:
        try:
            with open(self.log_filepath, "a", encoding="utf-8") as f:
                for span in spans:
                    span_dict = {
                        "trace_id": format(span.context.trace_id, "032x"),
                        "span_id": format(span.context.span_id, "016x"),
                        "parent_id": format(span.parent.span_id, "016x") if span.parent else None,
                        "name": span.name,
                        "start_time_unix_nano": span.start_time,
                        "end_time_unix_nano": span.end_time,
                        "duration_ms": round((span.end_time - span.start_time) / 1_000_000, 3) if span.end_time and span.start_time else 0,
                        "status": span.status.status_code.name,
                        "attributes": dict(span.attributes) if span.attributes else {},
                        "events": [
                            {"name": e.name, "timestamp": e.timestamp, "attributes": dict(e.attributes)}
                            for e in span.events
                        ]
                    }
                    SAVED_SPANS_DEQUE.append(span_dict)
                    f.write(json.dumps(span_dict) + "\n")
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE

    def shutdown(self):
        pass


# =====================================================================
# 3. PROMETHEUS METRICS DEFINITIONS
# =====================================================================
METRIC_REQUESTS_TOTAL = Counter(
    "pond_analysis_requests_total",
    "Total number of pond catchment analysis requests",
    ["status", "input_type"]
)

METRIC_ANALYSIS_DURATION = Histogram(
    "pond_analysis_duration_seconds",
    "Total processing time for pond & catchment analysis",
    buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]
)

METRIC_CATCHMENT_AREA = Histogram(
    "catchment_area_hectares",
    "Distribution of calculated catchment areas in hectares",
    buckets=[1.0, 5.0, 10.0, 15.0, 25.0, 50.0, 100.0, 500.0]
)

METRIC_WATER_VOLUME = Histogram(
    "expected_water_volume_cubic_meters",
    "Distribution of estimated harvestable water volume in cubic meters",
    buckets=[10000, 50000, 100000, 150000, 250000, 500000, 1000000]
)

METRIC_ACTIVE_REQUESTS = Gauge(
    "active_pond_analysis_requests",
    "Number of currently processing analysis requests"
)

# =====================================================================
# 4. TRACE-LOG CORRELATION FORMATTER
# =====================================================================
class OTelLogFormatter(logging.Formatter):
    """Formats log messages with active TraceID and SpanID."""
    def format(self, record):
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and ctx.is_valid:
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
        else:
            record.trace_id = "0" * 32
            record.span_id = "0" * 16
        return super().format(record)


def setup_correlated_logging():
    logger = logging.getLogger("pondplan.telemetry")
    logger.setLevel(logging.INFO)
    
    formatter = OTelLogFormatter(
        "[%(asctime)s] [%(levelname)s] [trace_id=%(trace_id)s span_id=%(span_id)s] [%(name)s]: %(message)s"
    )
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    # File handler
    fh = logging.FileHandler("otel_application.log", encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    return logger

app_logger = setup_correlated_logging()

# =====================================================================
# 5. INITIALIZE OPENTELEMETRY TRACER & METRICS PROVIDER
# =====================================================================
tracer_provider = TracerProvider(resource=RESOURCE)

# Add In-Memory & File exporter (guarantees local traces recording)
memory_exporter = MemoryAndFileSpanExporter()
tracer_provider.add_span_processor(SimpleSpanProcessor(memory_exporter))

# Try adding OTLP gRPC exporter for Jaeger if available
try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    otlp_grpc_exporter = OTLPSpanExporter(endpoint="localhost:4317", insecure=True)
    tracer_provider.add_span_processor(BatchSpanProcessor(otlp_grpc_exporter))
    app_logger.info("Configured OTLP gRPC SpanExporter (localhost:4317)")
except Exception as e:
    app_logger.warning(f"OTLP gRPC exporter init skipped: {e}")

# Register global tracer
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(SERVICE_NAME, SERVICE_VERSION)


# =====================================================================
# 6. FASTAPI INSTRUMENTATION & OBSERVABILITY ENDPOINTS
# =====================================================================
def instrument_application(app: FastAPI):
    """Instruments FastAPI with OpenTelemetry and adds /metrics and /telemetry routes."""
    
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        excluded_urls="metrics,health,telemetry.*,favicon.ico"
    )

    @app.get("/metrics", tags=["Observability"])
    def prometheus_metrics():
        """Exposes OpenTelemetry and application metrics in standard Prometheus text format."""
        return HTMLResponse(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )

    @app.get("/telemetry/spans", tags=["Observability"])
    def get_recent_spans():
        """Returns recent traces and spans captured in OpenTelemetry memory."""
        return JSONResponse(content={
            "service_name": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "total_spans_in_memory": len(SAVED_SPANS_DEQUE),
            "spans": list(reversed(SAVED_SPANS_DEQUE))
        })

    @app.get("/telemetry/dashboard", tags=["Observability"])
    def telemetry_dashboard():
        """Built-in OpenTelemetry Visualizer Dashboard showing Traces, Spans, and Metrics."""
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>OpenTelemetry Observability Dashboard — PondPlan</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 16px; margin-bottom: 24px; }}
        h1 {{ margin: 0; font-size: 24px; color: #38bdf8; display: flex; align-items: center; gap: 10px; }}
        .badge {{ background: #0284c7; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: bold; color: white; }}
        .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 16px; }}
        .card h3 {{ margin: 0 0 8px 0; font-size: 13px; color: #94a3b8; text-transform: uppercase; }}
        .card .value {{ font-size: 28px; font-weight: bold; color: #10b981; }}
        .card .sub {{ font-size: 11px; color: #64748b; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; }}
        th, td {{ padding: 12px 16px; text-align: left; font-size: 13px; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
        tr:hover {{ background: #243247; }}
        .tag {{ font-family: monospace; font-size: 11px; padding: 2px 6px; border-radius: 4px; background: #334155; color: #38bdf8; margin-right: 4px; display: inline-block; }}
        .btn {{ background: #0284c7; color: white; border: none; padding: 8px 16px; border-radius: 8px; cursor: pointer; text-decoration: none; font-size: 13px; font-weight: 600; }}
        .btn:hover {{ background: #0369a1; }}
        .flame-bar {{ background: #38bdf8; height: 18px; border-radius: 4px; display: flex; align-items: center; padding-left: 6px; font-size: 10px; font-weight: bold; color: #0f172a; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>📡 OpenTelemetry Observability Dashboard</h1>
            <p style="margin: 4px 0 0 0; color: #94a3b8; font-size: 13px;">Service: <code style="color: #38bdf8;">{SERVICE_NAME}</code> v{SERVICE_VERSION} &bull; Environment: <code>production</code></p>
        </div>
        <div style="display: flex; gap: 12px;">
            <a href="/metrics" target="_blank" class="btn" style="background: #10b981;">📊 View Prometheus /metrics</a>
            <a href="http://localhost:16686" target="_blank" class="btn" style="background: #f59e0b;">🔥 Open Jaeger UI (16686)</a>
            <button onclick="location.reload()" class="btn">🔄 Refresh Traces</button>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h3>Captured Spans</h3>
            <div class="value" id="total-spans">{len(SAVED_SPANS_DEQUE)}</div>
            <div class="sub">In-Memory Circular Buffer</div>
        </div>
        <div class="card">
            <h3>Instrumentation Status</h3>
            <div class="value" style="color: #38bdf8;">Active</div>
            <div class="sub">FastAPI + OTel SDK 1.45.1</div>
        </div>
        <div class="card">
            <h3>Tracing Exporter</h3>
            <div class="value" style="font-size: 20px; color: #f59e0b;">OTLP / In-Memory</div>
            <div class="sub">gRPC:4317 &bull; MemoryBuffer</div>
        </div>
        <div class="card">
            <h3>Metrics Exporter</h3>
            <div class="value" style="font-size: 20px; color: #a855f7;">Prometheus</div>
            <div class="sub">Endpoint: /metrics</div>
        </div>
    </div>

    <h2 style="font-size: 18px; margin-bottom: 12px; color: #e2e8f0;">Recent OpenTelemetry Distributed Traces & Spans</h2>
    <table>
        <thead>
            <tr>
                <th>Span Name</th>
                <th>Trace ID</th>
                <th>Span ID</th>
                <th>Duration (ms)</th>
                <th>Status</th>
                <th>Key Attributes & Telemetry Data</th>
            </tr>
        </thead>
        <tbody id="spans-body">
"""
        for s in list(reversed(SAVED_SPANS_DEQUE))[:25]:
            attrs_html = "".join([f'<span class="tag">{k}={v}</span>' for k, v in list(s['attributes'].items())[:4]])
            dur = s['duration_ms']
            bar_w = min(max(int(dur * 2), 20), 100)
            html += f"""
            <tr>
                <td><strong>{s['name']}</strong></td>
                <td><code style="color: #94a3b8; font-size: 11px;">{s['trace_id'][:12]}...</code></td>
                <td><code style="color: #94a3b8; font-size: 11px;">{s['span_id']}</code></td>
                <td>
                    <div style="width: 120px; background: #334155; border-radius: 4px;">
                        <div class="flame-bar" style="width: {bar_w}%;">{dur}ms</div>
                    </div>
                </td>
                <td><span style="color: #10b981; font-weight: bold;">{s['status']}</span></td>
                <td>{attrs_html}</td>
            </tr>
            """
        html += """
        </tbody>
    </table>
</body>
</html>"""
        return HTMLResponse(content=html)

    @app.get("/telemetry/logs", tags=["Observability"])
    def view_correlated_logs():
        """Displays recent trace-correlated application logs with highlighted trace_id and span_id."""
        log_lines = []
        try:
            with open("otel_application.log", "r", encoding="utf-8") as f:
                log_lines = [l.strip() for l in f.readlines() if l.strip()]
        except Exception:
            pass

        rows = []
        for l in log_lines[-30:]:
            # Highlight trace_id and span_id
            formatted = l.replace("[INFO]", '<span style="color: #38bdf8; font-weight: bold;">[INFO]</span>')
            formatted = formatted.replace("[WARNING]", '<span style="color: #f59e0b; font-weight: bold;">[WARN]</span>')
            formatted = formatted.replace("[ERROR]", '<span style="color: #ef4444; font-weight: bold;">[ERROR]</span>')
            if "trace_id=" in formatted:
                import re
                formatted = re.sub(
                    r"trace_id=([a-f0-9]+)",
                    r'<span style="color: #10b981; font-weight: bold;">trace_id=\1</span>',
                    formatted
                )
                formatted = re.sub(
                    r"span_id=([a-f0-9]+)",
                    r'<span style="color: #a855f7; font-weight: bold;">span_id=\1</span>',
                    formatted
                )
            rows.append(f'<div style="padding: 6px 10px; border-bottom: 1px solid #1e293b; font-family: monospace; font-size: 12px; line-height: 1.6;">{formatted}</div>')

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>OpenTelemetry Trace-Correlated Logs</title>
    <style>
        body {{ background: #0f172a; color: #f8fafc; font-family: -apple-system, sans-serif; margin: 0; padding: 24px; }}
        h1 {{ color: #38bdf8; margin: 0 0 8px 0; font-size: 22px; }}
        .box {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; overflow: hidden; margin-top: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    </style>
</head>
<body>
    <h1>📜 OpenTelemetry Trace-Correlated Application Logs</h1>
    <p style="color: #94a3b8; font-size: 13px; margin: 0;">Service: <code>{SERVICE_NAME}</code> &bull; Showing recent entries with active <span style="color: #10b981; font-weight: bold;">trace_id</span> and <span style="color: #a855f7; font-weight: bold;">span_id</span></p>
    <div class="box">
        {"".join(rows)}
    </div>
</body>
</html>"""
        return HTMLResponse(content=html)

    app_logger.info("OpenTelemetry successfully instrumented on FastAPI application.")
