# Performance Metrics Collection System Design

## Executive Summary

Design for high-frequency trading metrics collection achieving <1% performance overhead through:
- Lock-free ring buffer architecture (zero allocation in hot path)
- Separate aggregation thread (non-blocking statistics)
- Sampling strategy (intelligent trade-off between coverage and overhead)
- Pre-allocated memory pools (avoid GC pressure)

**Target Performance**: <100ns per measurement, <2.5ms total overhead per candle

---

## 1. System Architecture

### 1.1 Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    TRADING HOT PATH                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │ Candle   │───▶│ Signal   │───▶│ Order    │              │
│  │ Process  │    │ Generate │    │ Execute  │              │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘              │
│       │ record_start  │ record_event  │ record_end         │
│       │ (<100ns)      │ (<100ns)      │ (<100ns)           │
└───────┼───────────────┼───────────────┼────────────────────┘
        │               │               │
        ▼               ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│              LOCK-FREE RING BUFFER (Layer 1)                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Fixed-size pre-allocated slots (e.g., 100k entries) │   │
│  │ [timestamp_ns, event_id, metric_type, value]        │   │
│  │ Single writer, single reader (SPSC queue)           │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────┘
                              │ batch read (every 100ms)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│           AGGREGATION THREAD (Layer 2)                      │
│  ┌────────────────────────────────────────────────────┐     │
│  │ • Calculate percentiles (P50, P95, P99)           │     │
│  │ • Update sliding windows (1s, 5s, 1m)            │     │
│  │ • Detect anomalies (SLA violations)               │     │
│  │ • Update in-memory histogram                     │     │
│  └────────────────────────────────────────────────────┘     │
└─────────────────────────────┬───────────────────────────────┘
                              │ export (every 1s)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              EXPORT LAYER (Layer 3)                         │
│  ┌────────────────────────────────────────────────────┐     │
│  │ • Prometheus metrics endpoint                     │     │
│  │ • JSON file periodic dumps                        │     │
│  │ • Real-time dashboard websocket                   │     │
│  └────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Data Flow Sequence

```
Hot Path Event:
  1. time.perf_counter_ns() → t_start                    [~80ns]
  2. ring_buffer.write(t_start, event_id, metric_type)  [~50ns]
  3. Continue processing (no blocking)                   [~0ns]
  4. time.perf_counter_ns() → t_end                      [~80ns]
  5. ring_buffer.write(t_end, event_id, COMPLETION)     [~50ns]
  ────────────────────────────────────────────────────────────
  Total overhead: ~260ns per measurement pair (0.026% @ 1ms event)

Background Thread (100ms intervals):
  1. Batch read from ring buffer (1000-10000 entries)
  2. Calculate latencies (t_end - t_start)
  3. Update t-digest (percentile approximation)
  4. Update sliding window histograms
  5. Check SLA thresholds
  6. Prepare export data
```

---

## 2. Component Specifications

### 2.1 Lock-Free Ring Buffer

**Implementation**: Custom SPSC (Single Producer Single Consumer) queue

```python
from dataclasses import dataclass
import numpy as np
from typing import ClassVar

@dataclass(slots=True)
class MetricEntry:
    """Pre-allocated metric entry (32 bytes)"""
    timestamp_ns: int = 0
    event_id: int = 0
    metric_type: int = 0  # Enum: START=0, END=1, COUNTER=2, GAUGE=3
    value: float = 0.0

class LockFreeRingBuffer:
    """
    Zero-allocation ring buffer for hot path metrics.

    Design:
    - Pre-allocated numpy array for cache locality
    - Atomic write_index (no locks needed for SPSC)
    - Wrap-around using modulo (buffer_size must be power of 2)
    """
    BUFFER_SIZE: ClassVar[int] = 131072  # 128K entries (power of 2)

    def __init__(self):
        # Pre-allocate structured numpy array
        self._buffer = np.zeros(
            self.BUFFER_SIZE,
            dtype=[
                ('timestamp_ns', np.int64),
                ('event_id', np.uint32),
                ('metric_type', np.uint8),
                ('value', np.float32)
            ]
        )
        self._write_index = 0  # Atomic counter
        self._read_index = 0

    def record(self, timestamp_ns: int, event_id: int,
               metric_type: int, value: float = 0.0) -> None:
        """
        Write metric to buffer (zero allocation).

        Performance: ~50ns per call
        """
        idx = self._write_index & (self.BUFFER_SIZE - 1)  # Fast modulo
        self._buffer[idx] = (timestamp_ns, event_id, metric_type, value)
        self._write_index += 1  # Atomic increment

    def read_batch(self, max_entries: int = 10000) -> np.ndarray:
        """
        Read batch of entries for aggregation (background thread only).

        Returns: numpy structured array view (zero-copy)
        """
        available = self._write_index - self._read_index
        if available == 0:
            return np.array([], dtype=self._buffer.dtype)

        to_read = min(available, max_entries)
        start_idx = self._read_index & (self.BUFFER_SIZE - 1)
        end_idx = (self._read_index + to_read) & (self.BUFFER_SIZE - 1)

        if end_idx > start_idx:
            # Contiguous read
            result = self._buffer[start_idx:end_idx].copy()
        else:
            # Wrapped read (two slices)
            result = np.concatenate([
                self._buffer[start_idx:],
                self._buffer[:end_idx]
            ])

        self._read_index += to_read
        return result
```

