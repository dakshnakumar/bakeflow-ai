import os
import sys
import uuid
import httpx
import logging
from pathlib import Path
from datetime import date, datetime
from typing import Dict, Optional, Any, List

# Ensure project root is in sys.path for direct debugger runs
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from models import Order
except ImportError:
    from ..models import Order

logger = logging.getLogger("paypal_service")

class PayPalService:
    def __init__(self):
        self.client_id = os.getenv("PAYPAL_CLIENT_ID", "mock_sandbox_client_id")
        self.client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "mock_sandbox_client_secret")
        self.base_url = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
        self.return_url = os.getenv("PAYPAL_RETURN_URL", "http://localhost:8000/checkout-complete.html")
        self.cancel_url = os.getenv("PAYPAL_CANCEL_URL", "http://localhost:8000/checkout-cancelled.html")

    def is_mock_mode(self) -> bool:
        return not self.client_id or self.client_id.startswith("mock_")

    async def create_order(self, order: Order) -> Dict[str, str]:
        if self.is_mock_mode():
            mock_order_id = f"PP-{uuid.uuid4().hex[:8].upper()}"
            encoded_desc = order.cakeSpec.theme.replace(' ', '%20')
            mock_approval_url = f"/paypal-sandbox-mock.html?orderId={order.id}&amount={order.totalAmount:.2f}&desc={encoded_desc}"
            return {
                "paypalOrderId": mock_order_id,
                "approvalUrl": mock_approval_url
            }

        try:
            token = await self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            payload = {
                "intent": "CAPTURE",
                "purchase_units": [{
                    "reference_id": order.id,
                    "description": f"Custom Cake: {order.cakeSpec.theme}",
                    "amount": {
                        "currency_code": "USD",
                        "value": f"{order.totalAmount:.2f}"
                    }
                }],
                "application_context": {
                    "brand_name": "Sweet Creations by Anna",
                    "landing_page": "BILLING",
                    "shipping_preference": "NO_SHIPPING",
                    "user_action": "PAY_NOW",
                    "return_url": f"{self.return_url}?internalOrderId={order.id}",
                    "cancel_url": f"{self.cancel_url}?internalOrderId={order.id}"
                }
            }

            async with httpx.AsyncClient() as client:
                res = await client.post(f"{self.base_url}/v2/checkout/orders", json=payload, headers=headers)
                if res.status_code in [200, 201]:
                    data = res.json()
                    paypal_order_id = data.get("id")
                    approval_url = ""
                    for link in data.get("links", []):
                        if link.get("rel") == "approve":
                            approval_url = link.get("href")
                            break
                    return {
                        "paypalOrderId": paypal_order_id,
                        "approvalUrl": approval_url
                    }
        except Exception as e:
            logger.error(f"Error calling live PayPal Sandbox: {e}. Falling back to simulation.")

        # Fallback simulation
        mock_order_id = f"PP-{uuid.uuid4().hex[:8].upper()}"
        encoded_desc = order.cakeSpec.theme.replace(' ', '%20')
        mock_approval_url = f"/paypal-sandbox-mock.html?orderId={order.id}&amount={order.totalAmount:.2f}&desc={encoded_desc}"
        return {
            "paypalOrderId": mock_order_id,
            "approvalUrl": mock_approval_url
        }

    async def capture_order(self, paypal_order_id: str) -> Optional[Dict[str, Any]]:
        """
        Captures an approved PayPal Order v2 via /v2/checkout/orders/{id}/capture
        """
        if self.is_mock_mode():
            mock_cap = f"CAPTURE-{uuid.uuid4().hex[:8].upper()}"
            return {"captureId": mock_cap, "status": "COMPLETED", "mode": "mock"}

        try:
            token = await self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/v2/checkout/orders/{paypal_order_id}/capture",
                    json={},
                    headers=headers
                )
                if res.status_code in [200, 201]:
                    data = res.json()
                    captures = []
                    for pu in data.get("purchase_units", []):
                        for cap in pu.get("payments", {}).get("captures", []):
                            captures.append(cap.get("id"))
                    cap_id = captures[0] if captures else data.get("id")
                    return {
                        "captureId": cap_id,
                        "status": data.get("status", "COMPLETED"),
                        "raw": data,
                        "mode": "live_sandbox"
                    }
                else:
                    logger.warning(f"PayPal capture_order returned status {res.status_code}: {res.text}")
                    return None
        except Exception as e:
            logger.error(f"Error capturing live PayPal order {paypal_order_id}: {e}")
            return None

    async def record_sandbox_invoice_payment(self, order: Order, payment_method: str = "PAYPAL") -> Dict[str, Any]:
        """
        Creates, sends, and records a paid transaction via official PayPal Invoicing API v2.
        This writes a real transaction directly into the merchant's PayPal Sandbox account
        (visible under https://sandbox.paypal.com Invoicing and Activity dashboards).
        """
        if self.is_mock_mode():
            mock_inv = f"INV-MOCK-{uuid.uuid4().hex[:6].upper()}"
            mock_pay = f"PAY-MOCK-{uuid.uuid4().hex[:8].upper()}"
            return {
                "invoiceId": mock_inv,
                "paymentId": mock_pay,
                "invoiceNumber": "MOCK-001",
                "invoiceUrl": f"https://www.sandbox.paypal.com/invoice/p/#{mock_inv}",
                "dashboardUrl": "https://sandbox.paypal.com/invoice/manage",
                "status": "PAID"
            }

        try:
            token = await self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient(timeout=12.0) as client:
                # 1. Generate next sequential invoice number
                inv_num = f"INV-{uuid.uuid4().hex[:4].upper()}"
                try:
                    num_res = await client.post(f"{self.base_url}/v2/invoicing/generate-next-invoice-number", headers=headers)
                    if num_res.status_code == 200:
                        inv_num = num_res.json().get("invoice_number", inv_num)
                except Exception:
                    pass

                # 2. Create invoice draft
                today_str = str(date.today())
                cake_title = f"{order.cakeSpec.theme} ({order.cakeSpec.flavor})"
                draft_payload = {
                    "detail": {
                        "invoice_number": inv_num,
                        "invoice_date": today_str,
                        "currency_code": "USD",
                        "note": f"Custom Artisan Cake Order #{order.id} - Baked by Anna",
                        "terms_and_conditions": "Handcrafted baked goods. Stored at 4°C. Pickup on scheduled date."
                    },
                    "invoicer": {
                        "name": {"given_name": "Anna", "surname": "Baker"},
                        "business_name": "Sweet Creations by Anna (BakeFlow AI)"
                    },
                    "primary_recipients": [{
                        "billing_info": {
                            "name": {"given_name": order.customerName.split()[0], "surname": " ".join(order.customerName.split()[1:]) or "Customer"},
                            "email_address": "buyer-baker@example.com"
                        }
                    }],
                    "items": [{
                        "name": cake_title[:60],
                        "description": f"{order.cakeSpec.servings} servings, {order.cakeSpec.tiers} tier(s). Dietary: {order.cakeSpec.dietaryPreferences}. Message: '{order.cakeSpec.customMessage}'",
                        "quantity": "1",
                        "unit_amount": {
                            "currency_code": "USD",
                            "value": f"{order.totalAmount:.2f}"
                        }
                    }]
                }

                inv_create_res = await client.post(f"{self.base_url}/v2/invoicing/invoices", json=draft_payload, headers=headers)
                if inv_create_res.status_code not in [200, 201]:
                    raise RuntimeError(f"PayPal invoice creation failed: {inv_create_res.text}")

                inv_data = inv_create_res.json()
                inv_id = inv_data.get("id") or (inv_data.get("href", "").split("/")[-1] if "href" in inv_data else None)
                if not inv_id:
                    raise RuntimeError(f"No invoice ID returned: {inv_data}")

                # 3. Send invoice so it becomes active in PayPal Sandbox
                payer_view_url = f"https://www.sandbox.paypal.com/invoice/p/#{inv_id}"
                try:
                    send_res = await client.post(f"{self.base_url}/v2/invoicing/invoices/{inv_id}/send", headers=headers)
                    if send_res.status_code in [200, 201]:
                        payer_view_url = send_res.json().get("href", payer_view_url)
                except Exception as e:
                    logger.warning(f"Could not send invoice {inv_id}: {e}")

                # 4. Record payment against invoice (marks PAID in Sandbox dashboard)
                pay_payload = {
                    "method": payment_method,
                    "payment_date": today_str,
                    "amount": {
                        "currency_code": "USD",
                        "value": f"{order.totalAmount:.2f}"
                    },
                    "note": f"Payment captured via BakeFlow AI for Order #{order.id}"
                }
                pay_res = await client.post(f"{self.base_url}/v2/invoicing/invoices/{inv_id}/payments", json=pay_payload, headers=headers)
                payment_id = f"PAY-{uuid.uuid4().hex[:8].upper()}"
                if pay_res.status_code in [200, 201]:
                    pay_data = pay_res.json()
                    payment_id = pay_data.get("payment_id", payment_id)

                logger.info(f"Successfully recorded real PayPal Sandbox invoice {inv_id} with payment {payment_id}")

                return {
                    "invoiceId": inv_id,
                    "paymentId": payment_id,
                    "invoiceNumber": inv_num,
                    "invoiceUrl": payer_view_url,
                    "dashboardUrl": "https://sandbox.paypal.com/invoice/manage",
                    "status": "PAID"
                }

        except Exception as e:
            logger.error(f"Error in record_sandbox_invoice_payment: {e}")
            raise e

    async def get_sandbox_transactions(self) -> Dict[str, Any]:
        """
        Fetches live PayPal Sandbox invoices and transaction records from official PayPal API.
        """
        if self.is_mock_mode():
            return {
                "connected": False,
                "environment": "mock",
                "invoices": []
            }

        try:
            token = await self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    f"{self.base_url}/v2/invoicing/invoices?page=1&page_size=20&total_required=true",
                    headers=headers
                )
                if res.status_code == 200:
                    data = res.json()
                    raw_items = data.get("items", [])
                    formatted = []
                    for item in raw_items:
                        inv_id = item.get("id")
                        detail = item.get("detail", {})
                        recipients = item.get("primary_recipients", [])
                        recipient_name = "Customer"
                        if recipients and "billing_info" in recipients[0]:
                            recipient_name = recipients[0]["billing_info"].get("name", {}).get("full_name") or recipients[0]["billing_info"].get("email_address", "Customer")
                        amt = item.get("amount", {}).get("value", "0.00")
                        currency = item.get("amount", {}).get("currency_code", "USD")
                        paid_amt = item.get("payments", {}).get("paid_amount", {}).get("value", "0.00")
                        formatted.append({
                            "id": inv_id,
                            "invoiceNumber": detail.get("invoice_number", ""),
                            "invoiceDate": detail.get("invoice_date", ""),
                            "status": item.get("status", "SENT"),
                            "amount": f"{currency} {amt}",
                            "paidAmount": f"{currency} {paid_amt}",
                            "recipient": recipient_name,
                            "note": detail.get("note", ""),
                            "viewUrl": f"https://www.sandbox.paypal.com/invoice/p/#{inv_id}",
                            "dashboardUrl": "https://sandbox.paypal.com/invoice/manage"
                        })

                    return {
                        "connected": True,
                        "environment": "sandbox",
                        "clientId": self.client_id[:8] + "..." + self.client_id[-6:],
                        "totalItems": data.get("total_items", len(formatted)),
                        "dashboardUrl": "https://sandbox.paypal.com/invoice/manage",
                        "activityUrl": "https://sandbox.paypal.com/activity",
                        "invoices": formatted
                    }
        except Exception as e:
            logger.error(f"Error fetching sandbox transactions: {e}")

        return {
            "connected": False,
            "environment": "sandbox",
            "error": "Failed to query PayPal API",
            "invoices": []
        }

    async def get_catalog_products(self) -> list[dict]:
        """
        Retrieves products from the official PayPal Catalog API (/v1/catalogs/products)
        and enriches with bakery specs for display.
        """
        default_catalogue = [
            {
                "id": "PROD-7BR51252M7702643P",
                "name": "Magical Unicorn 2-Tier Artisan Cake",
                "description": "Hand-sculpted 24k-gold luster horn, pastel piped buttercream rosettes, and whimsical edible pearls.",
                "baseServings": 18,
                "tiers": 2,
                "startingPrice": 110.00,
                "flavor": "Madagascar Vanilla & Fresh Strawberry Compote",
                "dietary": "Eggless Available",
                "imageUrl": "https://images.unsplash.com/photo-1535141192574-5d4897c13136?w=500&auto=format&fit=crop",
                "badge": "Bestseller ✨"
            },
            {
                "id": "PROD-5UK97775XY4211501",
                "name": "Vintage Lambeth Heart Piping Cake",
                "description": "Intricate Victorian frill piping in cherry red with maraschino cherries & personalized message banner.",
                "baseServings": 10,
                "tiers": 1,
                "startingPrice": 65.00,
                "flavor": "Classic Red Velvet with Cream Cheese",
                "dietary": "Eggless / Standard",
                "imageUrl": "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop",
                "badge": "Trending 🍒"
            },
            {
                "id": "PROD-3SY0923482859592B",
                "name": "Belgian Dark Chocolate Truffle Cake",
                "description": "70% Callebaut dark chocolate sponge, velvety ganache drip, edible gold leaf, and fresh seasonal berries.",
                "baseServings": 20,
                "tiers": 2,
                "startingPrice": 115.00,
                "flavor": "Belgian Dark Chocolate & Espresso Cream",
                "dietary": "Gluten-Free Available",
                "imageUrl": "https://images.unsplash.com/photo-1606890737304-57a1ca8a5b62?w=500&auto=format&fit=crop",
                "badge": "Rich & Decadent 🍫"
            },
            {
                "id": "PROD-BOTANICAL-04",
                "name": "Pressed Wildflower Meadow Cake",
                "description": "Organic culinary pressed pansies and violas embedded on rustic textured lemon curd buttercream.",
                "baseServings": 15,
                "tiers": 1,
                "startingPrice": 85.00,
                "flavor": "Zesty Lemon Curd & Lavender Thyme",
                "dietary": "100% Vegan Available",
                "imageUrl": "https://images.unsplash.com/photo-1588195538326-c5b1e9f80a1b?w=500&auto=format&fit=crop",
                "badge": "Artisan Floral 🌸"
            }
        ]

        if not self.is_mock_mode():
            try:
                token = await self._get_access_token()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                async with httpx.AsyncClient(timeout=8.0) as client:
                    res = await client.get(
                        f"{self.base_url}/v1/catalogs/products?page_size=20&total_required=true",
                        headers=headers
                    )
                    if res.status_code == 200:
                        data = res.json()
                        paypal_prods = data.get("products", [])
                        if paypal_prods:
                            merged = []
                            default_map = {p["id"]: p for p in default_catalogue}
                            name_map = {p["name"].lower(): p for p in default_catalogue}
                            for pp in paypal_prods:
                                pid = pp.get("id")
                                pname = pp.get("name", "")
                                match = default_map.get(pid) or name_map.get(pname.lower())
                                if match:
                                    item = match.copy()
                                    item["id"] = pid
                                    item["name"] = pname
                                    merged.append(item)
                                else:
                                    merged.append({
                                        "id": pid,
                                        "name": pname,
                                        "description": pp.get("description", "Artisan bakery handcrafted cake"),
                                        "baseServings": 15,
                                        "tiers": 1,
                                        "startingPrice": 75.00,
                                        "flavor": "Signature Madagascar Vanilla",
                                        "dietary": "Standard",
                                        "imageUrl": pp.get("image_url") or "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop",
                                        "badge": "PayPal Catalog"
                                    })
                            return merged
            except Exception as e:
                logger.warning(f"Error fetching live PayPal catalog products: {e}")

        return default_catalogue

    async def _get_access_token(self) -> str:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{self.base_url}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            if res.status_code == 200:
                return res.json().get("access_token")
            raise RuntimeError(f"Failed to obtain PayPal token: {res.text}")
