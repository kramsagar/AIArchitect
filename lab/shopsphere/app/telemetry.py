"""OpenTelemetry setup: traces, metrics and logs over OTLP to the collector.

Configured with standard OTEL_* env vars (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME,
OTEL_RESOURCE_ATTRIBUTES, OTEL_SEMCONV_STABILITY_OPT_IN=http), so the same code works anywhere."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

VERSION = os.getenv("APP_VERSION", "1.0.0")


class JsonFormatter(logging.Formatter):
    """stdout JSON with trace correlation, so `docker logs` lines can be joined to Jaeger traces."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = trace.get_current_span().get_span_context()
        doc = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if ctx.is_valid:
            doc["trace_id"] = format(ctx.trace_id, "032x")
            doc["span_id"] = format(ctx.span_id, "016x")
        doc.update({k[5:]: v for k, v in record.__dict__.items() if k.startswith("shop.")})
        if record.exc_info:
            doc["exception"] = self.formatException(record.exc_info)
        return json.dumps(doc, default=str)


def setup(service_name: str) -> None:
    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", service_name),
            "service.namespace": "shopsphere",
            "service.version": VERSION,
            "service.instance.id": socket.gethostname(),
            "deployment.environment.name": os.getenv("DEPLOY_ENV", "lab"),
        }
    )
    enabled = os.getenv("OTEL_SDK_DISABLED", "false").lower() != "true"

    tracer_provider = TracerProvider(resource=resource)
    meter_readers = []
    logger_provider = LoggerProvider(resource=resource)
    if enabled:
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        meter_readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10_000))
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=meter_readers))
    set_logger_provider(logger_provider)

    root = logging.getLogger()
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(JsonFormatter())
    root.handlers = [stdout, LoggingHandler(level=logging.INFO, logger_provider=logger_provider)]

    AsyncPGInstrumentor().instrument()
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()


def log(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    """Structured log: fields go to stdout JSON and become OTel log attributes (searchable in Splunk)."""
    logger.log(level, msg, extra={f"shop.{k}": v for k, v in fields.items()})
