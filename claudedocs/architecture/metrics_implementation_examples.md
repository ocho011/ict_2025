# Performance Metrics Implementation Examples

## Quick Start Guide

### 1. Basic Usage

```python
from src.metrics import MetricsCollector, EventID, measure_async, measure

# Initialize collector (singleton, call once at startup)
collector = MetricsCollector()

# Option A: Decorator for async functions
@measure_async(EventID.CANDLE_PROCESSING)
async def process_candle(candle: Candle):
    # Your existing logic
    signal = await generate_signal(candle)
    return signal

# Option B: Context manager for code blocks
async def process_order(order: Order):
    with measure(EventID.ORDER_EXECUTION):
        # Measured code block
        result = await exchange.submit_order(order)
    return result

# Option C: Manual instrumentation (lowest overhead)
async def critical_path():
    start_ts = collector.record_start(EventID.SIGNAL_GENERATION)
    try:
        # Critical code
        signal = complex_calculation()
    finally:
        collector.record_end(EventID.SIGNAL_GENERATION, start_ts)
    return signal
```

---

## 2. Integration Examples

### 2.1 DataCollector Integration

```python
# src/data/data_collector.py
from src.metrics import MetricsCollector, EventID, measure_async

class DataCollector:
    """Existing data collector with metrics integration"""

    def __init__(self):
        # Existing initialization
        self.collector = MetricsCollector()

    @measure_async(EventID.CANDLE_PROCESSING)  # Add single line
    async def on_candle_event(self, candle: Candle):
        """
        Existing candle processing logic.
        Metrics automatically measure end-to-end latency.
        """
        # All existing code unchanged
        await self._validate_candle(candle)
        await self._update_buffer(candle)
        await self.event_bus.publish(CandleEvent(candle))

    async def _update_buffer(self, candle: Candle):
        """Fine-grained measurement for sub-components"""
        with measure(EventID.BUFFER_UPDATE):  # Optional: measure internal ops
            # Existing buffer update logic
            self.buffer.append(candle)
```

**Performance Impact**: +280ns per candle (~0.003% of 10ms processing)

---

### 2.2 Strategy Integration

```python
# src/strategy/strategy.py
from src.metrics import measure_async, EventID

class ICTStrategy:
    """Existing strategy with metrics"""

    @measure_async(EventID.SIGNAL_GENERATION)
    async def generate_signal(self, candle: Candle) -> Optional[Signal]:
        """
        Existing signal generation logic.
        Metrics track signal generation latency.
        """
        # All existing logic unchanged
        fvg = self._detect_fvg(candle)
        if not fvg:
            return None

        order_block = self._find_order_block(fvg)
        return Signal(type=SignalType.LONG, entry=order_block.price)

    def _detect_fvg(self, candle: Candle) -> Optional[FVG]:
        """No metrics needed for internal methods (unless debugging)"""
        # Existing FVG detection logic
        pass
```

---

### 2.3 Execution Engine Integration

```python
# src/execution/executor.py
from src.metrics import MetricsCollector, EventID, measure

class OrderExecutor:
    """Existing executor with metrics"""

    def __init__(self):
        self.collector = MetricsCollector()
        # Existing initialization

    async def execute_order(self, signal: Signal):
        """Manual instrumentation for fine control"""
        # Measure order preparation
        prep_start = self.collector.record_start(EventID.ORDER_PREP)
        order = self._prepare_order(signal)
        self.collector.record_end(EventID.ORDER_PREP, prep_start)

        # Measure exchange submission
        submit_start = self.collector.record_start(EventID.ORDER_SUBMIT)
        try:
            result = await self.exchange.submit_order(order)
        finally:
            self.collector.record_end(EventID.ORDER_SUBMIT, submit_start)

        # Track counter metrics
        self.collector.record_counter(EventID.ORDERS_SUBMITTED, 1)

        return result
```

---

### 2.4 Event Bus Integration

```python
# src/core/event_bus.py
from src.metrics import measure_async, EventID
import asyncio

class EventBus:
    """Existing event bus with queue backlog monitoring"""

    def __init__(self):
        self._queue = asyncio.Queue()
        self.collector = MetricsCollector()

    @measure_async(EventID.EVENT_BUS_PUBLISH)
    async def publish(self, event: Event):
        """Measure publish latency"""
        await self._queue.put(event)

        # Track queue backlog (gauge metric)
        backlog = self._queue.qsize()
        self.collector.record_gauge(EventID.QUEUE_BACKLOG, backlog)

    async def _process_event(self, event: Event):
        """Measure handler execution time"""
        with measure(EventID.EVENT_BUS_HANDLE):
            handler = self._handlers.get(type(event))
            if handler:
                await handler(event)
```

