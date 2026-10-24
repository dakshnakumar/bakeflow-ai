// BakeFlow AI - Frontend Orchestration

const PRESET_INQUIRIES = {
    unicorn: {
        text: "Hi! I'd like to order a 2-tier magical unicorn cake with gold horn and pastel rosettes for 18 guests this Saturday. Can you make it eggless?",
        image: "https://images.unsplash.com/photo-1535141192574-5d4897c13136?w=500&auto=format&fit=crop",
        name: "Jessica Taylor"
    },
    vintage: {
        text: "Looking for an aesthetic vintage Lambeth heart piping cake in cherry red for 10 people tomorrow. Message: 'Forever 21'",
        image: "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop",
        name: "Chloe Bennett"
    },
    chocolate: {
        text: "Need a decadent Belgian dark chocolate truffle celebration cake for 25 people with chocolate drip and berries this weekend.",
        image: "https://images.unsplash.com/photo-1606890737304-57a1ca8a5b62?w=500&auto=format&fit=crop",
        name: "Marcus Vance"
    }
};

let currentSelectedImage = null;
let currentModalOrderId = null;
let currentModalAmount = null;

document.addEventListener('DOMContentLoaded', () => {
    initSseKitchenStream();
    loadAllOrders();
});

// ==========================================
// 1. CHAT & AI INQUIRY FLOW
// ==========================================
function loadPresetInquiry() {
    const select = document.getElementById('preset-select');
    const key = select.value;
    if (!key || !PRESET_INQUIRIES[key]) return;

    const preset = PRESET_INQUIRIES[key];
    document.getElementById('chat-input').value = preset.text;
    selectPresetImage(key);
}

function selectPresetImage(key) {
    if (!PRESET_INQUIRIES[key]) return;
    const preset = PRESET_INQUIRIES[key];
    currentSelectedImage = preset.image;

    const chip = document.getElementById('image-preview-chip');
    const thumb = document.getElementById('preview-thumb');
    const filename = document.getElementById('preview-filename');

    thumb.src = preset.image;
    filename.textContent = `${key}-cake-reference.jpg`;
    chip.style.display = 'flex';
}

function clearSelectedImage() {
    currentSelectedImage = null;
    document.getElementById('image-preview-chip').style.display = 'none';
}

function handleChatKey(event) {
    if (event.key === 'Enter') {
        sendInquiry();
    }
}

async function sendInquiry() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text && !currentSelectedImage) return;

    // 1. Render customer outgoing bubble
    renderOutgoingMessage(text, currentSelectedImage);
    input.value = '';

    const payload = {
        customerName: "Jessica Taylor",
        customerPhone: "+1 (408) 555-0199",
        message: text,
        imageUrl: currentSelectedImage
    };

    clearSelectedImage();

    // 2. Render typing indicator
    const typingId = renderTypingIndicator();

    try {
        // 3. Call Spring Boot Backend
        const response = await fetch('/api/orders/inquiry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        removeTypingIndicator(typingId);

        if (response.ok) {
            const quote = await response.json();
            renderIncomingQuote(quote);
        } else {
            renderIncomingMessage("Sorry, I had trouble parsing that. Please try again!");
        }
    } catch (err) {
        removeTypingIndicator(typingId);
        renderIncomingMessage("Unable to connect to server. Please check your backend.");
        console.error(err);
    }
}

function renderOutgoingMessage(text, imageUrl) {
    const viewport = document.getElementById('chat-viewport');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble outgoing';

    let content = `<div class="bubble-sender">You (Customer)</div>`;
    if (imageUrl) {
        content += `<div class="bubble-image-wrap"><img src="${imageUrl}" alt="Reference Cake"></div>`;
    }
    content += `<div class="bubble-text">${escapeHtml(text)}</div>`;
    content += `<span class="bubble-time">${getCurrentTime()}</span>`;

    bubble.innerHTML = content;
    viewport.appendChild(bubble);
    viewport.scrollTop = viewport.scrollHeight;
}

function renderIncomingQuote(quote) {
    const viewport = document.getElementById('chat-viewport');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble incoming';

    const spec = quote.cakeSpec;

    bubble.innerHTML = `
        <div class="bubble-sender">BakeFlow Assistant 🧁</div>
        <div class="bubble-text">${escapeHtml(quote.agentMessage)}</div>
        <div class="quote-card">
            <div class="quote-header">
                <span class="quote-badge">ORDER #${quote.orderId}</span>
                <span class="quote-total">$${spec.totalPrice.toFixed(2)}</span>
            </div>
            <div class="quote-details">
                <div>Flavor: <strong>${spec.flavor}</strong></div>
                <div>Size: <strong>${spec.servings} guests (${spec.tiers} tier)</strong></div>
                <div>Dietary: <strong>${spec.dietaryPreferences}</strong></div>
                <div>Pickup: <strong>${spec.pickupDate}</strong></div>
            </div>
            <button class="paypal-action-button" onclick="openPayPalCheckout('${quote.orderId}', ${spec.totalPrice}, '${escapeHtml(spec.theme)}')">
                <span>Pay with</span>
                <strong>PayPal</strong>
                <span>• $${spec.totalPrice.toFixed(2)}</span>
            </button>
        </div>
        <span class="bubble-time">${getCurrentTime()}</span>
    `;

    viewport.appendChild(bubble);
    viewport.scrollTop = viewport.scrollHeight;
}

