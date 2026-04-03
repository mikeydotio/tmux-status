# Research: Python HTTP Server Frameworks

## Context
Need a minimal REST server: 2 endpoints (`GET /quota`, `GET /health`), optional API key auth, runs as a daemon. Low traffic (handful of clients polling every ~60s).

## Comparison

| Framework | Deps | Install Size | LoC for 2 endpoints + auth | Standalone? | Maintenance |
|-----------|------|-------------|---------------------------|-------------|-------------|
| `http.server` (stdlib) | 0 | 0 | ~80-120 | Yes | Python core |
| Flask | 3+ (Werkzeug, Jinja2, etc.) | ~5 MB | ~40-60 | Yes (dev server) / gunicorn (prod) | Active, mature |
| Bottle | 0 (single file) | ~200 KB | ~30-50 | Yes | Maintained, slow cadence |
| FastAPI | 5+ (Starlette, Pydantic, uvicorn) | ~15 MB | ~30-50 | Needs uvicorn | Active, popular |
| aiohttp | 3+ (multidict, yarl, etc.) | ~8 MB | ~50-70 | Yes | Active |

## Analysis

### stdlib `http.server`
- **Pros**: Zero dependencies. Always available. No version conflicts.
- **Cons**: No routing abstraction — you manually parse paths in `do_GET`. No JSON helpers. Verbose for even simple APIs. Threading model is basic (`ThreadingHTTPServer`).
- **Verdict**: Workable but ugly. Appropriate when "no new dependencies" is an absolute hard constraint.
- **Confidence**: High

### Flask
- **Pros**: Most widely known Python web framework. Excellent docs. `@app.route` decorator pattern is clean. Built-in dev server works fine for low-traffic internal services.
- **Cons**: Pulls in Werkzeug, Jinja2, MarkupSafe, itsdangerous, click, blinker — heavier than needed for 2 endpoints. Jinja2 is unnecessary (we never render HTML).
- **Verdict**: Overkill. The dependency weight isn't justified for 2 JSON endpoints.
- **Confidence**: High

### Bottle
- **Pros**: Single-file framework (~4500 lines, zero deps). Flask-like decorator routing. Built-in JSON helpers. Built-in server (WSGIRef-based) that's fine for low traffic. Can optionally use paste, gunicorn, etc. Mature (since 2009). Install: `pip install bottle` or literally copy `bottle.py` into the project.
- **Cons**: Smaller community than Flask. Less middleware ecosystem (but we only need one auth check). No async support (irrelevant for our use case).
- **Code example**:
  ```python
  import bottle
  app = bottle.Bottle()

  @app.route('/health')
  def health():
      return {"status": "ok"}

  @app.route('/quota')
  def quota():
      return load_cached_quota()

  app.run(host='0.0.0.0', port=7850)
  ```
- **Verdict**: Sweet spot. Zero-dep micro-framework with clean ergonomics. Perfect fit.
- **Confidence**: High

### FastAPI
- **Pros**: Modern, async, auto-generates OpenAPI docs. Type validation via Pydantic.
- **Cons**: Heavy dependency chain (Starlette, Pydantic, uvicorn, anyio, etc.). Requires uvicorn or similar ASGI server. Async adds complexity with no benefit for our blocking `curl_cffi` scraping.
- **Verdict**: Over-engineered for this use case.
- **Confidence**: High

### aiohttp
- **Pros**: Async-native, battle-tested.
- **Cons**: Similar weight to Flask. Async complicates `curl_cffi` integration (which is sync). No real benefit.
- **Verdict**: Wrong tool for this job.
- **Confidence**: High

## Recommendation

**Bottle** is the clear winner. Reasons:
1. Zero transitive dependencies — matches the project's minimal philosophy
2. Clean Flask-like API in ~30 lines of application code
3. Built-in server is perfectly adequate for <10 clients on a LAN/tailnet
4. Can be vendored as a single file if we want zero `pip install` requirement
5. Mature and stable (15+ years, API frozen)

**Fallback**: If we want truly zero external dependencies, stdlib `http.server` works but requires ~2x the code and manual JSON/routing plumbing. Given that `curl_cffi` is already a required dependency (for the scraper), adding `bottle` (a single-file, zero-dep package) is negligible overhead.

**Confidence**: High (95%) — this is a well-understood problem space with clear tradeoffs.
