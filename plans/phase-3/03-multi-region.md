---
title: "Phase 3.3 — Multi-Region Deployment"
description: "Cross-region replication for Postgres, global Gateway, and region-aware retrieval routing."
status: pending
dependencies: ["phase-3/02-auth-authz.md"]
---

# Multi-Region Deployment

## Description
Extend Loom from single-region to multi-region deployment. This enables lower latency for globally distributed agents and improves availability beyond 99.5%.

## Architecture

```
Region A (us-east)              Region B (eu-west)
┌─────────────────────┐         ┌─────────────────────┐
│  Gateway ──► Redis   │         │  Gateway ──► Redis   │
│       │              │         │       │              │
│  Postgres (primary)  │◄────────┤ Postgres (replica)   │
│       │              │  WAL    │                      │
│  Object Storage     │         │  Object Storage      │
└─────────────────────┘         └─────────────────────┘
```

## Multi-Region Postgres

### Active-Passive with Read Replicas
- One primary region (us-east) handles all writes
- Secondary regions (eu-west, ap-southeast) have read replicas
- WAL streaming keeps replicas up to date (sub-second lag)
- Failover: if primary goes down, promote a replica

### Connection Routing
```python
async def get_db_connection(read_only: bool = False):
    if read_only:
        # Route to nearest replica
        region = get_current_region()
        return await connect(settings.REPLICA_URLS[region])
    else:
        # Route to primary
        return await connect(settings.PRIMARY_DB_URL)
```

## Global Gateway

### Regional Gateways
Each region has its own Gateway instance:
- `api.loom.io` (routed via DNS/latency-based routing)
- `api.eu.loom.io`
- `api.ap.loom.io`

### Request Routing
- Read requests: handled by the nearest regional Gateway, reads from local replica
- Write requests: forwarded to the primary region's Gateway
- WebSocket connections: stick to the region they connected to (events broadcast via cross-region Redis pub/sub)

### Cross-Region Redis
Redis pub/sub is bridged across regions:
- Each region's Redis subscribes to a cross-region channel
- When a write happens in the primary region, the event is published to all regions
- Local Redis caches are invalidated

## Object Storage Replication
- Use S3 cross-region replication (or equivalent)
- Artifacts written in one region are automatically replicated to all others
- Reads prefer local region's storage

## File Targets
- `infra/terraform/` — Terraform configs for multi-region deployment
- `api/gateway.py` — add region-aware routing logic
- `services/context/service.py` — add read/write splitting (read from replica, write to primary)
- `infra/redis/cross-region.py` — cross-region Redis bridge

## Acceptance Criteria
- [ ] Read requests are served from the nearest region
- [ ] Write requests are forwarded to the primary region
- [ ] Postgres replicas stay within 1 second of primary
- [ ] Failover promotes a replica to primary within 30 seconds
- [ ] Cross-region Redis pub/sub delivers events to all regions
- [ ] Object storage replication completes within 60 seconds

## Dependencies
- Phase 3.2 (auth must work across regions)
