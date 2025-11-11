"""
Prometheus Metrics Service
Provides Prometheus-compatible metrics for SLO monitoring.

Metrics:
- active_calls{clinic_id} - Gauge
- admission_rejects_total{clinic_id} - Counter
- stt_latency_ms{clinic_id} - Histogram (p95 target: <800ms)
- tts_latency_ms{clinic_id} - Histogram (p95 target: <900ms)
- booking_latency_ms{clinic_id} - Histogram (p95 target: <1.5s)
- calendar_conflicts_total{clinic_id} - Counter
- error_rate{clinic_id,error_type} - Counter
"""

from typing import Dict, Optional, Any
from collections import defaultdict
from dataclasses import dataclass, field
import threading

from services.structured_logging import get_logger


@dataclass
class HistogramData:
    """Histogram data for latency metrics."""
    buckets: Dict[float, int] = field(default_factory=lambda: {
        100.0: 0,  # <100ms
        200.0: 0,  # <200ms
        400.0: 0,  # <400ms
        600.0: 0,  # <600ms
        800.0: 0,  # <800ms
        1000.0: 0,  # <1000ms
        1500.0: 0,  # <1500ms
        2000.0: 0,  # <2000ms
        float('inf'): 0  # +Inf
    })
    sum: float = 0.0
    count: int = 0