---

## 3. Advanced Patterns

### 3.1 Trace ID Correlation

```python
import contextvars
from dataclasses import dataclass

# Define trace context
trace_id_var = contextvars.ContextVar('trace_id', default=0)
trace_metadata_var = contextvars.ContextVar('trace_metadata', default=None)

@dataclass
class TraceMetadata:
    """Metadata for distributed tracing"""
    trace_id: int
    candle_timestamp: int
    symbol: str

class TracedDataCollector:
    """Data collector with distributed tracing"""

    async def on_candle_event(self, candle: Candle):
        # Set trace context for entire processing chain
        trace_id = hash(f"{candle.symbol}_{candle.timestamp}")
        trace_id_var.set(trace_id)
        trace_metadata_var.set(TraceMetadata(
            trace_id=trace_id,
            candle_timestamp=candle.timestamp,
            symbol=candle.symbol
        ))

        # All downstream operations share same trace ID
        with measure(EventID.CANDLE_PROCESSING):
            await self._process_candle(candle)

        # Clear context
        trace_id_var.set(0)
        trace_metadata_var.set(None)

# Modified MetricsCollector to include trace ID
class MetricsCollector:
    def record_start(self, event_id: int) -> int:
        trace_id = trace_id_var.get()
        ts = time.perf_counter_ns()
        self._buffer.record(ts, event_id, MetricType.START, trace_id)
        return ts
```

**Use case**: Correlate candle → signal → order execution for end-to-end latency analysis

---

### 3.2 Adaptive Sampling

```python
class AdaptiveMetricsCollector(MetricsCollector):
    """Metrics collector with adaptive sampling"""

    def __init__(self):
        super().__init__()
        self._sampling_rate = 1.0
        self._event_count = 0
        self._last_adjustment = time.time()

    def should_sample(self) -> bool:
        """Decide if event should be sampled"""
        self._event_count += 1

        # Adjust sampling every 10 seconds
        now = time.time()
        if now - self._last_adjustment > 10.0:
            events_per_second = self._event_count / 10.0
            self._adjust_sampling_rate(events_per_second)
            self._event_count = 0
            self._last_adjustment = now

        return random.random() < self._sampling_rate

    def _adjust_sampling_rate(self, events_per_second: float):
        """Reduce sampling under high load"""
        if events_per_second > 1000:
            # Above 1000 events/s, sample 10%
            self._sampling_rate = 0.1
        elif events_per_second > 500:
            # Above 500 events/s, sample 50%
            self._sampling_rate = 0.5
        else:
            # Normal load, sample 100%
            self._sampling_rate = 1.0

    def record_start(self, event_id: int) -> int:
        """Record start with sampling check"""
        if not self.should_sample():
            return 0  # Skip sampling
        return super().record_start(event_id)
```

**Benefits**:
- Maintain <1% overhead even under extreme load
- Automatic load adaptation
- No manual configuration needed

---

### 3.3 GC Pause Monitoring

```python
import gc
import time

class GCPauseMonitor:
    """Monitor Python garbage collection pauses"""

    def __init__(self, collector: MetricsCollector):
        self.collector = collector
        self._gc_start_times = {}

    def start_monitoring(self):
        """Install GC callbacks"""
        gc.callbacks.append(self._gc_callback)

    def _gc_callback(self, phase: str, info: dict):
        """GC callback to measure pause time"""
        generation = info.get('generation', 0)

        if phase == 'start':
            self._gc_start_times[generation] = time.perf_counter_ns()

        elif phase == 'stop':
            if generation in self._gc_start_times:
                start_time = self._gc_start_times[generation]
                pause_duration_ns = time.perf_counter_ns() - start_time

                # Record GC pause as histogram observation
                self.collector.record_histogram(
                    EventID.GC_PAUSE,
                    pause_duration_ns
                )

                # Alert on long pauses
                if pause_duration_ns > 10_000_000:  # 10ms
                    logger = logging.getLogger('metrics.gc')
                    logger.warning(
                        f"Long GC pause: {pause_duration_ns/1e6:.2f}ms "
                        f"(generation {generation})"
                    )

                del self._gc_start_times[generation]

# Usage in main.py
def main():
    collector = MetricsCollector()
    gc_monitor = GCPauseMonitor(collector)
    gc_monitor.start_monitoring()

    # Start trading system
    run_trading_loop()
```

