# Deploying on ECS

## Topology

```
                     ┌─────────────────────────────────────────┐
   CloudFront ───────┤  S3: JS bundle, spec docs, cube files   │
   (static)          └─────────────────────────────────────────┘

   Browser ──► ALB ──► ECS service: frame-query      (N tasks, stateless)
                  └──► ECS service: frame-metadata   (2 tasks, stateless)
                                │
                                ├──► ElastiCache Redis      ← SHARED result cache
                                ├──► RDS Postgres           ← spec registry
                                └──► Snowflake              ← the paid path
```

Everything in the ECS row is stateless and horizontally scalable. Everything
below it is shared state, and **all of it lives outside the task**.

---

## Redis does not go in the container

**Redis is optional to run, and required to scale out.** Nothing needs it for
development, CI, or a single-task deployment: leave `FRAME_REDIS_URL` unset and
the platform uses a per-task cache, which is correct for one task. The `redis`
package is an optional extra and is imported lazily, so it does not need to be
installed at all.

What follows is about the moment you run a second task. This is the deployment
decision most likely to be made wrong, because a sidecar looks simpler and
passes every test.

A cache inside the application container is a cache **per task**. Eight tasks
means eight independent caches, so a cold entry is fetched from the warehouse up
to eight times instead of once.

| Tasks | Per-task cache | Shared cache |
|---|---|---|
| 1 | 8.3 q/s | 8.3 q/s |
| 4 | 33.4 q/s | 8.3 q/s |
| 8 | **66.8 q/s** | 8.3 q/s |
| 16 | **133.6 q/s** | 8.3 q/s |

*(Warehouse queries per second at 10,000 concurrent users, from the measured
0.50 round-trips per dashboard load.)*

The capacity plan's 8.3 q/s assumes one cache. Three further problems make a
sidecar worse than the arithmetic suggests:

- **Every rolling deploy wipes every cache at the same instant**, so each
  deploy produces a warehouse miss storm.
- **Scale-out adds cold tasks precisely when load is already high** — the new
  task contributes misses at the moment you least want them.
- **Redis competes for the task's own memory limit**, so the cache and the
  application evict each other.

Use **ElastiCache (Redis or Valkey)** in the same VPC. Running Redis as its own
ECS *service* rather than a sidecar would also be shared and would work, but
you then own failover and patching for no saving.

### Configure it, when you need it

```bash
pip install -e ".[redis]"                 # optional extra; not installed by default

FRAME_REDIS_URL=rediss://frame-cache.abc123.use1.cache.amazonaws.com:6379
FRAME_REDIS_TIMEOUT=0.25        # seconds; a slow cache must not become slow serving
FRAME_CACHE_L1_ENTRIES=512      # per-task tier in front of Redis
FRAME_CACHE_L1_TTL=15           # seconds; short so tasks cannot drift on freshness
```

- Private subnets only. Security group inbound 6379 **from the ECS task
  security group**, nothing else.
- Enable encryption in transit (`rediss://`) and AUTH.
- Multi-AZ with a replica. A cache outage degrades to warehouse queries rather
  than an error — the code treats every Redis failure as a miss — but that
  degradation is expensive, so do not run a single node.
- `maxmemory-policy allkeys-lru`. Entries are TTL'd content-addressed results;
  evicting the least recently used is always safe.

### Sizing

Budget the working set: distinct plan hashes × result size. For ~50,000 hot
plans at ~30 KB each, that is roughly 1.5 GB plus overhead. Start with a node
offering 6–8 GB usable, then watch `evicted_keys` — sustained evictions mean
the working set does not fit and the hit rate will sag.

### Verify it is actually shared

`/api/v1/health` reports it directly:

```jsonc
"cache": {
  "shared": true,            // false = per-task. DO NOT scale out in this state.
  "hit_rate": 0.95,
  "l1": { "hits": 1260, "hit_rate": 0.95 },
  "l2": { "hits": 8400, "errors": 0, "hit_rate": 0.93 }
}
```

Alert on `shared: false` in any environment running more than one task, and on
a rising `l2.errors`.

---

## Why two tiers rather than only Redis

L1 is a small in-process LRU in front of Redis. A dashboard load asks for
overlapping plans within a few hundred milliseconds, and serving those from a
dictionary rather than a network round-trip is worth having.

