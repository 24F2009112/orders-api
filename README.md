# Orders API assignment

FastAPI implementation of the assigned orders API patterns:

- `POST /orders`: idempotent creation using `Idempotency-Key`. Replays return the same order ID.
- `GET /orders?limit=P&cursor=C`: cursor-based pagination through the fixed catalog IDs 1–41 with no gaps or repeats.
- Per-client sliding-window limit: 16 requests per 10 seconds using `X-Client-Id`; excess requests return 429 with `Retry-After`.
- CORS enabled for browser-based grading.

## Deploy on Render

- Runtime: Python 3
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Use a single instance/process so the in-memory idempotency and rate-limit state remains consistent. The fixed pagination catalog always contains IDs 1 through 41.

## Test locally

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
curl -i -X POST http://localhost:8000/orders -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-1' -d '{"item":"book"}'
curl 'http://localhost:8000/orders?limit=10'
curl 'http://localhost:8000/orders?limit=10&cursor=...'
```
