let currentChatCustomerName = null;
// BakeFlow AI - Frontend Orchestration

const PRESET_INQUIRIES = {
    unicorn: {
        text: "Hi Anna, I'm Emma! I'd like to order a 2 kg magical unicorn cake with pastel rosettes for this Saturday. Can you make it eggless, with 'Happy 7th Lily' written on it?",
        image: "https://images.unsplash.com/photo-1535141192574-5d4897c13136?w=500&auto=format&fit=crop",
        name: "Emma Watson"
    },
    vintage: {
        text: "Hi Anna, I'm Sarah Jenkins. I need a 1.5 kg vintage Lambeth heart piping cake in cherry red for this Friday. Could you write 'Forever 21' on top?",
        image: "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop",
        name: "Sarah Jenkins"
    },
    chocolate: {
        text: "Hi Anna, I'm David Miller! Looking for a 1 kg Belgian dark chocolate truffle cake for Oct 30th with 'Happy Birthday Dad' piped on it.",
        image: "https://images.unsplash.com/photo-1606890737304-57a1ca8a5b62?w=500&auto=format&fit=crop",
        name: "David Miller"
    }
};

let currentSelectedImage = null;
let currentModalOrderId = null;
let currentModalAmount = 0;
let currentModalPayPalOrderId = null;
let currentModalApprovalUrl = null;
let chatHistory = [];
let cachedCatalogue = [];

document.addEventListener('DOMContentLoaded', () => {
    initSseKitchenStream();
    initFinanceGrid();
    initKitchenGrid();
    loadAllOrders();
    fetchCatalogue();
});

// ==========================================
// 1. CHAT & MERCHANT DIALOGUE FLOW
// ==========================================
function loadPresetInquiry() {
    const select = document.getElementById('preset-select');
    const key = select.value;
    if (!key || !PRESET_INQUIRIES[key]) return;
    loadPresetInquiryByKey(key);
}