It is deliberately small (512 entries) and short-lived (15 s) so that tasks
cannot drift apart on freshness. It is **not** a substitute for L2, because it
is per task — which is the entire point of this document.

---

## The services

### frame-query

The hot path: compiles specs into SQL and serves results.

| Setting | Value | Why |
|---|---|---|
| CPU / memory | 1 vCPU / 2 GB | Cache hits are cheap; memory holds L1 and connections |
| Tasks | 8 at 10k users | 520 req/s ÷ ~150 req/s per task, doubled for headroom |
| Autoscale on | **in-flight requests or RPS** | I/O-bound: CPU stays flat while p95 triples |
| Health check | `GET /api/v1/health` | |
| Deployment | rolling, `minimumHealthyPercent: 100` | Avoids shrinking capacity mid-deploy |

**Do not autoscale on CPU.** The service spends its time waiting on Snowflake
and Redis. A CPU policy will not fire until users have already suffered.

### frame-metadata

Spec reads and writes. Separate so a query surge cannot starve publishing, and
so publishing cannot be scaled with query load. Two tasks are enough.

---

## Snowflake from ECS

- **Key-pair authentication.** Mount the private key from Secrets Manager;
  never bake it into an image. SSO (`externalbrowser`) cannot work in a
  container.
- **Connections are thread-local and reused.** With the default AnyIO
  threadpool of 40, each task can hold up to 40 sessions — 8 tasks is 320. Check
  that against your account's session limits and lower the threadpool if
  needed.
- **Separate warehouses for serving and batch.** Set
  `FRAME_SNOWFLAKE_WAREHOUSE_HEAVY` so expensive plans route away from the
  interactive cluster.
- **Interactive warehouse scales out, not up**: `MAX_CLUSTER_COUNT` 3–4 on an
  XSMALL. A bigger warehouse makes one query faster; more clusters let fifty
  people load a dashboard at once.

---

## Registry: move off the filesystem

The file-backed registry is right for development and wrong for several tasks:
there is no concurrent-write story and no version history. Postgres implements
the same interface (`get` / `put` / `delete` / `list`).

Until then, a shared EFS mount works but adds latency to every stat() — the
registry caches parsed specs by mtime, so this is survivable, not good.

---

## Single-task and development

None of the above is needed to run Frame. With `FRAME_REDIS_URL` unset and no
`redis` package installed, the cache is a per-task LRU and everything else is
identical — same key, same TTLs, same guards. `tests/test_cache.py` exists to
keep it that way: it fails if Redis becomes a hard dependency, if the import
stops being lazy, or if an unreachable URL breaks startup.

---

## Environment reference

```bash
# engine
FRAME_ENGINE=snowflake

# shared cache — required before scaling past one task
FRAME_REDIS_URL=rediss://...:6379
FRAME_REDIS_TIMEOUT=0.25
FRAME_CACHE_L1_ENTRIES=512
FRAME_CACHE_L1_TTL=15

# cost guards
FRAME_MAX_ROWS=50000
FRAME_STATEMENT_TIMEOUT=30
FRAME_LARGE_TABLE_ROWS=50000000
FRAME_WATERMARK_TTL=60

# snowflake
SNOWFLAKE_ACCOUNT=...
SNOWFLAKE_USER=frame_service
SNOWFLAKE_PRIVATE_KEY_PATH=/run/secrets/frame_rsa_key.p8
SNOWFLAKE_WAREHOUSE=FRAME_INTERACTIVE_XS
FRAME_SNOWFLAKE_WAREHOUSE_HEAVY=FRAME_BATCH_S
SNOWFLAKE_ROLE=FRAME_ANALYST_ALL
SNOWFLAKE_DATABASE=ANALYTICS
SNOWFLAKE_SCHEMA=OPS
```

---

## What to watch

| Signal | Where | Alert when |
|---|---|---|
| Cache is shared | `/health` → `cache.shared` | `false` with >1 task |
| Warehouse round-trips per dashboard load | `/health` → `warehouse` ÷ loads | above ~2 |
| Cache hit rate | `/health` → `cache.hit_rate` | below 0.90 |
| Redis errors | `/health` → `cache.l2.errors` | rising |
| Credits by dashboard | Snowflake `QUERY_HISTORY`, `query_tag LIKE 'frame:%'` | any dashboard dominating |

The first two are the ones that decide whether the deployment is affordable.
Everything else is ordinary web operations.