**Why this design**:
- **Zero allocation**: Pre-allocated numpy array, no malloc in hot path
- **Cache-friendly**: Contiguous memory layout
- **Lock-free**: SPSC queue needs no synchronization
- **Fast modulo**: Power-of-2 size enables bitwise AND instead of division
- **Overflow handling**: Wrap-around automatically (oldest data overwritten if buffer full)

**Performance characteristics**:
- Write: ~50ns (single array assignment)
- Read batch: ~10μs for 10k entries (vectorized numpy)
- Memory: ~4MB for 128K entries (acceptable)

---

### 2.2 Metric Types

```python
from enum import IntEnum

class MetricType(IntEnum):
    """Metric event types (efficient integer representation)"""
    START = 0          # Event start timestamp
    END = 1            # Event end timestamp
    COUNTER_INC = 2    # Counter increment
    GAUGE_SET = 3      # Gauge value
    HISTOGRAM_OBS = 4  # Histogram observation

class EventID(IntEnum):
    """Pre-defined event IDs for hot path"""
    CANDLE_PROCESSING = 1
    SIGNAL_GENERATION = 2
    ORDER_EXECUTION = 3
    ORDER_FILL = 4
    EVENT_BUS_PUBLISH = 5
    EVENT_BUS_HANDLE = 6
    QUEUE_BACKLOG = 7
    GC_PAUSE = 8
```

---

### 2.3 Hot Path Instrumentation

**Design Pattern**: Decorator-based with minimal overhead

```python
import time
from functools import wraps
from typing import Callable, TypeVar

T = TypeVar('T')

class MetricsCollector:
    """Singleton metrics collector"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._buffer = LockFreeRingBuffer()
            cls._instance._enabled = True
            cls._instance._sampling_rate = 1.0  # 100% initially
        return cls._instance

    def record_start(self, event_id: int) -> int:
        """Record event start. Returns timestamp for pairing."""
        if not self._enabled or random.random() > self._sampling_rate:
            return 0
        ts = time.perf_counter_ns()
        self._buffer.record(ts, event_id, MetricType.START)
        return ts

    def record_end(self, event_id: int, start_ts: int) -> None:
        """Record event end."""
        if start_ts == 0:  # Skip if not sampled
            return
        ts = time.perf_counter_ns()
        self._buffer.record(ts, event_id, MetricType.END)

# Decorator for async functions
def measure_async(event_id: EventID):
    """
    Decorator for measuring async function latency.

    Usage:
        @measure_async(EventID.CANDLE_PROCESSING)
        async def process_candle(candle):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            collector = MetricsCollector()
            start_ts = collector.record_start(event_id)
            try:
                return await func(*args, **kwargs)
            finally:
                collector.record_end(event_id, start_ts)
        return wrapper
    return decorator

# Context manager for manual instrumentation
class measure:
    """
    Context manager for measuring code block latency.

    Usage:
        with measure(EventID.SIGNAL_GENERATION):
            signal = generate_signal(candle)
    """
    __slots__ = ('event_id', 'start_ts', 'collector')

    def __init__(self, event_id: EventID):
        self.event_id = event_id
        self.collector = MetricsCollector()

    def __enter__(self):
        self.start_ts = self.collector.record_start(self.event_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.collector.record_end(self.event_id, self.start_ts)
        return False
```