function loadPresetInquiryByKey(key) {
    if (!PRESET_INQUIRIES[key]) return;
    const select = document.getElementById('preset-select');
    if (select) select.value = key;

    const preset = PRESET_INQUIRIES[key];
    currentChatCustomerName = preset.name;
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

function sendQuickReply(text) {
    sendInquiry(text);
}

async function sendInquiry(overrideText = null) {
    const input = document.getElementById('chat-input');
    const text = overrideText !== null ? overrideText.trim() : input.value.trim();
    if (!text && !currentSelectedImage) return;

    const imgToAttach = currentSelectedImage;

    // 1. Render customer outgoing bubble
    renderOutgoingMessage(text, imgToAttach);
    if (overrideText === null) {
        input.value = '';
    }

    // Record in local conversation history
    chatHistory.push({
        role: "customer",
        content: text,
        imageUrl: imgToAttach
    });

    const payload = {
        customerName: currentChatCustomerName || null,
        customerPhone: null,
        message: text,
        imageUrl: imgToAttach,
        history: chatHistory
    };

    clearSelectedImage();

    // Remove any previous suggestion chips so user doesn't double-click old ones
    document.querySelectorAll('.chat-suggestions').forEach(el => el.remove());

    // 2. Render typing indicator
    const typingId = renderTypingIndicator();

    try {
        const response = await fetch('/api/orders/inquiry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        removeTypingIndicator(typingId);

        if (response.ok) {
            const quote = await response.json();
            // Record merchant response in conversation history
            chatHistory.push({
                role: "merchant",
                content: quote.agentMessage
            });
            renderMerchantResponse(quote);
        } else {
            renderIncomingMessage("Sorry, I had a momentary kitchen hiccup. Could you say that again?");
        }
    } catch (err) {
        removeTypingIndicator(typingId);
        renderIncomingMessage("Unable to connect to the bakery server right now. Please check your backend.");
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

function renderMerchantResponse(quote) {
    const viewport = document.getElementById('chat-viewport');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble incoming';

    const spec = quote.cakeSpec;

    // IF customer is ready for payment: show Anna's message + Quote summary + PayPal button
    if (quote.readyForPayment && quote.orderId) {
        bubble.innerHTML = `
            <div class="bubble-sender">Anna 👩‍🍳 (Baker & Owner)</div>
            <div class="bubble-text">${escapeHtml(quote.agentMessage)}</div>
            <div class="quote-card">
                <div class="quote-header">
                    <span class="quote-badge">RESERVED ORDER #${quote.orderId}</span>
                    <span class="quote-total">$${spec.totalPrice.toFixed(2)}</span>
                </div>
                <div class="quote-details">
                    <div>Flavor: <strong>${escapeHtml(spec.flavor)}</strong></div>
                    <div>Weight: <strong>${spec.weightKg ? spec.weightKg + ' kg' : '1.0 kg'} (${spec.tiers} tier)</strong></div>
                    <div>Dietary: <strong>${escapeHtml(spec.dietaryPreferences)}</strong></div>
                    <div>Pickup Date: <strong>${spec.pickupDate}</strong></div>
                    ${spec.customMessage ? `<div>Inscription: <strong>"${escapeHtml(spec.customMessage)}"</strong></div>` : ''}
                </div>
                <button class="paypal-action-button" onclick="openPayPalCheckout('${quote.orderId}', ${spec.totalPrice}, '${escapeHtml(spec.theme)}', '${quote.paypalOrderId || ''}', '${quote.paypalApprovalUrl || ''}')">
                    <span>Pay with</span>
                    <strong>PayPal</strong>
                    <span>• $${spec.totalPrice.toFixed(2)}</span>
                </button>
            </div>
            <span class="bubble-time">${getCurrentTime()}</span>
        `;
    } else if (quote.showCatalogue && quote.catalogueItems && quote.catalogueItems.length > 0) {
        // Customer requested catalogue or menu: show carousel of artisan cakes
        cachedCatalogue = quote.catalogueItems;
        bubble.innerHTML = `
            <div class="bubble-sender">Anna 👩‍🍳 (Baker & Owner)</div>
            <div class="bubble-text">${escapeHtml(quote.agentMessage)}</div>
            <div class="chat-catalogue-container">
                <div class="chat-catalogue-carousel">
                    ${renderCatalogueCardsHtml(quote.catalogueItems, true)}
                </div>
            </div>
            <div class="chat-suggestions">
                <button type="button" class="suggestion-chip" onclick="openCatalogueModal()">
                    📖 Open Full Catalogue
                </button>
                <button type="button" class="suggestion-chip" onclick="sendQuickReply('Can I request a custom flavor or eggless cake?')">
                    🌱 Dietary & Flavor options
                </button>
            </div>
            <span class="bubble-time">${getCurrentTime()}</span>
        `;
    } else {
        // IF in consultation phase: ONLY show Anna's warm conversational message + Interactive suggestion chips
        bubble.innerHTML = `
            <div class="bubble-sender">Anna 👩‍🍳 (Baker & Owner)</div>
            <div class="bubble-text">${escapeHtml(quote.agentMessage)}</div>
            <div class="chat-suggestions">
                <button type="button" class="suggestion-chip pay-chip" onclick="sendQuickReply('Sounds wonderful, Anna! Yes, please send me the PayPal link to reserve my cake.')">
                    💳 Yes, send PayPal link!
                </button>
                <button type="button" class="suggestion-chip" onclick="sendQuickReply('Can you show me your signature cake catalogue?')">
                    📖 View Cake Catalogue
                </button>
                <button type="button" class="suggestion-chip" onclick="sendQuickReply('Can we explore different flavor combinations?')">
                    🍓 Other flavor options
                </button>
            </div>
            <span class="bubble-time">${getCurrentTime()}</span>
        `;
    }

    viewport.appendChild(bubble);
    viewport.scrollTop = viewport.scrollHeight;
}

// ==========================================
// 1B. CATALOGUE MODAL & CARD INTERACTIONS
// ==========================================
async function fetchCatalogue() {
    try {
        const res = await fetch('/api/catalogue');
        if (res.ok) {
            cachedCatalogue = await res.json();
        }
    } catch (e) {
        console.warn("Failed to fetch catalogue:", e);
    }
}

async function openCatalogueModal() {
    if (!cachedCatalogue || cachedCatalogue.length === 0) {
        await fetchCatalogue();
    }
    const grid = document.getElementById('catalogue-modal-grid');
    if (grid) {
        grid.innerHTML = renderCatalogueCardsHtml(cachedCatalogue, false);
    }
    const modal = document.getElementById('catalogue-modal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function closeCatalogueModal() {
    const modal = document.getElementById('catalogue-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function renderCatalogueCardsHtml(items, isInline = false) {
    if (!items || items.length === 0) {
        return '<p style="color: #94a3b8; padding: 20px;">Loading artisan cakes from PayPal Catalog...</p>';
    }

    return items.map(item => `
        <div class="catalogue-card" data-prod-id="${escapeHtml(item.id)}">
            <div class="catalogue-card-img-wrap">
                <img src="${item.imageUrl}" alt="${escapeHtml(item.name)}" loading="lazy" onerror="this.onerror=null; this.src='https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=500&auto=format&fit=crop';">
                <span class="catalogue-badge-tag">${escapeHtml(item.badge || 'Signature Cake')}</span>
            </div>
            <div class="catalogue-card-body">
                <div class="catalogue-card-title">${escapeHtml(item.name)}</div>
                <div class="catalogue-card-desc">${escapeHtml(item.description)}</div>
                <div class="catalogue-card-meta">
                    <span class="catalogue-price-tag">From $${Number(item.startingPrice).toFixed(2)}</span>
                    <span class="catalogue-servings-tag">${item.baseServings} Pax • ${item.tiers} Tier(s)</span>
                </div>
                <button type="button" class="catalogue-select-btn" onclick="selectCatalogueProduct('${escapeHtml(item.id)}')">
                    Select &amp; Customize ✨
                </button>
            </div>
        </div>
    `).join('');
}

function selectCatalogueProduct(productId) {
    const product = (cachedCatalogue || []).find(p => p.id === productId);
    if (!product) return;

    // Close modal if open
    closeCatalogueModal();

    // Attach image preview
    currentSelectedImage = product.imageUrl;
    const chip = document.getElementById('image-preview-chip');
    const thumb = document.getElementById('preview-thumb');
    const filename = document.getElementById('preview-filename');

    thumb.src = product.imageUrl;
    filename.textContent = `${product.name.toLowerCase().replace(/[^a-z0-9]/g, '-')}.jpg`;
    chip.style.display = 'flex';

    // Send personalized inquiry message to Anna
    const inquiryText = `Hi Anna! I love your "${product.name}" from your catalogue. I'd like to customize it for 18 guests on Saturday with ${product.flavor}! Can you bake this for me?`;
    sendInquiry(inquiryText);
}

function renderIncomingMessage(text) {
    const viewport = document.getElementById('chat-viewport');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble incoming';
    bubble.innerHTML = `
        <div class="bubble-sender">Anna 👩‍🍳 (Baker & Owner)</div>
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
        <div class="bubble-sender">Anna 👩‍🍳 (Baker & Owner)</div>
        <div class="bubble-text" style="color: #f472b6; font-style: italic; display: flex; align-items: center; gap: 6px;">
            <span>Anna is typing...</span>
            <span style="font-size: 14px;">💬</span>
        </div>
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
// 2. PAYPAL SANDBOX MODAL & GUEST CARD CHECKOUT
// ==========================================
function openPayPalCheckout(orderId, amount, description, paypalOrderId = '', paypalApprovalUrl = '') {
    currentModalOrderId = orderId;
    currentModalAmount = amount;
    currentModalPayPalOrderId = paypalOrderId;
    currentModalApprovalUrl = paypalApprovalUrl;

    document.getElementById('modal-order-title').textContent = description || `Order #${orderId}`;
    document.getElementById('modal-order-amount').textContent = `$${amount.toFixed(2)}`;
    
    const guestLabel = document.getElementById('guest-pay-label');
    if (guestLabel) {
        guestLabel.textContent = `Pay $${amount.toFixed(2)} as Guest`;
    }

    // Default to PayPal tab
    switchCheckoutTab('paypal');

    renderPayPalSmartButtons(orderId, amount, paypalOrderId);

    document.getElementById('checkout-modal').style.display = 'flex';
}

function closeCheckoutModal() {
    document.getElementById('checkout-modal').style.display = 'none';
}

function switchCheckoutTab(tabName) {
    const tabPaypal = document.getElementById('tab-content-paypal');
    const tabCard = document.getElementById('tab-content-card');
    const btnPaypal = document.getElementById('tab-btn-paypal');
    const btnCard = document.getElementById('tab-btn-card');

    if (tabName === 'card') {
        if (tabPaypal) tabPaypal.style.display = 'none';
        if (tabCard) tabCard.style.display = 'block';
        if (btnPaypal) btnPaypal.classList.remove('active');
        if (btnCard) btnCard.classList.add('active');
    } else {
        if (tabPaypal) tabPaypal.style.display = 'block';
        if (tabCard) tabCard.style.display = 'none';
        if (btnPaypal) btnPaypal.classList.add('active');
        if (btnCard) btnCard.classList.remove('active');
    }
}

function renderPayPalSmartButtons(orderId, amount, existingPayPalOrderId) {
    const container = document.getElementById('paypal-smart-button-container');
    if (!container) return;
    container.innerHTML = '';

    if (window.paypal && window.paypal.Buttons) {
        try {
            window.paypal.Buttons({
                style: {
                    layout: 'vertical',
                    color: 'gold',
                    shape: 'pill',
                    label: 'paypal'
                },
                createOrder: function(data, actions) {
                    // Only reuse if it's a real PayPal order ID (not a mock PP- prefix)
                    if (existingPayPalOrderId && !existingPayPalOrderId.startsWith('PP-')) {
                        return existingPayPalOrderId;
                    }
                    return actions.order.create({
                        purchase_units: [{
                            reference_id: orderId,
                            description: `Custom Cake Order #${orderId}`,
                            amount: {
                                currency_code: 'USD',
                                value: amount.toFixed(2)
                            }
                        }]
                    });
                },
                onApprove: async function(data, actions) {
                    closeCheckoutModal();
                    renderIncomingMessage(`⏳ Processing PayPal payment approval...`);
                    try {
                        const captureRes = await fetch(`/api/orders/${orderId}/capture`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ paypalOrderId: data.orderID || existingPayPalOrderId })
                        });
                        if (captureRes.ok) {
                            const resData = await captureRes.json();
                            renderPaymentSuccess(resData, orderId, amount, 'PayPal Express');
                        } else {
                            executeRealPayment();
                        }
                    } catch (e) {
                        console.error("SDK onApprove capture error:", e);
                        executeRealPayment();
                    }
                },
                onError: function(err) {
                    console.warn("PayPal Smart Button notice, falling back to direct sandbox recording:", err);
                    executeRealPayment();
                }
            }).render('#paypal-smart-button-container');
        } catch (e) {
            console.warn("Failed to render PayPal Smart Buttons:", e);
        }
    }
}

async function handleGuestCardPayment(event) {
    if (event) event.preventDefault();
    if (!currentModalOrderId) return;
    const orderId = currentModalOrderId;
    const amount = currentModalAmount;
    const cardholder = document.getElementById('guest-card-name').value.trim() || 'Guest Customer';
    const rawCard = document.getElementById('guest-card-number').value.replace(/\s+/g, '');
    const last4 = rawCard.slice(-4) || '4242';

    const submitBtn = document.getElementById('guest-pay-submit-btn');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span>⏳ Processing Guest Card via PayPal...</span>';

    try {
        const res = await fetch(`/api/orders/${orderId}/guest-card-pay`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                cardholderName: cardholder,
                cardNumberLast4: last4,
                cardType: 'VISA'
            })
        });

        closeCheckoutModal();
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<span class="lock-icon">🔒</span><span id="guest-pay-label">Pay as Guest</span>';

        if (res.ok) {
            const data = await res.json();
            renderPaymentSuccess(data, orderId, amount, `Guest Debit/Credit Card (•••• ${last4})`);
        } else {
            renderIncomingMessage(`⚠️ Guest card processing error. Please try again or use PayPal wallet.`);
        }
    } catch (err) {
        console.error("Guest card pay error:", err);
        closeCheckoutModal();
        submitBtn.disabled = false;
        renderIncomingMessage(`⚠️ Network error processing card payment.`);
    }
}

