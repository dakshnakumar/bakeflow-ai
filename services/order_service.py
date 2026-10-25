import random

SAMPLE_CUSTOMERS = [
    ("Sarah Jenkins", "+1 (415) 555-0142"),
    ("David Miller", "+1 (206) 555-0188"),
    ("Emma Watson", "+1 (312) 555-0194"),
    ("Chloe Bennett", "+1 (617) 555-0123"),
    ("Lucas Vance", "+1 (512) 555-0177"),
    ("Liam Davis", "+1 (408) 555-0156"),
    ("Sophia Martinez", "+1 (305) 555-0167"),
    ("Olivia Parker", "+1 (212) 555-0131"),
    ("Noah Walker", "+1 (702) 555-0182"),
    ("Mia Thompson", "+1 (602) 555-0199"),
]
import os
import sys
import asyncio
import json
from pathlib import Path
from datetime import date, datetime
from typing import Dict, List, Optional

# Ensure project root is in sys.path for direct debugger runs
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from models import Order, CakeSpecification, OrderStatus, InquiryRequest, QuoteResponse
except ImportError:
    from ..models import Order, CakeSpecification, OrderStatus, InquiryRequest, QuoteResponse

try:
    from services.ai_service import BakeryAiService
    from services.paypal_service import PayPalService
except ImportError:
    from .ai_service import BakeryAiService
    from .paypal_service import PayPalService