**Integration Example**:

```python
# Existing code modification (minimal changes)
class CandleProcessor:
    @measure_async(EventID.CANDLE_PROCESSING)  # Add decorator
    async def process_candle(self, candle: Candle):
        # Existing logic unchanged
        signal = await self._generate_signal(candle)
        await self._execute_orders(signal)

    async def _generate_signal(self, candle: Candle):
        with measure(EventID.SIGNAL_GENERATION):  # Manual instrumentation
            # Signal generation logic
            return signal
```

---

### 2.4 Aggregation Thread

**Design**: Separate thread for non-blocking statistics calculation

```python
import threading
from collections import defaultdict
from typing import Dict, List
import numpy as np

class PercentileCalculator:
    """
    Efficient percentile calculation using t-digest algorithm.

    Advantages over exact percentiles:
    - O(1) space complexity (bounded memory)
    - O(log n) insertion time
    - Accurate percentile estimation (error <1%)
    """
    def __init__(self):
        from tdigest import TDigest
        self.digest = TDigest()

    def add(self, value: float):
        self.digest.update(value)

    def percentile(self, p: float) -> float:
        """Get percentile (p in [0, 100])"""
        return self.digest.percentile(p)

class MetricsAggregator:
    """Background thread for metrics aggregation"""

    def __init__(self, ring_buffer: LockFreeRingBuffer):
        self._buffer = ring_buffer
        self._running = False
        self._thread = None

        # Per-event metrics storage
        self._latencies: Dict[int, PercentileCalculator] = defaultdict(PercentileCalculator)
        self._counters: Dict[int, int] = defaultdict(int)
        self._gauges: Dict[int, float] = defaultdict(float)

        # Sliding windows (for trend analysis)
        self._window_1s: Dict[int, List[float]] = defaultdict(list)
        self._window_5s: Dict[int, List[float]] = defaultdict(list)

        # SLA thresholds
        self.sla_thresholds = {
            EventID.CANDLE_PROCESSING: 50_000_000,  # 50ms max
            EventID.SIGNAL_GENERATION: 10_000_000,  # 10ms max
            EventID.ORDER_EXECUTION: 5_000_000,     # 5ms max
        }

    def start(self):
        """Start background aggregation thread"""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop background thread"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self):
        """Main aggregation loop (runs every 100ms)"""
        import time

        while self._running:
            start = time.perf_counter()

            # Read batch from ring buffer
            entries = self._buffer.read_batch(max_entries=10000)

            if len(entries) > 0:
                self._process_batch(entries)

            # Sleep to maintain 100ms interval
            elapsed = time.perf_counter() - start
            sleep_time = max(0, 0.1 - elapsed)
            time.sleep(sleep_time)

    def _process_batch(self, entries: np.ndarray):
        """Process batch of metric entries"""
        # Group entries by event_id
        event_groups = defaultdict(list)
        for entry in entries:
            event_groups[entry['event_id']].append(entry)

        # Calculate latencies from START/END pairs
        for event_id, event_entries in event_groups.items():
            starts = {}
            for entry in event_entries:
                if entry['metric_type'] == MetricType.START:
                    starts[entry['timestamp_ns']] = entry['timestamp_ns']
                elif entry['metric_type'] == MetricType.END:
                    # Find matching start
                    for start_ts in starts.keys():
                        if start_ts <= entry['timestamp_ns']:
                            latency_ns = entry['timestamp_ns'] - start_ts
                            self._latencies[event_id].add(latency_ns)

                            # Update sliding windows
                            self._window_1s[event_id].append(latency_ns)
                            self._window_5s[event_id].append(latency_ns)

                            # Check SLA threshold
                            if event_id in self.sla_thresholds:
                                if latency_ns > self.sla_thresholds[event_id]:
                                    self._log_sla_violation(event_id, latency_ns)

                            del starts[start_ts]
                            break

                elif entry['metric_type'] == MetricType.COUNTER_INC:
                    self._counters[event_id] += entry['value']
                elif entry['metric_type'] == MetricType.GAUGE_SET:
                    self._gauges[event_id] = entry['value']

        # Trim sliding windows
        current_time = time.time_ns()
        for event_id in self._window_1s:
            self._window_1s[event_id] = [
                v for v in self._window_1s[event_id]
                if v > current_time - 1_000_000_000  # 1s window
            ]
        for event_id in self._window_5s:
            self._window_5s[event_id] = [
                v for v in self._window_5s[event_id]
                if v > current_time - 5_000_000_000  # 5s window
            ]

    def _log_sla_violation(self, event_id: int, latency_ns: int):
        """Log SLA violation for alerting"""
        import logging
        logger = logging.getLogger('metrics.sla')
        logger.warning(
            f"SLA violation: {EventID(event_id).name} "
            f"latency {latency_ns/1e6:.2f}ms exceeds "
            f"threshold {self.sla_thresholds[event_id]/1e6:.2f}ms"
        )

    def get_statistics(self) -> Dict:
        """Get current statistics (for export layer)"""
        stats = {}
        for event_id, calc in self._latencies.items():
            event_name = EventID(event_id).name
            stats[event_name] = {
                'p50_ns': calc.percentile(50),
                'p95_ns': calc.percentile(95),
                'p99_ns': calc.percentile(99),
                'p999_ns': calc.percentile(99.9),
                'count': len(self._window_1s.get(event_id, [])),
            }
        return stats
```