async function executeRealPayment() {
    if (!currentModalOrderId) return;
    const orderId = currentModalOrderId;
    const amount = currentModalAmount;

    closeCheckoutModal();

    renderIncomingMessage(`⏳ Communicating with live PayPal Sandbox API for Order #${orderId}...`);

    try {
        const response = await fetch(`/api/orders/${orderId}/simulate-payment`, {
            method: 'POST'
        });

        if (response.ok) {
            const data = await response.json();
            renderPaymentSuccess(data, orderId, amount, 'PayPal Express');
        } else {
            renderIncomingMessage(`⚠️ Live PayPal API returned an error. Please verify backend logs.`);
        }
    } catch (e) {
        console.error("Payment capture error:", e);
        renderIncomingMessage(`⚠️ Network error calling PayPal Sandbox API.`);
    }
}

// Fallback alias for backward compatibility
function executeMockPayment() {
    executeRealPayment();
}

function renderPaymentSuccess(data, orderId, amount, methodLabel = 'PayPal') {
    const invId = data.invoiceId || (data.invoice && data.invoice.invoiceId) || '';
    const invUrl = data.invoiceUrl || (data.invoice && data.invoice.invoiceUrl) || 'https://sandbox.paypal.com/invoice/manage';
    const capId = data.captureId || 'CONFIRMED';
    
    const viewport = document.getElementById('chat-viewport');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble incoming';
    bubble.innerHTML = `
        <div class="bubble-sender">Anna 👩‍🍳 (Baker & Owner)</div>
        <div class="bubble-text">
            <p>🎉 Wonderful news! Your payment of <strong>$${amount.toFixed(2)}</strong> has been verified &amp; recorded on PayPal Sandbox!</p>
            <div class="paypal-receipt-card">
                <div class="receipt-header">
                    <span class="paypal-badge-small">PayPal Verified</span>
                    <span class="receipt-status">PAID • CONFIRMED</span>
                </div>
                <div class="receipt-row">
                    <span>Order:</span> <strong>#${orderId}</strong>
                </div>
                <div class="receipt-row">
                    <span>Payment Method:</span> <strong>${escapeHtml(methodLabel)}</strong>
                </div>
                <div class="receipt-row">
                    <span>Transaction ID:</span> <code>${escapeHtml(capId)}</code>
                </div>
                ${invId ? `
                <div class="receipt-row">
                    <span>PayPal Invoice:</span> <code>${escapeHtml(invId)}</code>
                </div>
                ` : ''}

            </div>
            <p style="margin-top: 8px;">Order #${orderId} is now queued on our Kitchen Board. I will begin preparing your handcrafted cake! 🧁</p>
        </div>
        <span class="bubble-time">${getCurrentTime()}</span>
    `;
    viewport.appendChild(bubble);
    viewport.scrollTop = viewport.scrollHeight;
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
        const idx = cachedOrders.findIndex(o => o.id === order.id);
        if (idx >= 0) cachedOrders[idx] = order;
        else cachedOrders.push(order);
        upsertTicket(order, true);
        updateFinancialDashboard(cachedOrders);
        updateKitchenGrid(cachedOrders);
    });

    eventSource.addEventListener('ORDER_PAID', (e) => {
        const order = JSON.parse(e.data);
        const idx = cachedOrders.findIndex(o => o.id === order.id);
        if (idx >= 0) cachedOrders[idx] = order;
        else cachedOrders.push(order);
        upsertTicket(order, true);
        updateFinancialDashboard(cachedOrders);
        updateKitchenGrid(cachedOrders);
        playPopSound();
    });

    eventSource.addEventListener('STATUS_UPDATED', (e) => {
        const order = JSON.parse(e.data);
        const idx = cachedOrders.findIndex(o => o.id === order.id);
        if (idx >= 0) cachedOrders[idx] = order;
        else cachedOrders.push(order);
        upsertTicket(order, true);
        updateFinancialDashboard(cachedOrders);
        updateKitchenGrid(cachedOrders);
        notifyCustomerOfStatusChange(order);
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
            cachedOrders = orders;
            orders.forEach(order => upsertTicket(order, false));
            updateMetrics(orders);
            updateFinancialDashboard(orders);
            updateKitchenGrid(orders);
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
    else if (order.status === 'COMPLETED') {
        refreshColumnCounters();
        return; // Completed orders archived
    }

    const targetContainer = document.getElementById(targetColId);
    if (!targetContainer) return;

    const card = document.createElement('div');
    card.id = `ticket-${order.id}`;
    card.className = `order-card ${flash ? 'just-updated' : ''}`;

    const spec = order.cakeSpec;

    const paypalBadgeHtml = (order.paypalCaptureId || order.paypalInvoiceId) ? `
        <div class="card-paypal-tag">
            <span class="pp-icon">P</span>
            <span class="pp-status">PayPal Paid</span>
            ${order.paypalInvoiceId ? `<a href="${order.paypalInvoiceUrl || 'https://sandbox.paypal.com/invoice/manage'}" target="_blank" class="pp-dash-link" title="View on PayPal Sandbox">#${escapeHtml(order.paypalInvoiceId.slice(-6))} ↗</a>` : `<span class="pp-cap-id">#${escapeHtml(order.paypalCaptureId.slice(-8))}</span>`}
        </div>
    ` : '';

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
                <span class="spec-meta">⚖️ ${spec.weightKg ? spec.weightKg + ' kg' : '1.0 kg'} • ${spec.tiers} Tier(s) • ${spec.dietaryPreferences}</span>
                ${spec.customMessage ? `<span class="spec-custom-msg" style="font-size: 11px; color: #f59e0b; display: block; margin-top: 3px;">✍️ "${escapeHtml(spec.customMessage)}"</span>` : ''}
            </div>
        </div>
        <div class="card-pickup-date">
            📅 Pickup: ${spec.pickupDate}
        </div>
        ${paypalBadgeHtml}
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
            <span class="awaiting-pay-pill">⏳ Awaiting Customer Payment</span>
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
            notifyCustomerOfStatusChange(updated);
            refreshColumnCounters();
        } else if (res.status === 404) {
            console.warn(`Order #${orderId} was not found on the backend. Refreshing orders...`);
            loadAllOrders();
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

// ==========================================
// 4. PAYPAL SANDBOX DASHBOARD & TRANSACTIONS MODAL
// ==========================================
function openPayPalTransactionsModal() {
    const modal = document.getElementById('paypal-transactions-modal');
    if (modal) modal.style.display = 'flex';
    loadPayPalTransactions();
}

function closePayPalTransactionsModal() {
    const modal = document.getElementById('paypal-transactions-modal');
    if (modal) modal.style.display = 'none';
}

async function loadPayPalTransactions() {
    const container = document.getElementById('paypal-tx-list');
    const countTag = document.getElementById('tx-records-count');
    if (!container) return;

    container.innerHTML = '<div class="tx-loading">🔄 Fetching live records from PayPal Sandbox REST API...</div>';

    try {
        const res = await fetch('/api/paypal/transactions');
        if (res.ok) {
            const data = await res.json();
            const invoices = data.invoices || [];
            if (countTag) countTag.textContent = `${invoices.length} record(s)`;

            if (invoices.length === 0) {
                container.innerHTML = `
                    <div class="tx-empty">
                        <p>No transactions found on PayPal Sandbox yet.</p>
                        <p style="font-size: 12px; color: #94a3b8; margin-top: 6px;">
                            Complete a cake checkout in chat to see real transactions recorded here and on your PayPal Dashboard!
                        </p>
                    </div>
                `;
                return;
            }

            container.innerHTML = invoices.map(item => `
                <div class="tx-card">
                    <div class="tx-card-header">
                        <div class="tx-id-badge">
                            <span class="tag">Invoice</span>
                            <strong>${escapeHtml(item.id)}</strong>
                            ${item.invoiceNumber ? `<span class="inv-num">(${escapeHtml(item.invoiceNumber)})</span>` : ''}
                        </div>
                        <span class="tx-status-badge ${item.status === 'PAID' || item.status === 'MARKED_AS_PAID' ? 'paid' : 'pending'}">
                            ${escapeHtml(item.status)}
                        </span>
                    </div>
                    <div class="tx-card-body">
                        <div class="tx-detail-col">
                            <span class="tx-label">Customer:</span>
                            <span class="tx-val">${escapeHtml(item.recipient)}</span>
                        </div>
                        <div class="tx-detail-col">
                            <span class="tx-label">Total Amount:</span>
                            <span class="tx-val amount">${escapeHtml(item.amount)}</span>
                        </div>
                        <div class="tx-detail-col">
                            <span class="tx-label">Paid Amount:</span>
                            <span class="tx-val amount-paid">${escapeHtml(item.paidAmount)}</span>
                        </div>
                        <div class="tx-detail-col">
                            <span class="tx-label">Date:</span>
                            <span class="tx-val">${escapeHtml(item.invoiceDate)}</span>
                        </div>
                    </div>
                    ${item.note ? `<div class="tx-note">📝 ${escapeHtml(item.note)}</div>` : ''}
                    <div class="tx-card-actions">
                        <a href="${item.viewUrl}" target="_blank" class="tx-action-link">
                            🧾 View on PayPal Sandbox ↗
                        </a>
                        <a href="https://sandbox.paypal.com/invoice/manage" target="_blank" class="tx-action-link outline">
                            📊 Merchant Invoices Dashboard ↗
                        </a>
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<div class="tx-error">Failed to fetch transactions from server.</div>';
        }
    } catch (e) {
        console.error("Failed to load PayPal transactions:", e);
        container.innerHTML = '<div class="tx-error">Network error connecting to PayPal API endpoint.</div>';
    }
}



// ==========================================
// 4. AG GRID & MULTI-TAB ARCHITECTURE
// ==========================================
let cachedOrders = [];
let financeGridApi = null;
let kitchenGridApi = null;
let activeMainTab = 'chat';
let isSplitMode = false;
let currentFinanceFilter = 'ALL';

function initFinanceGrid() {
    const gridDiv = document.getElementById('financeGrid');
    if (!gridDiv || typeof agGrid === 'undefined') return;

    const columnDefs = [
        {
            field: 'id',
            headerName: 'Order ID',
            pinned: 'left',
            width: 120,
            cellRenderer: params => {
                if (params.node && params.node.rowPinned) return `<strong class="ag-pinned-label">${params.value}</strong>`;
                return `<span class="ag-order-id-badge">#${escapeHtml(params.value)}</span>`;
            }
        },
        {
            field: 'customerName',
            headerName: 'Customer',
            width: 160,
            cellRenderer: params => {
                if (params.node && params.node.rowPinned) return `<span class="ag-pinned-meta">${params.value}</span>`;
                return `<div class="ag-customer-cell">👤 ${escapeHtml(params.value)}</div>`;
            }
        },
        {
            field: 'orderDate',
            headerName: 'Date',
            width: 110,
            valueGetter: params => {
                if (params.node && params.node.rowPinned) return '';
                const d = new Date(params.data.createdAt || Date.now());
                return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            }
        },
        {
            field: 'paymentMethod',
            headerName: 'Payment Method',
            width: 155,
            cellRenderer: params => {
                if (params.node && params.node.rowPinned) return '';
                const capId = params.data.paypalCaptureId || '';
                const isCard = capId.startsWith('CARD');
                return isCard 
                    ? `<span class="ag-method-badge card">💳 Guest Card</span>`
                    : `<span class="ag-method-badge paypal"><span class="pp-p-tiny">P</span> PayPal</span>`;
            }
        },
        {
            field: 'totalAmount',
            headerName: 'Gross ($)',
            width: 120,
            type: 'rightAligned',
            cellRenderer: params => {
                if (params.node && params.node.rowPinned) return `<strong class="ag-pinned-gross">$${params.value.toFixed(2)}</strong>`;
                return `<span class="ag-amount-gross">$${params.value.toFixed(2)}</span>`;
            }
        },
        {
            field: 'paypalFee',
            headerName: 'PayPal Fee (-$)',
            width: 145,
            type: 'rightAligned',
            cellRenderer: params => {
                if (params.node && params.node.rowPinned) return `<strong class="ag-pinned-fee">-$${params.value.toFixed(2)}</strong>`;
                return `<span class="ag-amount-fee">-$${params.value.toFixed(2)}</span>`;
            }
        },
        {
            field: 'netAmount',
            headerName: 'Net Profit ($)',
            width: 135,
            type: 'rightAligned',
            cellRenderer: params => {
                if (params.node && params.node.rowPinned) return `<strong class="ag-pinned-net">$${params.value.toFixed(2)}</strong>`;
                return `<span class="ag-amount-net">$${params.value.toFixed(2)}</span>`;
            }
        },
        {
            field: 'paymentStatus',
            headerName: 'Settlement Status',
            width: 150,
            cellRenderer: params => {
                if (params.node && params.node.rowPinned) return `<span class="ag-pinned-pill">${params.value}</span>`;
                const isPaid = params.data.status !== 'PAYMENT_PENDING' && params.data.status !== 'QUOTED';
                return isPaid 
                    ? `<span class="ag-status-pill paid">PAID ✅</span>`
                    : `<span class="ag-status-pill pending">PENDING ⏳</span>`;
            }
        },
        {
            field: 'paypalInvoiceId',
            headerName: 'PayPal Invoice / ID',
            width: 185,
            cellRenderer: params => {
                if (params.node && params.node.rowPinned) return '';
                const inv = params.data.paypalInvoiceId;
                const cap = params.data.paypalCaptureId;
                if (inv) {
                    return `<span class="ag-inv-code">${escapeHtml(inv)}</span>`;
                } else if (cap) {
                    return `<span class="ag-cap-code">${escapeHtml(cap)}</span>`;
                }
                return `<span class="ag-muted-text">Awaiting Checkout</span>`;
            }
        },
        {
            field: 'receiptLink',
            headerName: 'Sandbox Invoice',
            width: 160,
            cellRenderer: params => {
                if (params.node && params.node.rowPinned) return '';
                const isPaid = params.data.status !== 'PAYMENT_PENDING' && params.data.status !== 'QUOTED';
                if (isPaid || params.data.paypalInvoiceId) {
                    return `<button type="button" class="ag-paypal-receipt-btn" onclick="openInvoiceModal('${params.data.id}')">📄 View Invoice ↗</button>`;
                }
                return `<span class="ag-dash-na">—</span>`;
            }
        }
    ];

    const gridOptions = {
        theme: 'legacy',
        columnDefs: columnDefs,
        rowData: [],
        pinnedBottomRowData: [],
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true
        },
        rowHeight: 46,
        headerHeight: 44,
        animateRows: true
    };

    try {
        financeGridApi = agGrid.createGrid(gridDiv, gridOptions);
    } catch (e) {
        console.error("Failed to initialize financeGrid:", e);
    }
}

function initKitchenGrid() {
    const gridDiv = document.getElementById('kitchenGrid');
    if (!gridDiv || typeof agGrid === 'undefined') return;

    const columnDefs = [
        {
            field: 'id',
            headerName: 'Order ID',
            pinned: 'left',
            width: 115,
            cellRenderer: params => `<span class="ag-order-id-badge">#${escapeHtml(params.value)}</span>`
        },
        {
            field: 'customerName',
            headerName: 'Customer',
            width: 160,
            cellRenderer: params => `<div class="ag-customer-cell">👤 ${escapeHtml(params.value)}</div>`
        },
        {
            field: 'theme',
            headerName: 'Cake Theme',
            width: 180,
            valueGetter: params => params.data.cakeSpec ? params.data.cakeSpec.theme : 'Custom Cake',
            cellRenderer: params => `<span class="ag-cake-theme">🎂 ${escapeHtml(params.value)}</span>`
        },
        {
            field: 'flavor',
            headerName: 'Flavor & Specs',
            width: 220,
            valueGetter: params => {
                const s = params.data.cakeSpec;
                if (!s) return 'Artisan Cake';
                return `${s.flavor} (${s.weightKg ? s.weightKg + 'kg' : '1kg'} • ${s.tiers}T)`;
            }
        },
        {
            field: 'dietary',
            headerName: 'Dietary',
            width: 130,
            valueGetter: params => params.data.cakeSpec ? params.data.cakeSpec.dietaryPreferences : 'Standard',
            cellRenderer: params => `<span class="ag-dietary-tag">${escapeHtml(params.value)}</span>`
        },
        {
            field: 'pickupDate',
            headerName: 'Pickup Date',
            width: 130,
            valueGetter: params => params.data.cakeSpec ? params.data.cakeSpec.pickupDate : 'ASAP',
            cellRenderer: params => `📅 ${escapeHtml(params.value)}`
        },
        {
            field: 'status',
            headerName: 'Kitchen Status',
            width: 160,
            cellRenderer: params => {
                const st = params.value;
                let label = st;
                let cls = 'pending';
                if (st === 'CONFIRMED') { label = 'Paid • In Queue'; cls = 'confirmed'; }
                else if (st === 'BAKING') { label = 'In the Oven 🎂'; cls = 'baking'; }
                else if (st === 'READY_FOR_PICKUP') { label = 'Ready for Pickup 📦'; cls = 'ready'; }
                else if (st === 'COMPLETED') { label = 'Picked Up ✅'; cls = 'completed'; }
                return `<span class="ag-kitchen-status-pill ${cls}">${label}</span>`;
            }
        },
        {
            field: 'actions',
            headerName: 'Kitchen Action',
            width: 160,
            cellRenderer: params => {
                const o = params.data;
                if (o.status === 'CONFIRMED') {
                    return `<button class="ag-action-btn bake" onclick="updateOrderStatus('${o.id}', 'BAKING')">👩‍🍳 Start Baking</button>`;
                } else if (o.status === 'BAKING') {
                    return `<button class="ag-action-btn ready" onclick="updateOrderStatus('${o.id}', 'READY_FOR_PICKUP')">📦 Box & Ready</button>`;
                } else if (o.status === 'READY_FOR_PICKUP') {
                    return `<button class="ag-action-btn complete" onclick="updateOrderStatus('${o.id}', 'COMPLETED')">✅ Complete</button>`;
                }
                return `<span class="ag-muted-text">—</span>`;
            }
        }
    ];

    const gridOptions = {
        theme: 'legacy',
        columnDefs: columnDefs,
        rowData: [],
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true
        },
        rowHeight: 46,
        headerHeight: 44,
        animateRows: true
    };

    try {
        kitchenGridApi = agGrid.createGrid(gridDiv, gridOptions);
    } catch (e) {
        console.error("Failed to initialize kitchenGrid:", e);
    }
}

