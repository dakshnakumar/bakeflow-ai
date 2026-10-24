from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from datetime import date, datetime

class OrderStatus(str, Enum):
    QUOTED = "QUOTED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    CONFIRMED = "CONFIRMED"
    BAKING = "BAKING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class CakeSpecification(BaseModel):
    flavor: str
    servings: int
    tiers: int
    theme: str
    dietaryPreferences: str = "Standard"
    customMessage: str = "Happy Celebration!"
    pickupDate: date
    referenceImageUrl: Optional[str] = "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop"
    basePrice: float
    addOnsPrice: float
    totalPrice: float

class Order(BaseModel):
    id: str
    customerName: str
    customerPhone: str
    cakeSpec: CakeSpecification
    totalAmount: float
    status: OrderStatus = OrderStatus.QUOTED
    paypalOrderId: Optional[str] = None
    paypalCaptureId: Optional[str] = None
    paypalApprovalUrl: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.now)
    updatedAt: datetime = Field(default_factory=datetime.now)

class InquiryRequest(BaseModel):
    customerName: Optional[str] = "Guest Baker"
    customerPhone: Optional[str] = "+1 (408) 555-0199"
    message: str
    imageUrl: Optional[str] = None

class QuoteResponse(BaseModel):
    orderId: str
    customerName: str
    cakeSpec: CakeSpecification
    totalAmount: float
    status: OrderStatus
    paypalApprovalUrl: Optional[str]
    agentMessage: str

class OrderStatusUpdateRequest(BaseModel):
    newStatus: OrderStatus
    note: Optional[str] = None