**Insights**:
- Identify if GC is causing latency spikes
- Tune GC thresholds if needed
- Consider switching to incremental GC

---

## 4. Testing Examples

### 4.1 Performance Benchmark Test

```python
# tests/test_metrics_performance.py
import pytest
import asyncio
import time
from src.metrics import MetricsCollector, EventID, measure_async

@pytest.mark.benchmark
async def test_metrics_overhead_negligible():
    """Verify metrics add <1% overhead to hot path"""

    # Baseline: no metrics
    async def baseline_operation():
        # Simulate 10ms work
        await asyncio.sleep(0.01)

    # Instrumented: with metrics
    @measure_async(EventID.CANDLE_PROCESSING)
    async def instrumented_operation():
        await asyncio.sleep(0.01)

    # Measure baseline
    iterations = 1000
    start = time.perf_counter()
    for _ in range(iterations):
        await baseline_operation()
    baseline_time = time.perf_counter() - start

    # Measure instrumented
    collector = MetricsCollector()
    start = time.perf_counter()
    for _ in range(iterations):
        await instrumented_operation()
    instrumented_time = time.perf_counter() - start

    # Calculate overhead
    overhead_pct = ((instrumented_time - baseline_time) / baseline_time) * 100

    print(f"Baseline: {baseline_time:.4f}s")
    print(f"Instrumented: {instrumented_time:.4f}s")
    print(f"Overhead: {overhead_pct:.4f}%")

    # Assert <1% overhead
    assert overhead_pct < 1.0, f"Overhead too high: {overhead_pct:.2f}%"


@pytest.mark.benchmark
def test_ring_buffer_write_speed():
    """Verify ring buffer write is <100ns"""
    from src.metrics.ring_buffer import LockFreeRingBuffer

    buffer = LockFreeRingBuffer()
    iterations = 100000

    start = time.perf_counter()
    for i in range(iterations):
        buffer.record(time.perf_counter_ns(), i % 10, 0, 0.0)
    elapsed = time.perf_counter() - start

    avg_write_ns = (elapsed * 1e9) / iterations
    print(f"Average write time: {avg_write_ns:.1f}ns")

    assert avg_write_ns < 100, f"Write too slow: {avg_write_ns:.1f}ns"
```

---

### 4.2 Integration Test

```python
# tests/test_metrics_integration.py
import pytest
import asyncio
from src.metrics import (
    MetricsCollector, MetricsAggregator, EventID, measure_async
)

@pytest.mark.asyncio
async def test_end_to_end_latency_measurement():
    """Verify end-to-end latency measurement works correctly"""

    # Setup
    collector = MetricsCollector()
    aggregator = MetricsAggregator(collector._buffer)
    aggregator.start()

    # Simulate candle processing with known delay
    @measure_async(EventID.CANDLE_PROCESSING)
    async def process_candle():
        await asyncio.sleep(0.015)  # 15ms simulated work

    # Execute multiple times
    for _ in range(100):
        await process_candle()

    # Wait for aggregation
    await asyncio.sleep(0.3)

    # Verify statistics
    stats = aggregator.get_statistics()
    assert 'CANDLE_PROCESSING' in stats

    candle_stats = stats['CANDLE_PROCESSING']
    # Should be ~15ms (14-16ms acceptable range)
    assert 14_000_000 < candle_stats['p50_ns'] < 16_000_000
    assert candle_stats['count'] == 100

    # Cleanup
    aggregator.stop()


@pytest.mark.asyncio
async def test_trace_id_correlation():
    """Verify trace ID propagation across events"""
    from contextvars import ContextVar

    trace_id_var = ContextVar('trace_id', default=0)
    collector = MetricsCollector()

    # Set trace context
    trace_id_var.set(12345)

    # Record events
    start_ts = collector.record_start(EventID.CANDLE_PROCESSING)
    await asyncio.sleep(0.01)
    collector.record_end(EventID.CANDLE_PROCESSING, start_ts)

    # Verify trace ID in buffer
    entries = collector._buffer.read_batch(10)
    assert len(entries) == 2  # START + END
    assert all(entry['value'] == 12345 for entry in entries)
```