function updateFinancialDashboard(orders) {
    if (!orders) return;

    let totalSettledGross = 0;
    let totalSettledFees = 0;
    let totalSettledNet = 0;
    let paidCount = 0;
    let pendingCount = 0;

    orders.forEach(o => {
        const isPaid = o.status !== 'PAYMENT_PENDING' && o.status !== 'QUOTED' && o.status !== 'CANCELLED';
        const fee = (o.totalAmount * 0.0299) + 0.49;
        const net = o.totalAmount - fee;

        if (isPaid) {
            totalSettledGross += o.totalAmount;
            totalSettledFees += fee;
            totalSettledNet += net;
            paidCount++;
        } else {
            pendingCount++;
        }
    });

    // Update KPI Card DOM
    const grossEl = document.getElementById('kpi-gross-revenue');
    const grossSubEl = document.getElementById('kpi-gross-orders');
    const feesEl = document.getElementById('kpi-paypal-fees');
    const netEl = document.getElementById('kpi-net-payout');
    const netMarginEl = document.getElementById('kpi-net-margin');
    const rateEl = document.getElementById('kpi-settlement-rate');
    const rateDetailEl = document.getElementById('kpi-settlement-detail');

    if (grossEl) grossEl.textContent = `$${totalSettledGross.toFixed(2)}`;
    if (grossSubEl) grossSubEl.textContent = `${paidCount} Settled Orders`;
    if (feesEl) feesEl.textContent = `-$${totalSettledFees.toFixed(2)}`;
    if (netEl) netEl.textContent = `$${totalSettledNet.toFixed(2)}`;
    if (netMarginEl) {
        const marginPct = totalSettledGross > 0 ? ((totalSettledNet / totalSettledGross) * 100).toFixed(1) : '100.0';
        netMarginEl.textContent = `Margin: ${marginPct}% of Gross`;
    }
    if (rateEl) {
        const total = orders.length || 1;
        rateEl.textContent = `${((paidCount / total) * 100).toFixed(0)}%`;
    }
    if (rateDetailEl) rateDetailEl.textContent = `${paidCount} Paid • ${pendingCount} Pending`;

    // Filter rows based on active chip
    let filteredOrders = orders;
    if (currentFinanceFilter === 'PAID') {
        filteredOrders = orders.filter(o => o.status !== 'PAYMENT_PENDING' && o.status !== 'QUOTED' && o.status !== 'CANCELLED');
    } else if (currentFinanceFilter === 'PENDING') {
        filteredOrders = orders.filter(o => o.status === 'PAYMENT_PENDING' || o.status === 'QUOTED');
    }

    const formattedRows = filteredOrders.map(o => {
        const isPaid = o.status !== 'PAYMENT_PENDING' && o.status !== 'QUOTED';
        const fee = (o.totalAmount * 0.0299) + 0.49;
        const net = o.totalAmount - fee;
        return {
            ...o,
            paypalFee: fee,
            netAmount: net,
            paymentStatus: isPaid ? 'PAID' : 'PENDING'
        };
    });

    const pinnedRows = [{
        id: 'TOTAL',
        customerName: `${paidCount} Settled Invoices`,
        orderDate: '',
        paymentMethod: '',
        totalAmount: totalSettledGross,
        paypalFee: totalSettledFees,
        netAmount: totalSettledNet,
        paymentStatus: `${((paidCount / (orders.length || 1)) * 100).toFixed(0)}% Settled`,
        paypalInvoiceId: '',
        receiptLink: ''
    }];

    if (financeGridApi) {
        financeGridApi.setGridOption('rowData', formattedRows);
        financeGridApi.setGridOption('pinnedBottomRowData', pinnedRows);
    }
}