function renderIncomingMessage(text) {
    const viewport = document.getElementById('chat-viewport');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble incoming';
    bubble.innerHTML = `
        <div class="bubble-sender">BakeFlow Assistant 🧁</div>
        <div class="bubble-text">${escapeHtml(text)}</div>
        <span class="bubble-time">${getCurrentTime()}</span>
    `;
    viewport.appendChild(bubble);
    viewport.scrollTop = viewport.scrollHeight;
}

function renderTypingIndicator() {
    const viewport = document.getElementById('chat-viewport');
    const id = 'typing-' + Date.now();
    const bubble = document.createElement('div');
    bubble.id = id;
    bubble.className = 'chat-bubble incoming';
    bubble.innerHTML = `
        <div class="bubble-sender">BakeFlow Assistant 🧁</div>
        <div class="bubble-text" style="color: #94a3b8; font-style: italic;">Analyzing cake specifications & calculating PayPal quote...</div>
    `;
    viewport.appendChild(bubble);
    viewport.scrollTop = viewport.scrollHeight;
    return id;
}

function removeTypingIndicator(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// ==========================================
// 2. PAYPAL SANDBOX MODAL & CAPTURE
// ==========================================
function openPayPalCheckout(orderId, amount, description) {
    currentModalOrderId = orderId;
    currentModalAmount = amount;

    document.getElementById('modal-order-title').textContent = description || `Order #${orderId}`;
    document.getElementById('modal-order-amount').textContent = `$${amount.toFixed(2)}`;
    document.getElementById('checkout-modal').style.display = 'flex';
}

function closeCheckoutModal() {
    document.getElementById('checkout-modal').style.display = 'none';
}

async function executeMockPayment() {
    if (!currentModalOrderId) return;
    const orderId = currentModalOrderId;

    // Simulate clicking PayPal and receiving capture confirmation
    closeCheckoutModal();

    renderIncomingMessage(`⏳ Processing PayPal Sandbox approval for Order #${orderId}...`);

    try {
        const response = await fetch(`/api/orders/${orderId}/simulate-payment`, {
            method: 'POST'
        });

        if (response.ok) {
            renderIncomingMessage(`🎉 Payment of $${currentModalAmount.toFixed(2)} completed successfully via PayPal! Order #${orderId} is confirmed and sent to the baker's kitchen queue.`);
        }
    } catch (e) {
        console.error("Payment capture error:", e);
    }
}

// ==========================================
// 3. KITCHEN KANBAN & SSE STREAM
// ==========================================
function initSseKitchenStream() {
    const eventSource = new EventSource('/api/kitchen/stream');

    eventSource.addEventListener('INIT', (e) => {
        console.log("SSE Init:", e.data);
        document.getElementById('connection-status').className = 'connection-status';
        document.getElementById('sse-label').textContent = 'Kitchen Stream Live';
    });

    eventSource.addEventListener('ORDER_QUOTED', (e) => {
        const order = JSON.parse(e.data);
        upsertTicket(order, true);
    });

    eventSource.addEventListener('ORDER_PAID', (e) => {
        const order = JSON.parse(e.data);
        upsertTicket(order, true);
        playPopSound();
    });

    eventSource.addEventListener('STATUS_UPDATED', (e) => {
        const order = JSON.parse(e.data);
        upsertTicket(order, true);
    });

    eventSource.onerror = (err) => {
        console.warn("SSE connection error, retrying in background...");
        document.getElementById('connection-status').className = 'connection-status';
        document.getElementById('sse-label').textContent = 'Connecting...';
    };
}

async function loadAllOrders() {
    try {
        const res = await fetch('/api/orders');
        if (res.ok) {
            const orders = await res.json();
            clearKanbanColumns();
            orders.forEach(order => upsertTicket(order, false));
            updateMetrics(orders);
        }
    } catch (e) {
        console.error("Failed to load orders:", e);
    }
}

function clearKanbanColumns() {
    document.getElementById('tickets-pending').innerHTML = '';
    document.getElementById('tickets-confirmed').innerHTML = '';
    document.getElementById('tickets-baking').innerHTML = '';
    document.getElementById('tickets-ready').innerHTML = '';
}

function upsertTicket(order, flash) {
    // Remove if already exists in any column
    const existing = document.getElementById(`ticket-${order.id}`);
    if (existing) existing.remove();

    let targetColId = 'tickets-pending';
    if (order.status === 'CONFIRMED') targetColId = 'tickets-confirmed';
    else if (order.status === 'BAKING') targetColId = 'tickets-baking';
    else if (order.status === 'READY_FOR_PICKUP') targetColId = 'tickets-ready';
    else if (order.status === 'COMPLETED') return; // Completed orders archived

    const targetContainer = document.getElementById(targetColId);
    if (!targetContainer) return;

    const card = document.createElement('div');
    card.id = `ticket-${order.id}`;
    card.className = `order-card ${flash ? 'just-updated' : ''}`;

    const spec = order.cakeSpec;

    card.innerHTML = `
        <div class="card-top">
            <span class="order-id-badge">#${order.id}</span>
            <span class="price-pill">$${order.totalAmount.toFixed(2)}</span>
        </div>
        <div class="card-customer">👤 ${escapeHtml(order.customerName)}</div>
        <div class="card-cake-info">
            <img class="card-cake-thumb" src="${spec.referenceImageUrl}" alt="Cake">
            <div class="card-cake-specs">
                <span class="spec-theme">${escapeHtml(spec.theme)}</span>
                <span class="spec-flavor">${escapeHtml(spec.flavor)}</span>
                <span class="spec-meta">${spec.servings} Servings • ${spec.tiers} Tier(s) • ${spec.dietaryPreferences}</span>
            </div>
        </div>
        <div class="card-pickup-date">
            📅 Pickup: ${spec.pickupDate}
        </div>
        <div class="card-actions">
            ${renderCardActions(order)}
        </div>
    `;

    targetContainer.prepend(card);
    refreshColumnCounters();
}

function renderCardActions(order) {
    if (order.status === 'PAYMENT_PENDING' || order.status === 'QUOTED') {
        return `
            <button class="action-btn pay-simulate-btn" onclick="openPayPalCheckout('${order.id}', ${order.totalAmount}, '${escapeHtml(order.cakeSpec.theme)}')">
                💳 Simulate Pay
            </button>
        `;
    } else if (order.status === 'CONFIRMED') {
        return `
            <button class="action-btn bake-btn" onclick="updateOrderStatus('${order.id}', 'BAKING')">
                👩‍🍳 Start Baking
            </button>
        `;
    } else if (order.status === 'BAKING') {
        return `
            <button class="action-btn ready-btn" onclick="updateOrderStatus('${order.id}', 'READY_FOR_PICKUP')">
                📦 Box & Ready
            </button>
        `;
    } else if (order.status === 'READY_FOR_PICKUP') {
        return `
            <button class="action-btn complete-btn" onclick="updateOrderStatus('${order.id}', 'COMPLETED')">
                ✅ Picked Up
            </button>
        `;
    }
    return '';
}

async function updateOrderStatus(orderId, newStatus) {
    try {
        const res = await fetch(`/api/orders/${orderId}/status`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ newStatus: newStatus })
        });
        if (res.ok) {
            const updated = await res.json();
            upsertTicket(updated, true);
        }
    } catch (e) {
        console.error("Failed to update status:", e);
    }
}