class OrderService:
    def __init__(self, ai_service: BakeryAiService, paypal_service: PayPalService):
        self.ai_service = ai_service
        self.paypal_service = paypal_service
        self.orders: Dict[str, Order] = {}
        self.storage_file = ROOT_DIR / "orders_cache.json"
        self.order_counter = 1001
        self.subscribers: List[asyncio.Queue] = []
        self._load_orders()

    def _load_orders(self):
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        order = Order.model_validate(item)
                        self.orders[order.id] = order
            except Exception as e:
                pass

        if not self.orders:
            self._seed_initial_orders()
            self._save_orders()

        # Recalculate order counter based on highest existing BK-xxx
        max_num = 1000
        for oid in self.orders.keys():
            if oid.startswith("BK-"):
                try:
                    num = int(oid.replace("BK-", ""))
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        self.order_counter = max_num + 1

    def _save_orders(self):
        try:
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump([o.model_dump(mode="json") for o in self.orders.values()], f, indent=2)
        except Exception:
            pass

    def _seed_initial_orders(self):
        spec1 = CakeSpecification(
            flavor="Red Velvet with Cream Cheese",
            servings=12,
            tiers=1,
            theme="Vintage Lambeth Heart Piping",
            dietaryPreferences="Eggless",
            customMessage="Happy 25th Sarah!",
            pickupDate=date.today(),
            referenceImageUrl="https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop",
            basePrice=54.00,
            addOnsPrice=15.00,
            totalPrice=69.00
        )
        o1 = Order(
            id="BK-1000",
            customerName="Sarah Jenkins",
            customerPhone="+1-555-0192",
            cakeSpec=spec1,
            totalAmount=69.00,
            status=OrderStatus.BAKING,
            paypalOrderId="PP-DEMO-001",
            paypalCaptureId="CAP-DEMO-001"
        )
        self.orders[o1.id] = o1

        spec2 = CakeSpecification(
            flavor="Belgian Dark Chocolate",
            servings=20,
            tiers=2,
            theme="Gold Accent Birthday Tier",
            dietaryPreferences="Standard",
            customMessage="Happy 40th David!",
            pickupDate=date.today(),
            referenceImageUrl="https://images.unsplash.com/photo-1535141192574-5d4897c13136?w=500&auto=format&fit=crop",
            basePrice=90.00,
            addOnsPrice=25.00,
            totalPrice=115.00
        )
        o2 = Order(
            id="BK-999",
            customerName="David Miller",
            customerPhone="+1-555-0184",
            cakeSpec=spec2,
            totalAmount=115.00,
            status=OrderStatus.READY_FOR_PICKUP,
            paypalOrderId="PP-DEMO-002",
            paypalCaptureId="CAP-DEMO-002"
        )
        self.orders[o2.id] = o2

    async def process_inquiry(self, req: InquiryRequest) -> QuoteResponse:
        customer_name = req.customerName
        customer_phone = req.customerPhone or "+1-555-0199"

        # 1. Invoke AI Router with Merchant Persona (Anna), Payment Readiness & Catalogue check
        spec, agent_msg, ready_for_payment, show_catalogue, buyer_name = await self.ai_service.parse_inquiry_with_ai(
            text=req.message,
            image_url=req.imageUrl,
            history=req.history,
            customer_name=customer_name or "there"
        )

        if buyer_name and len(buyer_name.strip()) > 1:
            customer_name = buyer_name.strip()
        elif not customer_name or customer_name in ["Jessica Taylor", "Jessica", "Customer"]:
            rand_name, rand_phone = random.choice(SAMPLE_CUSTOMERS)
            customer_name = rand_name
            customer_phone = rand_phone

        catalogue_items = None
        if show_catalogue:
            catalogue_items = await self.paypal_service.get_catalog_products()

        # If customer is NOT ready to pay yet, keep as warm merchant consultation:
        # Do not create PayPal order or push to Kitchen Kanban board yet.
        if not ready_for_payment:
            return QuoteResponse(
                orderId=None,
                customerName=customer_name,
                cakeSpec=spec,
                totalAmount=spec.totalPrice if spec else None,
                status=None,
                paypalApprovalUrl=None,
                agentMessage=agent_msg,
                readyForPayment=False,
                showCatalogue=show_catalogue,
                catalogueItems=catalogue_items
            )

        # 2. Customer IS READY TO PAY: Create formal order and PayPal checkout
        order_id = f"BK-{self.order_counter}"
        self.order_counter += 1

        order = Order(
            id=order_id,
            customerName=customer_name,
            customerPhone=customer_phone,
            cakeSpec=spec,
            totalAmount=spec.totalPrice,
            status=OrderStatus.PAYMENT_PENDING
        )

        # 3. Create PayPal Order v2
        pp_res = await self.paypal_service.create_order(order)
        order.paypalOrderId = pp_res["paypalOrderId"]
        order.paypalApprovalUrl = pp_res["approvalUrl"]

        self.orders[order_id] = order
        self._save_orders()

        # 4. Broadcast to Kitchen Kanban SSE Stream
        await self.broadcast_event("ORDER_QUOTED", order)

        return QuoteResponse(
            orderId=order_id,
            customerName=order.customerName,
            cakeSpec=spec,
            totalAmount=order.totalAmount,
            status=order.status,
            paypalApprovalUrl=order.paypalApprovalUrl,
            agentMessage=agent_msg,
            readyForPayment=True
        )

    async def confirm_payment(
        self,
        order_id: str,
        capture_id: str,
        invoice_id: Optional[str] = None,
        invoice_url: Optional[str] = None,
        dashboard_url: Optional[str] = None
    ) -> Optional[Order]:
        order = self.orders.get(order_id)
        if order:
            order.paypalCaptureId = capture_id
            if invoice_id:
                order.paypalInvoiceId = invoice_id
            if invoice_url:
                order.paypalInvoiceUrl = invoice_url
            if dashboard_url:
                order.paypalDashboardUrl = dashboard_url
            order.status = OrderStatus.CONFIRMED
            order.updatedAt = datetime.now()
            self._save_orders()
            await self.broadcast_event("ORDER_PAID", order)
            return order
        return None

    async def update_status(self, order_id: str, new_status: OrderStatus) -> Optional[Order]:
        order = self.orders.get(order_id)
        if order:
            order.status = new_status
            order.updatedAt = datetime.now()
            self._save_orders()
            await self.broadcast_event("STATUS_UPDATED", order)
            return order
        return None

    def get_all_orders(self) -> List[Order]:
        self._load_orders()
        return list(self.orders.values())

    def get_order(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)

    async def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)

    async def broadcast_event(self, event_type: str, order: Order):
        payload = {
            "event": event_type,
            "data": order.model_dump(mode="json")
        }
        for q in self.subscribers:
            await q.put(payload)

    def clear_pending_orders(self) -> int:
        to_delete = [oid for oid, o in self.orders.items() if o.status in [OrderStatus.PAYMENT_PENDING, OrderStatus.QUOTED]]
        for oid in to_delete:
            del self.orders[oid]
        self._save_orders()
        return len(to_delete)

    def delete_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            del self.orders[order_id]
            self._save_orders()
            return True
        return False