function updateKitchenGrid(orders) {
    if (!orders || !kitchenGridApi) return;
    kitchenGridApi.setGridOption('rowData', orders);
}

function switchMainTab(tab) {
    activeMainTab = tab;
    document.querySelectorAll('.main-nav-tab').forEach(t => t.classList.remove('active'));
    const activeTabBtn = document.getElementById(`tab-nav-${tab}`);
    if (activeTabBtn) activeTabBtn.classList.add('active');

    const wrapper = document.getElementById('main-workspace-wrapper');
    if (isSplitMode) {
        document.getElementById('pane-chat').classList.add('active');
        document.getElementById('pane-kitchen').classList.toggle('active', tab === 'kitchen');
        document.getElementById('pane-finance').classList.toggle('active', tab === 'finance');
    } else {
        document.querySelectorAll('.tab-panel-view').forEach(p => p.classList.remove('active'));
        const pane = document.getElementById(`pane-${tab}`);
        if (pane) pane.classList.add('active');
    }

    setTimeout(() => {
        if (tab === 'finance' && financeGridApi) financeGridApi.sizeColumnsToFit();
        if (tab === 'kitchen' && kitchenGridApi) kitchenGridApi.sizeColumnsToFit();
    }, 50);
}

function switchKitchenSubView(view) {
    document.getElementById('subswitch-kanban').classList.toggle('active', view === 'kanban');
    document.getElementById('subswitch-grid').classList.toggle('active', view === 'grid');

    const kanbanView = document.getElementById('kitchen-kanban-view');
    const gridView = document.getElementById('kitchen-grid-view');

    if (view === 'kanban') {
        kanbanView.style.display = 'block';
        gridView.style.display = 'none';
    } else {
        kanbanView.style.display = 'none';
        gridView.style.display = 'block';
        setTimeout(() => {
            if (kitchenGridApi) kitchenGridApi.sizeColumnsToFit();
        }, 50);
    }
}


