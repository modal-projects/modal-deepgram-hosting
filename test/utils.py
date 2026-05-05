"""
Shared utilities for Modal-based load tests.

This module provides common functionality for both HTTP and WebSocket load tests:
- Result aggregation from multiple client containers
- Statistics calculation (mean, median, percentiles, etc.)
- Result and error reporting
- Client spawning with staggered delays
"""

import asyncio
import time
import statistics
from typing import List, Dict, Any, Callable, TypeVar

# Type for Modal function handles
ModalFunctionHandle = TypeVar("ModalFunctionHandle")


def aggregate_client_results(
    client_results: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Aggregate results and errors from all client containers.
    
    Args:
        client_results: List of dicts, each with "results" and "errors" keys
        
    Returns:
        Tuple of (all_results, all_errors)
    """
    all_results = []
    all_errors = []
    for client_result in client_results:
        all_results.extend(client_result.get("results", []))
        all_errors.extend(client_result.get("errors", []))
    return all_results, all_errors


def calculate_stats(response_times: List[float]) -> Dict[str, float]:
    """
    Calculate statistics for response times.
    
    Args:
        response_times: List of elapsed times in seconds
        
    Returns:
        Dict with mean, median, min, max, stdev, p50, p90, p95, p99
    """
    if not response_times:
        return {
            "mean": 0,
            "median": 0,
            "min": 0,
            "max": 0,
            "stdev": 0,
            "p50": 0,
            "p90": 0,
            "p95": 0,
            "p99": 0,
        }
    
    sorted_times = sorted(response_times)
    n = len(sorted_times)
    
    return {
        "mean": statistics.mean(response_times),
        "median": statistics.median(response_times),
        "min": min(response_times),
        "max": max(response_times),
        "stdev": statistics.stdev(response_times) if n > 1 else 0,
        "p50": sorted_times[int(n * 0.50)],
        "p90": sorted_times[int(n * 0.90)],
        "p95": sorted_times[int(n * 0.95)],
        "p99": sorted_times[int(n * 0.99)] if n > 100 else sorted_times[-1],
    }


def print_test_config(
    test_name: str,
    url: str,
    model: str,
    audio_url: str,
    num_clients: int,
    requests_per_client: int,
    stagger_delay: float,
    request_label: str = "requests",
):
    """Print test configuration header."""
    print("=" * 80)
    print(f"🚀 {test_name} (Each client in separate container)")
    print("=" * 80)
    print(f"URL: {url}")
    print(f"Model: {model}")
    print(f"Audio URL: {audio_url}")
    print(f"Clients: {num_clients}")
    print(f"{request_label.capitalize()} per client: {requests_per_client}")
    print(f"Total {request_label}: {num_clients * requests_per_client}")
    print(f"Stagger delay: {stagger_delay}s between clients")
    print("=" * 80)
    print()


def print_results_summary(
    all_results: List[Dict[str, Any]],
    all_errors: List[Dict[str, Any]],
    total_elapsed: float,
    request_label: str = "requests",
    extra_metrics: Dict[str, Any] | None = None,
):
    """
    Print aggregated results summary.
    
    Args:
        all_results: List of successful result dicts
        all_errors: List of error dicts
        total_elapsed: Total test time in seconds
        request_label: Label for requests (e.g., "requests" or "streams")
        extra_metrics: Optional dict of additional metrics to print
    """
    total_requests = len(all_results) + len(all_errors)
    successful_requests = len(all_results)
    failed_requests = len(all_errors)
    
    print()
    print("=" * 80)
    print(f"📊 Load Test Results (Aggregated from all containers)")
    print("=" * 80)
    print(f"Total time: {total_elapsed:.2f}s")
    print(f"Total {request_label}: {total_requests}")
    
    if total_requests > 0:
        print(f"Successful: {successful_requests} ({100 * successful_requests / total_requests:.1f}%)")
        print(f"Failed: {failed_requests} ({100 * failed_requests / total_requests:.1f}%)")
    else:
        print(f"Successful: {successful_requests}")
        print(f"Failed: {failed_requests}")
    print()
    
    # Calculate and print statistics
    if all_results:
        response_times = [r["elapsed"] for r in all_results]
        stats = calculate_stats(response_times)
        
        print(f"⏱️  Response Time Statistics (successful {request_label} only):")
        print(f"  Mean: {stats['mean']:.3f}s")
        print(f"  Median: {stats['median']:.3f}s")
        print(f"  Min: {stats['min']:.3f}s")
        print(f"  Max: {stats['max']:.3f}s")
        
        if stats['stdev'] > 0:
            print(f"  Std Dev: {stats['stdev']:.3f}s")
        
        print(f"  P50: {stats['p50']:.3f}s")
        print(f"  P90: {stats['p90']:.3f}s")
        print(f"  P95: {stats['p95']:.3f}s")
        print(f"  P99: {stats['p99']:.3f}s")
        print()
        
        # Throughput
        throughput = successful_requests / total_elapsed if total_elapsed > 0 else 0
        print(f"📈 Throughput: {throughput:.2f} {request_label}/second")
        
        # Print any extra metrics
        if extra_metrics:
            for label, value in extra_metrics.items():
                print(f"{label}: {value}")
    
    print()


def print_error_summary(all_errors: List[Dict[str, Any]]):
    """Print summary of errors grouped by error message."""
    if not all_errors:
        return
    
    print("❌ Errors:")
    error_counts: Dict[str, int] = {}
    for error in all_errors:
        error_msg = error.get("error", "Unknown error")
        error_counts[error_msg] = error_counts.get(error_msg, 0) + 1
    
    for error_msg, count in sorted(error_counts.items(), key=lambda x: -x[1]):
        print(f"  [{count}x] {error_msg[:100]}")


def build_results_dict(
    all_results: List[Dict[str, Any]],
    all_errors: List[Dict[str, Any]],
    total_elapsed: float,
) -> Dict[str, Any]:
    """
    Build the standard results dictionary for programmatic access.
    
    Args:
        all_results: List of successful result dicts
        all_errors: List of error dicts
        total_elapsed: Total test time in seconds
        
    Returns:
        Dict with total_requests, successful, failed, success_rate, 
        total_time, throughput, and response_times stats
    """
    total_requests = len(all_results) + len(all_errors)
    successful_requests = len(all_results)
    failed_requests = len(all_errors)
    
    response_times = [r["elapsed"] for r in all_results] if all_results else []
    stats = calculate_stats(response_times)
    
    return {
        "total_requests": total_requests,
        "successful": successful_requests,
        "failed": failed_requests,
        "success_rate": successful_requests / total_requests if total_requests > 0 else 0,
        "total_time": total_elapsed,
        "throughput": successful_requests / total_elapsed if total_elapsed > 0 else 0,
        "response_times": {
            "mean": stats["mean"],
            "median": stats["median"],
            "min": stats["min"],
            "max": stats["max"],
            "p50": stats["p50"],
            "p90": stats["p90"],
            "p95": stats["p95"],
            "p99": stats["p99"],
        }
    }


async def spawn_clients_with_stagger(
    client_fn: Any,
    num_clients: int,
    stagger_delay: float,
    client_kwargs: Dict[str, Any],
) -> List[Any]:
    """
    Spawn client containers with staggered delays.
    
    Args:
        client_fn: Modal function to spawn (must have .spawn() method)
        num_clients: Number of clients to spawn
        stagger_delay: Delay in seconds between spawning clients
        client_kwargs: Keyword arguments to pass to each client (must NOT include client_id)
        
    Returns:
        List of Modal function handles (call objects)
    """
    client_calls = []
    
    async def spawn_single_client(client_id):
        if client_id > 0:
            print(f"⏱️  Waiting {stagger_delay}s before starting Client {client_id}...")
            await asyncio.sleep(stagger_delay)
        print(f"🚀 Starting Client {client_id} in new container...")
        return await client_fn.spawn.aio(client_id=client_id, **client_kwargs)

    tasks = [spawn_single_client(client_id) for client_id in range(num_clients)]
    client_calls = await asyncio.gather(*tasks)
    
    print(f"\n✅ All {num_clients} clients spawned in separate containers!\n")
    print("⏳ Waiting for all clients to complete...\n")
    
    return client_calls


async def wait_for_clients(client_calls: List[Any]) -> List[Dict[str, Any]]:
    """
    Wait for all client containers to complete and collect results.
    
    Args:
        client_calls: List of Modal function handles from spawn()
        
    Returns:
        List of result dicts from each client
    """
    client_results = []
    for call in client_calls:
        result = await call.get.aio()
        client_results.append(result)
    return client_results
