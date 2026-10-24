import os
import sys
import re
import json
import base64
import logging
import httpx
from pathlib import Path
from datetime import date, timedelta
from typing import Optional, Tuple, Dict, Any

# Ensure project root is in sys.path for direct debugger runs
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from models import CakeSpecification
except ImportError:
    from ..models import CakeSpecification

import anthropic

logger = logging.getLogger("ai_service")

class BakeryAiService:
    def __init__(self, business_name: str = "Sweet Creations by Anna", 
                 base_price_per_serving: float = 4.50, 
                 tier_multiplier: float = 25.00):
        self.business_name = business_name
        self.base_price_per_serving = base_price_per_serving
        self.tier_multiplier = tier_multiplier
        
        # Provider selection: 'auto', 'claude', or 'gemini'
        self.provider = os.getenv("AI_PROVIDER", "auto").lower().strip()
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()

        # Initialize Claude client if key available and valid
        self.claude_client = (
            anthropic.AsyncAnthropic(api_key=self.anthropic_api_key) 
            if self._is_valid_key(self.anthropic_api_key)
            else None
        )

    async def parse_inquiry_with_ai(self, text: str, image_url: Optional[str] = None) -> Tuple[CakeSpecification, str]:
        """
        Unified AI Router supporting both Anthropic Claude 3.5 Sonnet and Google Gemini 1.5/2.5.
        Auto-routes based on AI_PROVIDER or available API keys.
        """
        active_engine = self._determine_engine()
        logger.info(f"AI Router selected engine: {active_engine.upper()}")

        if active_engine == "gemini":
            spec, msg = await self._call_gemini(text, image_url)
            if spec:
                return spec, msg
            logger.warning("Gemini call failed, checking Claude fallback...")
            active_engine = "claude"

        if active_engine == "claude":
            spec, msg = await self._call_claude(text, image_url)
            if spec:
                return spec, msg
            logger.warning("Claude call failed, falling back to heuristic engine...")

        # Ultimate resilient fallback
        logger.info("Using Rule-Based Heuristic Parser")
        spec = self._heuristic_parse(text, image_url)
        msg = self.generate_agent_quote_message(spec)
        return spec, msg

    # Compatibility alias
    async def parse_inquiry_with_claude(self, text: str, image_url: Optional[str] = None) -> Tuple[CakeSpecification, str]:
        return await self.parse_inquiry_with_ai(text, image_url)

    def _determine_engine(self) -> str:
        # Check explicit provider setting
        if self.provider == "gemini" and self._is_valid_key(self.gemini_api_key):
            return "gemini"
        if self.provider == "claude" and self.claude_client:
            return "claude"
        
        # Auto mode
        if self._is_valid_key(self.gemini_api_key):
            return "gemini"
        if self.claude_client:
            return "claude"
        return "heuristic"

    def _is_valid_key(self, k: str) -> bool:
        return bool(k and not k.startswith("mock_") and not k.startswith("your_"))

    # =========================================================================
    # 1. GOOGLE GEMINI (FLASH-LITE-LATEST)
    # =========================================================================
    async def _call_gemini(self, text: str, image_url: Optional[str]) -> Tuple[Optional[CakeSpecification], Optional[str]]:
        if not self._is_valid_key(self.gemini_api_key):
            return None, None

        try:
            logger.info("Invoking Google Gemini AI Agent...")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={self.gemini_api_key}"

            parts = []

            # Multimodal vision
            if image_url and image_url.startswith("http"):
                img_data, media_type = await self._fetch_image_base64(image_url)
                if img_data:
                    parts.append({
                        "inline_data": {
                            "mime_type": media_type,
                            "data": img_data
                        }
                    })

            parts.append({"text": self._build_prompt(text)})

            payload = {
                "contents": [{"parts": parts}],
                "systemInstruction": {
                    "parts": [{"text": f"You are the autonomous AI Assistant for {self.business_name}, a boutique artisan home bakery."}]
                },
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "OBJECT",
                        "properties": {
                            "flavor": {"type": "STRING"},
                            "servings": {"type": "INTEGER"},
                            "tiers": {"type": "INTEGER"},
                            "theme": {"type": "STRING"},
                            "dietaryPreferences": {"type": "STRING"},
                            "customMessage": {"type": "STRING"},
                            "pickupDate": {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                            "basePrice": {"type": "NUMBER"},
                            "addOnsPrice": {"type": "NUMBER"},
                            "totalPrice": {"type": "NUMBER"},
                            "agentMessage": {"type": "STRING"}
                        },
                        "required": ["flavor", "servings", "tiers", "theme", "dietaryPreferences", "pickupDate", "basePrice", "addOnsPrice", "totalPrice", "agentMessage"]
                    }
                }
            }

            async with httpx.AsyncClient(timeout=15.0) as http_client:
                res = await http_client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        raw_json = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        parsed = json.loads(raw_json)
                        logger.info(f"Gemini successfully extracted quote: {parsed.get('theme')} - ${parsed.get('totalPrice')}")
                        return self._map_dict_to_spec(parsed, image_url)
                else:
                    logger.error(f"Gemini API returned status {res.status_code}: {res.text}")

        except Exception as e:
            logger.error(f"Gemini API exception: {e}")
        return None, None

    # =========================================================================
    # 2. ANTHROPIC CLAUDE 3.5 SONNET
    # =========================================================================
    async def _call_claude(self, text: str, image_url: Optional[str]) -> Tuple[Optional[CakeSpecification], Optional[str]]:
        if not self.claude_client:
            return None, None

        try:
            logger.info("Invoking Claude 3.5 Sonnet Vision & Reasoning Agent...")
            content_blocks = []

            if image_url and image_url.startswith("http"):
                img_data, media_type = await self._fetch_image_base64(image_url)
                if img_data:
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": img_data
                        }
                    })

            content_blocks.append({"type": "text", "text": self._build_prompt(text)})

            tools = [{
                "name": "create_cake_quote",
                "description": "Extracts structured cake specifications and dynamic pricing from customer inquiry.",
                "input_schema": self._get_tool_json_schema()
            }]

            response = await self.claude_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0.2,
                system=f"You are the autonomous AI Assistant for {self.business_name}, a boutique artisan home bakery.",
                messages=[{"role": "user", "content": content_blocks}],
                tools=tools,
                tool_choice={"type": "tool", "name": "create_cake_quote"}
            )

            for block in response.content:
                if block.type == "tool_use" and block.name == "create_cake_quote":
                    return self._map_dict_to_spec(block.input, image_url)

        except Exception as e:
            logger.error(f"Claude API exception: {e}")
        return None, None

    # =========================================================================
    # 3. COMMON HELPERS & HEURISTIC FALLBACK
    # =========================================================================
    def _build_prompt(self, text: str) -> str:
        return (
            f"Customer Inquiry: \"{text}\"\n"
            f"Today's Date: {date.today().isoformat()}\n"
            f"Baker Business: {self.business_name}\n"
            f"Pricing Rules:\n"
            f"- Base price: ${self.base_price_per_serving:.2f} per guest serving\n"
            f"- Additional tier surcharge: ${self.tier_multiplier:.2f} per tier above 1\n"
            f"- Dietary accommodation (Eggless/Gluten-Free/Vegan): $15.00\n"
            f"- Custom fondant/sculpture detailing: $20.00\n"
            "Analyze the cake photo (if provided) and customer text to determine: flavor, servings, "
            "tiers, theme, dietary needs, estimated pickup date (YYYY-MM-DD), and pricing breakdown. "
            "Generate a warm, friendly agentMessage acknowledging specific cake design details."
        )

    def _get_tool_json_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "flavor": {"type": "string"},
                "servings": {"type": "integer"},
                "tiers": {"type": "integer"},
                "theme": {"type": "string"},
                "dietaryPreferences": {"type": "string"},
                "customMessage": {"type": "string"},
                "pickupDate": {"type": "string", "description": "YYYY-MM-DD"},
                "basePrice": {"type": "number"},
                "addOnsPrice": {"type": "number"},
                "totalPrice": {"type": "number"},
                "agentMessage": {"type": "string"}
            },
            "required": ["flavor", "servings", "tiers", "theme", "dietaryPreferences", "pickupDate", "basePrice", "addOnsPrice", "totalPrice", "agentMessage"]
        }

    async def _fetch_image_base64(self, image_url: str) -> Tuple[Optional[str], str]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(image_url)
                if res.status_code == 200:
                    b64 = base64.b64encode(res.content).decode("utf-8")
                    content_type = res.headers.get("content-type", "image/jpeg").split(";")[0]
                    if content_type not in ["image/jpeg", "image/png", "image/gif", "image/webp"]:
                        content_type = "image/jpeg"
                    return b64, content_type
        except Exception as e:
            logger.warning(f"Failed to fetch image bytes: {e}")
        return None, "image/jpeg"

    def _map_dict_to_spec(self, d: Dict[str, Any], image_url: Optional[str]) -> Tuple[CakeSpecification, str]:
        raw_date = str(d.get("pickupDate", ""))
        p_date = None
        try:
            p_date = date.fromisoformat(raw_date)
        except Exception:
            # Fall back to relative date parser if LLM returns text like 'this Saturday'
            p_date = self._extract_pickup_date(raw_date.lower())

        base_p = float(d.get("basePrice", 67.50))
        addon_p = float(d.get("addOnsPrice", 0.0))
        total_p = float(d.get("totalPrice", base_p + addon_p))

        spec = CakeSpecification(
            flavor=d.get("flavor", "Signature Vanilla Bean"),
            servings=int(d.get("servings", 15)),
            tiers=int(d.get("tiers", 1)),
            theme=d.get("theme", "Artisan Custom Handcrafted Design"),
            dietaryPreferences=d.get("dietaryPreferences", "Standard"),
            customMessage=d.get("customMessage", "Happy Celebration!"),
            pickupDate=p_date,
            referenceImageUrl=image_url or "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop",
            basePrice=base_p,
            addOnsPrice=addon_p,
            totalPrice=total_p
        )
        agent_msg = d.get("agentMessage", self.generate_agent_quote_message(spec))
        return spec, agent_msg

    def _heuristic_parse(self, text: str, image_url: str = None) -> CakeSpecification:
        lower = text.lower() if text else ""
        servings = self._extract_servings(lower)
        tiers = self._extract_tiers(lower)
        flavor = self._extract_flavor(lower)
        theme = self._extract_theme(lower)
        dietary = self._extract_dietary(lower)
        pickup_date = self._extract_pickup_date(lower)
        custom_message = self._extract_custom_message(text)

        base_price = round(servings * self.base_price_per_serving, 2)
        add_ons = 0.0
        if tiers > 1:
            add_ons += (tiers - 1) * self.tier_multiplier
        if dietary.lower() != "standard":
            add_ons += 15.00
        if any(k in lower for k in ["fondant", "sculpture", "unicorn", "custom", "gold"]):
            add_ons += 20.00

        total_price = round(base_price + add_ons, 2)
        ref_image = image_url if image_url and image_url.strip() else "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop"

        return CakeSpecification(
            flavor=flavor,
            servings=servings,
            tiers=tiers,
            theme=theme,
            dietaryPreferences=dietary,
            customMessage=custom_message,
            pickupDate=pickup_date,
            referenceImageUrl=ref_image,
            basePrice=base_price,
            addOnsPrice=round(add_ons, 2),
            totalPrice=total_price
        )

    def generate_agent_quote_message(self, spec: CakeSpecification) -> str:
        return (
            f"🧁 Hello! This is your Baker Assistant for {self.business_name}.\n\n"
            f"I've prepared a quote for your custom cake:\n"
            f"• Design & Theme: {spec.theme}\n"
            f"• Flavor: {spec.flavor} ({spec.dietaryPreferences})\n"
            f"• Size: {spec.servings} servings across {spec.tiers} tier(s)\n"
            f"• Estimated Pickup Date: {spec.pickupDate.isoformat()}\n\n"
            f"💰 Total: ${spec.totalPrice:.2f} (Base: ${spec.basePrice:.2f} + Custom Detailing: ${spec.addOnsPrice:.2f})\n\n"
            f"To lock in your oven slot with PayPal, click the payment link below:"
        )

    def _extract_servings(self, text: str) -> int:
        match = re.search(r'(\d+)\s*(servings?|people|guests|pax|slices?)', text)
        return int(match.group(1)) if match else 15

    def _extract_tiers(self, text: str) -> int:
        if any(k in text for k in ["3-tier", "3 tier", "three tier"]): return 3
        if any(k in text for k in ["2-tier", "2 tier", "two tier", "double tier"]): return 2
        return 1

    def _extract_flavor(self, text: str) -> str:
        if "chocolate truffle" in text or "truffle" in text: return "Chocolate Truffle"
        if "chocolate" in text: return "Belgian Dark Chocolate"
        if "red velvet" in text: return "Classic Red Velvet with Cream Cheese"
        if "vanilla" in text or "buttercream" in text: return "Madagascar Vanilla Bean"
        if "strawberry" in text or "berry" in text: return "Fresh Strawberry Compote"
        if "lemon" in text or "citrus" in text: return "Zesty Lemon Curd"
        if "lotus" in text or "biscoff" in text: return "Lotus Biscoff Crunch"
        if "coffee" in text or "tiramisu" in text: return "Espresso Tiramisu"
        return "Signature Vanilla & Buttercream"

    def _extract_theme(self, text: str) -> str:
        if "unicorn" in text: return "Magical Unicorn with Gold Horn"
        if "wedding" in text: return "Elegant Floral Wedding"
        if "vintage" in text or "heart" in text: return "Vintage Lambeth Heart Piping"
        if "superhero" in text or "spiderman" in text: return "Superhero Themed"
        if "baby shower" in text: return "Pastel Cloud Baby Shower"
        if "birthday" in text: return "Festive Birthday Celebration"
        return "Artisan Custom Handcrafted Design"

    def _extract_dietary(self, text: str) -> str:
        if "eggless" in text: return "Eggless"
        if "gluten-free" in text or "gluten free" in text: return "Gluten-Free"
        if "vegan" in text: return "100% Vegan"
        if "nut-free" in text or "nut free" in text: return "Nut-Free"
        return "Standard"

    def _extract_pickup_date(self, text: str) -> date:
        today = date.today()
        if "tomorrow" in text: return today + timedelta(days=1)
        if "sunday" in text:
            days_ahead = (6 - today.weekday()) % 7
            return today + timedelta(days=days_ahead if days_ahead != 0 else 7)
        if "saturday" in text or "weekend" in text:
            days_ahead = (5 - today.weekday()) % 7
            return today + timedelta(days=days_ahead if days_ahead != 0 else 7)
        return today + timedelta(days=3)

    def _extract_custom_message(self, text: str) -> str:
        match = re.search(r'[\'"]([^\'"]+)[\'"]', text)
        return match.group(1) if match else "Happy Celebration!"
