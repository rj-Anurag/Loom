---
title: "Phase 3.5 — Horizontal Autoscaling"
description: "Kubernetes HPA for Gateway and Agent services. Queue-depth-based scaling for Retrieval and Coordination. Load testing suite."
status: pending
dependencies: ["phase-3/01-observability.md"]
---

# Horizontal Autoscaling

## Description
Configure Kubernetes Horizontal Pod Autoscalers (HPA) for each Loom service based on relevant metrics. Gateway and Agent services scale on CPU/memory. Retrieval and Coordination services scale on queue depth and lock contention.

## Scaling Strategies

### Gateway (Stateless, HTTP)
```
Metric: CPU utilization
Target: 70%
Min: 2 pods (HA)
Max: 20 pods
Scale up: sustained > 70% for 3 minutes
Scale down: sustained < 40% for 10 minutes
```

### Agent Services (Stateless, Task-Driven)
```
Metric: Custom — pending tasks in queue
Target: < 10 pending tasks per pod
Min: 2 pods
Max: 50 pods
Scale up: > 20 pending tasks per pod
Scale down: < 5 pending tasks per pod
```

### Context Service (Stateful, Read-Heavy)
```
Metric: CPU + memory
Target: 60% CPU
Min: 2 pods
Max: 10 pods
Note: Read replicas scale independently of write primary
```

### Retrieval Service (CPU-Bound, Embeddings)
```
Metric: Custom — embedding queue depth
Target: < 50 queued items per pod
Min: 1 pod
Max: 10 pods
Scale up: > 100 items in embedding:queue
Scale down: < 10 items for 15 minutes
```

### Coordination Service (Lock-Heavy)
```
Metric: Custom — lock contention rate (failed lock attempts / total)
Target: < 5% contention rate
Min: 1 pod
Max: 5 pods
Note: Uses Redis for shared state, so it scales horizontally
```

## Kubernetes Configuration

### HPA Definition
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: loom-gateway
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: loom-gateway
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

### Custom Metrics
For queue-depth and lock-contention metrics, use a Prometheus adapter:
```yaml
- type: Pods
  pods:
    metric:
      name: loom_embedding_queue_depth
    target:
      type: AverageValue
      averageValue: "50"
```

## Load Testing Suite

### End-to-End Load Test
Create `tests/load/test_scaling.py`:
```python
@pytest.mark.load_test
async def test_scale_up_under_load():
    """Simulate increasing agent count and verify autoscaling."""
    # Start with 2 agents
    # Ramp up to 50 agents over 5 minutes
    # Verify Gateway HPA scales to at least 5 pods
    # Verify all requests succeed (< 0.1% error rate)
    pass
```

### Benchmark Scenarios
| Scenario | Description | Target |
|---|---|---|
| Steady state | 10 agents, normal workload | All metrics green |
| Read spike | 100 agents reading concurrently | P99 latency < 500ms |
| Write spike | 50 agents writing concurrently | < 5% conflict rate |
| Mixed load | 30 agents reading + 10 writing | No degradation |
| Burst | 0 to 100 agents in 30 seconds | Graceful scale-up |

## File Targets
- `infra/kubernetes/hpa-gateway.yaml`
- `infra/kubernetes/hpa-context.yaml`
- `infra/kubernetes/hpa-retrieval.yaml`
- `infra/kubernetes/hpa-coordination.yaml`
- `infra/kubernetes/hpa-agent.yaml`
- `infra/kubernetes/prometheus-adapter.yaml`
- `tests/load/test_scaling.py` — autoscaling load tests
- `scripts/run-scale-test.sh` — load test runner

## Acceptance Criteria
- [ ] HPAs are configured for all services
- [ ] Gateway scales from 2 to 10+ pods under load
- [ ] Retrieval worker count scales with embedding queue depth
- [ ] No service downtime during scale-up events
- [ ] Load tests pass with < 0.1% error rate at peak load
- [ ] Scale-down is graceful (no in-flight request drops)
- [ ] Custom Prometheus metrics are available for HPA

## TDD Instructions
```python
@pytest.mark.load_test
async def test_gateway_scales_under_load(load_test_framework):
    metrics = await load_test_framework.run_scenario("read_spike", agents=100)
    assert metrics.p99_latency_ms < 500
    assert metrics.error_rate < 0.001
    assert metrics.pod_count >= 5

@pytest.mark.load_test
async def test_retrieval_scales_with_queue(load_test_framework):
    metrics = await load_test_framework.run_scenario("write_spike", agents=50)
    assert metrics.max_queue_depth < 200
}

## Dependencies
- Phase 3.1 (observability metrics needed for HPA metrics)