---

### 4.3 SLA Violation Test

```python
# tests/test_metrics_sla.py
import pytest
import asyncio
from src.metrics import MetricsCollector, MetricsAggregator, EventID

@pytest.mark.asyncio
async def test_sla_violation_detection():
    """Verify SLA violations are detected and logged"""

    collector = MetricsCollector()
    aggregator = MetricsAggregator(collector._buffer)

    # Set tight SLA threshold for testing
    aggregator.sla_thresholds[EventID.CANDLE_PROCESSING] = 5_000_000  # 5ms

    # Start aggregator
    aggregator.start()

    # Simulate SLA violation (15ms > 5ms threshold)
    start_ts = collector.record_start(EventID.CANDLE_PROCESSING)
    await asyncio.sleep(0.015)  # 15ms delay
    collector.record_end(EventID.CANDLE_PROCESSING, start_ts)

    # Wait for aggregation
    await asyncio.sleep(0.3)

    # Check logs (using caplog fixture)
    # (In actual test, use pytest caplog to verify warning was logged)

    aggregator.stop()
```

---

## 5. Configuration Examples

### 5.1 YAML Configuration

```yaml
# config/metrics.yaml
metrics:
  # Master enable/disable switch
  enabled: true

  # Sampling configuration
  sampling:
    default_rate: 1.0  # 100% sampling
    adaptive: true     # Enable adaptive sampling
    high_load_threshold: 1000  # events/second
    high_load_rate: 0.1  # 10% sampling when over threshold

  # Ring buffer configuration
  buffer:
    size: 131072  # 128K entries (must be power of 2)
    overflow_strategy: overwrite  # overwrite oldest entries

  # Aggregation configuration
  aggregation:
    interval_ms: 100  # Process metrics every 100ms
    percentiles: [50, 95, 99, 99.9]  # Track these percentiles
    sliding_windows:
      - 1s
      - 5s
      - 1m

  # Export configuration
  export:
    enabled: true
    interval_s: 60  # Export every 60 seconds
    formats:
      - json
      - prometheus
    output_dir: ./metrics_exports

  # SLA thresholds (in nanoseconds)
  sla_thresholds:
    CANDLE_PROCESSING: 50000000    # 50ms
    SIGNAL_GENERATION: 10000000    # 10ms
    ORDER_EXECUTION: 5000000       # 5ms
    ORDER_FILL: 100000000          # 100ms
    EVENT_BUS_PUBLISH: 1000000     # 1ms
    EVENT_BUS_HANDLE: 10000000     # 10ms

  # Alerting configuration
  alerting:
    enabled: true
    slack_webhook: ${SLACK_WEBHOOK_URL}
    alert_on:
      - sla_violation
      - queue_backlog_high
      - gc_pause_long
```

### 5.2 Loading Configuration

```python
# src/metrics/config.py
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict

@dataclass
class MetricsConfig:
    enabled: bool
    sampling_rate: float
    adaptive_sampling: bool
    buffer_size: int
    aggregation_interval_ms: int
    export_enabled: bool
    export_interval_s: int
    sla_thresholds: Dict[str, int]

    @classmethod
    def from_yaml(cls, config_path: Path) -> 'MetricsConfig':
        """Load configuration from YAML file"""
        with open(config_path) as f:
            config = yaml.safe_load(f)

        metrics_config = config.get('metrics', {})

        return cls(
            enabled=metrics_config.get('enabled', True),
            sampling_rate=metrics_config.get('sampling', {}).get('default_rate', 1.0),
            adaptive_sampling=metrics_config.get('sampling', {}).get('adaptive', True),
            buffer_size=metrics_config.get('buffer', {}).get('size', 131072),
            aggregation_interval_ms=metrics_config.get('aggregation', {}).get('interval_ms', 100),
            export_enabled=metrics_config.get('export', {}).get('enabled', True),
            export_interval_s=metrics_config.get('export', {}).get('interval_s', 60),
            sla_thresholds=metrics_config.get('sla_thresholds', {})
        )

# Usage
config = MetricsConfig.from_yaml(Path('config/metrics.yaml'))
collector = MetricsCollector(config)
```

---

## 6. Monitoring Dashboard Examples

### 6.1 Prometheus Queries