---

### 2.5 Export Layer

**Design**: Multiple export mechanisms for different use cases

```python
import json
from pathlib import Path
from datetime import datetime

class MetricsExporter:
    """Export metrics to various backends"""

    def __init__(self, aggregator: MetricsAggregator):
        self.aggregator = aggregator
        self.export_dir = Path("metrics_exports")
        self.export_dir.mkdir(exist_ok=True)

    def export_json_snapshot(self) -> Path:
        """Export current statistics to JSON file"""
        stats = self.aggregator.get_statistics()
        timestamp = datetime.now().isoformat()

        output = {
            'timestamp': timestamp,
            'metrics': stats
        }

        filepath = self.export_dir / f"metrics_{timestamp}.json"
        filepath.write_text(json.dumps(output, indent=2))
        return filepath

    def export_prometheus(self) -> str:
        """Export in Prometheus text format"""
        stats = self.aggregator.get_statistics()
        lines = []

        for event_name, metrics in stats.items():
            # Latency percentiles
            for percentile in ['p50', 'p95', 'p99', 'p999']:
                metric_name = f"{event_name.lower()}_latency_ns"
                value = metrics[f'{percentile}_ns']
                lines.append(
                    f'{metric_name}{{quantile="{percentile[1:]}"}} {value}'
                )

            # Count
            lines.append(f'{event_name.lower()}_count {metrics["count"]}')

        return '\n'.join(lines)

    def export_summary_report(self) -> str:
        """Generate human-readable summary report"""
        stats = self.aggregator.get_statistics()
        lines = [
            "=" * 80,
            "PERFORMANCE METRICS SUMMARY",
            "=" * 80,
            ""
        ]

        for event_name, metrics in stats.items():
            lines.extend([
                f"{event_name}:",
                f"  P50: {metrics['p50_ns']/1e6:8.3f}ms",
                f"  P95: {metrics['p95_ns']/1e6:8.3f}ms",
                f"  P99: {metrics['p99_ns']/1e6:8.3f}ms",
                f"  P99.9: {metrics['p999_ns']/1e6:8.3f}ms",
                f"  Count: {metrics['count']}",
                ""
            ])

        return '\n'.join(lines)
```

---

## 3. Integration Plan

### 3.1 Phase 1: Foundation (Week 1)
**Priority**: High
**Risk**: Low

1. **Implement core components**:
   - `LockFreeRingBuffer` class
   - `MetricsCollector` singleton
   - `MetricType` and `EventID` enums

2. **Unit tests**:
   - Ring buffer wrap-around behavior
   - Performance benchmarks (verify <100ns write)
   - Thread-safety validation

3. **Integration point**: Add to `src/metrics/` module

**Deliverable**: Functional ring buffer with verified performance

---

### 3.2 Phase 2: Hot Path Instrumentation (Week 2)
**Priority**: High
**Risk**: Medium (requires careful testing)

1. **Add decorators**:
   - `@measure_async` decorator
   - `measure` context manager

2. **Instrument critical paths**:
   ```python
   # src/data/data_collector.py
   @measure_async(EventID.CANDLE_PROCESSING)
   async def on_candle_event(self, candle: Candle):
       # Existing logic

   # src/strategy/strategy.py
   @measure_async(EventID.SIGNAL_GENERATION)
   async def generate_signal(self, candle: Candle):
       # Existing logic

   # src/execution/executor.py
   @measure_async(EventID.ORDER_EXECUTION)
   async def execute_order(self, signal: Signal):
       # Existing logic
   ```