function refreshColumnCounters() {
    const pending = document.getElementById('tickets-pending').children.length;
    const confirmed = document.getElementById('tickets-confirmed').children.length;
    const baking = document.getElementById('tickets-baking').children.length;
    const ready = document.getElementById('tickets-ready').children.length;

    document.getElementById('count-pending').textContent = pending;
    document.getElementById('count-confirmed').textContent = confirmed;
    document.getElementById('count-baking').textContent = baking;
    document.getElementById('count-ready').textContent = ready;

    document.getElementById('active-orders-count').textContent = confirmed + baking + ready;
}

function updateMetrics(orders) {
    let paidTotal = 0;
    orders.forEach(o => {
        if (o.status !== 'QUOTED' && o.status !== 'PAYMENT_PENDING' && o.status !== 'CANCELLED') {
            paidTotal += o.totalAmount;
        }
    });
    document.getElementById('paid-total-value').textContent = `$${paidTotal.toFixed(2)}`;
}

// Helpers
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

function getCurrentTime() {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function playPopSound() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.frequency.setValueAtTime(587.33, audioCtx.currentTime); // D5
        osc.frequency.exponentialRampToValueAtTime(880, audioCtx.currentTime + 0.15); // A5
        gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.2);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.2);
    } catch (e) {}
}
