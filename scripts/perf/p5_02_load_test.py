#!/usr/bin/env python3
"""
P5-02: 1000 concurrent load test + P99 latency report

This script performs load testing on the ERIS API endpoints with 1000 concurrent requests
and generates a detailed performance report including P99 latency metrics.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from pathlib import Path


# Configuration
BASE_URL = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
CONCURRENCY = int(os.environ.get("P5_02_CONCURRENCY", "1000"))
REQUESTS_PER_ENDPOINT = int(os.environ.get("P5_02_REQUESTS_PER_ENDPOINT", "10"))
TIMEOUT_SECONDS = float(os.environ.get("P5_02_TIMEOUT_SECONDS", "30"))
OUTPUT_DIR = os.environ.get("P5_02_OUTPUT_DIR", "scripts/perf/reports")


# Endpoints to test
ENDPOINTS = [
    ("GET", "/health"),
    ("GET", "/health/detail"),
    ("POST", "/telegram/webhook"),
]


@dataclass
class LoadTestResult:
    """Single request result"""
    endpoint: str
    method: str
    ok: bool
    status: int | None
    latency_ms: float
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class EndpointStats:
    """Statistics for a single endpoint"""
    endpoint: str
    method: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    success_rate: float
    latency_ms: dict[str, float]
    errors: list[str]


def percentile(values: list[float], pct: float) -> float | None:
    """Calculate percentile of values"""
    if not values:
        return None
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * pct)
    return ordered[idx]


def create_webhook_payload() -> dict[str, Any]:
    """Create a test webhook payload"""
    return {
        "update_id": 999999,
        "message": {
            "message_id": 1,
            "date": int(time.time()),
            "chat": {"id": 999999, "type": "private"},
            "from": {
                "id": 999999,
                "is_bot": False,
                "first_name": "LoadTest",
                "username": "load_test_user",
                "language_code": "zh"
            },
            "text": "Performance test message"
        }
    }


def make_request(method: str, endpoint: str) -> LoadTestResult:
    """Make a single HTTP request"""
    url = f"{BASE_URL}{endpoint}"
    started = time.perf_counter()
    
    try:
        if method == "GET":
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                elapsed = (time.perf_counter() - started) * 1000
                return LoadTestResult(
                    endpoint=endpoint,
                    method=method,
                    ok=200 <= resp.status < 300,
                    status=resp.status,
                    latency_ms=elapsed,
                    error=None
                )
        elif method == "POST":
            if endpoint == "/telegram/webhook":
                payload = create_webhook_payload()
            else:
                payload = {}
            
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                elapsed = (time.perf_counter() - started) * 1000
                return LoadTestResult(
                    endpoint=endpoint,
                    method=method,
                    ok=200 <= resp.status < 300,
                    status=resp.status,
                    latency_ms=elapsed,
                    error=None
                )
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return LoadTestResult(
            endpoint=endpoint,
            method=method,
            ok=False,
            status=exc.code,
            latency_ms=elapsed,
            error=f"HTTPError:{exc.code}"
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return LoadTestResult(
            endpoint=endpoint,
            method=method,
            ok=False,
            status=None,
            latency_ms=elapsed,
            error=f"{type(exc).__name__}:{exc}"
        )


def calculate_endpoint_stats(results: list[LoadTestResult], method: str, endpoint: str) -> EndpointStats:
    """Calculate statistics for a specific endpoint"""
    endpoint_results = [r for r in results if r.method == method and r.endpoint == endpoint]
    
    if not endpoint_results:
        return EndpointStats(
            endpoint=endpoint,
            method=method,
            total_requests=0,
            successful_requests=0,
            failed_requests=0,
            success_rate=0.0,
            latency_ms={},
            errors=[]
        )
    
    total = len(endpoint_results)
    successful = sum(1 for r in endpoint_results if r.ok)
    failed = total - successful
    success_rate = (successful / total * 100) if total > 0 else 0.0
    
    latencies = [r.latency_ms for r in endpoint_results]
    errors = [r.error for r in endpoint_results if r.error]
    
    latency_stats = {
        "min": round(min(latencies), 2) if latencies else 0.0,
        "p50": round(percentile(latencies, 0.50) or 0, 2),
        "p75": round(percentile(latencies, 0.75) or 0, 2),
        "p90": round(percentile(latencies, 0.90) or 0, 2),
        "p95": round(percentile(latencies, 0.95) or 0, 2),
        "p99": round(percentile(latencies, 0.99) or 0, 2),
        "p99_9": round(percentile(latencies, 0.999) or 0, 2),
        "max": round(max(latencies), 2) if latencies else 0.0,
        "mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        "std": round(statistics.stdev(latencies), 2) if len(latencies) > 1 else 0.0,
    }
    
    return EndpointStats(
        endpoint=endpoint,
        method=method,
        total_requests=total,
        successful_requests=successful,
        failed_requests=failed,
        success_rate=round(success_rate, 2),
        latency_ms=latency_stats,
        errors=errors[:10]  # Limit to first 10 errors
    )


def generate_report(all_results: list[LoadTestResult]) -> dict[str, Any]:
    """Generate comprehensive load test report"""
    total_requests = len(all_results)
    total_successful = sum(1 for r in all_results if r.ok)
    total_failed = total_requests - total_successful
    
    # Calculate overall latency statistics
    all_latencies = [r.latency_ms for r in all_results]
    overall_latency = {
        "min": round(min(all_latencies), 2) if all_latencies else 0.0,
        "p50": round(percentile(all_latencies, 0.50) or 0, 2),
        "p75": round(percentile(all_latencies, 0.75) or 0, 2),
        "p90": round(percentile(all_latencies, 0.90) or 0, 2),
        "p95": round(percentile(all_latencies, 0.95) or 0, 2),
        "p99": round(percentile(all_latencies, 0.99) or 0, 2),
        "p99_9": round(percentile(all_latencies, 0.999) or 0, 2),
        "max": round(max(all_latencies), 2) if all_latencies else 0.0,
        "mean": round(statistics.fmean(all_latencies), 2) if all_latencies else 0.0,
        "std": round(statistics.stdev(all_latencies), 2) if len(all_latencies) > 1 else 0.0,
    }
    
    # Calculate per-endpoint statistics
    endpoint_stats = []
    for method, endpoint in ENDPOINTS:
        stats = calculate_endpoint_stats(all_results, method, endpoint)
        endpoint_stats.append(stats)
    
    # Check if P99 < 500ms (acceptance criteria)
    p99_passed = overall_latency["p99"] < 500.0
    
    report = {
        "test_summary": {
            "test_name": "P5-02 Load Test",
            "timestamp": datetime.now().isoformat(),
            "base_url": BASE_URL,
            "concurrency": CONCURRENCY,
            "requests_per_endpoint": REQUESTS_PER_ENDPOINT,
            "total_endpoints": len(ENDPOINTS),
            "total_requests": total_requests,
            "successful_requests": total_successful,
            "failed_requests": total_failed,
            "overall_success_rate": round((total_successful / total_requests * 100) if total_requests > 0 else 0, 2),
            "acceptance_criteria": {
                "p99_threshold_ms": 500,
                "p99_actual_ms": overall_latency["p99"],
                "passed": p99_passed
            }
        },
        "overall_latency_ms": overall_latency,
        "endpoint_statistics": [
            {
                "endpoint": stat.endpoint,
                "method": stat.method,
                "total_requests": stat.total_requests,
                "successful_requests": stat.successful_requests,
                "failed_requests": stat.failed_requests,
                "success_rate": stat.success_rate,
                "latency_ms": stat.latency_ms,
                "errors": stat.errors
            }
            for stat in endpoint_stats
        ],
        "recommendations": generate_recommendations(endpoint_stats, overall_latency, p99_passed)
    }
    
    return report


def generate_recommendations(endpoint_stats: list[EndpointStats], overall_latency: dict[str, float], p99_passed: bool) -> list[str]:
    """Generate performance recommendations based on test results"""
    recommendations = []
    
    # Check overall P99
    if not p99_passed:
        recommendations.append(f"❌ P99 latency {overall_latency['p99']}ms exceeds 500ms threshold - requires optimization")
    else:
        recommendations.append(f"✅ P99 latency {overall_latency['p99']}meets 500ms threshold")
    
    # Check per-endpoint performance
    for stat in endpoint_stats:
        if stat.success_rate < 99.0:
            recommendations.append(f"⚠️ {stat.method} {stat.endpoint} success rate {stat.success_rate}% is below 99%")
        
        if stat.latency_ms.get("p99", 0) > 500:
            recommendations.append(f"⚠️ {stat.method} {stat.endpoint} P99 latency {stat.latency_ms['p99']}ms exceeds 500ms")
        
        if stat.failed_requests > 0:
            recommendations.append(f"⚠️ {stat.method} {stat.endpoint} had {stat.failed_requests} failed requests")
    
    # Check for high variance
    if overall_latency.get("std", 0) > overall_latency.get("mean", 0) * 0.5:
        recommendations.append(f"⚠️ High latency variance detected (std: {overall_latency['std']}ms, mean: {overall_latency['mean']}ms)")
    
    if not recommendations:
        recommendations.append("✅ All performance metrics are within acceptable ranges")
    
    return recommendations


def save_report(report: dict[str, Any], output_dir: str) -> str:
    """Save report to file"""
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"p5_02_load_test_report_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    return filepath


def main() -> int:
    """Main load test execution"""
    print(f"🚀 Starting P5-02 Load Test")
    print(f"📊 Configuration: Concurrency={CONCURRENCY}, Requests/Endpoint={REQUESTS_PER_ENDPOINT}")
    print(f"🌐 Target: {BASE_URL}")
    print(f"⏱️  Timeout: {TIMEOUT_SECONDS}s")
    print(f"📁 Output Directory: {OUTPUT_DIR}")
    print()
    
    all_results = []
    total_requests = CONCURRENCY * REQUESTS_PER_ENDPOINT * len(ENDPOINTS)
    completed_requests = 0
    
    start_time = time.time()
    
    # Execute load test for each endpoint
    for method, endpoint in ENDPOINTS:
        print(f"🔄 Testing {method} {endpoint}...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = [
                executor.submit(make_request, method, endpoint)
                for _ in range(CONCURRENCY * REQUESTS_PER_ENDPOINT)
            ]
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                all_results.append(result)
                completed_requests += 1
                
                # Progress indicator
                if completed_requests % 100 == 0:
                    progress = (completed_requests / total_requests) * 100
                    print(f"   Progress: {completed_requests}/{total_requests} ({progress:.1f}%)")
    
    elapsed = time.time() - start_time
    
    print(f"\n✅ Load test completed in {elapsed:.2f}s")
    print(f"📊 Total requests: {len(all_results)}")
    print(f"✅ Successful: {sum(1 for r in all_results if r.ok)}")
    print(f"❌ Failed: {sum(1 for r in all_results if not r.ok)}")
    
    # Generate report
    print(f"\n📈 Generating performance report...")
    report = generate_report(all_results)
    
    # Save report
    report_path = save_report(report, OUTPUT_DIR)
    print(f"💾 Report saved to: {report_path}")
    
    # Print summary
    print(f"\n📋 Performance Summary:")
    print(f"   Overall P50: {report['overall_latency_ms']['p50']}ms")
    print(f"   Overall P95: {report['overall_latency_ms']['p95']}ms")
    print(f"   Overall P99: {report['overall_latency_ms']['p99']}ms")
    print(f"   Success Rate: {report['test_summary']['overall_success_rate']}%")
    
    # Print acceptance criteria
    acceptance = report['test_summary']['acceptance_criteria']
    print(f"\n🎯 Acceptance Criteria:")
    print(f"   P99 Threshold: {acceptance['p99_threshold_ms']}ms")
    print(f"   P99 Actual: {acceptance['p99_actual_ms']}ms")
    print(f"   Result: {'✅ PASSED' if acceptance['passed'] else '❌ FAILED'}")
    
    # Print recommendations
    print(f"\n💡 Recommendations:")
    for rec in report['recommendations']:
        print(f"   {rec}")
    
    # Return exit code based on acceptance criteria
    return 0 if acceptance['passed'] else 1


if __name__ == "__main__":
    raise SystemExit(main())