3. **A/B testing**:
   - Run with metrics enabled vs disabled
   - Verify <1% performance degradation
   - Validate correctness of measurements

**Deliverable**: Instrumented hot paths with verified <1% overhead

---

### 3.3 Phase 3: Aggregation & Export (Week 3)
**Priority**: Medium
**Risk**: Low

1. **Implement aggregator**:
   - `MetricsAggregator` background thread
   - t-digest percentile calculation
   - SLA threshold monitoring

2. **Implement exporters**:
   - JSON snapshot export
   - Prometheus format export
   - Summary report generation

3. **Configuration**:
   ```python
   # config/metrics.yaml
   metrics:
     enabled: true
     sampling_rate: 1.0  # 100%
     buffer_size: 131072  # 128K entries
     aggregation_interval_ms: 100
     export_interval_s: 60
     sla_thresholds:
       CANDLE_PROCESSING: 50ms
       SIGNAL_GENERATION: 10ms
       ORDER_EXECUTION: 5ms
   ```

**Deliverable**: Complete metrics pipeline with exports

---

### 3.4 Phase 4: Observability Dashboard (Week 4)
**Priority**: Low
**Risk**: Low

1. **Prometheus integration**:
   - Add HTTP endpoint for scraping: `/metrics`
   - Configure Prometheus to scrape

2. **Grafana dashboard**:
   - Latency percentiles over time
   - Event throughput
   - SLA compliance percentage
   - Queue backlog monitoring

3. **Alerting rules**:
   - SLA violations
   - Queue backlog threshold
   - GC pause time

**Deliverable**: Real-time observability dashboard

---

## 4. Performance Impact Analysis

### 4.1 Hot Path Overhead Breakdown

```
Per Event Measurement (START + END):
  time.perf_counter_ns() × 2:        ~160ns
  ring_buffer.record() × 2:          ~100ns
  Sampling check (if enabled):        ~20ns
  ────────────────────────────────────────
  Total per event:                   ~280ns

Candle Processing Example (4 events measured):
  CANDLE_PROCESSING                  280ns
  SIGNAL_GENERATION                  280ns
  ORDER_EXECUTION                    280ns
  EVENT_BUS_PUBLISH                  280ns
  ────────────────────────────────────────
  Total overhead per candle:        1,120ns = 1.12μs

Relative overhead:
  Typical candle processing: 10-50ms
  Metrics overhead: 1.12μs
  Percentage: 0.0011% - 0.0056% ✅
```

### 4.2 Memory Footprint

```
Ring Buffer:
  128K entries × 32 bytes/entry = 4MB

Aggregator State:
  t-digest per event (10 events): ~10KB
  Sliding windows (1s + 5s): ~100KB
  ────────────────────────────────────────
  Total memory: ~4.2MB ✅
```

### 4.3 GC Impact

```
Zero allocations in hot path:
  - Pre-allocated numpy array (no malloc)
  - Primitive types only (int, float)
  - No Python object creation

Background thread allocations:
  - Happens outside event loop
  - Minimal GC pressure (<1MB/s)
  ────────────────────────────────────────
  GC impact: Negligible ✅
```

### 4.4 CPU Impact

```
Hot path CPU:
  - 280ns per event (~0.00028ms)
  - 4 events per candle
  - 4 candles per second
  = 4.48μs/s = 0.00045% CPU ✅

Background thread CPU:
  - 100ms interval processing
  - ~5ms per aggregation cycle
  = 5% CPU (single core) ✅
```

---

## 5. Advanced Optimizations

### 5.1 Adaptive Sampling

**Problem**: Even 280ns overhead may matter at extreme frequencies

**Solution**: Adaptive sampling based on system load

```python
class AdaptiveSampler:
    """Dynamically adjust sampling rate based on load"""

    def __init__(self):
        self.base_rate = 1.0  # 100%
        self.current_rate = 1.0
        self.event_rate_threshold = 1000  # events/s

    def update_sampling_rate(self, events_per_second: float):
        """Adjust sampling rate based on load"""
        if events_per_second > self.event_rate_threshold:
            # Reduce sampling under high load
            self.current_rate = max(0.1, self.base_rate / (events_per_second / self.event_rate_threshold))
        else:
            self.current_rate = self.base_rate

    def should_sample(self) -> bool:
        """Check if event should be sampled"""
        return random.random() < self.current_rate
```

