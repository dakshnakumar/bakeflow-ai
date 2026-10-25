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

    async def parse_inquiry_with_ai(
        self,
        text: str,
        image_url: Optional[str] = None,
        history: Optional[list] = None,
        customer_name: Optional[str] = "Jessica"
    ) -> Tuple[CakeSpecification, str, bool, bool, Optional[str]]:
        """
        Unified AI Router supporting Google Gemini and Anthropic Claude 3.5 Sonnet.
        Functions as Anna (Artisan Home Baker Merchant) - friendly, culinary-minded dialogue.
        Crucially: Only marks ready_for_payment=True when customer is explicitly ready to pay.
        Returns: (spec, agent_message, ready_for_payment, show_catalogue)
        """
        active_engine = self._determine_engine()
        logger.info(f"AI Router selected engine: {active_engine.upper()}")

        if active_engine == "gemini":
            spec, msg, ready, show_cat, buyer = await self._call_gemini(text, image_url, history, customer_name)
            if spec:
                return spec, msg, ready, show_cat, buyer
            logger.warning("Gemini call failed, checking Claude fallback...")
            active_engine = "claude"

        if active_engine == "claude":
            spec, msg, ready, show_cat, buyer = await self._call_claude(text, image_url, history, customer_name)
            if spec:
                return spec, msg, ready, show_cat, buyer
            logger.warning("Claude call failed, falling back to heuristic engine...")

        # Ultimate resilient merchant fallback
        logger.info("Using Rule-Based Merchant Persona Engine")
        return self._heuristic_merchant_response(text, image_url, history, customer_name)

    # Compatibility alias
    async def parse_inquiry_with_claude(self, text: str, image_url: Optional[str] = None) -> Tuple[CakeSpecification, str, bool, bool, Optional[str]]:
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
    # 1. GOOGLE GEMINI (FLASH-LITE-LATEST) - MERCHANT PERSONA
    # =========================================================================
    async def _call_gemini(
        self,
        text: str,
        image_url: Optional[str],
        history: Optional[list],
        customer_name: Optional[str]
    ) -> Tuple[Optional[CakeSpecification], Optional[str], Optional[bool], Optional[bool], Optional[str]]:
        if not self._is_valid_key(self.gemini_api_key):
            return None, None, None, None, None

        try:
            logger.info("Invoking Google Gemini Merchant AI Agent...")
            gemini_model = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={self.gemini_api_key}"

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

            parts.append({"text": self._build_prompt(text, history, customer_name)})

            payload = {
                "contents": [{"parts": parts}],
                "systemInstruction": {
                    "parts": [{"text": self._build_system_instruction()}]
                },
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "OBJECT",
                        "properties": {
                            "buyerName": {"type": "STRING", "description": "The buyer's real name if introduced (e.g. Sarah, Emma, David). If not mentioned, return empty string."},
                            "flavor": {"type": "STRING"},
                            "weightKg": {"type": "NUMBER", "description": "Weight in Kilograms (e.g. 1.0, 1.5, 2.0). Standard base is 1.0 kg."},
                            "servings": {"type": "INTEGER", "description": "Estimated portions (approx 10 portions per 1 kg)"},
                            "tiers": {"type": "INTEGER"},
                            "theme": {"type": "STRING"},
                            "dietaryPreferences": {"type": "STRING"},
                            "customMessage": {"type": "STRING", "description": "Custom message or inscription to pipe on the cake. Empty string if not requested yet."},
                            "pickupDate": {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                            "basePrice": {"type": "NUMBER"},
                            "addOnsPrice": {"type": "NUMBER"},
                            "totalPrice": {"type": "NUMBER"},
                            "readyForPayment": {"type": "BOOLEAN", "description": "True ONLY if all 4 details (buyer name, weight in kg, date, message) are settled AND customer explicitly says yes/book/pay/send link."},
                            "showCatalogue": {"type": "BOOLEAN", "description": "True if customer asks to see the menu, catalogue, or cake options."},
                            "agentMessage": {"type": "STRING", "description": "Warm personal response from Anna the baker. Always talk in KG (never servings). If buyer name, weight in kg, pickup date, or custom writing are missing, ask for them naturally like a friendly WhatsApp baker."}
                        },
                        "required": ["flavor", "weightKg", "servings", "tiers", "theme", "dietaryPreferences", "pickupDate", "basePrice", "addOnsPrice", "totalPrice", "readyForPayment", "showCatalogue", "agentMessage"]
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
                        logger.info(f"Gemini successfully extracted response: readyForPayment={parsed.get('readyForPayment')} showCatalogue={parsed.get('showCatalogue')} - ${parsed.get('totalPrice')}")
                        return self._map_dict_to_spec(parsed, image_url)
                else:
                    logger.error(f"Gemini API returned status {res.status_code}: {res.text}")

        except Exception as e:
            logger.error(f"Gemini API exception: {e}")
        return None, None, None, None, None

    # =========================================================================
    # 2. ANTHROPIC CLAUDE 3.5 SONNET - MERCHANT PERSONA
    # =========================================================================
    async def _call_claude(
        self,
        text: str,
        image_url: Optional[str],
        history: Optional[list],
        customer_name: Optional[str]
    ) -> Tuple[Optional[CakeSpecification], Optional[str], Optional[bool], Optional[bool], Optional[str]]:
        if not self.claude_client:
            return None, None, None, None, None

        try:
            logger.info("Invoking Claude 3.5 Sonnet Merchant Reasoning Agent...")
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

            content_blocks.append({"type": "text", "text": self._build_prompt(text, history, customer_name)})

            tools = [{
                "name": "merchant_cake_response",
                "description": "Extracts cake design specifications, calculates price, determines payment readiness, catalogue visibility, and writes Anna's human merchant response.",
                "input_schema": self._get_tool_json_schema()
            }]

            response = await self.claude_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0.3,
                system=self._build_system_instruction(),
                messages=[{"role": "user", "content": content_blocks}],
                tools=tools,
                tool_choice={"type": "tool", "name": "merchant_cake_response"}
            )

            for block in response.content:
                if block.type == "tool_use" and block.name == "merchant_cake_response":
                    return self._map_dict_to_spec(block.input, image_url)

        except Exception as e:
            logger.error(f"Claude API exception: {e}")
        return None, None, None, None, None

    # =========================================================================
    # 3. COMMON HELPERS & MERCHANT PERSONA INSTRUCTIONS
    # =========================================================================
    def _build_system_instruction(self) -> str:
        return (
            f"You are Anna, the passionate master decorator and head artisan baker at {self.business_name}, "
            "a boutique home bakery in San Jose, CA.\n"
            "You are chatting directly with clients over WhatsApp / Instagram DM.\n\n"
            "MERCHANT PERSONA & VOICE:\n"
            "- Speak naturally as a warm, enthusiastic human baker in the 1st person ('I', 'my kitchen', 'I would love to bake this for you!').\n"
            "- DO NOT sound like an AI chatbot, corporate helpdesk, or support bot. No robotic checklists.\n"
            "- Use friendly emojis naturally (💕, 👩‍🍳, 🎂, ✨, 🧁).\n\n"
            "4 ESSENTIAL ORDER DETAILS YOU MUST COLLECT:\n"
            "1. BUYER NAME: If you do not know their name, warmly ask who you are chatting with ('Who am I baking this for? May I have your name?').\n"
            "2. WEIGHT IN KG (NEVER SAY SERVINGS!): Always talk and quote in Kilograms (e.g. 'How many kg cake would you like? 1 kg serves ~8-10 people, 1.5 kg, or 2 kg+?'). Base pricing is $45.00/kg.\n"
            "3. PICKUP DATE: Ask what date they need the cake ('When is your celebration? What date do you need to pick it up?').\n"
            "4. CUSTOM MESSAGE: Ask what message or inscription to write on the cake ('Would you like any special message piped on the cake, like Happy Birthday or a name?').\n\n"
            "CONVERSATION PHASES:\n"
            "1. CONSULTATION (readyForPayment = false):\n"
            "   - If any of the 4 details (buyer name, weight in kg, pickup date, or custom writing) are still missing, compliment their cake idea and warmly ask for the missing details.\n"
            "   - readyForPayment MUST be false until all key details are agreed.\n"
            "2. CATALOGUE BROWSE (showCatalogue = true, readyForPayment = false):\n"
            "   - If they ask for your menu or cake catalogue, show it and ask which design they like.\n"
            "3. PAYMENT (readyForPayment = true):\n"
            "   - ONLY when the cake details are settled AND the customer confirms they want to proceed, says yes, 'book it', 'let us do it', 'ready to pay', or asks for the link.\n"
            "   - Let them know the secure PayPal link is attached below to finalize the booking."
        )

    def _build_prompt(self, text: str, history: Optional[list] = None, customer_name: Optional[str] = "Customer") -> str:
        hist_text = ""
        if history:
            hist_text = "Prior Conversation History:\n"
            for item in history:
                role = getattr(item, 'role', '') if hasattr(item, 'role') else (item.get('role', '') if isinstance(item, dict) else '')
                role_label = "Customer" if role == 'customer' else "Anna (Baker)"
                content = getattr(item, 'content', '') if hasattr(item, 'content') else (item.get('content', '') if isinstance(item, dict) else str(item))
                hist_text += f"{role_label}: {content}\n"
            hist_text += "\n"

        return (
            f"{hist_text}"
            f"Customer Name: {customer_name}\n"
            f"Current Message: \"{text}\"\n"
            f"Today's Date: {date.today().isoformat()}\n"
            f"Bakery: {self.business_name}\n"
            f"Pricing Rules:\n"
            f"- Base: ${self.base_price_per_serving:.2f}/serving\n"
            f"- Extra tiers: ${self.tier_multiplier:.2f} per tier above 1\n"
            f"- Dietary (Eggless/Gluten-Free/Vegan): $15.00\n"
            f"- Custom artistic fondant/sculpture: $20.00\n\n"
            "Instructions:\n"
            "1. Extract or maintain cake specifications (flavor, servings, tiers, theme, dietary, pickup date, price).\n"
            "2. Decide if customer is ready to pay (readyForPayment = true ONLY if they explicitly confirmed booking or asked for the payment link).\n"
            "3. Write Anna's warm, personal message (agentMessage) according to the merchant persona."
        )

    def _get_tool_json_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "buyerName": {"type": "string", "description": "Buyer name if introduced, otherwise empty string."},
                "flavor": {"type": "string"},
                "weightKg": {"type": "number", "description": "Weight in Kilograms (e.g. 1.0, 1.5, 2.0). Standard base is 1.0 kg."},
                "servings": {"type": "integer"},
                "tiers": {"type": "integer"},
                "theme": {"type": "string"},
                "dietaryPreferences": {"type": "string"},
                "customMessage": {"type": "string", "description": "Message or text to pipe on cake."},
                "pickupDate": {"type": "string", "description": "YYYY-MM-DD"},
                "basePrice": {"type": "number"},
                "addOnsPrice": {"type": "number"},
                "totalPrice": {"type": "number"},
                "readyForPayment": {"type": "boolean"},
                "showCatalogue": {"type": "boolean"},
                "agentMessage": {"type": "string"}
            },
            "required": ["flavor", "weightKg", "servings", "tiers", "theme", "dietaryPreferences", "pickupDate", "basePrice", "addOnsPrice", "totalPrice", "readyForPayment", "showCatalogue", "agentMessage"]
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

    def _map_dict_to_spec(self, d: Dict[str, Any], image_url: Optional[str]) -> Tuple[CakeSpecification, str, bool, bool, Optional[str]]:
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
        ready_for_payment = bool(d.get("readyForPayment", False))
        show_catalogue = bool(d.get("showCatalogue", False))

        weight_kg = float(d.get("weightKg", 1.0))
        servings = int(d.get("servings", int(round(weight_kg * 10))))
        buyer_name = str(d.get("buyerName", "")).strip() or None

        spec = CakeSpecification(
            flavor=d.get("flavor", "Signature Vanilla Bean"),
            weightKg=weight_kg,
            servings=servings,
            tiers=int(d.get("tiers", 1)),
            theme=d.get("theme", "Artisan Custom Handcrafted Design"),
            dietaryPreferences=d.get("dietaryPreferences", "Standard"),
            customMessage=d.get("customMessage", ""),
            pickupDate=p_date,
            referenceImageUrl=image_url or "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop",
            basePrice=base_p,
            addOnsPrice=addon_p,
            totalPrice=total_p
        )
        agent_msg = d.get("agentMessage")
        if not agent_msg:
            if ready_for_payment:
                agent_msg = self.generate_merchant_payment_message(spec, buyer_name or "there")
            elif show_catalogue:
                agent_msg = self.generate_merchant_catalogue_message(buyer_name or "there")
            else:
                agent_msg = self.generate_merchant_consultation_message(spec, buyer_name or "there")
        return spec, agent_msg, ready_for_payment, show_catalogue, buyer_name

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

    def _heuristic_merchant_response(
        self,
        text: str,
        image_url: Optional[str] = None,
        history: Optional[list] = None,
        customer_name: Optional[str] = "Jessica"
    ) -> Tuple[CakeSpecification, str, bool, bool, Optional[str]]:
        # Gather cumulative text from history if present so context is preserved across turns
        combined_text = text
        if history:
            prev_texts = []
            for item in history:
                role = getattr(item, 'role', '') if hasattr(item, 'role') else (item.get('role', '') if isinstance(item, dict) else '')
                if role == 'customer':
                    c = getattr(item, 'content', '') if hasattr(item, 'content') else (item.get('content', '') if isinstance(item, dict) else '')
                    if c:
                        prev_texts.append(c)
            if prev_texts:
                combined_text = " ".join(prev_texts) + " " + text

        spec = self._heuristic_parse(combined_text, image_url)
        ready_for_payment = self._is_ready_for_payment(text, history)
        show_catalogue = self._is_catalogue_request(text)

        buyer_name = self._extract_buyer_name(combined_text) or customer_name
        if ready_for_payment:
            msg = self.generate_merchant_payment_message(spec, buyer_name)
        elif show_catalogue:
            msg = self.generate_merchant_catalogue_message(buyer_name)
        else:
            msg = self.generate_merchant_consultation_message(spec, buyer_name)

        return spec, msg, ready_for_payment, show_catalogue, buyer_name

    def _is_catalogue_request(self, text: str) -> bool:
        lower = text.lower().strip()
        catalogue_cues = [
            "catalogue", "catalog", "menu", "what cakes", "what do you have",
            "show me cakes", "show cakes", "options", "browse", "signature cakes",
            "cake designs", "flavors do you have", "what can you make"
        ]
        return any(cue in lower for cue in catalogue_cues)

    def generate_merchant_catalogue_message(self, customer_name: Optional[str] = "Jessica") -> str:
        first_name = customer_name.split()[0] if customer_name else "there"
        return (
            f"Hi {first_name}! 💕 I'd love to show you our signature cake collection! "
            "Here are our most popular handcrafted artisan designs fresh from my kitchen. "
            "Tap **Select & Customize** on any cake to tailor the flavor, size, and date for your special day! 🧁✨"
        )

    def _is_ready_for_payment(self, text: str, history: Optional[list] = None) -> bool:
        lower = text.lower().strip()
        
        # Explicit positive readiness triggers
        positive_cues = [
            "send link", "send the link", "send paypal", "paypal link",
            "ready to pay", "ready to book", "i'm ready", "im ready",
            "let's do it", "lets do it", "sounds great, send", "sounds good, send",
            "yes please", "yes send", "please send", "book it", "book this",
            "lock it in", "confirm order", "go ahead", "take my money", "pay now",
            "how do i pay", "where do i pay", "send invoice", "ready for payment"
        ]
        if any(cue in lower for cue in positive_cues):
            return True

        # Short affirmatives when history already contains consultation
        short_affirmatives = ["yes", "yeah", "yep", "sure", "definitely", "perfect", "sounds good", "sounds great", "ok", "okay"]
        if lower in short_affirmatives or lower.startswith("yes"):
            if history and len(history) > 0:
                return True

        return False

    def generate_merchant_consultation_message(self, spec: CakeSpecification, customer_name: Optional[str] = "Jessica") -> str:
        first_name = customer_name.split()[0] if customer_name else "there"
        dietary_str = f" with {spec.dietaryPreferences.lower()} recipe" if spec.dietaryPreferences.lower() != "standard" else ""
        date_str = spec.pickupDate.strftime("%A, %b %d")

        return (
            f"Hi {first_name}! Anna here 💕\n\n"
            f"I would absolutely love to bake this {spec.theme.lower()} cake for your celebration! "
            f"For {spec.servings} guests across {spec.tiers} tier(s), our {spec.flavor.lower()}{dietary_str} "
            f"pairs delightfully with handcrafted fresh buttercream.\n\n"
            f"Your estimated total is ${spec.totalPrice:.2f} (including custom artistic detailing) for pickup on {date_str}.\n\n"
            f"Would you like me to reserve your oven slot and send over the PayPal link?"
        )

    def generate_merchant_payment_message(self, spec: CakeSpecification, customer_name: Optional[str] = "Jessica") -> str:
        first_name = customer_name.split()[0] if customer_name else "there"
        date_str = spec.pickupDate.strftime("%A, %b %d")

        return (
            f"Wonderful, {first_name}! 🎉 I have your oven slot reserved for {date_str}!\n\n"
            f"I've attached your official PayPal link below to complete the deposit and confirm your order. "
            f"Once received, I'll start prepping your {spec.flavor} cake in the kitchen! 👩‍🍳✨"
        )

    def generate_agent_quote_message(self, spec: CakeSpecification) -> str:
        return self.generate_merchant_consultation_message(spec)

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

    async def parse_voice_command(self, transcript: str, active_orders: list) -> Dict[str, Any]:
        """
        Parses hands-free spoken kitchen voice instructions like:
        - "Sarah's cake is in the oven"
        - "Mark order 1018 as ready for pickup"
        - "Just boxed the vintage heart cake"
        Returns: {"success": bool, "orderId": "BK-...", "newStatus": str, "spokenFeedback": str}
        """
        transcript_clean = transcript.strip().lower()
        
        # 1. Determine target status (Check COMPLETED first, then READY_FOR_PICKUP, then BAKING)
        target_status = None
        if any(w in transcript_clean for w in [
            "picked up", "pickedup", "picked", "collected", "collect", "delivered",
            "completed", "complete", "handed over", "customer took", "finished order"
        ]):
            target_status = "COMPLETED"
        elif any(w in transcript_clean for w in [
            "ready", "box", "boxed", "boxing", "ready for pickup", "ready for pick up", "pickup", "pick up", "decorating done"
        ]):
            target_status = "READY_FOR_PICKUP"
        elif any(w in transcript_clean for w in [
            "oven", "bake", "baking", "started baking", "started", "in the oven", "in oven"
        ]):
            target_status = "BAKING"
        else:
            target_status = "BAKING"

        # 2. Match Target Order
        target_order = None
        
        # Check for explicit order number like "BK-1026", "BK 1026", "order 1026", "1026"
        num_match = re.search(r"(?:bk[- ]?|order\s*|ticket\s*)?(\d{3,4})", transcript_clean)
        if num_match:
            explicit_id = f"BK-{num_match.group(1)}"
            for o in active_orders:
                if o.id.lower() == explicit_id.lower():
                    target_order = o
                    break
            if not target_order:
                return {
                    "success": False,
                    "spokenFeedback": f"I heard order #{explicit_id}, but could not find that active ticket on the kitchen board."
                }

        if not target_order:
            for o in active_orders:
                c_name = o.customerName.lower()
                first_name = c_name.split()[0]
                if first_name in transcript_clean or c_name in transcript_clean:
                    target_order = o
                    break

        if not target_order:
            for o in active_orders:
                flavor = (o.cakeSpec.flavor if o.cakeSpec else "").lower()
                theme = (o.cakeSpec.theme if o.cakeSpec else "").lower()
                if (theme and any(word in transcript_clean for word in theme.split() if len(word) > 3)) or \
                   (flavor and any(word in transcript_clean for word in flavor.split() if len(word) > 3)):
                    target_order = o
                    break

        if not target_order and len(active_orders) == 1:
            target_order = active_orders[0]
        elif not target_order and len(active_orders) > 1:
            return {
                "success": False,
                "spokenFeedback": "I heard your update, but there are multiple active tickets. Please say the customer name or order number."
            }

        if not target_order:
            return {
                "success": False,
                "spokenFeedback": "I heard you, but I could not find an active kitchen ticket matching that description."
            }

        customer_first = target_order.customerName.split()[0]
        status_readable = {
            "BAKING": "marked as in the oven",
            "READY_FOR_PICKUP": "boxed and ready for pickup",
            "COMPLETED": "marked as picked up and completed"
        }.get(target_status, "updated")

        spoken_msg = f"Got it! {customer_first}'s cake #{target_order.id} is now {status_readable}."

        return {
            "success": True,
            "orderId": target_order.id,
            "newStatus": target_status,
            "spokenFeedback": spoken_msg
        }

    def _extract_kg(self, text: str) -> float:
        match = re.search(r'(\d+(?:\.\d+)?)\s*(?:kg|kilos?|kilograms?)', text.lower())
        if match:
            return float(match.group(1))
        s_match = re.search(r'(\d+)\s*(?:servings?|people|guests|pax)', text.lower())
        if s_match:
            return round(int(s_match.group(1)) / 10.0, 1)
        return 1.0

    def _extract_buyer_name(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:my name is|i am|i'm|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r'(?:call me)\s+([A-Z][a-z]+)',
            r'(?:name:\s*)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip().title()
        return None
