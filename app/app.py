"""Lab 3 demo application.

A small Flask service used as the workload for the Monitoring, Logging &
DevSecOps lab. It exposes:

* Prometheus metrics on ``/metrics``
* Structured JSON logs (stdout + optional file shipped by Filebeat -> Logstash -> Elasticsearch)
* Feature flags (file based, env overrides, runtime toggles, percentage rollout)
* Endpoints to simulate latency and errors so alerts and dashboards can be demonstrated
"""

import hmac
import json
import logging
import os
import random
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

from flask import Flask, Response, g, jsonify, render_template, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from feature_flags import FeatureFlags

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_NAME = os.getenv("APP_NAME", "lab3-app")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
MAX_ITEMS = 1000
MAX_NAME_LENGTH = 100
START_TIME = time.time()

# --------------------------------------------------------------------------- #
# Prometheus metrics (module level so they are registered only once)
# --------------------------------------------------------------------------- #
REQUEST_COUNT = Counter(
    "app_http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "app_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
IN_PROGRESS = Gauge("app_http_requests_in_progress", "HTTP requests currently being served")
ITEMS_GAUGE = Gauge("app_items_total", "Number of items stored in memory")
FLAG_ENABLED = Gauge("app_feature_flag_enabled", "Feature flag enabled state (1/0)", ["flag"])
FLAG_ROLLOUT = Gauge("app_feature_flag_rollout_percentage", "Feature flag rollout percentage", ["flag"])
APP_INFO = Gauge("app_info", "Application build information", ["version"])
ALERTS_RECEIVED = Counter("app_alerts_received_total", "Alerts received from Alertmanager", ["alertname", "status"])


# --------------------------------------------------------------------------- #
# Structured JSON logging
# --------------------------------------------------------------------------- #
class JsonFormatter(logging.Formatter):
    """Render log records as one JSON object per line (easy for Logstash)."""

    def format(self, record):
        payload = {
            "@timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": APP_NAME,
            "version": APP_VERSION,
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def build_logger():
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    logger.handlers.clear()
    formatter = JsonFormatter()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_file = os.getenv("LOG_FILE", "")
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def log_event(logger, level, message, **fields):
    logger.log(level, message, extra={"extra_fields": fields})


# --------------------------------------------------------------------------- #
# Application factory
# --------------------------------------------------------------------------- #
def create_app(flags_path=None):
    app = Flask(__name__)
    logger = build_logger()
    flags = FeatureFlags(flags_path or os.getenv("FLAGS_FILE", os.path.join(BASE_DIR, "config", "flags.json")))
    admin_token = os.getenv("ADMIN_TOKEN", "")
    items = []
    items_lock = threading.Lock()

    app.config["FLAGS"] = flags
    APP_INFO.labels(version=APP_VERSION).set(1)
    ITEMS_GAUGE.set(0)

    # ------------------------------ hooks -------------------------------- #
    @app.before_request
    def start_request():
        g.start_time = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        g.user_id = request.cookies.get("uid") or uuid.uuid4().hex
        IN_PROGRESS.inc()

    @app.after_request
    def finish_request(response):
        IN_PROGRESS.dec()
        endpoint = request.url_rule.rule if request.url_rule else "unmatched"
        elapsed = time.perf_counter() - g.get("start_time", time.perf_counter())
        REQUEST_COUNT.labels(request.method, endpoint, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(request.method, endpoint).observe(elapsed)

        # Security headers (checked by unit tests)
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'"

        if "uid" not in request.cookies:
            response.set_cookie("uid", g.user_id, max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax")

        if endpoint not in ("/metrics", "/health"):
            status = response.status_code
            level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
            log_event(
                logger,
                level,
                "request completed",
                event="http_request",
                request_id=g.get("request_id"),
                method=request.method,
                path=request.path,
                endpoint=endpoint,
                status=status,
                duration_ms=round(elapsed * 1000, 2),
                client_ip=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=request.headers.get("User-Agent", ""),
            )
        return response

    # ------------------------------ pages -------------------------------- #
    @app.route("/")
    def index():
        user_flags = {name: flags.is_enabled(name, g.user_id) for name in flags.names()}
        return render_template("index.html", flags=user_flags, version=APP_VERSION)

    @app.route("/health")
    def health():
        return jsonify(status="healthy", version=APP_VERSION, uptime_seconds=round(time.time() - START_TIME, 1))

    @app.route("/metrics")
    def metrics():
        for name, state in flags.summary().items():
            FLAG_ENABLED.labels(flag=name).set(1 if state["enabled"] else 0)
            FLAG_ROLLOUT.labels(flag=name).set(state["rollout_percentage"] if state["enabled"] else 0)
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    # ------------------------------ items API ---------------------------- #
    @app.route("/api/items", methods=["GET"])
    def list_items():
        with items_lock:
            return jsonify(items=list(items), count=len(items))

    @app.route("/api/items", methods=["POST"])
    def add_item():
        if flags.is_enabled("maintenance_mode", g.user_id):
            log_event(logger, logging.WARNING, "write rejected: maintenance mode", event="maintenance_block")
            return jsonify(error="Service is in maintenance mode, writes are disabled"), 503

        payload = request.get_json(silent=True) or {}
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            return jsonify(error="Field 'name' is required"), 400
        name = name.strip()
        if len(name) > MAX_NAME_LENGTH:
            return jsonify(error=f"Field 'name' must be at most {MAX_NAME_LENGTH} characters"), 400

        item = {"id": uuid.uuid4().hex[:8], "name": name, "created_at": datetime.now(timezone.utc).isoformat()}
        with items_lock:
            items.append(item)
            if len(items) > MAX_ITEMS:
                del items[0: len(items) - MAX_ITEMS]
            ITEMS_GAUGE.set(len(items))
        log_event(logger, logging.INFO, "item created", event="item_created", item_id=item["id"])
        return jsonify(item), 201

    # ------------------------------ feature flags ------------------------ #
    @app.route("/api/flags", methods=["GET"])
    def list_flags():
        return jsonify(flags.all(g.user_id))

    @app.route("/api/flags/<name>", methods=["POST"])
    def toggle_flag(name):
        if not admin_token:
            return jsonify(error="Runtime flag toggling is disabled (ADMIN_TOKEN not set)"), 403
        supplied = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(supplied.encode(), admin_token.encode()):
            log_event(logger, logging.WARNING, "unauthorised flag toggle attempt", event="auth_failure", flag=name)
            return jsonify(error="Invalid admin token"), 401
        if name not in flags.names():
            return jsonify(error=f"Unknown flag '{name}'"), 404
        payload = request.get_json(silent=True) or {}
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return jsonify(error="Field 'enabled' must be a boolean"), 400
        flags.set_runtime(name, enabled)
        log_event(logger, logging.INFO, "feature flag toggled", event="flag_toggled", flag=name, enabled=enabled)
        return jsonify(flag=name, enabled=enabled)

    # ------------------------------ chaos / demo ------------------------- #
    @app.route("/api/slow")
    def slow():
        delay = random.uniform(0.2, 2.0)  # nosec B311 - demo latency, not security related
        time.sleep(delay)
        return jsonify(message="slow response", delay_seconds=round(delay, 3))

    @app.route("/api/error")
    def error():
        log_event(logger, logging.ERROR, "simulated failure", event="simulated_error")
        return jsonify(error="Simulated internal server error"), 500

    # ------------------------------ alert sink --------------------------- #
    @app.route("/api/alerts", methods=["POST"])
    def receive_alerts():
        """Webhook used by Alertmanager so alerts also land in ELK."""
        payload = request.get_json(silent=True) or {}
        for alert in payload.get("alerts", []):
            labels = alert.get("labels", {})
            alertname = labels.get("alertname", "unknown")
            status = alert.get("status", "unknown")
            ALERTS_RECEIVED.labels(alertname=alertname, status=status).inc()
            log_event(
                logger,
                logging.WARNING,
                f"prometheus alert {alertname} is {status}",
                event="prometheus_alert",
                alertname=alertname,
                alert_status=status,
                severity=labels.get("severity", "none"),
                summary=alert.get("annotations", {}).get("summary", ""),
            )
        return jsonify(received=len(payload.get("alerts", [])))

    return app


if __name__ == "__main__":
    # Production-grade WSGI server that works on Windows, Linux and macOS.
    # Binds to all interfaces so the Prometheus container can scrape it via host.docker.internal.
    from waitress import serve

    os.environ.setdefault("LOG_FILE", os.path.join(BASE_DIR, "..", "logs", "app.log"))
    host = os.getenv("HOST", "0.0.0.0")  # nosec B104 - lab VM, needed for container scraping
    port = int(os.getenv("PORT", "5000"))
    print(f"Lab3 app listening on http://localhost:{port}")
    serve(create_app(), host=host, port=port, threads=8)