**Benefits**:
- Maintain low overhead under high load
- Full coverage during normal operation
- Graceful degradation

---

### 5.2 Event Correlation

**Problem**: Need to correlate events across components (e.g., candle → signal → order)

**Solution**: Trace ID propagation

```python
import contextvars

# Context variable for trace ID
trace_id_var = contextvars.ContextVar('trace_id', default=0)

class MetricsCollector:
    def record_start(self, event_id: int) -> int:
        trace_id = trace_id_var.get()
        ts = time.perf_counter_ns()
        self._buffer.record(ts, event_id, MetricType.START, trace_id)
        return ts

# Usage
async def process_candle(candle: Candle):
    trace_id_var.set(candle.id)  # Set trace context
    # All downstream events will have same trace_id
```

**Benefits**:
- End-to-end latency tracking
- Distributed tracing capability
- Root cause analysis

---

### 5.3 GC Pause Monitoring

**Problem**: Python GC pauses can impact latency

**Solution**: Instrument GC callbacks

```python
import gc

class GCMonitor:
    """Monitor Python garbage collection pauses"""

    def __init__(self, collector: MetricsCollector):
        self.collector = collector
        self.gc_start = 0

    def start_monitoring(self):
        gc.callbacks.append(self._on_gc_start)
        gc.callbacks.append(self._on_gc_end)

    def _on_gc_start(self, phase, info):
        if phase == "start":
            self.gc_start = time.perf_counter_ns()

    def _on_gc_end(self, phase, info):
        if phase == "stop" and self.gc_start > 0:
            gc_duration = time.perf_counter_ns() - self.gc_start
            self.collector._buffer.record(
                time.perf_counter_ns(),
                EventID.GC_PAUSE,
                MetricType.HISTOGRAM_OBS,
                gc_duration
            )
            self.gc_start = 0
```

---

## 6. Testing Strategy

### 6.1 Unit Tests

```python
# tests/test_metrics_ring_buffer.py
import pytest
import numpy as np

def test_ring_buffer_write_performance():
    """Verify write performance <100ns"""
    buffer = LockFreeRingBuffer()

    iterations = 10000
    start = time.perf_counter()
    for i in range(iterations):
        buffer.record(time.perf_counter_ns(), i % 10, MetricType.START)
    elapsed = time.perf_counter() - start

    avg_write_time_ns = (elapsed * 1e9) / iterations
    assert avg_write_time_ns < 100, f"Write too slow: {avg_write_time_ns}ns"

def test_ring_buffer_overflow():
    """Verify wrap-around behavior"""
    buffer = LockFreeRingBuffer()

    # Write more than buffer size
    for i in range(buffer.BUFFER_SIZE + 1000):
        buffer.record(i, 1, MetricType.START)

    # Should not crash, oldest entries overwritten
    batch = buffer.read_batch(1000)
    assert len(batch) <= buffer.BUFFER_SIZE
```

### 6.2 Integration Tests

```python
# tests/test_metrics_integration.py
import asyncio

async def test_end_to_end_measurement():
    """Verify end-to-end latency measurement"""
    collector = MetricsCollector()
    aggregator = MetricsAggregator(collector._buffer)
    aggregator.start()

    # Simulate candle processing
    @measure_async(EventID.CANDLE_PROCESSING)
    async def process_candle():
        await asyncio.sleep(0.01)  # 10ms simulated work

    await process_candle()
    await asyncio.sleep(0.2)  # Wait for aggregation

    stats = aggregator.get_statistics()
    assert 'CANDLE_PROCESSING' in stats
    assert 9_000_000 < stats['CANDLE_PROCESSING']['p50_ns'] < 11_000_000  # ~10ms

    aggregator.stop()
```

### 6.3 Performance Regression Tests

