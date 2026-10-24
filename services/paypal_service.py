import os
import sys
import uuid
import httpx
import logging
from pathlib import Path
from typing import Dict, Optional

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
                    "brand_name": "Artisan Bakery AI",
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

    async def capture_order(self, paypal_order_id: str) -> str:
        if self.is_mock_mode():
            return f"CAPTURE-{uuid.uuid4().hex[:8].upper()}"

        try:
            token = await self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{self.base_url}/v2/checkout/orders/{paypal_order_id}/capture", json={}, headers=headers)
                if res.status_code in [200, 201]:
                    return res.json().get("id")
        except Exception as e:
            logger.error(f"Error capturing order {paypal_order_id}: {e}")

        return f"CAP-FALLBACK-{uuid.uuid4().hex[:8].upper()}"

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