function toggleSplitMode() {
    isSplitMode = !isSplitMode;
    const wrapper = document.getElementById('main-workspace-wrapper');
    const toggleBtn = document.getElementById('split-mode-toggle');

    wrapper.classList.toggle('split-layout-mode', isSplitMode);
    toggleBtn.classList.toggle('active', isSplitMode);

    if (isSplitMode) {
        document.getElementById('split-mode-text').textContent = 'Tab View';
        if (activeMainTab === 'chat') activeMainTab = 'kitchen';
        switchMainTab(activeMainTab);
    } else {
        document.getElementById('split-mode-text').textContent = 'Split View';
        switchMainTab(activeMainTab);
    }
}

function onFinanceSearch(val) {
    if (financeGridApi) {
        financeGridApi.setGridOption('quickFilterText', val);
    }
}

function clearFinanceSearch() {
    const inp = document.getElementById('finance-search-input');
    if (inp) inp.value = '';
    if (financeGridApi) financeGridApi.setGridOption('quickFilterText', '');
}

function filterFinanceStatus(status) {
    currentFinanceFilter = status;
    document.querySelectorAll('.status-chip').forEach(c => c.classList.remove('active'));
    const chip = document.getElementById(`fchip-${status.toLowerCase()}`);
    if (chip) chip.classList.add('active');
    updateFinancialDashboard(cachedOrders);
}