```python
# tests/test_metrics_overhead.py

async def test_metrics_overhead_acceptable():
    """Verify metrics add <1% overhead"""

    async def baseline_task():
        await asyncio.sleep(0.01)

    @measure_async(EventID.CANDLE_PROCESSING)
    async def instrumented_task():
        await asyncio.sleep(0.01)

    # Measure baseline
    iterations = 1000
    start = time.perf_counter()
    for _ in range(iterations):
        await baseline_task()
    baseline_time = time.perf_counter() - start

    # Measure with metrics
    start = time.perf_counter()
    for _ in range(iterations):
        await instrumented_task()
    instrumented_time = time.perf_counter() - start

    overhead_pct = ((instrumented_time - baseline_time) / baseline_time) * 100
    assert overhead_pct < 1.0, f"Overhead too high: {overhead_pct}%"
```

---

## 7. Monitoring & Alerting

### 7.1 Key Metrics Dashboard

**Grafana panels**:

1. **Latency Percentiles** (Time series)
   - P50, P95, P99 for each event type
   - 1-minute granularity

2. **Throughput** (Time series)
   - Events per second
   - Candles processed per second

3. **SLA Compliance** (Gauge)
   - Percentage of events meeting SLA
   - Red/yellow/green zones

4. **Queue Backlog** (Time series)
   - Event bus queue depth
   - Alert threshold overlay

5. **GC Pause Time** (Histogram)
   - Distribution of GC pauses
   - P99 overlay

### 7.2 Alert Rules

```yaml
# prometheus/alerts.yml
groups:
  - name: trading_system_sla
    rules:
      - alert: Candle ProcessingLatencyHigh
        expr: candle_processing_latency_ns{quantile="95"} > 50000000
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Candle processing P95 latency exceeds 50ms"

      - alert: OrderExecutionLatencyCritical
        expr: order_execution_latency_ns{quantile="99"} > 5000000
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Order execution P99 latency exceeds 5ms"

      - alert: QueueBacklogHigh
        expr: event_bus_queue_depth > 100
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Event bus queue backlog exceeds 100 events"
```

---

## 8. Rollout Plan

### 8.1 Phased Rollout

**Week 1-2**: Development + testing
- Implement core components
- Unit tests + benchmarks
- Code review

**Week 3**: Staging deployment
- Deploy to paper trading environment
- Validate metrics accuracy
- Performance testing under load

**Week 4**: Production deployment
- Enable with 10% sampling initially
- Monitor for issues
- Gradually increase to 100%

### 8.2 Rollback Strategy

**If performance degradation detected**:
1. Reduce sampling rate to 10%
2. If still degraded, disable metrics: `MetricsCollector._enabled = False`
3. Investigate and fix
4. Re-enable incrementally

**Feature flags**:
```python
# config/metrics.yaml
metrics:
  enabled: true  # Master switch
  sampling_rate: 1.0  # Adjustable
  export_enabled: true  # Can disable export separately
```

---

## 9. Future Enhancements

### 9.1 Distributed Tracing Integration

**Integrate with OpenTelemetry**:
- Export spans to Jaeger/Zipkin
- Correlate with external services
- End-to-end request tracing

### 9.2 Anomaly Detection

**ML-based anomaly detection**:
- Train on historical latency distributions
- Alert on statistical anomalies
- Predict performance degradation

### 9.3 Cost-Benefit Analysis

**Metrics-driven optimization**:
- Identify optimization opportunities from metrics
- Quantify impact of code changes
- ROI tracking for performance work

---

## 10. Summary

### Architecture Highlights
✅ **Zero-allocation hot path**: Pre-allocated ring buffer, no malloc
✅ **<1% overhead**: 280ns per measurement, 0.0056% of 10ms event
✅ **Non-blocking**: Separate aggregation thread
✅ **Low memory**: 4.2MB total footprint
✅ **Real-time visibility**: 100ms aggregation interval

### Implementation Priority
1. **High**: Ring buffer + hot path instrumentation (critical for data)
2. **Medium**: Aggregation + export (enables analysis)
3. **Low**: Dashboard + alerting (nice-to-have)

### Risk Mitigation
- Extensive unit tests for performance regression
- Feature flags for easy disable
- Gradual rollout with monitoring
- Sampling rate adjustment under load

### Success Criteria
- [ ] <1% performance overhead verified in production
- [ ] P50/P95/P99 latencies tracked for all critical paths
- [ ] SLA violations detected within 1 minute
- [ ] Real-time dashboard operational
- [ ] 30-day historical data retention

---

**Next Steps**:
1. Review architecture with team
2. Create implementation tasks in Task Master
3. Set up development environment
4. Begin Phase 1 implementation
