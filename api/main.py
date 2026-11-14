import os
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field
import redis
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
INITIAL_TICKETS = int(os.getenv("TOTAL_TICKETS", 100))

# --- MEMORY LEAK SIMULATION STORAGE ---
# Global list holding memory chunks in RAM indefinitely (Simulates an unbounded cache bug)
LEAK_STORAGE = []

r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    socket_timeout=2.0,
    socket_connect_timeout=2.0
)

BOOKINGS_COUNTER = Counter(
    "ticketpulse_bookings_total",
    "Total tickets booked through TicketPulse",
    ["status"]
)

INVENTORY_GAUGE = Gauge(
    "ticketpulse_inventory_remaining",
    "Current live ticket inventory remaining in Redis"
)

REQUEST_LATENCY = Histogram(
    "ticketpulse_request_latency_seconds",
    "API request latency in seconds",
    ["endpoint"]
)

BOOKING_LUA = """
local current = tonumber(redis.call('get', KEYS[1]) or '0')
local qty = tonumber(ARGV[1])
if current >= qty then
    local remaining = current - qty
    redis.call('set', KEYS[1], remaining)
    redis.call('incrby', 'total_sold', qty)
    return {1, remaining}
else
    return {0, current}
end
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if not r.exists("tickets_inventory"):
            r.set("tickets_inventory", INITIAL_TICKETS)
            r.set("total_sold", 0)
        current_stock = int(r.get("tickets_inventory") or 0)
        INVENTORY_GAUGE.set(current_stock)
    except Exception as e:
        print(f"Redis init warning: {e}")
    yield

app = FastAPI(title="TicketPulse API", lifespan=lifespan)

class BookingRequest(BaseModel):
    user_id: str = Field(default_factory=lambda: f"user_{uuid.uuid4().hex[:6]}")
    quantity: int = Field(default=1, ge=1, le=10)

@app.get("/")
def root():
    return {"service": "ticketpulse-api", "status": "online"}

@app.get("/health")
def health_check():
    try:
        start = time.time()
        if r.ping():
            return {
                "status": "healthy",
                "database": "redis",
                "latency_ms": round((time.time() - start) * 1000, 2)
            }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis unreachable: {str(e)}"
        )
    raise HTTPException(status_code=503, detail="Unhealthy")

@app.get("/metrics")
def get_metrics():
    try:
        current_stock = int(r.get("tickets_inventory") or 0)
        INVENTORY_GAUGE.set(current_stock)
    except Exception:
        pass
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/tickets")
def get_tickets():
    with REQUEST_LATENCY.labels(endpoint="/tickets").time():
        try:
            available = int(r.get("tickets_inventory") or 0)
            total_sold = int(r.get("total_sold") or 0)
            INVENTORY_GAUGE.set(available)
            return {
                "available_tickets": available,
                "total_sold": total_sold,
                "status": "in_stock" if available > 0 else "sold_out"
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/book", status_code=status.HTTP_201_CREATED)
def book_ticket(req: BookingRequest):
    with REQUEST_LATENCY.labels(endpoint="/book").time():
        try:
            lua = r.register_script(BOOKING_LUA)
            result = lua(keys=["tickets_inventory"], args=[req.quantity])
            success, remaining = result[0], result[1]

            if success == 1:
                BOOKINGS_COUNTER.labels(status="success").inc(req.quantity)
                INVENTORY_GAUGE.set(remaining)
                return {
                    "success": True,
                    "booking_id": f"BK-{uuid.uuid4().hex[:8].upper()}",
                    "user_id": req.user_id,
                    "quantity": req.quantity,
                    "tickets_remaining": remaining
                }
            else:
                BOOKINGS_COUNTER.labels(status="sold_out").inc(req.quantity)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Sold out! Only {remaining} tickets left."
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

# --- CHAOS DRILL: MEMORY LEAK TRIGGER ---
@app.post("/simulate/leak")
def trigger_memory_leak(mb: int = 30):
    # Allocate uncollectable megabytes into RAM
    chunk = b"X" * (mb * 1024 * 1024)
    LEAK_STORAGE.append(chunk)
    current_leaked = len(LEAK_STORAGE) * mb
    return {
        "status": "leak_injected",
        "injected_chunk_mb": mb,
        "total_leaked_mb": current_leaked,
        "chunks_count": len(LEAK_STORAGE)
    }

@app.post("/simulate/leak/clear")
def clear_memory_leak():
    global LEAK_STORAGE
    LEAK_STORAGE.clear()
    import gc
    gc.collect()
    return {"status": "memory_cleared", "total_leaked_mb": 0}