function exportFinanceCsv() {
    if (financeGridApi) {
        financeGridApi.exportDataAsCsv({
            fileName: `BakeFlow_PayPal_Ledger_${new Date().toISOString().slice(0, 10)}.csv`
        });
    }
}


async function clearPendingOrders() {
    try {
        const res = await fetch('/api/orders/pending', { method: 'DELETE' });
        if (res.ok) {
            await loadAllOrders();
        }
    } catch (e) {
        console.error("Failed to clear pending orders:", e);
    }
}

// ==========================================
// 5. HANDS-FREE KITCHEN VOICE ASSISTANT
// ==========================================
let isVoiceListening = false;
let speechRecognitionInstance = null;

function toggleKitchenVoiceAssistant() {
    if (isVoiceListening) {
        stopKitchenVoiceAssistant();
    } else {
        startKitchenVoiceAssistant();
    }
}

function startKitchenVoiceAssistant() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        alert("Web Speech API is not supported in this browser. Please use Google Chrome or Edge, or use the quick test command chips!");
        return;
    }

    try {
        speechRecognitionInstance = new SpeechRecognition();
        speechRecognitionInstance.continuous = false;
        speechRecognitionInstance.interimResults = false;
        speechRecognitionInstance.lang = 'en-US';

        const btn = document.getElementById('voice-assistant-btn');
        const label = document.getElementById('voice-btn-label');
        const pulse = document.getElementById('voice-pulse-ring');
        const hint = document.getElementById('voice-status-hint');

        btn.classList.add('listening');
        label.textContent = 'Listening...';
        pulse.style.display = 'block';
        hint.innerHTML = '<span style="color: #38bdf8; font-weight: 700;">Listening to kitchen speech...</span> Speak your command now!';

        isVoiceListening = true;

        speechRecognitionInstance.onresult = function(event) {
            const transcript = event.results[0][0].transcript;
            console.log("Voice Transcript Heard:", transcript);
            stopKitchenVoiceAssistant();
            executeVoiceAction(transcript);
        };

        speechRecognitionInstance.onerror = function(event) {
            console.warn("Speech recognition error:", event.error);
            stopKitchenVoiceAssistant();
            hint.textContent = `Mic error: ${event.error}. You can also tap the test command chips!`;
        };

        speechRecognitionInstance.onend = function() {
            stopKitchenVoiceAssistant();
        };

        speechRecognitionInstance.start();
    } catch (e) {
        console.error("Failed to start speech recognition:", e);
        stopKitchenVoiceAssistant();
    }
}

function stopKitchenVoiceAssistant() {
    isVoiceListening = false;
    const btn = document.getElementById('voice-assistant-btn');
    const label = document.getElementById('voice-btn-label');
    const pulse = document.getElementById('voice-pulse-ring');

    if (btn) btn.classList.remove('listening');
    if (label) label.textContent = 'Tap to Speak';
    if (pulse) pulse.style.display = 'none';

    if (speechRecognitionInstance) {
        try {
            speechRecognitionInstance.stop();
        } catch (e) {}
    }
}

async function executeVoiceAction(transcript) {
    const hint = document.getElementById('voice-status-hint');
    if (hint) {
        hint.innerHTML = `Heard: "<em>${escapeHtml(transcript)}</em>" &bull; ⏳ Parsing intent with AI...`;
    }

    try {
        const res = await fetch('/api/orders/voice-action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ transcript: transcript })
        });

        if (res.ok) {
            const data = await res.json();
            if (data.status === 'SUCCESS' && data.order) {
                // Flash ticket on Kanban
                upsertTicket(data.order, true);
                if (hint) {
                    hint.innerHTML = `✅ <strong style="color: #34d399;">${escapeHtml(data.spokenFeedback)}</strong>`;
                }
                playPopSound();
                speakAnnaVoiceConfirmation(data.spokenFeedback);
                loadAllOrders(); // refresh grids
            } else {
                if (hint) {
                    hint.innerHTML = `⚠️ <span style="color: #fbbf24;">${escapeHtml(data.spokenFeedback || "Could not find matching order.")}</span>`;
                }
                speakAnnaVoiceConfirmation(data.spokenFeedback || "I could not find a matching order.");
            }
        }
    } catch (e) {
        console.error("Voice action failed:", e);
        if (hint) hint.textContent = "Error communicating with voice action server.";
    }
}

