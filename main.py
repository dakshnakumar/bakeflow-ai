import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Explicitly ensure the project root directory is at the front of sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load .env variables
load_dotenv(ROOT_DIR / ".env")

import asyncio
import json
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from models import InquiryRequest, QuoteResponse, Order, OrderStatusUpdateRequest
from services.ai_service import BakeryAiService
from services.paypal_service import PayPalService
from services.order_service import OrderService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("baker_ai_main")

app = FastAPI(
    title="BakeFlow AI • PayPal Hackathon 2026",
    description="Autonomous Order Lifecycle & Kitchen Kanban for Home Bakers",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ai_service = BakeryAiService()
paypal_service = PayPalService()
order_service = OrderService(ai_service=ai_service, paypal_service=paypal_service)

# ==========================================
# REST API ENDPOINTS
# ==========================================

@app.post("/api/orders/inquiry", response_model=QuoteResponse)
async def submit_inquiry(request: InquiryRequest):
    return await order_service.process_inquiry(request)

@app.get("/api/orders", response_model=list[Order])
async def get_all_orders():
    return order_service.get_all_orders()

@app.get("/api/orders/{order_id}", response_model=Order)
async def get_order(order_id: str):
    order = order_service.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.patch("/api/orders/{order_id}/status", response_model=Order)
async def update_order_status(order_id: str, request: OrderStatusUpdateRequest):
    updated = await order_service.update_status(order_id, request.newStatus)
    if not updated:
        raise HTTPException(status_code=404, detail="Order not found")
    return updated

@app.post("/api/orders/{order_id}/simulate-payment")
async def simulate_payment(order_id: str):
    mock_capture_id = f"CAP-PY-{asyncio.get_event_loop().time()}"
    order = await order_service.confirm_payment(order_id, mock_capture_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "status": "SUCCESS",
        "message": "Payment captured via PayPal Sandbox simulation",
        "order": order
    }

@app.post("/api/paypal/webhook")
async def handle_paypal_webhook(request: Request):
    try:
        body = await request.json()
        event_type = body.get("event_type", "")
        logger.info(f"Received PayPal Webhook: {event_type}")

        if event_type in ["PAYMENT.CAPTURE.COMPLETED", "CHECKOUT.ORDER.APPROVED"]:
            resource = body.get("resource", {})
            capture_id = resource.get("id", "")
            custom_id = resource.get("custom_id") or resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id", "")
            
            if not custom_id and "purchase_units" in resource and len(resource["purchase_units"]) > 0:
                custom_id = resource["purchase_units"][0].get("reference_id", "")

            if custom_id:
                await order_service.confirm_payment(custom_id, capture_id)
                logger.info(f"Order {custom_id} marked CONFIRMED by PayPal Webhook")

        return {"status": "WEBHOOK_PROCESSED"}
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return {"status": "WEBHOOK_ERROR", "error": str(e)}

@app.get("/api/kitchen/stream")
async def stream_kitchen_events(request: Request):
    queue = await order_service.subscribe()

    async def event_generator():
        yield {
            "event": "INIT",
            "data": "Connected to Python Kitchen Real-Time Stream"
        }
        try:
            while True:
                if await request.is_disconnected():
                    break
                payload = await queue.get()
                yield {
                    "event": payload["event"],
                    "data": json.dumps(payload["data"])
                }
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            order_service.unsubscribe(queue)

    return EventSourceResponse(event_generator())

# Mount static frontend
STATIC_DIR = ROOT_DIR / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    print("==================================================================")
    print("🧁 BakeFlow AI (Python/FastAPI) starting at http://localhost:8000")
    print("==================================================================")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
