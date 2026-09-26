const API = window.OPTIGO_API_BASE || "http://127.0.0.1:8000";
const state = { account: null, view: "dashboard" };
const ROLE_VIEWS = {
  CUSTOMER: ["dashboard", "shipments", "booking", "payments", "tracking", "notifications", "complaints"],
  ADMINISTRATOR: ["dashboard", "shipments", "operations", "tasks", "warehouse", "finance", "complaints", "tracking", "reports", "route-planner"],
  OPERATIONS_MANAGER: ["dashboard", "shipments", "operations", "tasks", "warehouse", "finance", "complaints", "tracking", "reports", "route-planner"],
  ACCOUNTS_OFFICER: ["finance", "reports"],
  BOOKING_OFFICER: ["shipments", "operations", "tracking"],
  DELIVERY_AGENT: ["tasks"],
  PICKUP_AGENT: ["tasks"],
  SUPPORT_OFFICER: ["complaints", "tracking"],
  TRACKING_OFFICER: ["tracking", "shipments", "reports"],
  WAREHOUSE_OFFICER: ["warehouse", "tasks", "shipments"]
};
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const money = (value, currency="INR") => `${currency} ${Number(value || 0).toLocaleString("en-IN", {minimumFractionDigits:2, maximumFractionDigits:2})}`;
const statusClass = (s) => `status-${String(s || "").toLowerCase().replaceAll("_", "-")}`;
function toast(message, error=false){const node=$("#toast");node.textContent=message==="Order created successfully"?"Order placed successfully":message;node.style.background=error?"#8A1A49":"#1D2935";node.classList.add("show");setTimeout(()=>node.classList.remove("show"),3300)}
async function api(path, options={}){const headers={"Content-Type":"application/json",...(options.headers||{})};let bookingForm=null;if(path==="/api/shipments"&&options.method==="POST"){bookingForm=$("#booking-form");if(bookingForm){const requestBody=options.body||"";if(!bookingForm.dataset.idempotencyKey||bookingForm.dataset.bookingPayload!==requestBody){bookingForm.dataset.idempotencyKey=crypto.randomUUID();bookingForm.dataset.bookingPayload=requestBody}headers["Idempotency-Key"]=bookingForm.dataset.idempotencyKey}}const response=await fetch(`${API}${path}`,{...options,credentials:"include",headers});let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.detail||"The request could not be completed");if(bookingForm){delete bookingForm.dataset.idempotencyKey;delete bookingForm.dataset.bookingPayload;}return data}
function formatDate(value){return value?new Date(value).toLocaleDateString("en-IN",{day:"2-digit",month:"short",year:"numeric"}):"—"}
function renderAuth(mode="login"){const register=mode==="register";$("#login-form").classList.toggle("hidden",register);$("#register-form").classList.toggle("hidden",!register);$("#auth-eyebrow").textContent=register?"NEW CUSTOMER":"WELCOME BACK";$("#auth-title").textContent=register?"Create your OptiGo account":"Sign in to your workspace";$("#auth-subtitle").textContent=register?"Book and follow every shipment from one place.":"Use your OptiGo account to continue.";$("#auth-error").textContent="";$("#auth-error").classList.remove("show");$("#auth-switch").innerHTML=register?"Already have an account? <button type=\"button\" data-auth-mode=\"login\">Sign in</button>":"New to OptiGo? <button type=\"button\" data-auth-mode=\"register\">Create an account</button>"}
function showAuthMessage(message,success=false){const node=$("#auth-error");node.textContent=message;node.classList.toggle("success",success);node.classList.add("show")}
function showAuthError(message){showAuthMessage(message,false)}
function showShell(){
  const a=state.account;
  const allowed=ROLE_VIEWS[a.role]||[];
  if(!allowed.length){showAuthError("This account has no workspace role. Contact an administrator.");return}
  state.view=allowed[0];
  $("#auth-shell").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
  $("#account-name").textContent=a.name;
  $("#account-role").textContent=a.role.replaceAll("_"," ");
  $("#avatar").textContent=(a.name||"S").slice(0,1).toUpperCase();
  $("#staff-nav").classList.toggle("hidden",a.role==="CUSTOMER");
  const sectionName={ACCOUNTS_OFFICER:"Accounts",BOOKING_OFFICER:"Booking",DELIVERY_AGENT:"Delivery",PICKUP_AGENT:"Pickup",SUPPORT_OFFICER:"Support",TRACKING_OFFICER:"Tracking",WAREHOUSE_OFFICER:"Warehouse"}[a.role]||"Operations";
  $("#staff-nav .nav-label").textContent=sectionName;
  const taskLabel={DELIVERY_AGENT:"My deliveries",PICKUP_AGENT:"My pickups",WAREHOUSE_OFFICER:"My warehouse tasks",ADMINISTRATOR:"Team tasks",OPERATIONS_MANAGER:"Team tasks"}[a.role]||"My tasks";
  $("#staff-nav [data-view=tasks]").lastChild.textContent=taskLabel;
  document.querySelectorAll("#nav-list [data-view]").forEach(node=>node.classList.toggle("hidden",!allowed.includes(node.dataset.view)));
  navigate(state.view);
}
function setTitle(title){$("#page-title").textContent=title;document.querySelectorAll(".nav-item").forEach(n=>n.classList.toggle("active",n.dataset.view===state.view))}
function tableRows(shipments){if(!shipments.length)return `<div class="empty-state"><strong>No shipments found</strong><span>When a booking is created it will appear here.</span></div>`;return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Tracking ID</th><th>Status</th><th>Booked</th><th>Expected</th><th>Charge</th></tr></thead><tbody>${shipments.map(s=>`<tr><td><button class="tracking-link link-button" data-track="${esc(s.tracking_id)}">${esc(s.tracking_id)}</button></td><td><span class="status-badge ${statusClass(s.status)}">${esc(s.status.replaceAll("_"," "))}</span></td><td>${formatDate(s.booking_date)}</td><td>${formatDate(s.expected_delivery)}</td><td>${money(s.charge,s.currency)}</td></tr>`).join("")}</tbody></table></div>`}
async function dashboard(){setTitle("Overview");const d=await api("/api/dashboard");const m=d.metrics;$("#view").innerHTML=`<div class="section-heading"><div><h2>Good to see you, ${esc(state.account.name.split(" ")[0])}.</h2><p>Here is the latest view of your OptiGo activity.</p></div><button class="button primary ${state.account.role!=="CUSTOMER"?"hidden":""}" data-view="booking">New booking <span>＋</span></button></div><div class="metric-grid"><div class="metric-card blue"><div class="label">Total shipments</div><div class="value">${m.total}</div><div class="hint">All shipments</div></div><div class="metric-card green"><div class="label">Delivered</div><div class="value">${m.delivered}</div><div class="hint">Completed shipments</div></div><div class="metric-card orange"><div class="label">In progress</div><div class="value">${m.in_transit}</div><div class="hint">Moving through network</div></div><div class="metric-card pink"><div class="label">Needs attention</div><div class="value">${m.attention}</div><div class="hint">Failed or unavailable</div></div></div><div class="grid-2"><section class="panel"><div class="panel-header"><h3>Recent shipments</h3><button class="button ghost small" data-view="shipments">View all</button></div>${tableRows(d.recent_shipments)}</section><section class="panel"><h3>Tracking at a glance</h3><p class="muted" style="font-size:13px">Find a shipment by tracking ID and follow its progress.</p><button class="button secondary" data-view="tracking">Track a shipment <span>→</span></button></section></div>`}
async function shipments(){setTitle("Shipments");$("#view").innerHTML=`<div class="section-heading"><div><h2>${state.account.role==="CUSTOMER"?"Your shipments":"Operational shipments"}</h2><p>Manage shipments and follow their progress.</p></div></div><div class="search-bar"><input id="shipment-search" placeholder="Search by OBU tracking ID"><button class="button primary" id="shipment-search-button">Search</button></div><div id="shipment-results"><div class="empty-state">Loading shipments…</div></div>`;const load=async()=>{const query=$("#shipment-search").value?`?search=${encodeURIComponent($("#shipment-search").value)}`:"";$("#shipment-results").innerHTML=tableRows(await api("/api/shipments"+query))};$("#shipment-search-button").onclick=load;await load()}
async function loadRazorpayCheckout(order, shipmentId, resultNode){
  if(!window.Razorpay){
    await new Promise((resolve,reject)=>{const script=document.createElement("script");script.src="https://checkout.razorpay.com/v1/checkout.js";script.onload=resolve;script.onerror=()=>reject(new Error("Razorpay checkout could not be loaded"));document.body.appendChild(script)});
  }
  const checkout=new Razorpay({key:order.key_id,amount:order.amount,currency:order.currency,order_id:order.order_id,name:"OptiGo",description:"Courier shipment",handler:async response=>{
    try{
      const verified=await api("/api/payments/razorpay/verify",{method:"POST",body:JSON.stringify({shipment_id:shipmentId,order_id:response.razorpay_order_id,payment_id:response.razorpay_payment_id,signature:response.razorpay_signature})});
      resultNode.innerHTML='<div class="result-card"><h4>Payment verified</h4><div>'+esc(verified.invoice_no)+' · '+esc(verified.payment_status)+'</div></div>';
    }catch(err){resultNode.innerHTML='<div class="error-text">'+esc(err.message)+'</div>'}
  }});
  checkout.open();
}
async function startShipmentPayment(shipmentId, resultNode){
  resultNode.innerHTML='<div class="muted">Preparing secure payment…</div>';
  try{
    const order=await api("/api/payments/razorpay/order",{method:"POST",body:JSON.stringify({shipment_id:shipmentId})});
    if(order.provider!=="razorpay")throw new Error("Razorpay checkout is unavailable");
    await loadRazorpayCheckout(order,shipmentId,resultNode);
  }catch(err){resultNode.innerHTML='<div class="error-text">'+esc(err.message)+'</div>'}
}
function booking(){
  setTitle("New booking");
  $("#view").innerHTML='<div class="section-heading"><div><h2>Send a parcel with confidence.</h2><p>Enter the shipment details and we will prepare everything for delivery.</p></div></div><form id="booking-form" class="panel"><div class="callout">Your shipping price is calculated from the current backend rate before you place the order.</div><h3>Sender details</h3>'+locationFields("sender","Sender")+'<h3 style="margin-top:28px">Receiver details</h3>'+locationFields("receiver","Receiver")+'<h3 style="margin-top:28px">Parcel details</h3><div class="form-grid three"><div class="field"><label>Weight (kg)<input name="weight_kg" type="number" step="0.001" min="0.001" required></label></div><div class="field"><label>Length (cm)<input name="length_cm" type="number" step="0.01" min="0.01" required></label></div><div class="field"><label>Width (cm)<input name="width_cm" type="number" step="0.01" min="0.01" required></label></div><div class="field"><label>Height (cm)<input name="height_cm" type="number" step="0.01" min="0.01" required></label></div><div class="field"><label>Delivery type<select name="delivery_type_code"><option value="STANDARD">Standard</option><option value="EXPRESS">Express</option><option value="SAME_DAY">Same day</option></select></label></div><div class="field" style="display:flex;align-items:end;gap:20px"><label style="display:flex;align-items:center;gap:8px"><input name="fragile" type="checkbox" style="width:auto"> Fragile</label><label style="display:flex;align-items:center;gap:8px"><input name="priority" type="checkbox" style="width:auto"> Priority</label></div></div><section class="price-summary" aria-live="polite"><strong>Shipping price</strong><div id="booking-price">Enter the parcel weight to calculate your price.</div></section><fieldset class="payment-choice"><legend>Payment mode</legend><label><input type="radio" name="payment_mode" value="CASH" required> Cash on delivery</label><label><input type="radio" name="payment_mode" value="RAZORPAY" required> Pay online with Razorpay</label></fieldset><div class="form-actions"><button class="button primary" type="submit" disabled>Place order <span>→</span></button></div><div id="booking-result"></div></form>';
  wireLocationFields("sender");
  wireLocationFields("receiver");
  const form=$("#booking-form");
  const submit=form.querySelector('button[type="submit"]');
  const weightInput=form.elements.weight_kg;
  const deliveryInput=form.elements.delivery_type_code;
  api("/api/payments/options").then(options=>{
    const online=form.querySelector('[name="payment_mode"][value="RAZORPAY"]');
    if(!online)return;
    online.disabled=!options.razorpay_available;
    if(!options.razorpay_available)online.parentElement.append(" (test checkout unavailable; use cash)");
  }).catch(()=>{
    const online=form.querySelector('[name="payment_mode"][value="RAZORPAY"]');
    if(online)online.disabled=true;
  });
  let quote=null;
  let quoteSequence=0;
  let quoteTimer;
  async function refreshQuote(){
    const weight=Number(weightInput.value);
    const delivery=deliveryInput.value;
    const sequence=++quoteSequence;
    if(!Number.isFinite(weight)||weight<=0){quote=null;$("#booking-price").textContent="Enter the parcel weight to calculate your price.";submit.disabled=true;return}
    $("#booking-price").textContent="Updating price…";
    submit.disabled=true;
    try{
      const result=await api("/api/pricing/quote",{method:"POST",body:JSON.stringify({weight_kg:weight,delivery_type_code:delivery,destination_zone:"LOCAL"})});
      if(sequence!==quoteSequence)return;
      quote={weight,delivery,amount:result.amount,currency:result.currency};
      $("#booking-price").innerHTML='<strong>'+money(result.amount,result.currency)+'</strong><small>Calculated from the current rate for '+esc(delivery.toLowerCase().replaceAll("_"," "))+' delivery.</small>';
      submit.disabled=false;
    }catch(err){
      if(sequence!==quoteSequence)return;
      quote=null;
      $("#booking-price").textContent="Price unavailable: "+err.message;
      submit.disabled=true;
    }
  }
  weightInput.addEventListener("input",()=>{clearTimeout(quoteTimer);quoteTimer=setTimeout(refreshQuote,250)});
  deliveryInput.addEventListener("change",refreshQuote);
  form.onsubmit=async(event)=>{
    event.preventDefault();
    const currentWeight=Number(weightInput.value);
    if(!quote||quote.weight!==currentWeight||quote.delivery!==deliveryInput.value){await refreshQuote();if(!quote||quote.weight!==currentWeight||quote.delivery!==deliveryInput.value)return}
    const data=new FormData(form);
    submit.disabled=true;
    const value=(name)=>String(data.get(name)||"").trim();
    const address=(prefix)=>({line1:[value(prefix+"_house_number"),value(prefix+"_line1")].filter(Boolean).join(", "),city:value(prefix+"_city"),state:value(prefix+"_state"),postal_code:value(prefix+"_postal_code"),country:"IN",contact_name:value(prefix+"_contact_name"),contact_phone:value(prefix+"_contact_phone")});
    const payload={sender:address("sender"),receiver:address("receiver"),weight_kg:currentWeight,length_cm:Number(value("length_cm")),width_cm:Number(value("width_cm")),height_cm:Number(value("height_cm")),delivery_type_code:deliveryInput.value,destination_zone:"LOCAL",payment_mode:value("payment_mode"),fragile:data.get("fragile")==="on",priority:data.get("priority")==="on"};
    try{
      const shipment=await api("/api/shipments",{method:"POST",body:JSON.stringify(payload)});
      const online=payload.payment_mode==="RAZORPAY";
      $("#booking-result").innerHTML='<div class="result-card"><h4>Order placed successfully</h4><div>Your tracking ID is <strong>'+esc(shipment.tracking_id)+'</strong>.</div><div>Shipping price: <strong>'+money(shipment.charge,shipment.currency)+'</strong></div><div class="muted">Expected delivery: '+formatDate(shipment.expected_delivery)+'</div><div>Payment mode: '+(online?"Razorpay online":"Cash on delivery")+'</div>'+(online?'<button type="button" class="button primary" id="pay-booking-online">Pay online with Razorpay</button><div id="booking-payment-result"></div>':'<div class="muted">Pay the shipping charge in cash when the parcel is delivered.</div>')+'</div>';
      form.reset();
      quote=null;
      $("#booking-price").textContent="Enter the parcel weight to calculate your price.";
      submit.disabled=true;
      toast("Order placed successfully");
      if(online)$("#pay-booking-online").onclick=()=>startShipmentPayment(shipment.shipment_id,$("#booking-payment-result"));
    }catch(err){
      $("#booking-result").innerHTML='<div class="error-text">'+esc(err.message)+'</div>';
      submit.disabled=false;
    }
  };
}
function tracking(){setTitle("Track shipment");$("#view").innerHTML=`<div class="section-heading"><div><h2>Follow the movement timeline.</h2><p>Enter your tracking ID to follow the shipment’s progress.</p></div></div><form id="track-form" class="search-bar"><input id="track-input" placeholder="e.g. OBUTRK000001" required><button class="button primary">Track shipment</button></form><div id="track-result"></div>`;$("#track-form").onsubmit=async(e)=>{e.preventDefault();try{const t=await api(`/api/track/${encodeURIComponent($("#track-input").value)}`);const a=t.delivery_assessment||{};$("#track-result").innerHTML=`<div class="grid-2"><section class="panel"><div class="panel-header"><h3>${esc(t.tracking_id)}</h3><span class="status-badge ${statusClass(t.status)}">${esc(t.status.replaceAll("_"," "))}</span></div><p class="muted" style="font-size:13px">${esc(t.delivery_type)} delivery · expected ${formatDate(t.expected_delivery)}</p><div class="assessment-callout ${a.is_delayed?"delayed":""}"><strong>${esc((a.state||"ON_SCHEDULE").replaceAll("_"," "))}</strong><span>${a.is_delayed?`${a.days_overdue} day(s) beyond the stored ETA`:`Schedule assessment based on the stored ETA`}</span></div><div class="timeline">${t.history.map(h=>`<div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-body"><strong>${esc(h.status.replaceAll("_"," "))}</strong><p>${esc(h.remarks)}</p><small>${formatDate(h.event_at)} · ${esc(h.location_id)}</small></div></div>`).join("")}</div></section><section class="panel"><h3>Tracking privacy</h3><p class="muted" style="font-size:13px">This view is intentionally limited to shipment movement. Private contacts, OTP values, proof references, and financial details are not shown here.</p></section></div>`}catch(err){$("#track-result").innerHTML=`<div class="panel empty-state"><strong>Tracking ID not found</strong><span>${esc(err.message)}</span></div>`}}}
function taskAddress(address){return [address.line1,address.city,address.state,address.postal_code].filter(Boolean).map(esc).join(", ")}
async function tasks(){
  setTitle(state.account.role==="DELIVERY_AGENT"?"My deliveries":state.account.role==="PICKUP_AGENT"?"My pickups":"My tasks");
  const d=await api("/api/tasks");
  const open=d.tasks.filter(t=>!["COMPLETED","CANCELLED"].includes(t.status_code));
  $("#view").innerHTML=`<div class="section-heading"><div><h2>${state.account.role==="DELIVERY_AGENT"?"My deliveries":state.account.role==="PICKUP_AGENT"?"My pickups":"Assigned work"}</h2><p>${open.length} active task${open.length===1?"":"s"} awaiting action.</p></div></div><div class="task-list">${open.length?open.map(t=>{
    const destination=t.task_type_code==="PICKUP"?t.sender:t.receiver;
    const active=t.status_code==="ASSIGNED"||t.status_code==="IN_PROGRESS";
    return `<article class="task-card"><div><h4>${esc(t.tracking_id||t.shipment_id)} <span class="status-badge ${statusClass(t.shipment_status)}">${esc((t.shipment_status||"").replaceAll("_"," "))}</span></h4><p>${esc(t.task_type_code)} · ${esc(t.status_code)} · due ${formatDate(t.scheduled_reference_at)}</p><p><strong>${t.task_type_code==="PICKUP"?"Pickup":"Destination"}:</strong> ${taskAddress(destination)}</p><p><strong>Contact:</strong> ${esc(destination.contact_name||"—")} · ${esc(destination.contact_phone||"—")}</p>${t.task_type_code==="DELIVERY"&&Number(t.cash_due)>0?`<p><strong>Cash to collect:</strong> ${money(t.cash_due)}</p>`:""}${t.failure_reason?`<p style="color:var(--failed)">${esc(t.failure_reason)}</p>`:""}</div><div class="task-actions">${active&&t.task_type_code==="PICKUP"?`<button class="button primary small" data-task-action="pickup" data-id="${esc(t.assignment_id)}">Complete pickup</button>`:""}${active&&t.task_type_code==="DELIVERY"?`${t.shipment_status==="IN_TRANSIT"?`<button class="button primary small" data-task-action="start" data-id="${esc(t.assignment_id)}">Start delivery</button>`:""}${t.shipment_status==="OUT_FOR_DELIVERY"?`<button class="button ghost small" data-task-action="location" data-shipment-id="${esc(t.shipment_id)}">Share GPS location</button><button class="button secondary small" data-task-action="otp" data-id="${esc(t.assignment_id)}">Request OTP</button><button class="button primary small" data-task-action="deliver" data-id="${esc(t.assignment_id)}">Verify delivery</button>`:""}`:""}${active&&t.task_type_code==="WAREHOUSE"?`<button class="button primary small" data-view="warehouse">Record warehouse receipt</button>`:""}</div></article>`}).join(""):`<div class="panel empty-state"><strong>No assigned tasks</strong><span>New work will appear here when the preceding department completes its step.</span></div>`}</div>`;
  for(const t of open.filter(item=>item.task_type_code==="DELIVERY"&&Number(item.cash_due)>0)){
    const button=[...document.querySelectorAll('[data-task-action="deliver"]')].find(node=>node.dataset.id===t.assignment_id);
    if(button)button.insertAdjacentHTML("beforebegin",`<label class="cash-confirm"><input type="checkbox" data-cash-confirm="${esc(t.assignment_id)}"> I collected ${money(t.cash_due)} in cash</label>`);
  }
}
async function reports(){setTitle("Reports");const [r,d]=await Promise.all([api("/api/reports/summary"),api("/api/reports/delays")]);const entries=Object.entries(r.by_status||{});const max=Math.max(...entries.map(([,v])=>v),1);$("#view").innerHTML=`<div class="section-heading"><div><h2>Shipment health</h2><p>Review shipment performance and delivery trends.</p></div></div><div class="metric-grid"><div class="metric-card blue"><div class="label">Total shipments</div><div class="value">${r.total_shipments}</div></div><div class="metric-card green"><div class="label">Invoice total</div><div class="value" style="font-size:23px">${money(r.invoice_total)}</div></div><div class="metric-card orange"><div class="label">Average delivery</div><div class="value">${r.average_delivery_days??"—"}</div><div class="hint">days for delivered records</div></div><div class="metric-card pink"><div class="label">Delayed now</div><div class="value">${d.total_delayed}</div><div class="hint">past stored ETA</div></div></div><section class="panel"><h3>Shipments by status</h3><div class="bar-list">${entries.map(([key,value])=>`<div class="bar-row"><span>${esc(key.replaceAll("_"," "))}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(4,value/max*100)}%"></div></div><strong>${value}</strong></div>`).join("")}</div></section><section class="panel"><h3>Delayed shipments</h3>${d.shipments.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tracking ID</th><th>Status</th><th>Days overdue</th><th>Expected</th></tr></thead><tbody>${d.shipments.map(s=>`<tr><td>${esc(s.tracking_id)}</td><td>${esc(s.status.replaceAll("_"," "))}</td><td>${s.assessment.days_overdue}</td><td>${formatDate(s.assessment.expected_delivery)}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state"><strong>No delayed shipments</strong><span>All active shipments are within their stored ETA.</span></div>`}</section>`}
async function operations(){
  setTitle("Assignments");
  const [lookups,shipments,taskData]=await Promise.all([api("/api/operations/lookups"),api("/api/shipments"),api("/api/tasks")]);
  const typeForStatus={BOOKED:"PICKUP",CONFIRMED:"PICKUP",PICKED_UP:"WAREHOUSE",IN_TRANSIT:"DELIVERY"};
  const roleForType={PICKUP:"PICKUP_AGENT",WAREHOUSE:"WAREHOUSE_OFFICER",DELIVERY:"DELIVERY_AGENT"};
  const assigned=new Set(taskData.tasks.map(t=>`${t.shipment_id}:${t.task_type_code}`));
  const pending=shipments.filter(s=>typeForStatus[s.status]&&!assigned.has(`${s.shipment_id}:${typeForStatus[s.status]}`));
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Unassigned work</h2><p>New bookings are dispatched automatically. Use this queue to resolve exceptions.</p></div></div>${pending.length?`<section class="panel"><form id="assignment-form" class="form-grid"><div class="field"><label>Shipment<select name="shipment_id" required>${pending.map(s=>`<option value="${esc(s.shipment_id)}">${esc(s.tracking_id)} · ${esc(s.status.replaceAll("_"," "))}</option>`).join("")}</select></label></div><div class="field"><label>Staff member<select name="staff_id" required></select></label></div><div class="field"><label>Task type<input id="assignment-type-label" readonly></label><input type="hidden" name="task_type_code"></div><div class="form-actions" style="grid-column:1/-1"><button class="button primary">Assign task <span>→</span></button></div></form><div id="assignment-result"></div></section>`:`<div class="panel empty-state"><strong>All current shipments have their next task assigned.</strong></div>`}`;
  if(!pending.length)return;
  const form=$("#assignment-form");
  const update=()=>{const shipment=pending.find(s=>s.shipment_id===form.elements.shipment_id.value);const type=typeForStatus[shipment.status];form.elements.task_type_code.value=type;$("#assignment-type-label").value=type.replaceAll("_"," ");form.elements.staff_id.innerHTML=lookups.staff.filter(s=>s.role_code===roleForType[type]).map(s=>`<option value="${esc(s.staff_id)}">${esc(s.employee_id)} · ${esc(s.role_code.replaceAll("_"," "))}</option>`).join("")};
  form.elements.shipment_id.onchange=update;
  update();
  form.onsubmit=async(e)=>{e.preventDefault();const f=new FormData(form);try{const r=await api("/api/assignments",{method:"POST",body:JSON.stringify(Object.fromEntries(f))});await operations();toast(`Assigned ${r.tracking_id}`)}catch(err){$("#assignment-result").innerHTML=`<div class="error-text">${esc(err.message)}</div>`}};
}
async function warehouse(){
  setTitle("Warehouse");
  const [taskData,lookups,rows]=await Promise.all([api("/api/tasks"),api("/api/operations/lookups"),api("/api/warehouse/scans")]);
  const ready=taskData.tasks.filter(t=>t.task_type_code==="WAREHOUSE"&&t.status_code==="ASSIGNED"&&t.shipment_status==="PICKED_UP");
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Warehouse receipts</h2><p>Scanning a picked-up parcel passes it to delivery.</p></div></div>${ready.length?`<section class="panel"><form id="warehouse-form" class="form-grid"><div class="field"><label>Parcel<select name="shipment_id" required>${ready.map(t=>`<option value="${esc(t.shipment_id)}">${esc(t.tracking_id)} · ${esc(t.receiver.city)}</option>`).join("")}</select></label></div><div class="field"><label>Receiving hub<select name="hub_id" required>${lookups.hubs.map(h=>`<option value="${esc(h.hub_id)}">${esc(h.name)} · ${esc(h.city)}</option>`).join("")}</select></label></div><input type="hidden" name="scan_type" value="RECEIVED"><div class="form-actions" style="grid-column:1/-1"><button class="button primary">Confirm receipt <span>→</span></button></div></form><div id="warehouse-result"></div></section>`:`<div class="panel empty-state"><strong>No parcels awaiting receipt</strong><span>Pickup will hand parcels to this queue.</span></div>`}<section class="panel"><h3>Recent scans</h3>${rows.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Shipment</th><th>Hub</th><th>Type</th><th>Time</th></tr></thead><tbody>${rows.slice(0,20).map(r=>`<tr><td>${esc(r.shipment_id)}</td><td>${esc(r.hub_id)}</td><td>${esc(r.scan_type)}</td><td>${formatDate(r.scanned_at)}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state">No scans yet</div>`}</section>`;
  if(!ready.length)return;
  $("#warehouse-form").onsubmit=async(e)=>{e.preventDefault();try{const r=await api("/api/warehouse/scans",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(e.currentTarget)))});await warehouse();toast(`Receipt recorded for ${r.shipment_id}`)}catch(err){$("#warehouse-result").innerHTML=`<div class="error-text">${esc(err.message)}</div>`}};
}
async function finance(){
  setTitle("Finance");
  const [f,detail]=await Promise.all([api("/api/finance/summary"),api("/api/finance/invoices")]);
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Invoices and payments</h2><p>Review charges, cash collection and online payment status.</p></div></div><div class="metric-grid"><div class="metric-card blue"><div class="label">Invoices</div><div class="value">${f.invoices}</div></div><div class="metric-card green"><div class="label">Invoice total</div><div class="value" style="font-size:23px">${money(f.invoice_total)}</div></div><div class="metric-card orange"><div class="label">Recorded payments</div><div class="value">${f.payments}</div></div><div class="metric-card pink"><div class="label">Refunds</div><div class="value">${f.refunds}</div></div></div><section class="panel"><h3>Recent invoices</h3>${detail.invoices.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tracking ID</th><th>Invoice</th><th>Amount</th><th>Mode</th><th>Status</th><th>Cash due</th></tr></thead><tbody>${detail.invoices.map(row=>`<tr><td>${esc(row.tracking_id)}</td><td>${esc(row.invoice_no)}</td><td>${money(row.total,row.currency)}</td><td>${esc(row.payment_mode)}</td><td>${esc(row.payment_status)}</td><td>${money(row.cash_due,row.currency)}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state">No invoices yet</div>`}</section>`;
}
async function notifications(){setTitle("Notifications");const d=await api("/api/notifications");$("#view").innerHTML=`<div class="section-heading"><div><h2>Your notifications</h2><p>Booking and movement updates for your shipments.</p></div></div><div class="notification-list">${d.notifications.length?d.notifications.map(n=>`<article class="notification-card ${n.is_read?"read":"unread"}"><div><strong>${esc(n.type_code.replaceAll("_"," "))}</strong><p>${esc(n.message)}</p><small>${formatDate(n.created_at)} · ${esc(n.channel_code)}</small></div>${n.is_read?`<span class="status-badge status-delivered">Read</span>`:`<button class="button ghost small" data-notification-read="${esc(n.notification_id)}">Mark read</button>`}</article>`).join(""):`<div class="panel empty-state"><strong>No notifications yet</strong><span>Updates will appear after your shipment changes status.</span></div>`}</div>`}
async function complaints(){setTitle("Support & complaints");const d=await api("/api/complaints");const staff=state.account.role!=="CUSTOMER";const ships=staff?[]:await api("/api/shipments");$("#view").innerHTML=`<div class="section-heading"><div><h2>${staff?"Complaint queue":"How can we help?"}</h2><p>${staff?"Review and resolve customer complaints.":"Tell the OptiGo team what needs attention."}</p></div></div>${staff?"":`<form id="complaint-form" class="panel stack-form"><label>Shipment (optional)<select name="shipment_id"><option value="">General support</option>${ships.map(s=>`<option value="${esc(s.shipment_id)}">${esc(s.tracking_id)} · ${esc(s.status)}</option>`).join("")}</select></label><label>Subject<input name="subject" required minlength="3" maxlength="150" placeholder="What went wrong?"></label><label>Description<textarea name="description" required minlength="5" maxlength="4000" rows="4" placeholder="Describe the issue clearly"></textarea></label><button class="button primary" type="submit">Submit complaint <span>→</span></button><div id="complaint-result"></div></form>`}<div class="complaint-list">${d.complaints.length?d.complaints.map(c=>`<article class="panel complaint-card"><div class="panel-header"><h3>${esc(c.subject)}</h3><span class="status-badge status-${esc(c.status_code.toLowerCase().replaceAll("_","-"))}">${esc(c.status_code.replaceAll("_"," "))}</span></div><p>${esc(c.description)}</p><small>${formatDate(c.created_at)}${c.shipment_id?` · shipment ${esc(c.shipment_id)}`:""}</small>${staff?`<div class="complaint-actions"><select data-complaint-status="${esc(c.complaint_id)}"><option ${c.status_code==="OPEN"?"selected":""}>OPEN</option><option ${c.status_code==="IN_PROGRESS"?"selected":""}>IN_PROGRESS</option><option ${c.status_code==="RESOLVED"?"selected":""}>RESOLVED</option><option ${c.status_code==="CLOSED"?"selected":""}>CLOSED</option></select><button class="button ghost small" data-complaint-update="${esc(c.complaint_id)}">Update status</button></div>`:""}</article>`).join(""):`<div class="panel empty-state"><strong>No complaints found</strong><span>Submitted support requests will appear here.</span></div>`}</div>`}
async function routePlanner(){setTitle("Route planner");const sample='[{"stop_id":"S1","label":"Andheri","latitude":19.1197,"longitude":72.8468},{"stop_id":"S2","label":"Powai","latitude":19.1176,"longitude":72.9060}]';$("#view").innerHTML=`<div class="section-heading"><div><h2>Optimize a delivery sequence.</h2><p>Arrange delivery stops in an efficient order.</p></div></div><section class="panel"><form id="route-form" class="form-grid"><div class="field"><label>Start latitude<input name="start_latitude" type="number" step="any" value="19.0760" required></label></div><div class="field"><label>Start longitude<input name="start_longitude" type="number" step="any" value="72.8777" required></label></div><div class="field" style="grid-column:1/-1"><label>Stops JSON<textarea name="stops" rows="7" required>${sample}</textarea></label></div><div class="form-actions" style="grid-column:1/-1"><button class="button primary">Optimize route <span>→</span></button></div></form><div id="route-result"></div></section></div>`;$("#route-form").onsubmit=async(e)=>{e.preventDefault();const f=new FormData(e.currentTarget);try{const stops=JSON.parse(f.get("stops"));const r=await api("/api/routes/optimize",{method:"POST",body:JSON.stringify({start_latitude:Number(f.get("start_latitude")),start_longitude:Number(f.get("start_longitude")),stops})});$("#route-result").innerHTML=`<div class="result-card"><h4>${esc(r.algorithm)}</h4><div>Total distance: <strong>${r.total_distance_km} km</strong></div><ol>${r.stops.map(s=>`<li>${esc(s.label)} · ${s.distance_from_previous_km} km from previous stop</li>`).join("")}</ol></div>`}catch(err){$("#route-result").innerHTML=`<div class="error-text">${esc(err.message)}</div>`}}}
async function payments(){
  setTitle("Payments");
  const [all,options]=await Promise.all([api("/api/shipments"),api("/api/payments/options")]);
  const pending=all.filter(s=>s.payment_mode==="RAZORPAY"&&s.payment_status!=="PAID");
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Online payments</h2><p>Complete payment for a shipment awaiting Razorpay checkout.</p></div></div>${!options.razorpay_available?`<div class="panel empty-state"><strong>Razorpay test checkout is not configured.</strong><span>Cash bookings still work. Online checkout will appear after test keys are configured.</span></div>`:pending.length?`<section class="panel"><form id="payment-form" class="form-grid"><div class="field" style="grid-column:1/-1"><label>Shipment<select name="shipment_id" required>${pending.map(s=>`<option value="${esc(s.shipment_id)}">${esc(s.tracking_id)} · ${money(s.charge,s.currency)}</option>`).join("")}</select></label></div><div class="form-actions" style="grid-column:1/-1"><button class="button primary">Pay with Razorpay <span>→</span></button></div></form><div id="payment-result"></div></section>`:`<div class="panel empty-state"><strong>No online payment is due.</strong></div>`}`;
  if($("#payment-form"))$("#payment-form").onsubmit=(e)=>{e.preventDefault();startShipmentPayment(new FormData(e.currentTarget).get("shipment_id"),$("#payment-result"))};
}
async function navigate(view){if(!state.account||!(ROLE_VIEWS[state.account.role]||[]).includes(view))return;state.view=view;document.querySelector("#sidebar").classList.remove("open");$("#view").innerHTML='<div class="panel empty-state">Loading workspace…</div>';try{if(view==="dashboard")await dashboard();else if(view==="shipments")await shipments();else if(view==="booking")booking();else if(view==="tracking")tracking();else if(view==="notifications")await notifications();else if(view==="complaints")await complaints();else if(view==="tasks")await tasks();else if(view==="operations")await operations();else if(view==="route-planner")await routePlanner();else if(view==="payments")await payments();else if(view==="reports")await reports();else if(view==="warehouse")await warehouse();else if(view==="finance")await finance()}catch(err){toast(err.message,true);$("#view").innerHTML=`<div class="panel empty-state"><strong>Unable to load this view</strong><span>${esc(err.message)}</span></div>`}}
async function handleTaskAction(task){
  const action=task.dataset.taskAction,id=task.dataset.id;
  try{
    if(action==="location"){
      if(!navigator.geolocation)throw new Error("This browser does not provide GPS access");
      navigator.geolocation.getCurrentPosition(async position=>{try{await api(`/api/shipments/${task.dataset.shipmentId}/locations`,{method:"POST",body:JSON.stringify({latitude:position.coords.latitude,longitude:position.coords.longitude,scan_type:"GPS",location_text:"GPS update"})});toast("GPS location shared")}catch(err){toast(err.message,true)}},()=>toast("GPS permission was not granted",true),{enableHighAccuracy:true,timeout:10000});
      return;
    }
    if(action==="start")await api(`/api/assignments/${id}/start-delivery`,{method:"POST"});
    else if(action==="pickup")await api(`/api/assignments/${id}/pickup-complete`,{method:"POST"});
    else if(action==="otp"){
      await api(`/api/assignments/${id}/otp`,{method:"POST"});
      toast("Delivery code sent to the customer's Notifications");
      return;
    }
    else if(action==="deliver"){
      const cashBox=[...document.querySelectorAll("[data-cash-confirm]")].find(node=>node.dataset.cashConfirm===id);
      if(cashBox&&!cashBox.checked)throw new Error("Confirm cash collection before completing delivery");
      const code=prompt("Enter the code from the customer's Notifications");
      if(!code)return;
      await api(`/api/assignments/${id}/deliver`,{method:"POST",body:JSON.stringify({code,remarks:"OTP verified",cash_collected:Boolean(cashBox?.checked)})});
    }
    else return;
    toast("Task updated");
    navigate("tasks");
  }catch(err){toast(err.message,true)}
}
document.addEventListener("click",(e)=>{
  const view=e.target.closest("[data-view]")?.dataset.view;
  if(view){e.preventDefault();navigate(view)}
  const auth=e.target.closest("[data-auth-mode]")?.dataset.authMode;
  if(auth)renderAuth(auth);
  const track=e.target.closest("[data-track]")?.dataset.track;
  if(track){navigate("tracking").then(()=>{if($("#track-input")){ $("#track-input").value=track;$("#track-form").requestSubmit()}})}
  const task=e.target.closest("[data-task-action]");
  if(task)handleTaskAction(task);
});
document.addEventListener("click",(e)=>{const read=e.target.closest("[data-notification-read]");if(read){(async()=>{try{await api(`/api/notifications/${read.dataset.notificationRead}/read`,{method:"POST"});await notifications();toast("Notification marked as read")}catch(err){toast(err.message,true)}})()}const update=e.target.closest("[data-complaint-update]");if(update){const select=document.querySelector(`[data-complaint-status="${CSS.escape(update.dataset.complaintUpdate)}"]`);(async()=>{try{await api(`/api/complaints/${update.dataset.complaintUpdate}`,{method:"PATCH",body:JSON.stringify({status_code:select.value})});await complaints();toast("Complaint status updated")}catch(err){toast(err.message,true)}})()}});
document.addEventListener("submit",async(e)=>{if(e.target.id==="login-form"||e.target.id==="register-form"){e.preventDefault();const f=new FormData(e.target);$("#auth-error").classList.remove("show");try{const path=e.target.id==="login-form"?"/api/auth/login":"/api/auth/register";const a=await api(path,{method:"POST",body:JSON.stringify(Object.fromEntries(f))});if(e.target.id==="register-form"){const email=f.get("email");renderAuth("login");$("#login-form [name=email]").value=email;showAuthMessage("Account Created Successfully. Please sign in to continue.",true);$("#login-form [name=password]").focus();return}state.account=a.account;showShell();toast("Signed in successfully")}catch(err){showAuthError(err.message||"Unable to sign in")}}});
document.addEventListener("submit",async(e)=>{if(e.target.id==="complaint-form"){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target));if(!payload.shipment_id)delete payload.shipment_id;try{await api("/api/complaints",{method:"POST",body:JSON.stringify(payload)});e.target.reset();$("#complaint-result").innerHTML=`<div class="result-card"><h4>Complaint submitted</h4><div>Support will review your request.</div></div>`;await complaints();toast("Complaint submitted")}catch(err){$("#complaint-result").innerHTML=`<div class="error-text">${esc(err.message)}</div>`}}});
function closeLogoutModal(){$("#logout-modal").classList.add("hidden")}
$("#logout-button").onclick=()=>{$("#logout-modal").classList.remove("hidden");$("#cancel-logout").focus()};$("#cancel-logout").onclick=closeLogoutModal;$("#logout-modal").onclick=(e)=>{if(e.target.id==="logout-modal")closeLogoutModal()};$("#confirm-logout").onclick=async()=>{const button=$("#confirm-logout");button.disabled=true;try{await api("/api/auth/logout",{method:"POST"});state.account=null;closeLogoutModal();$("#app-shell").classList.add("hidden");$("#auth-shell").classList.remove("hidden");renderAuth("login")}catch(err){closeLogoutModal();toast(err.message,true)}finally{button.disabled=false}};function closeDeleteModal(){$("#delete-account-modal").classList.add("hidden")}$("#delete-account-button").onclick=()=>{$("#delete-account-modal").classList.remove("hidden");$("#cancel-delete-account").focus()};$("#cancel-delete-account").onclick=closeDeleteModal;$("#delete-account-modal").onclick=(e)=>{if(e.target.id==="delete-account-modal")closeDeleteModal()};$("#confirm-delete-account").onclick=async()=>{const button=$("#confirm-delete-account");button.disabled=true;try{await api("/api/auth/account",{method:"DELETE"});state.account=null;closeDeleteModal();$("#app-shell").classList.add("hidden");$("#auth-shell").classList.remove("hidden");renderAuth("login");showAuthMessage("Account deleted successfully.",true)}catch(err){closeDeleteModal();toast(err.message,true)}finally{button.disabled=false}};$("#menu-button").onclick=()=>{$("#sidebar").classList.toggle("open");$("#sidebar-overlay").classList.toggle("show")};$("#sidebar-overlay").onclick=()=>{$("#sidebar").classList.remove("open");$("#sidebar-overlay").classList.remove("show")};
(async()=>{
  // Opening the site always begins at sign-in, even when this browser held a prior customer cookie.
  try{await api("/api/auth/logout",{method:"POST"})}catch{}
  state.account=null;
  renderAuth("login");
  $("#login-form button[type=submit]").disabled=false;
  $("#auth-switch button").disabled=false;
})();