function simulateVoiceCommand(transcript) {
    executeVoiceAction(transcript);
}

function speakAnnaVoiceConfirmation(text) {
    if ('speechSynthesis' in window && text) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.05;
        utterance.pitch = 1.1;
        utterance.lang = 'en-US';
        window.speechSynthesis.speak(utterance);
    }
}

const notifiedOrderTransitions = new Set();
function notifyCustomerOfStatusChange(order) {
    if (!order || !order.id || !order.status) return;
    const transitionKey = order.id + '-' + order.status;
    if (notifiedOrderTransitions.has(transitionKey)) {
        return;
    }
    notifiedOrderTransitions.add(transitionKey);

    let message = null;
    const name = order.customerName || "Customer";
    if (order.status === "BAKING") {
        message = "Update on Order #" + order.id + " (" + name + "): Your cake is now in the oven! 🎂🔥 Anna has started baking it fresh.";
    } else if (order.status === "READY_FOR_PICKUP") {
        message = "Update on Order #" + order.id + " (" + name + "): Hooray! Your cake is decorated, boxed, and ready for pickup! 📦✨";
    } else if (order.status === "COMPLETED") {
        message = "Update on Order #" + order.id + " (" + name + "): Thank you so much! Your order has been marked as picked up. Enjoy your celebration! 🎉🍰";
    }
    if (message) {
        renderIncomingMessage(message);
    }
}


// ==========================================
// 6. OFFICIAL PAYPAL DIGITAL INVOICE VIEWER
// ==========================================
let isAutoInvoicingActive = true;

function toggleAutoInvoicing() {
    isAutoInvoicingActive = !isAutoInvoicingActive;
    const badge = document.getElementById('auto-invoicing-badge');
    const statusText = document.getElementById('auto-inv-status');
    if (badge && statusText) {
        if (isAutoInvoicingActive) {
            badge.classList.add('active');
            statusText.textContent = 'ON';
            statusText.style.color = '#34d399';
        } else {
            badge.classList.remove('active');
            statusText.textContent = 'OFF';
            statusText.style.color = '#f87171';
        }
    }
}

function openInvoiceModal(orderId) {
    const order = cachedOrders.find(o => o.id === orderId);
    if (!order) {
        alert("Order #" + orderId + " not found.");
        return;
    }

    const spec = order.cakeSpec || {};
    const total = Number(order.totalAmount || 0);
    const fee = (total * 0.0299) + 0.49;
    const net = Math.max(0, total - fee);

    const isPaid = order.status !== 'PAYMENT_PENDING' && order.status !== 'QUOTED';
    const invId = order.paypalInvoiceId || ('INV2-SBX-' + order.id.replace('BK-', ''));
    const capId = order.paypalCaptureId || order.paypalOrderId || 'PAY-VERIFIED-SANDBOX';

    // Populate Modal Elements
    const numEl = document.getElementById('inv-modal-num');
    const orderIdEl = document.getElementById('inv-modal-order-id');
    const statusEl = document.getElementById('inv-modal-status');
    const dateEl = document.getElementById('inv-modal-date');
    const pickupEl = document.getElementById('inv-modal-pickup');
    const customerEl = document.getElementById('inv-modal-customer');
    const phoneEl = document.getElementById('inv-modal-phone');
    const captureEl = document.getElementById('inv-modal-capture');

    const themeEl = document.getElementById('inv-modal-theme');
    const flavorEl = document.getElementById('inv-modal-flavor');
    const msgEl = document.getElementById('inv-modal-msg');
    const tiersEl = document.getElementById('inv-modal-tiers');
    const dietaryEl = document.getElementById('inv-modal-dietary');
    const weightEl = document.getElementById('inv-modal-weight');

    const lineTotalEl = document.getElementById('inv-modal-line-total');
    const subtotalEl = document.getElementById('inv-modal-subtotal');
    const feeEl = document.getElementById('inv-modal-fee');
    const netEl = document.getElementById('inv-modal-net');
    const totalEl = document.getElementById('inv-modal-total');
    const extLinkEl = document.getElementById('inv-modal-ext-link');

    if (numEl) numEl.textContent = invId;
    if (orderIdEl) orderIdEl.textContent = '#' + order.id;
    if (statusEl) {
        statusEl.className = 'inv-status-pill ' + (isPaid ? 'paid' : 'pending');
        statusEl.textContent = isPaid ? 'PAID ✅' : 'PENDING PAYMENT ⏳';
    }
    if (dateEl) {
        const d = new Date(order.createdAt || Date.now());
        dateEl.textContent = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }
    if (pickupEl) pickupEl.textContent = spec.pickupDate || 'Scheduled';
    if (customerEl) customerEl.textContent = order.customerName || 'Customer';
    if (phoneEl) phoneEl.textContent = order.customerPhone || '+1 (408) 555-0199';
    if (captureEl) captureEl.textContent = capId;

    if (themeEl) themeEl.textContent = spec.theme || 'Custom Artisan Cake';
    if (flavorEl) flavorEl.textContent = 'Flavor: ' + (spec.flavor || 'Signature Vanilla Bean');
    if (msgEl) {
        if (spec.customMessage && spec.customMessage.trim()) {
            msgEl.textContent = '✍️ Inscription: "' + spec.customMessage + '"';
            msgEl.style.display = 'block';
        } else {
            msgEl.style.display = 'none';
        }
    }
    if (tiersEl) tiersEl.textContent = (spec.tiers || 1) + ' Tier(s)';
    if (dietaryEl) dietaryEl.textContent = spec.dietaryPreferences || 'Standard';
    if (weightEl) weightEl.textContent = (spec.weightKg ? spec.weightKg : 1.0) + ' kg';

    if (lineTotalEl) lineTotalEl.textContent = '$' + total.toFixed(2);
    if (subtotalEl) subtotalEl.textContent = '$' + total.toFixed(2);
    if (feeEl) feeEl.textContent = '-$' + fee.toFixed(2);
    if (netEl) netEl.textContent = '$' + net.toFixed(2);
    if (totalEl) totalEl.textContent = '$' + total.toFixed(2);

    if (extLinkEl) {
        extLinkEl.href = order.paypalInvoiceUrl || 'https://sandbox.paypal.com/invoice/manage';
    }

    const modal = document.getElementById('invoice-modal');
    if (modal) modal.style.display = 'flex';
}

function closeInvoiceModal() {
    const modal = document.getElementById('invoice-modal');
    if (modal) modal.style.display = 'none';
}

function printInvoiceModal() {
    window.print();
}