class MetricsService:
    """
    Prometheus-compatible metrics service for SLO monitoring.
    
    Provides counters, gauges, and histograms for:
    - Active calls per clinic
    - Admission rejects
    - STT/TTS latency
    - Booking latency
    - Calendar conflicts
    - Error rates
    """
    
    def __init__(self):
        self.logger = get_logger("metrics")
        self._lock = threading.Lock()
        
        # Gauges
        self._active_calls: Dict[str, int] = defaultdict(int)
        
        # Counters
        self._admission_rejects: Dict[str, int] = defaultdict(int)
        self._calendar_conflicts: Dict[str, int] = defaultdict(int)
        self._errors: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # Histograms
        self._stt_latency: Dict[str, HistogramData] = defaultdict(HistogramData)
        self._tts_latency: Dict[str, HistogramData] = defaultdict(HistogramData)
        self._booking_latency: Dict[str, HistogramData] = defaultdict(HistogramData)
    
    def set_active_calls(self, clinic_id: str, count: int):
        """Set active calls gauge for a clinic."""
        with self._lock:
            self._active_calls[clinic_id] = count
    
    def increment_admission_rejects(self, clinic_id: str):
        """Increment admission rejects counter for a clinic."""
        with self._lock:
            self._admission_rejects[clinic_id] += 1
    
    def increment_calendar_conflicts(self, clinic_id: str):
        """Increment calendar conflicts counter for a clinic."""
        with self._lock:
            self._calendar_conflicts[clinic_id] += 1
    
    def record_stt_latency(self, clinic_id: str, latency_ms: float):
        """Record STT latency in histogram."""
        with self._lock:
            hist = self._stt_latency[clinic_id]
            hist.sum += latency_ms
            hist.count += 1
            
            # Update buckets - increment all buckets >= the value (Prometheus histogram semantics)
            for bucket in sorted(hist.buckets.keys()):
                if latency_ms <= bucket:
                    hist.buckets[bucket] += 1
    
    def record_tts_latency(self, clinic_id: str, latency_ms: float):
        """Record TTS latency in histogram."""
        with self._lock:
            hist = self._tts_latency[clinic_id]
            hist.sum += latency_ms
            hist.count += 1
            
            # Update buckets - increment all buckets >= the value (Prometheus histogram semantics)
            for bucket in sorted(hist.buckets.keys()):
                if latency_ms <= bucket:
                    hist.buckets[bucket] += 1
    
    def record_booking_latency(self, clinic_id: str, latency_ms: float):
        """Record booking latency in histogram."""
        with self._lock:
            hist = self._booking_latency[clinic_id]
            hist.sum += latency_ms
            hist.count += 1
            
            # Update buckets - increment all buckets >= the value (Prometheus histogram semantics)
            for bucket in sorted(hist.buckets.keys()):
                if latency_ms <= bucket:
                    hist.buckets[bucket] += 1
    
    def get_prometheus_metrics(self) -> str:
        """
        Generate Prometheus-formatted metrics string.
        
        Returns:
            Prometheus metrics in text format
        """
        lines = []
        
        with self._lock:
            # Gauges
            lines.append("# TYPE active_calls gauge")
            for clinic_id, count in self._active_calls.items():
                lines.append(f'active_calls{{clinic_id="{clinic_id}"}} {count}')
            
            # Counters
            lines.append("# TYPE admission_rejects_total counter")
            for clinic_id, count in self._admission_rejects.items():
                lines.append(f'admission_rejects_total{{clinic_id="{clinic_id}"}} {count}')
            
            lines.append("# TYPE calendar_conflicts_total counter")
            for clinic_id, count in self._calendar_conflicts.items():
                lines.append(f'calendar_conflicts_total{{clinic_id="{clinic_id}"}} {count}')
            
            lines.append("# TYPE error_rate counter")
            for clinic_id, errors in self._errors.items():
                for error_type, count in errors.items():
                    lines.append(f'error_rate{{clinic_id="{clinic_id}",error_type="{error_type}"}} {count}')
            
            # Histograms
            lines.append("# TYPE stt_latency_ms histogram")
            for clinic_id, hist in self._stt_latency.items():
                for bucket, count in sorted(hist.buckets.items()):
                    if bucket == float('inf'):
                        lines.append(f'stt_latency_ms_bucket{{clinic_id="{clinic_id}",le="+Inf"}} {count}')
                    else:
                        lines.append(f'stt_latency_ms_bucket{{clinic_id="{clinic_id}",le="{bucket}"}} {count}')
                lines.append(f'stt_latency_ms_sum{{clinic_id="{clinic_id}"}} {hist.sum}')
                lines.append(f'stt_latency_ms_count{{clinic_id="{clinic_id}"}} {hist.count}')
            
            lines.append("# TYPE tts_latency_ms histogram")
            for clinic_id, hist in self._tts_latency.items():
                for bucket, count in sorted(hist.buckets.items()):
                    if bucket == float('inf'):
                        lines.append(f'tts_latency_ms_bucket{{clinic_id="{clinic_id}",le="+Inf"}} {count}')
                    else:
                        lines.append(f'tts_latency_ms_bucket{{clinic_id="{clinic_id}",le="{bucket}"}} {count}')
                lines.append(f'tts_latency_ms_sum{{clinic_id="{clinic_id}"}} {hist.sum}')
                lines.append(f'tts_latency_ms_count{{clinic_id="{clinic_id}"}} {hist.count}')
            
            lines.append("# TYPE booking_latency_ms histogram")
            for clinic_id, hist in self._booking_latency.items():
                for bucket, count in sorted(hist.buckets.items()):
                    if bucket == float('inf'):
                        lines.append(f'booking_latency_ms_bucket{{clinic_id="{clinic_id}",le="+Inf"}} {count}')
                    else:
                        lines.append(f'booking_latency_ms_bucket{{clinic_id="{clinic_id}",le="{bucket}"}} {count}')
                lines.append(f'booking_latency_ms_sum{{clinic_id="{clinic_id}"}} {hist.sum}')
                lines.append(f'booking_latency_ms_count{{clinic_id="{clinic_id}"}} {hist.count}')
        
        return '\n'.join(lines) + '\n'
    
    def _calculate_p95(self, hist: HistogramData) -> Optional[float]:
        """Calculate p95 latency from histogram."""
        if hist.count == 0:
            return None
        
        target_count = int(hist.count * 0.95)
        current_count = 0
        
        for bucket in sorted(hist.buckets.keys()):
            current_count += hist.buckets[bucket]
            if current_count >= target_count:
                return bucket
        
        return None


# Global instance
_metrics_service: Optional[MetricsService] = None


def get_metrics_service() -> MetricsService:
    """Get the global MetricsService instance."""
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = MetricsService()
    return _metrics_service