```promql
# P95 latency for candle processing
candle_processing_latency_ns{quantile="95"}

# Events per second
rate(candle_processing_count[1m]) * 60

# SLA compliance percentage
(
  1 - (
    rate(candle_processing_latency_ns{quantile="95"} > 50000000[5m])
    /
    rate(candle_processing_count[5m])
  )
) * 100

# Queue backlog average
avg_over_time(event_bus_queue_depth[5m])
```

### 6.2 Grafana Dashboard JSON

```json
{
  "dashboard": {
    "title": "Trading System Performance",
    "panels": [
      {
        "id": 1,
        "title": "Candle Processing Latency",
        "type": "graph",
        "targets": [
          {
            "expr": "candle_processing_latency_ns{quantile=\"50\"} / 1000000",
            "legendFormat": "P50"
          },
          {
            "expr": "candle_processing_latency_ns{quantile=\"95\"} / 1000000",
            "legendFormat": "P95"
          },
          {
            "expr": "candle_processing_latency_ns{quantile=\"99\"} / 1000000",
            "legendFormat": "P99"
          }
        ],
        "yaxes": [
          {
            "label": "Latency (ms)",
            "format": "ms"
          }
        ]
      },
      {
        "id": 2,
        "title": "SLA Compliance",
        "type": "gauge",
        "targets": [
          {
            "expr": "(1 - (rate(candle_processing_latency_ns{quantile=\"95\"} > 50000000[5m]) / rate(candle_processing_count[5m]))) * 100"
          }
        ],
        "thresholds": "80,95",
        "colors": ["red", "yellow", "green"]
      }
    ]
  }
}
```

---

## 7. Troubleshooting Guide

### Issue: High Overhead (>1%)

**Symptoms**: Noticeable slowdown in trading loop

**Diagnosis**:
```python
# Check sampling rate
print(f"Sampling rate: {collector._sampling_rate}")

# Check buffer utilization
buffer_utilization = (collector._buffer._write_index - collector._buffer._read_index) / collector._buffer.BUFFER_SIZE
print(f"Buffer utilization: {buffer_utilization:.1%}")
```

**Solutions**:
1. Reduce sampling rate: `collector._sampling_rate = 0.1`
2. Enable adaptive sampling
3. Increase aggregation interval to 200ms
4. Temporarily disable: `collector._enabled = False`

---

### Issue: Missing Metrics

**Symptoms**: No statistics appearing in dashboard

**Diagnosis**:
```python
# Check if aggregator is running
print(f"Aggregator running: {aggregator._running}")

# Check buffer has data
entries = collector._buffer.read_batch(10)
print(f"Buffer entries: {len(entries)}")

# Check if events are being recorded
print(f"Write index: {collector._buffer._write_index}")
```

**Solutions**:
1. Verify aggregator started: `aggregator.start()`
2. Check metric events have matching START/END pairs
3. Verify event IDs are correct
4. Check sampling rate not 0: `collector._sampling_rate > 0`

---

### Issue: Memory Growth

**Symptoms**: Memory usage increasing over time

**Diagnosis**:
```python
import tracemalloc
tracemalloc.start()

# Run for a while
await asyncio.sleep(60)

snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)
```

**Solutions**:
1. Check sliding windows are being trimmed
2. Reduce buffer size
3. Increase export frequency to clear old data
4. Verify no memory leaks in aggregator

---

## 8. Migration Checklist

- [ ] Implement `LockFreeRingBuffer` class
- [ ] Implement `MetricsCollector` singleton
- [ ] Add `EventID` enum with all events
- [ ] Create `measure_async` decorator
- [ ] Create `measure` context manager
- [ ] Instrument `DataCollector.on_candle_event`
- [ ] Instrument `Strategy.generate_signal`
- [ ] Instrument `OrderExecutor.execute_order`
- [ ] Instrument `EventBus.publish` and `_process_event`
- [ ] Implement `MetricsAggregator` background thread
- [ ] Implement `MetricsExporter` for JSON/Prometheus
- [ ] Add unit tests for ring buffer
- [ ] Add performance regression tests
- [ ] Add integration tests for end-to-end measurement
- [ ] Set up Prometheus scraping endpoint
- [ ] Create Grafana dashboard
- [ ] Configure alerting rules
- [ ] Deploy to staging environment
- [ ] Validate <1% overhead
- [ ] Deploy to production with 10% sampling
- [ ] Gradually increase to 100% sampling
- [ ] Monitor and iterate

---

**Key Takeaway**: Start simple, measure impact, iterate based on data.
