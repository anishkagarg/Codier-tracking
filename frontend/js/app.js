const API = window.OPTIGO_API_BASE || "";
const state = { account: null, view: "dashboard", pendingBooking: null, pendingAddress: null, financeSection: "overview", taskNotice: null, complaintData: null };
let customerAddresses = [];
let startupReady = Promise.resolve();
let shipmentDetailOpener = null;
const ROLE_VIEWS = {
  CUSTOMER: ["booking", "tracking", "notifications", "addressbook", "shipments", "complaints", "terms"],
  ADMINISTRATOR: ["dashboard", "shipments", "operations", "tasks", "warehouse", "finance", "staff", "complaints", "tracking", "reports", "route-planner"],
  OPERATIONS_MANAGER: ["dashboard", "shipments", "operations", "tasks", "warehouse", "finance", "complaints", "tracking", "reports", "route-planner"],
  ACCOUNTS_OFFICER: ["finance", "reports"],
  BOOKING_OFFICER: ["shipments", "operations", "tracking"],
  DELIVERY_AGENT: ["tasks", "work-history", "complaints"],
  PICKUP_AGENT: ["tasks", "work-history"],
  SUPPORT_OFFICER: ["complaints", "tracking"],
  TRACKING_OFFICER: ["shipments", "reports"],
  WAREHOUSE_OFFICER: ["warehouse", "tasks", "shipments"]
};
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
function rememberAccount(account){sessionStorage.setItem("optigo-account",JSON.stringify(account));}
function forgetAccount(){sessionStorage.removeItem("optigo-account");}
function cachedAccount(){try{const account=JSON.parse(sessionStorage.getItem("optigo-account")||"null");return account&&account.role&&account.name?account:null;}catch{return null;}}
const money = (value, currency="INR") => `${currency} ${Number(value || 0).toLocaleString("en-IN", {minimumFractionDigits:2, maximumFractionDigits:2})}`;
const pricingSavingsMarkup = (quote) => Number(quote?.discount || 0) > 0
  ? `<small class="price-savings">You save ${money(quote.discount, quote.currency)}${quote.discounts?.length ? ` with ${quote.discounts.map((offer) => esc(offer.label)).join(" + ")}` : ""}</small><small class="price-subtotal">Before offers: ${money(quote.subtotal, quote.currency)}</small>`
  : "";
const statusClass = (s) => `status-${String(s || "").toLowerCase().replaceAll("_", "-")}`;
function toast(message, error=false){const node=$("#toast");node.textContent=message==="Order created successfully"?"Order placed successfully":message;node.style.background=error?"var(--failed)":"var(--text)";node.classList.add("show");setTimeout(()=>node.classList.remove("show"),3300)}
async function api(path, options={}){const headers={"Content-Type":"application/json",...(options.headers||{})};let bookingForm=null;if(path==="/api/shipments"&&options.method==="POST"){bookingForm=$("#booking-form");if(bookingForm){const requestBody=options.body||"";if(!bookingForm.dataset.idempotencyKey||bookingForm.dataset.bookingPayload!==requestBody){bookingForm.dataset.idempotencyKey=crypto.randomUUID();bookingForm.dataset.bookingPayload=requestBody}headers["Idempotency-Key"]=bookingForm.dataset.idempotencyKey}}const response=await fetch(`${API}${path}`,{...options,credentials:"include",headers});let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.detail||"The request could not be completed");if(bookingForm){delete bookingForm.dataset.idempotencyKey;delete bookingForm.dataset.bookingPayload;}return data}
function formatDate(value){return value?new Date(value).toLocaleDateString("en-IN",{day:"2-digit",month:"short",year:"numeric"}):"—"}
function formatDateTime(value){return value?new Date(value).toLocaleString("en-IN",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}):"—"}
function renderAuth(mode="login"){
  const forms={login:"#login-form",register:"#register-form",forgot:"#forgot-request-form",reset:"#forgot-confirm-form"};
  Object.entries(forms).forEach(([name,selector])=>$(selector).classList.toggle("hidden",name!==mode));
  const titles={login:["Sign in to OptiGo","Use your email address and password."],register:["Create your OptiGo account","Set up your account to book and follow shipments."],forgot:["Reset your password","Enter your email address. We’ll send a one-time reset code if an account is active."],reset:["Choose a new password","Enter the six-digit code from your email and create a new password."]};
  $("#auth-title").textContent=titles[mode][0];
  $("#auth-subtitle").textContent=titles[mode][1];
  $("#auth-error").textContent="";
  $("#auth-error").classList.remove("show","success");
  document.querySelectorAll(".auth-tabs [data-auth-mode]").forEach(tab=>tab.classList.toggle("active",tab.dataset.authMode===mode));
  $("#auth-switch").classList.toggle("hidden",mode==="forgot"||mode==="reset");
  $("#auth-switch").innerHTML=mode==="register"?"Already have an account? <button type=\"button\" data-auth-mode=\"login\">Sign in</button>":"New to OptiGo? <button type=\"button\" data-auth-mode=\"register\">Create an account</button>";
}
function showAuthMessage(message,success=false){const node=$("#auth-error");node.textContent=message;node.classList.toggle("success",success);node.classList.add("show")}
function showAuthError(message){showAuthMessage(message,false)}
function openPublicAuth(mode="login"){
  $("#landing-shell").inert=true;
  $("#auth-shell").classList.remove("hidden");
  renderAuth(mode);
  const firstInput=$("#auth-shell form:not(.hidden) input");
  setTimeout(()=>firstInput?.focus({preventScroll:true}),30);
}
function closePublicAuth(){
  $("#auth-shell").classList.add("hidden");
  $("#landing-shell").inert=false;
  $("[data-landing-action=login]")?.focus({preventScroll:true});
}
function scrollToLandingSection(selector, focusSelector){
  const section=$(selector);
  if(!section)return;
  section.scrollIntoView({behavior:"smooth",block:"center"});
  if(focusSelector)setTimeout(()=>$(focusSelector)?.focus({preventScroll:true}),450);
}
function showShell(restoreView=false){
  const a=state.account;
  const allowed=ROLE_VIEWS[a.role]||[];
  if(!allowed.length){showAuthError("This account has no workspace role. Contact an administrator.");return}
  const savedView=sessionStorage.getItem("optigo-view");
  state.view=restoreView&&allowed.includes(savedView)?savedView:allowed[0];
  $("#auth-shell").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
  $("#app-shell").classList.toggle("customer-workspace",a.role==="CUSTOMER");
  $("#sidebar").dataset.role=a.role;
  $("#account-name").textContent=a.name;
  $("#account-role").textContent=a.role.replaceAll("_"," ");
  $("#avatar").textContent=(a.name||"S").slice(0,1).toUpperCase();
  $("#customer-header-name").textContent=a.name;
  $("#customer-rail-name").textContent=a.name;
  $("#customer-avatar").textContent=(a.name||"S").slice(0,1).toUpperCase();
  $("#staff-nav").classList.toggle("hidden",a.role==="CUSTOMER");
  const sectionName={ACCOUNTS_OFFICER:"Accounts",BOOKING_OFFICER:"Booking",DELIVERY_AGENT:"Delivery",PICKUP_AGENT:"Pickup",SUPPORT_OFFICER:"Support",TRACKING_OFFICER:"Tracking",WAREHOUSE_OFFICER:"Warehouse"}[a.role]||"Operations";
  $("#staff-nav .nav-label").textContent=sectionName;
  const taskLabel={DELIVERY_AGENT:"My deliveries",PICKUP_AGENT:"My pickups",WAREHOUSE_OFFICER:"My warehouse tasks",ADMINISTRATOR:"Team tasks",OPERATIONS_MANAGER:"Team tasks"}[a.role]||"My tasks";
  $("#staff-nav [data-view=tasks]").lastChild.textContent=taskLabel;
  document.querySelectorAll("#nav-list [data-view]").forEach(node=>node.classList.toggle("hidden",!allowed.includes(node.dataset.view)));
  if(state.pendingBooking&&a.role==="CUSTOMER"){
    const pending=state.pendingBooking;
    state.pendingBooking=null;
    navigate("booking").then(()=>{
      const form=$("#booking-form");
      if(!form)return;
      ["sender_postal_code","receiver_postal_code","weight_kg","delivery_type_code"].forEach(name=>{if(form.elements[name]&&pending[name])form.elements[name].value=pending[name]});
      form.elements.weight_kg?.dispatchEvent(new Event("input",{bubbles:true}));
    });
  }else navigate(state.view);
}
function setCustomerBookingGuidance(show){
  const rail=$("#customer-services"),guidance=$("#customer-booking-guidance");
  if(!rail||!guidance||state.account?.role!=="CUSTOMER")return;
  rail.classList.toggle("show-booking-guidance",show);
  guidance.classList.toggle("hidden",!show);
}
function setTitle(title){$("#page-title").textContent=title;document.querySelectorAll(".nav-item,.customer-service-link").forEach(n=>{const active=n.dataset.view===state.view;n.classList.toggle("active",active);if(active)n.setAttribute("aria-current","page");else n.removeAttribute("aria-current")})}
function shipmentLink(shipmentId,trackingId,label){const text=trackingId||label||"View shipment";return `<button type="button" class="tracking-link link-button" data-shipment-detail="${esc(shipmentId)}" aria-label="View shipment journey${trackingId?` for ${esc(trackingId)}`:""}">${esc(text)}</button>`}
function wireShipmentLinks(container,items){if(!container)return;const rows=container.querySelectorAll("tbody tr");items.forEach((item,index)=>{const cell=rows[index]?.cells[0];if(!cell||!item.shipment_id)return;cell.innerHTML=shipmentLink(item.shipment_id,item.tracking_id,cell.textContent.trim())})}
function tableRows(shipments){if(!shipments.length)return `<div class="empty-state"><strong>No shipments found</strong><span>When a booking is created it will appear here.</span></div>`;return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Tracking ID</th><th>Status</th><th>Booked</th><th>Expected</th><th>Charge</th></tr></thead><tbody>${shipments.map(s=>`<tr class="shipment-click-row" data-shipment-detail-row="${esc(s.shipment_id)}" tabindex="0" aria-label="Open full tracking details for ${esc(s.tracking_id)}"><td>${shipmentLink(s.shipment_id,s.tracking_id)}</td><td><span class="status-badge ${statusClass(s.status)}">${esc(s.status.replaceAll("_"," "))}</span></td><td>${formatDate(s.booking_date)}</td><td>${formatDate(s.expected_delivery)}</td><td>${money(s.charge,s.currency)}</td></tr>`).join("")}</tbody></table></div>`}
async function addressbook(){setTitle("AddressBook");customerAddresses=await api("/api/addresses");$("#view").innerHTML=`<div class="section-heading"><div><h2>Saved delivery addresses</h2><p>Keep receiver details ready for your next shipment.</p></div></div><div class="addressbook-layout"><form id="addressbook-form" class="panel"><h3>Add an address</h3><div class="form-grid"><div class="field full"><label>Street address<input name="line1" required minlength="2" maxlength="300" autocomplete="street-address"></label></div><div class="field"><label>Contact name<input name="contact_name" required minlength="2" maxlength="120" autocomplete="name"></label></div><div class="field"><label>Phone<input name="contact_phone" type="tel" required minlength="7" maxlength="30" autocomplete="tel"></label></div><div class="field"><label>City<input name="city" required minlength="2" maxlength="100" autocomplete="address-level2"></label></div><div class="field"><label>State<input name="state" required minlength="2" maxlength="100" autocomplete="address-level1"></label></div><div class="field"><label>6-digit PIN code<input name="postal_code" required inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="postal-code"></label></div><input type="hidden" name="country" value="IN"></div><div class="form-actions"><button type="submit" class="button primary">Save address</button></div><div id="addressbook-result" aria-live="polite"></div></form><section class="addressbook-list"><h3>Your saved addresses</h3>${customerAddresses.length?customerAddresses.map((a,index)=>`<article class="addressbook-entry"><div><strong>${esc(a.contact_name)}</strong><p>${esc(a.line1)}, ${esc(a.city)}, ${esc(a.state)} ${esc(a.postal_code)}</p><small>${esc(a.contact_phone)}</small></div><button class="button secondary small" data-use-address="${index}">Use for delivery</button></article>`).join(""):`<div class="panel empty-state"><strong>No saved addresses yet</strong><span>Add a delivery address to reuse it when booking a shipment.</span></div>`}</section></div>`;$("#addressbook-form").onsubmit=async event=>{event.preventDefault();const form=event.currentTarget,button=form.querySelector("button[type=submit]");button.disabled=true;try{await api("/api/addresses",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form)))});await addressbook();toast("Address saved")}catch(err){$("#addressbook-result").innerHTML=`<div class="error-text">${esc(err.message)}</div>`}finally{if(button.isConnected)button.disabled=false}}}
async function dashboard(){setTitle("Overview");const d=await api("/api/dashboard");const m=d.metrics;$("#view").innerHTML=`<div class="section-heading"><div><h2>Good to see you, ${esc(state.account.name.split(" ")[0])}.</h2><p>Here is the latest view of your OptiGo activity.</p></div><button class="button primary ${state.account.role!=="CUSTOMER"?"hidden":""}" data-view="booking">New booking <span>＋</span></button></div><div class="metric-grid"><div class="metric-card blue"><div class="label">Total shipments</div><div class="value">${m.total}</div><div class="hint">All shipments</div></div><div class="metric-card green"><div class="label">Delivered</div><div class="value">${m.delivered}</div><div class="hint">Completed shipments</div></div><div class="metric-card orange"><div class="label">In progress</div><div class="value">${m.in_transit}</div><div class="hint">Moving through network</div></div><div class="metric-card pink"><div class="label">Needs attention</div><div class="value">${m.attention}</div><div class="hint">Failed or unavailable</div></div></div><div class="grid-2"><section class="panel"><div class="panel-header"><h3>Recent shipments</h3><button class="button ghost small" data-view="shipments">View all</button></div>${tableRows(d.recent_shipments)}</section><section class="panel"><h3>Tracking at a glance</h3><p class="muted" style="font-size:13px">Find a shipment by tracking ID and follow its progress.</p><button class="button secondary" data-view="tracking">Track a shipment <span>→</span></button></section></div>${state.account.role==="CUSTOMER"?`<section class="panel"><div class="panel-header"><h3>Terms &amp; regulations</h3><button class="button ghost small" data-view="terms">Read terms</button></div><p class="muted" style="font-size:13px">Review delivery charges, OTP handover, payments, complaint handling and privacy before you book.</p></section>`:""}`}
function terms(){setTitle("Terms & regulations");$("#view").innerHTML=`<div class="section-heading"><div><h2>Customer terms &amp; regulations</h2><p>These terms explain how OptiGo handles bookings, delivery and customer support.</p></div></div><section class="panel"><h3>Before you book</h3><div class="grid-2"><div><h4>Accurate parcel details</h4><p class="muted">Enter a correct address, contact number, weight and parcel dimensions. The shown price is the payable shipping charge; Express delivery adds ₹100 and Priority handling adds ₹100.</p></div><div><h4>Permitted shipments</h4><p class="muted">Use OptiGo only for lawful parcels. Do not send dangerous, prohibited, illegal or restricted items.</p></div><div><h4>Payment</h4><p class="muted">For cash bookings, the recorded shipping charge is payable when the parcel is delivered. Online demo payments do not collect real money.</p></div><div><h4>Delivery and OTP</h4><p class="muted">Share the delivery OTP only when the assigned courier is present with your parcel. OTP verification completes delivery confirmation.</p></div></div></section><section class="panel"><h3>During and after delivery</h3><div class="grid-2"><div><h4>Tracking and updates</h4><p class="muted">Shipment status and recorded locations are provided for your booking. Delivery dates are estimates and can change because of operational conditions.</p></div><div><h4>Complaints and support</h4><p class="muted">Raise a complaint from Support &amp; complaints. The support team can communicate with the responsible department and reply in the complaint record.</p></div><div><h4>Privacy</h4><p class="muted">Your contact, address, payment and delivery-code information is used only to operate your shipment and is not displayed in public tracking.</p></div><div><h4>Your responsibilities</h4><p class="muted">Keep your account details secure, be available at the delivery address, and review the shipment details before confirming a booking.</p></div></div></section><p class="muted">For a specific booking question, use Support &amp; complaints and include the tracking ID.</p>`}
async function shipments(){setTitle(state.account.role==="CUSTOMER"?"Booking history":"Shipments");const subtitle=state.account.role==="TRACKING_OFFICER"?"Search shipments and open any tracking ID to review its full movement history.":"Review the bookings connected to your account and track their progress.";$("#view").innerHTML=`<div class="section-heading"><div><h2>${state.account.role==="CUSTOMER"?"Your booking history":"Operational shipments"}</h2><p>${subtitle}</p></div></div><div class="search-bar"><input id="shipment-search" placeholder="Search by OBU tracking ID"><button class="button primary" id="shipment-search-button">Search</button></div><div id="shipment-results"><div class="empty-state">Loading bookings…</div></div>`;const load=async()=>{const query=$("#shipment-search").value?`?search=${encodeURIComponent($("#shipment-search").value)}`:"";$("#shipment-results").innerHTML=tableRows(await api("/api/shipments"+query))};$("#shipment-search-button").onclick=load;await load()}
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
async function completeDemoPayment(shipmentId, resultNode){
  resultNode.innerHTML='<div class="muted">Processing online payment…</div>';
  try{
    const demo=await api("/api/payments/demo/complete",{method:"POST",body:JSON.stringify({shipment_id:shipmentId})});
    resultNode.innerHTML='<div class="result-card"><h4>Online payment request processed</h4><div>No amount has been collected.</div><div class="muted">Invoice '+esc(demo.invoice_no)+' remains '+esc(demo.payment_status)+'.</div></div>';
  }catch(err){resultNode.innerHTML='<div class="error-text">'+esc(err.message)+'</div>'}
}
function booking(){
  setTitle("New booking");
  $("#view").innerHTML='<form id="booking-form" class="panel" novalidate><p class="callout">Address suggestions send the text you type (such as street, city and state) to external location providers. You can skip suggestions and enter every address field manually.</p><h3>Sender details</h3>'+locationFields("sender","Sender")+'<h3 style="margin-top:28px">Receiver details</h3>'+locationFields("receiver","Receiver")+'<h3 style="margin-top:28px">Parcel details</h3><div class="form-grid three"><div class="field"><label>Weight (kg)<input name="weight_kg" type="number" step="0.001" min="0.001" required></label></div><div class="field"><label>Length (cm)<input name="length_cm" type="number" step="0.01" min="0.01" required></label></div><div class="field"><label>Width (cm)<input name="width_cm" type="number" step="0.01" min="0.01" required></label></div><div class="field"><label>Height (cm)<input name="height_cm" type="number" step="0.01" min="0.01" required></label></div><div class="field"><label>Delivery type<select name="delivery_type_code" required><option value="STANDARD">Standard</option><option value="EXPRESS">Express (+₹100)</option></select></label></div><div class="field" style="display:flex;align-items:end;gap:20px"><label style="display:flex;align-items:center;gap:8px"><input name="fragile" type="checkbox" style="width:auto"> Fragile</label><label style="display:flex;align-items:center;gap:8px"><input name="priority" type="checkbox" style="width:auto"> Priority handling (+₹100)</label></div></div><section class="price-summary" aria-live="polite"><strong>Exact shipping charge</strong><div id="booking-price">Enter parcel details to calculate the exact charge.</div></section><fieldset class="payment-choice"><legend>Payment mode</legend><label><input type="radio" name="payment_mode" value="CASH" required> Cash on delivery</label><label><input type="radio" name="payment_mode" value="DEMO" required> Simulated online payment (no money collected)</label></fieldset><div class="form-actions"><button class="button primary" type="submit">Place order <span>→</span></button></div><div id="booking-result" aria-live="polite"></div></form>';
  wireLocationFields("sender");
  wireLocationFields("receiver");
  const form=$("#booking-form");
  if(state.pendingAddress){const address=state.pendingAddress;state.pendingAddress=null;form.elements.receiver_line1.value=address.line1||"";form.elements.receiver_contact_name.value=address.contact_name||"";form.elements.receiver_contact_phone.value=address.contact_phone||"";form.elements.receiver_city.value=address.city||"";form.elements.receiver_state.value=address.state||"";form.elements.receiver_postal_code.value=address.postal_code||""}
  const submit=form.querySelector('button[type="submit"]');
  const weightInput=form.elements.weight_kg;
  const deliverySelect=form.elements.delivery_type_code;
  const parcelInputs=["weight_kg","length_cm","width_cm","height_cm"].map(name=>form.elements[name]);
  const priorityInput=form.elements.priority;
  const selectedDelivery=()=>deliverySelect.value;
  const quoteInput=()=>({weight:Number(weightInput.value),length:Number(form.elements.length_cm.value),width:Number(form.elements.width_cm.value),height:Number(form.elements.height_cm.value),delivery:selectedDelivery(),priority:priorityInput.checked});
  const sameQuote=(left,right)=>left&&Object.keys(right).every(key=>left[key]===right[key]);
  api("/api/payments/options").then(options=>{
    const demo=form.querySelector('[name="payment_mode"][value="DEMO"]');
    if(!demo)return;
    demo.disabled=!options.demo_online_available;
    demo.parentElement.lastChild.textContent = options.demo_online_available ? " Simulated online payment (no money collected)" : " Online payment unavailable; use cash";
  }).catch(()=>{
    const demo=form.querySelector('[name="payment_mode"][value="DEMO"]');
    if(demo)demo.disabled=true;
  });
  let quote=null;
  let quoteSequence=0;
  let quoteTimer;
  async function refreshQuote(){
    const details=quoteInput();
    const sequence=++quoteSequence;
    if([details.weight,details.length,details.width,details.height].some(value=>!Number.isFinite(value)||value<=0)){quote=null;$("#booking-price").textContent="Enter weight, length, width and height to calculate your price.";return}
    $("#booking-price").textContent="Updating price…";
    try{
      const result=await api("/api/pricing/quote",{method:"POST",body:JSON.stringify({weight_kg:details.weight,length_cm:details.length,width_cm:details.width,height_cm:details.height,delivery_type_code:details.delivery,destination_zone:"LOCAL",priority:details.priority})});
      if(sequence!==quoteSequence)return;
      quote={...details,amount:result.amount,subtotal:result.subtotal??result.amount,discount:result.discount??"0.00",discounts:result.discounts||[],serviceUpgradeFee:result.service_upgrade_fee??"0.00",currency:result.currency};
      const upgrades=[];
      if(details.delivery==="EXPRESS")upgrades.push("Express +₹100");
      if(details.priority)upgrades.push("Priority +₹100");
      const upgradeSummary=upgrades.length?'<small>'+esc(upgrades.join(" · "))+"</small>":"";
      $("#booking-price").innerHTML='<strong>'+money(result.amount,result.currency)+'</strong><small>Exact payable charge for '+esc(details.delivery.toLowerCase().replaceAll("_"," "))+" delivery.</small>"+upgradeSummary+pricingSavingsMarkup(quote);
    }catch(err){
      if(sequence!==quoteSequence)return;
      quote=null;
      $("#booking-price").textContent="Price unavailable: "+err.message;
    }
  }
  const scheduleQuote=()=>{clearTimeout(quoteTimer);quoteTimer=setTimeout(refreshQuote,250)};
  parcelInputs.forEach(input=>input.addEventListener("input",scheduleQuote));
  deliverySelect.addEventListener("change",scheduleQuote);
  priorityInput.addEventListener("change",scheduleQuote);
  form.onsubmit=async(event)=>{
    event.preventDefault();
    if(!form.checkValidity()){
      $("#booking-result").innerHTML='<div class="error-text">Credentials are empty. You can\'t place an order.</div>';
      form.querySelector(":invalid")?.focus();
      return;
    }
    const currentQuote=quoteInput();
    const currentWeight=currentQuote.weight;
    const delivery=currentQuote.delivery;
    if(!sameQuote(quote,currentQuote)){await refreshQuote();if(!sameQuote(quote,currentQuote)){$("#booking-result").innerHTML='<div class="error-text">Unable to calculate the shipping price. Please try again.</div>';return}}
    const data=new FormData(form);
    submit.disabled=true;
    const value=(name)=>String(data.get(name)||"").trim();
    const address=(prefix)=>({line1:[value(prefix+"_house_number"),value(prefix+"_line1")].filter(Boolean).join(", "),city:value(prefix+"_city"),state:value(prefix+"_state"),postal_code:value(prefix+"_postal_code"),country:"IN",contact_name:value(prefix+"_contact_name"),contact_phone:value(prefix+"_contact_phone")});
    const payload={sender:address("sender"),receiver:address("receiver"),weight_kg:currentWeight,length_cm:Number(value("length_cm")),width_cm:Number(value("width_cm")),height_cm:Number(value("height_cm")),delivery_type_code:delivery,destination_zone:"LOCAL",payment_mode:value("payment_mode"),fragile:data.get("fragile")==="on",priority:data.get("priority")==="on"};
    try{
      const shipment=await api("/api/shipments",{method:"POST",body:JSON.stringify(payload)});
      const demo=payload.payment_mode==="DEMO";
      $("#booking-result").innerHTML='<div class="result-card"><h4>Order placed successfully</h4><div>Your tracking ID is <strong>'+esc(shipment.tracking_id)+'</strong>.</div><div>Shipping price: <strong>'+money(shipment.charge,shipment.currency)+'</strong></div>'+pricingSavingsMarkup(quote)+'<div class="muted">Expected delivery: '+formatDate(shipment.expected_delivery)+'</div><div>Payment mode: '+(demo?"Simulated online payment":"Cash on delivery")+'</div>'+(demo?'<p class="muted">Demo only: no money is collected, transferred or recorded.</p><button type="button" class="button primary" id="complete-demo-payment">Run simulated checkout</button><div id="booking-payment-result"></div>':'<div class="muted">Pay the shipping charge in cash when the parcel is delivered.</div>')+'</div>';
      form.reset();
      quote=null;
      $("#booking-price").textContent="Enter weight, length, width and height to calculate your price.";
      submit.disabled=false;
      toast("Order placed successfully");
      if(demo)$("#complete-demo-payment").onclick=()=>completeDemoPayment(shipment.shipment_id,$("#booking-payment-result"));
    }catch(err){
      $("#booking-result").innerHTML='<div class="error-text">'+esc(err.message)+'</div>';
      submit.disabled=false;
    }
  };
}
function trackingResultMarkup(t, publicView=false){
  const a=t.delivery_assessment||{};
  const latest=t.latest_location;
  const latestLocation=latest
    ? `<div class="latest-location"><strong>Latest live location</strong><span>${Number(latest.latitude).toFixed(5)}, ${Number(latest.longitude).toFixed(5)}</span><small>GPS update recorded ${formatDate(latest.recorded_at)}</small><a href="https://www.openstreetmap.org/?mlat=${encodeURIComponent(latest.latitude)}&mlon=${encodeURIComponent(latest.longitude)}#map=15/${encodeURIComponent(latest.latitude)}/${encodeURIComponent(latest.longitude)}" target="_blank" rel="noopener">View on map ↗</a></div>`
    : `<div class="latest-location unavailable"><strong>Latest recorded hand-off</strong><span>${esc(t.history.at(-1)?.remarks||"Shipment booked")}</span><small>A live GPS update has not been shared yet.</small></div>`;
  return `<div class="${publicView?"public-tracking-grid":"grid-2"}"><section class="panel tracking-status-card"><div class="panel-header"><h3>${esc(t.tracking_id)}</h3><span class="status-badge ${statusClass(t.status)}">${esc(t.status.replaceAll("_"," "))}</span></div><p class="muted" style="font-size:13px">${esc(t.delivery_type)} delivery · expected ${formatDate(t.expected_delivery)}</p>${latestLocation}<div class="assessment-callout ${a.is_delayed?"delayed":""}"><strong>${esc((a.state||"ON_SCHEDULE").replaceAll("_"," "))}</strong><span>${a.is_delayed?`${a.days_overdue} day(s) beyond the stored delivery date`:`On the current delivery schedule`}</span></div><div class="timeline">${t.history.map(h=>`<div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-body"><strong>${esc(h.status.replaceAll("_"," "))}</strong><p>${esc(h.remarks)}</p><small>${formatDate(h.event_at)} · ${esc(h.location_id)}</small></div></div>`).join("")}</div></section><section class="panel tracking-privacy-card"><h3>Tracking privacy</h3><p class="muted" style="font-size:13px">Only shipment movement is shown. Contact details, payment information, delivery codes and proof references remain private.</p></section></div>`;
}
function shipmentJourneyMarkup(t){
  const area=address=>[address?.city,address?.state,address?.postal_code].filter(Boolean).join(", ")||"Address area not recorded";
  const fullAddress=address=>[address?.line1,address?.city,address?.state,address?.postal_code,address?.country].filter(Boolean).join(", ")||area(address);
  const events=(t.movement_events||[]).slice().sort((left,right)=>Date.parse(left.event_at)-Date.parse(right.event_at));
  const timeline=events.length?`<div class="timeline">${events.map(event=>{const gps=event.kind==="GPS"&&Number.isFinite(Number(event.latitude))&&Number.isFinite(Number(event.longitude));const label=event.kind==="STATUS"?(event.status||"Shipment update").replaceAll("_"," "):event.kind==="GPS"?"Courier GPS update":"Location scan";const endpoint=event.address_role==="sender"?t.sender:event.address_role==="receiver"?t.receiver:null;const location=gps?`${Number(event.latitude).toFixed(5)}, ${Number(event.longitude).toFixed(5)}`:endpoint?fullAddress(endpoint):event.location_text||"Location not recorded";const mapLink=gps?`<a class="shipment-movement-map" href="https://www.openstreetmap.org/?mlat=${encodeURIComponent(event.latitude)}&mlon=${encodeURIComponent(event.longitude)}#map=15/${encodeURIComponent(event.latitude)}/${encodeURIComponent(event.longitude)}" target="_blank" rel="noopener">View recorded point on map ↗</a>`:"";return `<div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-body"><strong>${esc(label)}</strong><p>${esc(event.remarks||location)}</p><small>${formatDate(event.event_at)} · ${esc(location)}${event.scan_type?` · ${esc(event.scan_type.replaceAll("_"," "))}`:""}</small>${mapLink}</div></div>`}).join("")}</div>`:`<div class="empty-state"><strong>No movement events recorded yet</strong><span>The booking will appear here as its pickup, warehouse and delivery scans are recorded.</span></div>`;
  const lost=["LOST","MISSING"].includes((t.status||"").toUpperCase());
  return `<div class="shipment-detail-summary"><span class="status-badge ${statusClass(t.status)}">${esc((t.status||"UNKNOWN").replaceAll("_"," "))}</span><span>${esc(t.delivery_type_code||"Standard")} delivery</span><span>Expected ${formatDate(t.expected_delivery)}</span></div>${lost?`<div class="shipment-lost-notice" role="status"><strong>This shipment is marked as lost.</strong><p>All recorded movement events are listed below. Unrecorded movements cannot be recovered by the tracking screen.</p></div>`:""}<section class="shipment-movements"><h3>Movement history · ${events.length} recorded event${events.length===1?"":"s"}</h3>${timeline}</section>`;
}
async function openShipmentDetails(shipmentId,opener){
  const dialog=$("#shipment-detail-dialog"),content=$("#shipment-detail-content");
  if(!dialog||!shipmentId)return;
  shipmentDetailOpener=opener||document.activeElement;
  $("#shipment-detail-close").onclick=()=>dialog.close();
  dialog.onclose=()=>{if(shipmentDetailOpener?.isConnected)shipmentDetailOpener.focus();shipmentDetailOpener=null};
  $("#shipment-detail-title").textContent="Shipment details";
  content.innerHTML='<div class="empty-state">Loading recorded shipment history…</div>';
  dialog.showModal();
  try{const detail=await api(`/api/shipments/${encodeURIComponent(shipmentId)}/tracking`);$("#shipment-detail-title").textContent=`Journey · ${detail.tracking_id}`;content.innerHTML=shipmentJourneyMarkup(detail)}
  catch(error){content.innerHTML=`<div class="shipment-detail-error" role="alert"><strong>Shipment history could not be loaded.</strong><p>${esc(error.message)}</p></div>`}
}
function tracking(){
  setTitle("Track shipment");
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Follow the movement timeline.</h2><p>Enter a tracking ID to review status changes, warehouse hand-offs and every recorded GPS update.</p></div></div><form id="track-form" class="search-bar"><input id="track-input" placeholder="e.g. OBUTRK000001" required><button class="button primary">Track shipment</button></form><div id="track-result"></div>`;
  $("#track-form").onsubmit=async event=>{event.preventDefault();const trackingId=$("#track-input").value.trim().toUpperCase();$("#track-input").value=trackingId;const result=$("#track-result");result.innerHTML='<div class="panel empty-state">Loading recorded shipment journey…</div>';try{const shipment=await api(`/api/shipments/tracking/${encodeURIComponent(trackingId)}`);result.innerHTML=shipmentJourneyMarkup(shipment)}catch(error){result.innerHTML=`<div class="panel empty-state"><strong>Tracking ID not found</strong><span>${esc(error.message)}</span></div>`}};
}
function taskAddress(address){return [address.line1,address.city,address.state,address.postal_code].filter(Boolean).map(esc).join(", ")}
function pickupTaskCard(task,{pending=false}={}){
  const statusClassName=task.status_code==="COMPLETED"?"status-delivered":task.status_code==="FAILED"?"status-failed":"status-booked";
  const result=pending?`<button class="button primary small" data-task-action="pickup" data-id="${esc(task.assignment_id)}">Complete pickup</button>`:`<span class="status-badge ${statusClassName}">${esc(task.status_code.replaceAll("_"," "))}</span>`;
  return `<article class="task-card"><div><h4>${shipmentLink(task.shipment_id,task.tracking_id)} <span class="status-badge ${statusClass(task.shipment_status)}">${esc((task.shipment_status||"").replaceAll("_"," "))}</span></h4><p><strong>Pickup from:</strong> ${taskAddress(task.sender)}</p><p><strong>Contact:</strong> ${esc(task.sender.contact_name||"—")} · ${esc(task.sender.contact_phone||"—")}</p><p>${pending?`Scheduled ${formatDate(task.scheduled_reference_at)}`:`Completed ${formatDateTime(task.completed_at)}`}</p></div><div class="task-actions">${result}</div></article>`;
}
async function tasks(){
  setTitle(state.account.role==="DELIVERY_AGENT"?"My deliveries":state.account.role==="PICKUP_AGENT"?"My pickups":"My tasks");
  const [d,complaintQueue]=await Promise.all([api("/api/tasks"),state.account.role==="DELIVERY_AGENT"?api("/api/complaints"):Promise.resolve(null)]);
  if(state.account.role==="PICKUP_AGENT"){
    const pickups=d.tasks.filter(task=>task.task_type_code==="PICKUP");
    const pending=pickups.filter(task=>["ASSIGNED","IN_PROGRESS"].includes(task.status_code));
    const completed=pickups.filter(task=>task.status_code==="COMPLETED");
    const resolved=pickups.filter(task=>["COMPLETED","FAILED"].includes(task.status_code)).length;
    $("#view").innerHTML=`<div class="section-heading"><div><h2>My pickups</h2><p>Your assigned queue and completed pickups.</p></div></div><div class="metric-grid pickup-metrics"><div class="metric-card orange"><div class="label">Pending pickups</div><div class="value">${pending.length}</div><div class="hint">Assigned and awaiting completion</div></div><div class="metric-card green"><div class="label">Completed pickups</div><div class="value">${completed.length}</div><div class="hint">Recorded under your account</div></div><div class="metric-card blue"><div class="label">Work done</div><div class="value">${resolved}</div><div class="hint">Completed or failed pickup actions</div></div></div><section class="pickup-work-section"><div class="section-heading"><div><h2>Pending pickups</h2><p>Complete a pickup after collecting the parcel from the sender.</p></div></div><div class="task-list">${pending.length?pending.map(task=>pickupTaskCard(task,{pending:true})).join(""):`<div class="panel empty-state"><strong>No pending pickups</strong><span>New pickups assigned to you will appear here.</span></div>`}</div></section><section class="pickup-work-section"><div class="section-heading"><div><h2>Completed pickups</h2><p>Pickups you have successfully completed.</p></div></div><div class="task-list">${completed.length?completed.map(task=>pickupTaskCard(task)).join(""):`<div class="panel empty-state"><strong>No completed pickups yet</strong><span>Completed pickup records will remain available here.</span></div>`}</div></section>`;
    return;
  }
  const open=d.tasks.filter(t=>!["COMPLETED","CANCELLED"].includes(t.status_code));
  const activeComplaints=complaintQueue?.complaints.filter(c=>!["RESOLVED","CLOSED"].includes(c.status_code))||[];
  const deliveryComplaintAlert=activeComplaints.length?`<section class="panel task-page-feedback" role="status"><strong>Complaint needs your action</strong><p>${activeComplaints.length} customer complaint${activeComplaints.length===1?"":"s"} is assigned to your delivery work. Reply to the customer and update the case before ${formatDateTime(activeComplaints[0].due_at)}.</p><button class="button secondary small" type="button" data-view="complaints">Open complaint${activeComplaints.length===1?"":"s"}</button></section>`:"";
  $("#view").innerHTML=`<div class="section-heading"><div><h2>${state.account.role==="DELIVERY_AGENT"?"My deliveries":state.account.role==="PICKUP_AGENT"?"My pickups":"Assigned work"}</h2><p>${open.length} active task${open.length===1?"":"s"} awaiting action.</p></div></div>${deliveryComplaintAlert}<div class="task-list">${open.length?open.map(t=>{
    const destination=t.task_type_code==="PICKUP"?t.sender:t.receiver;
    const active=t.status_code==="ASSIGNED"||t.status_code==="IN_PROGRESS";
    const isAssignedDeliveryAgent=state.account.role==="DELIVERY_AGENT"&&t.staff_id===state.account.staff_id;
    const canStartDelivery=isAssignedDeliveryAgent||["ADMINISTRATOR","OPERATIONS_MANAGER"].includes(state.account.role);
    return `<article class="task-card"><div><h4>${esc(t.tracking_id||t.shipment_id)} <span class="status-badge ${statusClass(t.shipment_status)}">${esc((t.shipment_status||"").replaceAll("_"," "))}</span></h4><p>${esc(t.task_type_code)} · ${esc(t.status_code)} · due ${formatDate(t.scheduled_reference_at)}</p><p><strong>${t.task_type_code==="PICKUP"?"Pickup":"Destination"}:</strong> ${taskAddress(destination)}</p><p><strong>Contact:</strong> ${esc(destination.contact_name||"—")} · ${esc(destination.contact_phone||"—")}</p>${t.task_type_code==="DELIVERY"&&Number(t.cash_due)>0?`<p><strong>Cash to collect:</strong> ${money(t.cash_due)}</p>`:""}${t.failure_reason?`<p style="color:var(--failed)">${esc(t.failure_reason)}</p>`:""}</div><div class="task-actions">${active&&t.task_type_code==="PICKUP"?`<button class="button primary small" data-task-action="pickup" data-id="${esc(t.assignment_id)}">Complete pickup</button>`:""}${active&&t.task_type_code==="DELIVERY"?`${canStartDelivery&&t.shipment_status==="IN_TRANSIT"?`<button class="button primary small" data-task-action="start" data-id="${esc(t.assignment_id)}">Start delivery</button>`:""}${isAssignedDeliveryAgent&&t.shipment_status==="OUT_FOR_DELIVERY"?`<button class="button ghost small" data-task-action="location" data-id="${esc(t.assignment_id)}" data-shipment-id="${esc(t.shipment_id)}">Share GPS location</button><button class="button secondary small" data-task-action="otp" data-id="${esc(t.assignment_id)}">Request OTP</button><button class="button primary small" data-task-action="deliver" data-id="${esc(t.assignment_id)}">Verify delivery</button>`:""}${t.shipment_status==="OUT_FOR_DELIVERY"&&!isAssignedDeliveryAgent?`<span class="task-owner-note">The assigned delivery agent completes this task.</span>`:""}`:""}${active&&t.task_type_code==="WAREHOUSE"?`<button class="button primary small" data-view="warehouse">Record warehouse receipt</button>`:""}</div></article>`}).join(""):`<div class="panel empty-state"><strong>No assigned tasks</strong><span>New work will appear here when the preceding department completes its step.</span></div>`}</div>`;
  Array.from(document.querySelectorAll(".task-card h4")).forEach((heading,index)=>{const task=open[index];if(!task?.shipment_id)return;const link=document.createElement("button");link.type="button";link.className="tracking-link link-button";link.dataset.shipmentDetail=task.shipment_id;link.setAttribute("aria-label",`View shipment journey for ${task.tracking_id}`);link.textContent=task.tracking_id||task.shipment_id;heading.firstChild?.remove();heading.insertBefore(link,heading.firstChild);heading.insertBefore(document.createTextNode(" "),link.nextSibling)});
  if(state.taskNotice){
    const notice=state.taskNotice;
    state.taskNotice=null;
    $("#view .section-heading")?.insertAdjacentHTML("afterend",`<div class="task-page-feedback" role="status">${esc(notice)}</div>`);
  }
  for(const t of open.filter(item=>item.task_type_code==="DELIVERY"&&Number(item.cash_due)>0)){
    const button=[...document.querySelectorAll('[data-task-action="deliver"]')].find(node=>node.dataset.id===t.assignment_id);
    if(button)button.insertAdjacentHTML("beforebegin",`<label class="cash-confirm"><input type="checkbox" data-cash-confirm="${esc(t.assignment_id)}"> I collected ${money(t.cash_due)} in cash</label>`);
  }
  open.forEach((t,index)=>{
    const actions=document.querySelectorAll(".task-card")[index]?.querySelector(".task-actions");
    if(!actions||!t.assignment_id)return;
    const verify=actions.querySelector('[data-task-action="deliver"]');
    if(verify)verify.insertAdjacentHTML("afterend",`<div class="delivery-otp-entry hidden" data-delivery-otp-entry="${esc(t.assignment_id)}"><label for="delivery-otp-${esc(t.assignment_id)}">Delivery OTP</label><div><input id="delivery-otp-${esc(t.assignment_id)}" data-delivery-otp-input="${esc(t.assignment_id)}" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="Enter 6-digit OTP"><button class="button primary small" type="button" data-task-action="deliver-confirm" data-id="${esc(t.assignment_id)}">Confirm delivery</button></div></div>`);
    actions.insertAdjacentHTML("beforeend",`<div class="task-feedback" data-task-feedback="${esc(t.assignment_id)}" role="status" aria-live="polite"></div>`);
  });
}
async function workHistory(){
  const isDelivery=state.account.role==="DELIVERY_AGENT";
  const taskType=isDelivery?"DELIVERY":"PICKUP";
  const activityName=isDelivery?"delivery":"pickup";
  const completionDetail=isDelivery?"Delivery completed and recorded":"Pickup completed and recorded";
  setTitle("Working history");
  const d=await api("/api/tasks");
  const activity=d.tasks.filter(task=>task.task_type_code===taskType&&["COMPLETED","FAILED"].includes(task.status_code)).sort((a,b)=>new Date(b.completed_at||b.assigned_at)-new Date(a.completed_at||a.assigned_at));
  const rows=activity.map(task=>`<tr><td>${formatDateTime(task.completed_at||task.assigned_at)}</td><td>${shipmentLink(task.shipment_id,task.tracking_id)}</td><td><span class="status-badge ${task.status_code==="COMPLETED"?"status-delivered":"status-failed"}">${esc(task.status_code.replaceAll("_"," "))}</span></td><td>${esc(task.status_code==="FAILED"?task.failure_reason||`${taskType[0]}${taskType.slice(1).toLowerCase()} could not be completed`:completionDetail)}</td></tr>`).join("");
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Working history</h2><p>Completed and unsuccessful ${activityName} actions recorded under your account.</p></div></div>${activity.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Date and time</th><th>Tracking ID</th><th>Outcome</th><th>Details</th></tr></thead><tbody>${rows}</tbody></table></div>`:`<div class="panel empty-state"><strong>No ${activityName} activity recorded</strong><span>Completed and unsuccessful ${activityName} actions will appear here.</span></div>`}`;
}
async function reports(){
  setTitle("Reports");
  const [r,d]=await Promise.all([api("/api/reports/summary"),api("/api/reports/delays")]);
  const entries=Object.entries(r.by_status||{}),max=Math.max(...entries.map(([,value])=>value),1);
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Shipment health</h2><p>Review shipment performance and delivery trends.</p></div></div><div class="metric-grid"><div class="metric-card blue"><div class="label">Total shipments</div><div class="value">${r.total_shipments}</div></div><div class="metric-card green"><div class="label">Invoice total</div><div class="value" style="font-size:23px">${money(r.invoice_total)}</div></div><div class="metric-card orange"><div class="label">Average delivery</div><div class="value">${r.average_delivery_days??"—"}</div><div class="hint">days for delivered records</div></div><div class="metric-card pink"><div class="label">Delayed now</div><div class="value">${d.total_delayed}</div><div class="hint">past stored ETA</div></div></div><section class="panel"><h3>Shipments by status</h3><div class="bar-list">${entries.map(([key,value])=>`<div class="bar-row"><span>${esc(key.replaceAll("_"," "))}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(4,value/max*100)}%"></div></div><strong>${value}</strong></div>`).join("")}</div></section><section class="panel"><h3>Delayed shipments</h3>${d.shipments.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tracking ID</th><th>Status</th><th>Days overdue</th><th>Expected</th></tr></thead><tbody>${d.shipments.map(s=>`<tr><td>${shipmentLink(s.shipment_id,s.tracking_id)}</td><td>${esc(s.status.replaceAll("_"," "))}</td><td>${s.assessment.days_overdue}</td><td>${formatDate(s.assessment.expected_delivery)}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state"><strong>No delayed shipments</strong><span>All active shipments are within their stored ETA.</span></div>`}</section>`;
}
async function operations(confirmation=null){
  setTitle("Assignments");
  const [lookups,shipments,taskData]=await Promise.all([api("/api/operations/lookups"),api("/api/shipments"),api("/api/tasks")]);
  const typeForStatus={BOOKED:"PICKUP",CONFIRMED:"PICKUP",PICKED_UP:"WAREHOUSE",IN_TRANSIT:"DELIVERY"};
  const roleForType={PICKUP:"PICKUP_AGENT",WAREHOUSE:"WAREHOUSE_OFFICER",DELIVERY:"DELIVERY_AGENT"};
  const assigned=new Set(taskData.tasks.map(t=>`${t.shipment_id}:${t.task_type_code}`));
  const pending=shipments.filter(s=>typeForStatus[s.status]&&!assigned.has(`${s.shipment_id}:${typeForStatus[s.status]}`));
  const confirmationMarkup=confirmation?`<section class="assignment-confirmation" role="status"><strong>Okay, the task has been assigned.</strong><span>${confirmation.existing?"This shipment already had the required task, so no duplicate was created.":`The task for ${esc(confirmation.trackingId)} is now assigned.`}</span></section>`:"";
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Unassigned work</h2><p>New bookings are dispatched automatically. Use this queue to resolve exceptions.</p></div></div>${confirmationMarkup}${pending.length?`<section class="panel"><form id="assignment-form" class="form-grid"><div class="field"><label>Shipment<select name="shipment_id" required>${pending.map(s=>`<option value="${esc(s.shipment_id)}">${esc(s.tracking_id)} · ${esc(s.status.replaceAll("_"," "))}</option>`).join("")}</select></label></div><div class="field"><label>Staff member<select name="staff_id" required></select></label></div><div class="field"><label>Task type<input id="assignment-type-label" readonly></label><input type="hidden" name="task_type_code"></div><div class="form-actions" style="grid-column:1/-1"><button class="button primary">Assign task <span>→</span></button></div></form><div id="assignment-result"></div></section>`:`<div class="panel empty-state"><strong>All current shipments have their next task assigned.</strong></div>`}`;
  if(!pending.length)return;
  const form=$("#assignment-form");
  const update=()=>{const shipment=pending.find(s=>s.shipment_id===form.elements.shipment_id.value);const type=typeForStatus[shipment.status];form.elements.task_type_code.value=type;$("#assignment-type-label").value=type.replaceAll("_"," ");form.elements.staff_id.innerHTML=lookups.staff.filter(s=>s.role_code===roleForType[type]).map(s=>`<option value="${esc(s.staff_id)}">${esc(s.employee_id)} · ${esc(s.role_code.replaceAll("_"," "))}</option>`).join("")};
  form.elements.shipment_id.onchange=update;
  update();
  const preview=document.createElement("button");preview.type="button";preview.className="button ghost small shipment-preview-button";form.elements.shipment_id.closest(".field").append(preview);
  const syncPreview=()=>{const shipment=pending.find(item=>item.shipment_id===form.elements.shipment_id.value);if(!shipment)return;preview.dataset.shipmentDetail=shipment.shipment_id;preview.textContent=`View ${shipment.tracking_id} journey`};form.elements.shipment_id.addEventListener("change",syncPreview);syncPreview();
  form.onsubmit=async(e)=>{e.preventDefault();const button=form.querySelector("button[type=submit]");if(button.disabled)return;button.disabled=true;const f=new FormData(form),payload=Object.fromEntries(f),shipment=pending.find(item=>item.shipment_id===payload.shipment_id);try{const r=await api("/api/assignments",{method:"POST",body:JSON.stringify(payload)});await operations({trackingId:r.tracking_id||shipment?.tracking_id,existing:false})}catch(err){if(err.message.includes("already has an assignment")){await operations({trackingId:shipment?.tracking_id,existing:true});return}$("#assignment-result").innerHTML=`<div class="error-text">${esc(err.message)}</div>`;button.disabled=false}};
}
async function warehouse(confirmation=null){
  setTitle("Warehouse");
  const [taskData,lookups,rows,inTransit]=await Promise.all([api("/api/tasks"),api("/api/operations/lookups"),api("/api/warehouse/scans"),api("/api/warehouse/in-transit")]);
  const ready=taskData.tasks.filter(t=>t.task_type_code==="WAREHOUSE"&&t.status_code==="ASSIGNED"&&t.shipment_status==="PICKED_UP");
  const hubNames=Object.fromEntries(lookups.hubs.map(h=>[h.hub_id,`${h.name} · ${h.city}`]));
  const trackingByShipment=Object.fromEntries(taskData.tasks.map(t=>[t.shipment_id,t.tracking_id]));
  const readyOptions=ready.map(t=>`<option value="${esc(t.shipment_id)}">${esc(t.tracking_id)} · ${esc(t.receiver.city)}</option>`).join("");
  const transitOptions=inTransit.map(t=>`<option value="${esc(t.shipment_id)}">${esc(t.tracking_id)} · ${esc(t.receiver.city||"destination unavailable")}</option>`).join("");
  const hubOptions=lookups.hubs.map(h=>`<option value="${esc(h.hub_id)}">${esc(h.name)} · ${esc(h.city)}</option>`).join("");
  const receiptConfirmation=confirmation?.kind==="first"?`<div class="warehouse-confirmation" role="status"><strong>First hub receipt recorded.</strong><span>${esc(confirmation.trackingId)} is now in transit and a delivery task has been created.</span></div>`:"";
  const transferConfirmation=confirmation?.kind==="transfer"?`<div class="warehouse-confirmation" role="status"><strong>Hub arrival recorded.</strong><span>${esc(confirmation.trackingId)} has been added to the shipment journey at the selected hub.</span></div>`:"";
  const firstReceipt=ready.length?`<section class="panel"><div class="panel-header"><h3>First warehouse receipt</h3><span class="status-badge status-picked-up">${ready.length} READY</span></div><p class="muted">Receive a picked-up parcel at its first hub. This opens the delivery task.</p>${receiptConfirmation}<form id="warehouse-form" class="form-grid warehouse-receipt-form"><div class="field"><label>Parcel<select name="shipment_id" required>${readyOptions}</select></label></div><div class="field"><label>Receiving hub<select name="hub_id" required>${hubOptions}</select></label></div><input type="hidden" name="scan_type" value="RECEIVED"><div class="form-actions" style="grid-column:1/-1"><button class="button primary">Confirm first receipt <span>→</span></button></div></form><div id="warehouse-result" aria-live="polite"></div></section>`:`<section class="panel empty-state warehouse-empty"><strong>No parcels are awaiting their first hub receipt</strong><span>A parcel appears here after its assigned pickup agent completes pickup.</span></section>`;
  const transferForm=inTransit.length?`<section class="panel"><div class="panel-header"><h3>Record an inter-hub arrival</h3><span class="status-badge status-in-transit">${inTransit.length} IN TRANSIT</span></div><p class="muted">Each confirmed receiving scan adds a real stop to the shipment journey. Choose the hub where the parcel has arrived.</p>${transferConfirmation}<form id="warehouse-transfer-form" class="form-grid warehouse-receipt-form"><div class="field"><label>Parcel<select name="shipment_id" required>${transitOptions}</select></label></div><div class="field"><label>Arrived at hub<select name="hub_id" required>${hubOptions}</select></label></div><input type="hidden" name="scan_type" value="RECEIVED"><div class="form-actions" style="grid-column:1/-1"><button class="button secondary">Record hub arrival</button></div></form><div id="warehouse-transfer-result" aria-live="polite"></div></section>`:`<section class="panel empty-state warehouse-empty"><strong>No inter-hub arrivals are awaiting a scan</strong><span>Parcels currently moving between hubs will appear here.</span></section>`;
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Warehouse receipts</h2><p>Record first receipts and every confirmed inter-hub arrival for a complete shipment route.</p></div></div><div class="metric-grid warehouse-metrics"><div class="metric-card orange"><div class="label">Ready for first receipt</div><div class="value">${ready.length}</div><div class="hint">Picked-up parcels assigned to this queue</div></div><div class="metric-card blue"><div class="label">In transit</div><div class="value">${inTransit.length}</div><div class="hint">Parcels that may need another hub scan</div></div><div class="metric-card green"><div class="label">Recent recorded scans</div><div class="value">${rows.length}</div><div class="hint">Warehouse arrivals on record</div></div></div><div class="warehouse-scan-sections">${firstReceipt}${transferForm}</div><section class="panel"><h3>Recent warehouse receipts</h3>${rows.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tracking ID</th><th>Receiving hub</th><th>Scan</th><th>Recorded</th></tr></thead><tbody>${rows.slice(0,20).map(r=>`<tr><td>${esc(trackingByShipment[r.shipment_id]||r.tracking_id||r.shipment_id)}</td><td>${esc(hubNames[r.hub_id]||r.hub_id)}</td><td>${esc(r.scan_type)}</td><td>${formatDateTime(r.scanned_at)}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state"><strong>No warehouse receipts recorded yet</strong><span>The first confirmed receipt will appear here.</span></div>`}</section>`;
  const warehouseTables=Array.from(document.querySelectorAll("#view .data-table"));if(rows.length)wireShipmentLinks(warehouseTables[0]?.closest(".table-wrap"),rows.slice(0,20).map(row=>({...row,tracking_id:trackingByShipment[row.shipment_id]||row.tracking_id})));
  for(const formId of ["warehouse-form","warehouse-transfer-form"]){const form=$("#"+formId);if(!form)continue;form.onsubmit=async event=>{event.preventDefault();const result=$(formId==="warehouse-form"?"#warehouse-result":"#warehouse-transfer-result"),button=form.querySelector("button[type=submit]");if(button.disabled)return;button.disabled=true;try{const r=await api("/api/warehouse/scans",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form)))});await warehouse({kind:formId==="warehouse-form"?"first":"transfer",trackingId:r.tracking_id})}catch(error){result.innerHTML=`<div class="error-text">${esc(error.message)}</div>`;button.disabled=false}}}
}
async function staffAdmin(){
  setTitle("Staff accounts");
  const data=await api("/api/admin/staff");
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Staff access</h2><p>Create role-specific logins and set temporary OptiGo passwords for department accounts.</p></div></div><div class="grid-2 staff-admin-grid"><section class="panel"><h3>Create staff account</h3><form id="staff-form" class="stack-form"><label>Full name<input name="name" required minlength="2" maxlength="120"></label><label>Work email<input name="email" type="email" required maxlength="254"></label><div class="form-grid"><div class="field"><label>Phone<input name="phone" required minlength="7" maxlength="30"></label></div><div class="field"><label>Employee ID<input value="Generated automatically" readonly aria-label="Employee ID is generated automatically"></label></div><div class="field"><label>Department<select name="department_code" required>${data.departments.map(d=>`<option value="${esc(d.code)}">${esc(d.name)}</option>`).join("")}</select></label></div><div class="field"><label>Role<select name="role_code" required>${data.roles.map(r=>`<option value="${esc(r.code)}" ${r.code==="WAREHOUSE_OFFICER"?"selected":""}>${esc(r.name)}</option>`).join("")}</select></label></div></div><label>Temporary password<input name="password" type="password" required minlength="8" maxlength="200" autocomplete="new-password"></label><button class="button primary" type="submit">Create staff login <span>→</span></button><div id="staff-result"></div></form></section><section class="panel"><h3>Department logins</h3><p class="staff-password-guidance">Reset an OptiGo sign-in password here; this does not change the person’s Gmail password. The administrator account can also reset its own password after signing in.</p>${data.staff.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Employee</th><th>Role</th><th>Department</th><th>Status</th><th>Password</th></tr></thead><tbody>${data.staff.map(s=>`<tr><td><strong>${esc(s.name)}</strong><br><small>${esc(s.employee_id)} · ${esc(s.email)}</small></td><td>${esc(s.role_code.replaceAll("_"," "))}</td><td>${esc(s.department_code.replaceAll("_"," "))}</td><td><span class="status-badge ${s.active?"status-delivered":"status-cancelled"}">${s.active?"ACTIVE":"INACTIVE"}</span></td><td>${s.active?`<button type="button" class="button secondary small" data-staff-password-reset="${esc(s.staff_id)}" data-staff-name="${esc(s.name)}" data-staff-email="${esc(s.email)}" data-staff-role="${esc(s.role_code.replaceAll("_"," "))}">Set password</button>`:`<span class="muted">Unavailable</span>`}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state">No staff accounts found</div>`}</section></div><dialog class="staff-password-dialog" id="staff-password-dialog" aria-labelledby="staff-password-title"><form id="staff-password-form"><h2 id="staff-password-title">Set an OptiGo password</h2><p id="staff-password-account" class="muted"></p><p class="staff-password-warning">Saving immediately replaces this account’s current website password. It does not change a Gmail password. Share the new password with the account holder through a private channel.</p><label for="staff-new-password">New temporary password</label><input id="staff-new-password" name="password" type="password" minlength="12" maxlength="200" autocomplete="new-password" required><div id="staff-password-result" class="staff-password-result" aria-live="polite"></div><div class="staff-password-actions"><button type="button" class="button ghost small" id="staff-generate-password">Generate secure password</button><button type="button" class="button secondary small hidden" id="staff-copy-password">Copy password</button><span class="staff-password-action-spacer"></span><button type="button" class="button ghost small" id="staff-password-cancel">Cancel</button><button type="submit" class="button primary small" id="staff-password-submit">Save password</button></div></form></dialog>`;
  $("#staff-form").onsubmit=async(e)=>{
    e.preventDefault();
    const form=e.currentTarget,button=form.querySelector('button[type="submit"]');
    button.disabled=true;
    try{
      const created=await api("/api/admin/staff",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form)))});
      $("#staff-result").innerHTML=`<div class="result-card"><h4>Staff login created</h4><div>${esc(created.name)} can now sign in as ${esc(created.role_code.replaceAll("_"," "))} using ${esc(created.email)}.</div></div>`;
      toast("Staff login created");
      await staffAdmin();
    }catch(err){$("#staff-result").innerHTML=`<div class="error-text">${esc(err.message)}</div>`;button.disabled=false}
  };
  const resetDialog=$("#staff-password-dialog"),resetForm=$("#staff-password-form"),resetInput=$("#staff-new-password"),resetSubmit=$("#staff-password-submit"),resetStatus=$("#staff-password-result");
  resetForm.onsubmit=async event=>{
    event.preventDefault();
    if(!resetForm.reportValidity())return;
    resetSubmit.disabled=true;
    resetStatus.textContent="Saving the new password…";
    try{
      const account=await api(`/api/admin/staff/${encodeURIComponent(resetForm.dataset.staffId)}/password`,{method:"POST",body:JSON.stringify({password:resetInput.value})});
      resetStatus.textContent=`Password updated for ${account.name} (${account.email}). Copy it now; it will be cleared when this dialog closes.`;
      resetInput.type="text";
      resetInput.readOnly=true;
      resetSubmit.classList.add("hidden");
      $("#staff-generate-password").classList.add("hidden");
      $("#staff-copy-password").classList.remove("hidden");
      const resetButton=document.querySelector(`[data-staff-password-reset="${CSS.escape(account.staff_id)}"]`);
      if(resetButton){resetButton.disabled=true;resetButton.textContent="Password set"}
      toast("OptiGo password updated");
    }catch(err){resetStatus.innerHTML=`<span class="error-text">${esc(err.message)}</span>`;resetSubmit.disabled=false}
  };
  $("#staff-generate-password").onclick=()=>{resetInput.value=`${crypto.randomUUID().replaceAll("-","")}aB9!`;resetInput.focus();resetStatus.textContent="Generated locally. Save it to apply this password."};
  $("#staff-copy-password").onclick=async()=>{try{await navigator.clipboard.writeText(resetInput.value);toast("Temporary password copied")}catch{resetInput.focus();resetInput.select();toast("Copy is blocked by this browser; the password is selected")}};
  $("#staff-password-cancel").onclick=()=>resetDialog.close();
  resetDialog.addEventListener("click",event=>{if(event.target===resetDialog)resetDialog.close()});
  resetDialog.addEventListener("close",()=>{resetForm.reset();delete resetForm.dataset.staffId;resetInput.type="password";resetInput.readOnly=false;resetSubmit.classList.remove("hidden");resetSubmit.disabled=false;$("#staff-generate-password").classList.remove("hidden");$("#staff-copy-password").classList.add("hidden");resetStatus.textContent=""});
}
async function finance(filters={}){
  setTitle("Finance");
  const localToday=new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
  const periodStart=filters.periodStart||`${localToday.slice(0,7)}-01`;
  const periodEnd=filters.periodEnd||localToday;
  const asOf=filters.asOf||localToday;
  const query=new URLSearchParams({period_start:periodStart,period_end:periodEnd,as_of:asOf});
  const d=await api(`/api/finance/workbench?${query}`);
  const canRecord=["ACCOUNTS_OFFICER","ADMINISTRATOR"].includes(state.account.role);
  const options=(items)=>items.map(code=>`<option value="${esc(code)}">${esc(code.replaceAll("_"," ").toLowerCase().replace(/\b\w/g,c=>c.toUpperCase()))}</option>`).join("");
  const transactionRows=d.recent_transactions.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Date</th><th>Entry</th><th>Category / description</th><th>Reference</th><th>Amount</th></tr></thead><tbody>${d.recent_transactions.map(row=>`<tr><td>${formatDate(row.entry_date)}</td><td><span class="status-badge ${row.entry_type==="EXPENSE"?"status-cancelled":"status-delivered"}">${row.entry_type.replaceAll("_"," ")}</span></td><td><strong>${esc(row.category.replaceAll("_"," "))}</strong><br><small>${esc(row.description)}</small></td><td>${esc(row.reference_no||"—")}</td><td>${money(row.amount)}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state"><strong>No manual income or cost entries yet</strong><span>Record genuine expenses and non-shipping income as they occur.</span></div>`;
  const positionRows=rows=>rows.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Account</th><th>Category</th><th>Balance date</th><th>Balance</th></tr></thead><tbody>${rows.map(row=>`<tr><td><strong>${esc(row.account_name)}</strong>${row.notes?`<br><small>${esc(row.notes)}</small>`:""}</td><td>${esc(row.category.replaceAll("_"," "))}</td><td>${formatDate(row.balance_date)}</td><td>${money(row.amount)}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state"><strong>No balances recorded</strong><span>Add the latest verified account balances below.</span></div>`;
  const unpaidRows=d.unpaid_invoices.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tracking ID</th><th>Invoice</th><th>Issued</th><th>Mode</th><th>Status</th><th>Amount due</th></tr></thead><tbody>${d.unpaid_invoices.map(row=>`<tr><td>${shipmentLink(row.shipment_id,row.tracking_id)}</td><td>${esc(row.invoice_no)}</td><td>${formatDate(row.issued_at)}</td><td>${esc(row.payment_mode)}</td><td><span class="status-badge status-delayed">${esc(row.payment_status)}</span></td><td>${money(row.total,row.currency)}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state"><strong>No unpaid invoices</strong><span>All recorded invoices are marked paid.</span></div>`;
  const codRows=d.open_cod_settlements.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tracking ID</th><th>Collected</th><th>Reference</th><th>State</th></tr></thead><tbody>${d.open_cod_settlements.map(row=>`<tr><td>${shipmentLink(row.shipment_id,row.tracking_id)}</td><td>${money(row.amount)}</td><td>${esc(row.reference)}</td><td><span class="status-badge status-delayed">${esc(row.status)}</span></td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state"><strong>No COD settlements are awaiting review</strong></div>`;
  const refundRows=d.refund_review_queue.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tracking ID</th><th>Amount</th><th>Reason</th><th>Reference</th><th>Status</th></tr></thead><tbody>${d.refund_review_queue.map(row=>`<tr><td>${shipmentLink(row.shipment_id,row.tracking_id)}</td><td>${money(row.amount)}</td><td>${esc(row.reason)}</td><td>${esc(row.reference)}</td><td><span class="status-badge status-delayed">${esc(row.status)}</span></td></tr>`).join("")}</tbody></table></div>`:`<div class="empty-state"><strong>No refunds need review</strong><span>Verify any refund in its payment provider before recording it as completed.</span></div>`;
  const categoryData=d.categories;
  const transactionForm=canRecord?`<section class="panel"><h3>Record income or operating cost</h3><p class="muted finance-form-note">Use receipts, payroll records or other source documents. Entries cannot be edited or deleted; use references to prevent duplicates.</p><form id="finance-transaction-form" class="stack-form"><label>Entry type<select name="entry_type"><option value="EXPENSE">Operating expense</option><option value="OTHER_INCOME">Other income</option></select></label><label>Category<select name="category">${options(categoryData.transactions.EXPENSE)}</select></label><div class="form-grid"><label>Amount (INR)<input name="amount" type="number" min="0.01" step="0.01" required></label><label>Date<input name="entry_date" type="date" value="${localToday}" required></label></div><label>Description<input name="description" minlength="3" maxlength="500" placeholder="e.g. Fuel for delivery van" required></label><label>Receipt / reference (optional)<input name="reference_no" maxlength="100" placeholder="Invoice number or receipt ID"></label><button class="button primary" type="submit">Save entry</button><div id="finance-transaction-result" aria-live="polite"></div></form></section>`:"";
  const positionForm=canRecord?`<section class="panel"><h3>Record an asset or liability balance</h3><p class="muted finance-form-note">Enter a verified current balance. Later snapshots update the account for later dates while preserving its history.</p><form id="finance-position-form" class="stack-form"><label>Account type<select name="position_type"><option value="ASSET">Asset</option><option value="LIABILITY">Liability</option></select></label><label>Category<select name="category">${options(categoryData.positions.ASSET)}</select></label><label>Account name<input name="account_name" minlength="2" maxlength="120" placeholder="e.g. Main bank account" required></label><div class="form-grid"><label>Balance (INR)<input name="amount" type="number" min="0" step="0.01" required></label><label>Balance as of<input name="balance_date" type="date" value="${localToday}" required></label></div><label>Supporting note (optional)<input name="notes" maxlength="500" placeholder="Bank statement date, supplier statement, etc."></label><button class="button primary" type="submit">Save balance snapshot</button><div id="finance-position-result" aria-live="polite"></div></form></section>`:"";
  const result=Number(d.pnl.net_profit_loss);
  const resultLabel=result<0?"Operational loss":"Operational profit";
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Accounts operations</h2><p>Reconcile courier collections, keep costs current and review the company’s operating position.</p></div></div><div class="callout finance-truth-note"><strong>Operational statement, not audited accounts.</strong> Revenue is shipping revenue billed in OptiGo, not necessarily cash received. Profit/loss includes only recorded income, completed refunds and recorded expenses. The balance sheet includes only balances entered here; verify them against bank, cash, supplier and tax records before relying on it.</div><form id="finance-period-form" class="panel finance-period-form"><label>Profit &amp; loss from<input name="period_start" type="date" value="${esc(d.period_start)}" required></label><label>Through<input name="period_end" type="date" value="${esc(d.period_end)}" required></label><label>Balance sheet as of<input name="as_of" type="date" value="${esc(d.as_of)}" required></label><button class="button secondary" type="submit">Update statements</button></form><div class="metric-grid finance-metrics"><div class="metric-card blue"><div class="label">Shipping revenue billed</div><div class="value">${money(d.pnl.shipping_revenue_billed)}</div><div class="hint">${d.pnl.invoice_count} invoice(s) in period</div></div><div class="metric-card green"><div class="label">Other income</div><div class="value">${money(d.pnl.other_income)}</div><div class="hint">Manually recorded</div></div><div class="metric-card orange"><div class="label">Operating expenses</div><div class="value">${money(d.pnl.operating_expenses)}</div><div class="hint">Manually recorded</div></div><div class="metric-card pink"><div class="label">${resultLabel}</div><div class="value ${result<0?"finance-loss":"finance-profit"}">${money(d.pnl.net_profit_loss)}</div><div class="hint">After ${money(d.pnl.completed_refunds)} completed refunds</div></div></div><div class="finance-statement-grid"><section class="panel"><h3>Profit &amp; loss · ${formatDate(d.period_start)} – ${formatDate(d.period_end)}</h3><div class="finance-statement-lines"><div><span>Shipping revenue billed</span><strong>${money(d.pnl.shipping_revenue_billed)}</strong></div><div><span>Other income</span><strong>${money(d.pnl.other_income)}</strong></div><div class="finance-deduction"><span>Completed refunds</span><strong>− ${money(d.pnl.completed_refunds)}</strong></div><div class="finance-deduction"><span>Recorded operating expenses</span><strong>− ${money(d.pnl.operating_expenses)}</strong></div><div class="finance-statement-total"><span>Operational net ${result<0?"loss":"profit"}</span><strong>${money(d.pnl.net_profit_loss)}</strong></div></div>${d.pnl.other_currency_invoice_count?`<p class="error-text">${d.pnl.other_currency_invoice_count} invoice(s) in currencies other than INR are excluded.</p>`:""}</section><section class="panel"><h3>Balance sheet · ${formatDate(d.as_of)}</h3><div class="finance-statement-lines"><div><span>Total assets entered</span><strong>${money(d.balance_sheet.assets)}</strong></div><div><span>Total liabilities entered</span><strong>${money(d.balance_sheet.liabilities)}</strong></div><div><span>Balancing equity¹</span><strong>${money(d.balance_sheet.equity)}</strong></div><div class="finance-statement-total"><span>Liabilities + equity</span><strong>${money(Number(d.balance_sheet.liabilities)+Number(d.balance_sheet.equity))}</strong></div></div><p class="muted finance-form-note">¹ Calculated as assets minus liabilities. The accounting equation is assets = liabilities + equity. This residual is not a separately verified capital account.</p></section></div><div class="finance-accounts-grid"><section class="panel"><div class="panel-header"><h3>Assets</h3><strong>${money(d.balance_sheet.assets)}</strong></div>${positionRows(d.balance_sheet.asset_positions)}</section><section class="panel"><div class="panel-header"><h3>Liabilities</h3><strong>${money(d.balance_sheet.liabilities)}</strong></div>${positionRows(d.balance_sheet.liability_positions)}</section></div><div class="finance-entry-grid">${transactionForm}${positionForm}</div><section class="panel"><h3>Collection follow-up</h3><div class="finance-queue-summary"><div><strong>${d.collections.unpaid_invoice_count}</strong><span>unpaid invoice(s) · ${money(d.collections.unpaid_invoice_total)}</span></div><div><strong>${d.collections.open_cod_settlement_count}</strong><span>COD settlement(s) pending · ${money(d.collections.open_cod_settlement_total)}</span></div><div><strong>${d.collections.pending_refund_count}</strong><span>refund(s) needing status review</span></div><div><strong>${d.collections.paid_invoice_count}</strong><span>paid invoice(s) this period · ${money(d.collections.paid_invoice_total)}</span></div></div></section><section class="panel"><h3>Invoices awaiting payment</h3>${unpaidRows}</section><section class="panel"><h3>COD settlements awaiting review</h3><p class="muted finance-form-note">Verify deposits in bank records; this screen does not mark transfers complete.</p>${codRows}</section><section class="panel"><h3>Refunds awaiting status review</h3><p class="muted finance-form-note">Verify refunds with the payment provider. OptiGo does not initiate transfers.</p>${refundRows}</section><section class="panel"><h3>Recent income and expense entries</h3>${transactionRows}</section>`;
  const financeView=$("#view");
  const [,truthNote,periodForm,metrics,statementGrid,accountsGrid,entryGrid,collectionSummary,unpaidPanel,codPanel,refundPanel,transactionHistory]=Array.from(financeView.children);
  const [pnlStatement,balanceSummary]=Array.from(statementGrid.children);
  const [assetAccounts,liabilityAccounts]=Array.from(accountsGrid.children);
  const [transactionEntry,positionEntry]=Array.from(entryGrid.children);
  statementGrid.remove();accountsGrid.remove();entryGrid.remove();
  financeView.insertAdjacentHTML("beforeend",`<nav class="finance-section-tabs" role="tablist" aria-label="Accounts workspace"><button class="finance-section-tab" type="button" role="tab" id="finance-tab-overview" data-finance-tab="overview" aria-controls="finance-panel-overview">Overview</button><button class="finance-section-tab" type="button" role="tab" id="finance-tab-collections" data-finance-tab="collections" aria-controls="finance-panel-collections">Collections</button><button class="finance-section-tab" type="button" role="tab" id="finance-tab-transactions" data-finance-tab="transactions" aria-controls="finance-panel-transactions">Transactions</button><button class="finance-section-tab" type="button" role="tab" id="finance-tab-balance" data-finance-tab="balance" aria-controls="finance-panel-balance">Balance sheet</button></nav><section class="finance-section" id="finance-panel-overview" data-finance-panel="overview" role="tabpanel" aria-labelledby="finance-tab-overview" tabindex="0"></section><section class="finance-section" id="finance-panel-collections" data-finance-panel="collections" role="tabpanel" aria-labelledby="finance-tab-collections" tabindex="0"></section><section class="finance-section" id="finance-panel-transactions" data-finance-panel="transactions" role="tabpanel" aria-labelledby="finance-tab-transactions" tabindex="0"></section><section class="finance-section" id="finance-panel-balance" data-finance-panel="balance" role="tabpanel" aria-labelledby="finance-tab-balance" tabindex="0"></section>`);
  const financePanels=Object.fromEntries(Array.from(financeView.querySelectorAll("[data-finance-panel]")).map(panel=>[panel.dataset.financePanel,panel]));
  financePanels.overview.append(truthNote,periodForm,metrics,pnlStatement);
  financePanels.collections.append(collectionSummary,unpaidPanel,codPanel,refundPanel);
  wireShipmentLinks(unpaidPanel,d.unpaid_invoices);wireShipmentLinks(codPanel,d.open_cod_settlements);wireShipmentLinks(refundPanel,d.refund_review_queue);
  if(transactionEntry)financePanels.transactions.append(transactionEntry);financePanels.transactions.append(transactionHistory);
  const balanceTop=document.createElement("div");balanceTop.className="finance-balance-grid";if(positionEntry)balanceTop.append(positionEntry);else balanceTop.classList.add("finance-balance-readonly");balanceTop.append(balanceSummary);
  const balanceAccounts=document.createElement("div");balanceAccounts.className="finance-accounts-grid";balanceAccounts.append(assetAccounts,liabilityAccounts);
  financePanels.balance.append(balanceTop,balanceAccounts);
  const sectionIntros={overview:["Financial overview","Review the selected period’s operating result."],collections:["Collections and follow-up","Review unpaid invoices, cash-on-delivery settlements and refund status."],transactions:["Income and operating costs","Record verified entries and review the transaction register."],balance:["Assets and liabilities","Review recorded balances and the accounting equation."]};
  for(const [section,[title,description]] of Object.entries(sectionIntros))financePanels[section].insertAdjacentHTML("afterbegin",`<div class="finance-section-intro"><h3>${title}</h3><p>${description}</p></div>`);
  const collectionQueues=[[unpaidPanel,d.collections.unpaid_invoice_count],[codPanel,d.collections.open_cod_settlement_count],[refundPanel,d.collections.pending_refund_count]];
  let openedQueue=false;
  for(const [panel,itemCount] of collectionQueues){const heading=panel.querySelector("h3");const label=heading.textContent;const content=document.createElement("div");content.className="finance-queue-content";for(const child of Array.from(panel.children))if(child!==heading)content.append(child);const details=document.createElement("details");details.className="finance-queue-accordion";details.open=itemCount>0&&!openedQueue;if(details.open)openedQueue=true;const summary=document.createElement("summary");summary.innerHTML=`<span>${esc(label)}</span><span class="finance-queue-count">${itemCount?`${itemCount} open`:"Clear"}</span>`;details.append(summary,content);panel.replaceChildren(details);panel.classList.add("finance-queue-panel")}
  const financeTabs=Array.from(financeView.querySelectorAll("[data-finance-tab]"));
  const activateFinanceSection=(section,focus=false)=>{if(!financePanels[section])section="overview";state.financeSection=section;for(const tab of financeTabs){const active=tab.dataset.financeTab===section;tab.setAttribute("aria-selected",String(active));tab.tabIndex=active?0:-1;if(active&&focus)tab.focus()}for(const [name,panel] of Object.entries(financePanels))panel.classList.toggle("active",name===section)};
  for(const tab of financeTabs){tab.addEventListener("click",()=>activateFinanceSection(tab.dataset.financeTab));tab.addEventListener("keydown",event=>{const index=financeTabs.indexOf(tab);let next=null;if(event.key==="ArrowRight")next=financeTabs[(index+1)%financeTabs.length];else if(event.key==="ArrowLeft")next=financeTabs[(index+financeTabs.length-1)%financeTabs.length];else if(event.key==="Home")next=financeTabs[0];else if(event.key==="End")next=financeTabs[financeTabs.length-1];if(next){event.preventDefault();activateFinanceSection(next.dataset.financeTab,true)}})}
  activateFinanceSection(state.financeSection);
  const transactionNode=$("#finance-transaction-form");
  if(transactionNode){const category=transactionNode.elements.category;transactionNode.elements.entry_type.onchange=()=>{category.innerHTML=options(categoryData.transactions[transactionNode.elements.entry_type.value])};transactionNode.onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;const values=new FormData(form);const button=form.querySelector("button[type=submit]");button.disabled=true;try{await api("/api/finance/transactions",{method:"POST",body:JSON.stringify({entry_type:values.get("entry_type"),category:values.get("category"),amount:values.get("amount"),entry_date:values.get("entry_date"),description:values.get("description"),reference_no:values.get("reference_no")||null})});toast("Finance entry saved");await finance({periodStart,periodEnd,asOf,section:state.financeSection})}catch(error){$("#finance-transaction-result").innerHTML=`<span class="error-text">${esc(error.message)}</span>`;button.disabled=false}}}
  const positionNode=$("#finance-position-form");
  if(positionNode){const category=positionNode.elements.category;positionNode.elements.position_type.onchange=()=>{category.innerHTML=options(categoryData.positions[positionNode.elements.position_type.value])};positionNode.onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;const values=new FormData(form);const button=form.querySelector("button[type=submit]");button.disabled=true;try{await api("/api/finance/positions",{method:"POST",body:JSON.stringify({position_type:values.get("position_type"),category:values.get("category"),account_name:values.get("account_name"),amount:values.get("amount"),balance_date:values.get("balance_date"),notes:values.get("notes")})});toast("Balance snapshot saved");await finance({periodStart,periodEnd,asOf,section:state.financeSection})}catch(error){$("#finance-position-result").innerHTML=`<span class="error-text">${esc(error.message)}</span>`;button.disabled=false}}}
  $("#finance-period-form").onsubmit=event=>{event.preventDefault();const values=new FormData(event.currentTarget);finance({periodStart:values.get("period_start"),periodEnd:values.get("period_end"),asOf:values.get("as_of"),section:state.financeSection}).catch(error=>toast(error.message,true))};
}
async function notifications(){setTitle("Notifications");const d=await api("/api/notifications");$("#view").innerHTML=`<div class="section-heading"><div><h2>Your notifications</h2><p>Booking and movement updates, including active delivery codes for your shipments.</p></div></div><div class="notification-list">${d.notifications.length?d.notifications.map(n=>`<article class="notification-card ${n.is_read?"read":"unread"} ${n.type_code==="OTP"?"notification-otp":""}"><div><strong>${esc(n.type_code==="OTP"?"Delivery verification code":n.type_code.replaceAll("_"," "))}</strong>${n.tracking_id?`<p>${shipmentLink(n.shipment_id,n.tracking_id,"View shipment")}</p>`:""}<p>${esc(n.message)}</p>${n.delivery_code?`<div class="notification-delivery-code"><span>Active delivery code</span><strong>${esc(n.delivery_code)}</strong><small>Expires ${formatDateTime(n.expires_at)} · Share with the courier only when your parcel arrives.</small></div>`:n.type_code==="OTP"?`<small>This code has expired or has already been used. A new code can be requested by the delivery courier.</small>`:""}<small>${formatDate(n.created_at)} · ${esc(n.channel_code)}</small></div>${n.is_read?`<span class="status-badge status-delivered">Read</span>`:`<button class="button ghost small" data-notification-read="${esc(n.notification_id)}">Mark read</button>`}</article>`).join(""):`<div class="panel empty-state"><strong>No notifications yet</strong><span>Shipment and delivery updates will appear here.</span></div>`}</div>`}
async function complaints(){
  setTitle("Support & complaints");
  const d=await api("/api/complaints");
  state.complaintData=d;
  const staff=state.account.role!=="CUSTOMER",ships=staff?[]:await api("/api/shipments");
  $("#view").innerHTML=`<div class="section-heading"><div><h2>${staff?"Complaint queue":"How can we help?"}</h2><p>${staff?"Support coordinates the case; Delivery provides the operational response.":"Tell Support what needs attention. We will coordinate with the responsible team."}</p></div></div>${staff?"":`<form id="complaint-form" class="panel stack-form"><label>Shipment (optional)<select name="shipment_id"><option value="">General support</option>${ships.map(s=>`<option value="${esc(s.shipment_id)}">${esc(s.tracking_id)} · ${esc(s.status)}</option>`).join("")}</select></label><label>Subject<input name="subject" required minlength="3" maxlength="150" placeholder="What went wrong?"></label><label>Description<textarea name="description" required minlength="5" maxlength="4000" rows="4" placeholder="Describe the issue clearly"></textarea></label><button class="button primary" type="submit">Submit complaint <span>→</span></button><div id="complaint-result"></div></form>`}<div class="complaint-list">${d.complaints.length?d.complaints.map(c=>`<article class="panel complaint-card"><div class="panel-header"><h3>${esc(c.subject)}</h3><span class="status-badge status-${esc(c.status_code.toLowerCase().replaceAll("_","-"))}">${esc(c.status_code.replaceAll("_"," "))}</span></div><p>${esc(c.description)}</p><p class="muted">${c.action_department?`<strong>Responsible department:</strong> ${esc(c.action_department)} · `:""}<strong>Reply due:</strong> ${formatDateTime(c.due_at)}</p><small>${formatDate(c.created_at)}${c.shipment_id?` · ${shipmentLink(c.shipment_id,null,"View shipment")}`:""}</small>${staff?`<div class="complaint-actions"><select data-complaint-status="${esc(c.complaint_id)}">${state.account.role==="DELIVERY_AGENT"?`<option ${c.status_code==="IN_PROGRESS"?"selected":""}>IN_PROGRESS</option>`:`<option ${c.status_code==="OPEN"?"selected":""}>OPEN</option><option ${c.status_code==="IN_PROGRESS"?"selected":""}>IN_PROGRESS</option><option ${c.status_code==="RESOLVED"?"selected":""}>RESOLVED</option><option ${c.status_code==="CLOSED"?"selected":""}>CLOSED</option>`}</select><button class="button ghost small" data-complaint-update="${esc(c.complaint_id)}">${state.account.role==="DELIVERY_AGENT"?"Start working":"Update status"}</button></div>`:""}</article>`).join(""):`<div class="panel empty-state"><strong>No complaints found</strong><span>Submitted support requests will appear here.</span></div>`}</div>`;
}
async function routePlanner(){setTitle("Route planner");const sample='[{"stop_id":"S1","label":"Andheri","latitude":19.1197,"longitude":72.8468},{"stop_id":"S2","label":"Powai","latitude":19.1176,"longitude":72.9060}]';$("#view").innerHTML=`<div class="section-heading"><div><h2>Optimize a delivery sequence.</h2><p>Arrange delivery stops in an efficient order.</p></div></div><section class="panel"><form id="route-form" class="form-grid"><div class="field"><label>Start latitude<input name="start_latitude" type="number" step="any" value="19.0760" required></label></div><div class="field"><label>Start longitude<input name="start_longitude" type="number" step="any" value="72.8777" required></label></div><div class="field" style="grid-column:1/-1"><label>Stops JSON<textarea name="stops" rows="7" required>${sample}</textarea></label></div><div class="form-actions" style="grid-column:1/-1"><button class="button primary">Optimize route <span>→</span></button></div></form><div id="route-result"></div></section></div>`;$("#route-form").onsubmit=async(e)=>{e.preventDefault();const f=new FormData(e.currentTarget);try{const stops=JSON.parse(f.get("stops"));const r=await api("/api/routes/optimize",{method:"POST",body:JSON.stringify({start_latitude:Number(f.get("start_latitude")),start_longitude:Number(f.get("start_longitude")),stops})});$("#route-result").innerHTML=`<div class="result-card"><h4>${esc(r.algorithm)}</h4><div>Total distance: <strong>${r.total_distance_km} km</strong></div><ol>${r.stops.map(s=>`<li>${esc(s.label)} · ${s.distance_from_previous_km} km from previous stop</li>`).join("")}</ol></div>`}catch(err){$("#route-result").innerHTML=`<div class="error-text">${esc(err.message)}</div>`}}}
const baseComplaints=complaints;
complaints=async function(){
  await baseComplaints();
  const data=state.complaintData||await api("/api/complaints");
  document.querySelectorAll(".complaint-card").forEach((card,index)=>{
    const complaint=data.complaints[index], thread=document.createElement("div"), form=document.createElement("form");
    thread.className="complaint-thread";
    const customerMessages=complaint.messages?.filter(message=>message.audience==="CUSTOMER")||[],internalMessages=complaint.messages?.filter(message=>message.audience==="INTERNAL")||[];
    thread.innerHTML=`<section class="complaint-conversation"><h4>Customer conversation</h4>${customerMessages.length?customerMessages.map(message=>`<p><strong>${esc(message.sender_role.replaceAll("_"," "))}:</strong> ${esc(message.message)}<small>${formatDateTime(message.created_at)}</small></p>`).join(""):`<p class="muted">No customer-facing reply yet.</p>`}</section>${state.account.role!=="CUSTOMER"&&internalMessages.length?internalMessages.map(message=>`<p class="complaint-team-message"><strong>${esc(message.sender_role.replaceAll("_"," "))}:</strong> ${esc(message.message)}<small>${formatDateTime(message.created_at)}</small></p>`).join(""):""}`;
    form.className="complaint-message-form";
    form.dataset.complaintMessage=complaint.complaint_id;
    const deliveryAgent=state.account.role==="DELIVERY_AGENT",customer=state.account.role==="CUSTOMER";
    form.innerHTML=`${deliveryAgent?`<input type="hidden" name="audience" value="INTERNAL">`:customer?`<input type="hidden" name="audience" value="CUSTOMER">`:`<label class="complaint-audience">Message recipient<select name="audience" aria-label="Message recipient"><option value="CUSTOMER">Customer — visible in their complaint</option><option value="INTERNAL">Assigned delivery agent — internal note</option></select></label>`}<textarea name="message" rows="2" minlength="2" maxlength="4000" required placeholder="${deliveryAgent?"Report the action taken to Support…":"Write a response…"}"></textarea><button class="button secondary small">${deliveryAgent?"Send update to Support":"Send message"}</button>`;
    card.append(thread,form);
  });
};
async function payments(){
  setTitle("Payments");
  const [all,options]=await Promise.all([api("/api/shipments"),api("/api/payments/options")]);
  const pending=all.filter(s=>s.payment_mode==="DEMO"&&s.payment_status!=="PAID");
  $("#view").innerHTML=`<div class="section-heading"><div><h2>Online payments</h2><p>Review online payment requests for your shipments.</p></div></div>${!options.demo_online_available?`<div class="panel empty-state"><strong>Online payment is unavailable.</strong><span>Cash bookings are still available.</span></div>`:pending.length?`<section class="panel"><form id="payment-form" class="form-grid"><div class="field" style="grid-column:1/-1"><label>Shipment<select name="shipment_id" required>${pending.map(s=>`<option value="${esc(s.shipment_id)}">${esc(s.tracking_id)} · ${money(s.charge,s.currency)}</option>`).join("")}</select></label></div><div class="form-actions" style="grid-column:1/-1"><button class="button primary">Continue to online payment <span>→</span></button></div></form><div id="payment-result"></div></section>`:`<div class="panel empty-state"><strong>No online payment is due.</strong></div>`}`;
  if($("#payment-form"))$("#payment-form").onsubmit=(e)=>{e.preventDefault();completeDemoPayment(new FormData(e.currentTarget).get("shipment_id"),$("#payment-result"))};
}
async function navigate(view){if(!state.account||!(ROLE_VIEWS[state.account.role]||[]).includes(view))return;state.view=view;setCustomerBookingGuidance(state.account.role==="CUSTOMER"&&view==="booking");document.querySelector("#sidebar").classList.remove("open");$("#view").innerHTML='<div class="panel empty-state">Loading workspace…</div>';try{if(view==="dashboard")await dashboard();else if(view==="shipments")await shipments();else if(view==="booking")booking();else if(view==="tracking")tracking();else if(view==="addressbook")await addressbook();else if(view==="notifications")await notifications();else if(view==="complaints")await complaints();else if(view==="terms")terms();else if(view==="tasks")await tasks();else if(view==="work-history")await workHistory();else if(view==="operations")await operations();else if(view==="route-planner")await routePlanner();else if(view==="payments")await payments();else if(view==="reports")await reports();else if(view==="warehouse")await warehouse();else if(view==="finance")await finance();else if(view==="staff")await staffAdmin()}catch(err){toast(err.message,true);$("#view").innerHTML=`<div class="panel empty-state"><strong>Unable to load this view</strong><span>${esc(err.message)}</span></div>`}}
function setTaskFeedback(assignmentId,message,isError=false){
  const feedback=[...document.querySelectorAll("[data-task-feedback]")].find(node=>node.dataset.taskFeedback===assignmentId);
  if(feedback)feedback.innerHTML=`<span class="${isError?"is-error":"is-success"}">${esc(message)}</span>`;
}
function setTaskButtonBusy(button,busy,label){
  if(!button)return;
  button.disabled=busy;
  if(label)button.textContent=label;
}
async function deliverySessionIsCurrent(){
  const session=await api("/api/auth/me");
  if(!session.authenticated||!session.account)throw new Error("Your OptiGo session has ended. Please sign in again.");
  if((session.account.staff_id||session.account.email)===(state.account?.staff_id||state.account?.email))return true;
  // A customer and an agent share the same browser session. Do not let an
  // older tab submit an action as whichever account most recently signed in.
  state.account=session.account;
  showShell();
  return false;
}
async function handleTaskAction(task){
  const action=task.dataset.taskAction,id=task.dataset.id;
  try{
    if(["location","otp","deliver","deliver-confirm"].includes(action)&&!(await deliverySessionIsCurrent()))return;
    if(action==="location"){
      if(!navigator.geolocation)throw new Error("This browser does not provide GPS access");
      setTaskButtonBusy(task,true,"Sharing location…");
      setTaskFeedback(id,"Getting your current location…");
      navigator.geolocation.getCurrentPosition(async position=>{
        try{
          await api(`/api/shipments/${task.dataset.shipmentId}/locations`,{method:"POST",body:JSON.stringify({latitude:position.coords.latitude,longitude:position.coords.longitude,scan_type:"GPS",location_text:"GPS update"})});
          setTaskFeedback(id,"Okay, location shared.");
        }catch(err){setTaskFeedback(id,err.message,true)}
        finally{setTaskButtonBusy(task,false,"Share GPS location")}
      },()=>{setTaskFeedback(id,"GPS permission was not granted. Allow location access and try again.",true);setTaskButtonBusy(task,false,"Share GPS location")},{enableHighAccuracy:true,timeout:10000});
      return;
    }
    if(action==="start"){
      await api(`/api/assignments/${id}/start-delivery`,{method:"POST"});
      state.taskNotice="Delivery started. You can now share location, request the customer OTP, and complete delivery.";
      navigate("tasks");
      return;
    }
    if(action==="pickup"){
      await api(`/api/assignments/${id}/pickup-complete`,{method:"POST"});
      state.taskNotice="Pickup completed and recorded.";
      navigate("tasks");
      return;
    }
    if(action==="otp"){
      setTaskButtonBusy(task,true,"Requesting OTP…");
      setTaskFeedback(id,"Requesting a delivery OTP for the customer…");
      await api(`/api/assignments/${id}/otp`,{method:"POST"});
      setTaskFeedback(id,"OTP requested. The customer can now find it in Notifications.");
      setTaskButtonBusy(task,false,"Request new OTP");
      return;
    }
    if(action==="deliver"){
      const entry=[...document.querySelectorAll("[data-delivery-otp-entry]")].find(node=>node.dataset.deliveryOtpEntry===id);
      if(!entry)return;
      entry.classList.remove("hidden");
      const input=entry.querySelector("[data-delivery-otp-input]");
      input?.focus();
      setTaskFeedback(id,"Enter the 6-digit OTP from the customer's Notifications, then confirm delivery.");
      return;
    }
    if(action==="deliver-confirm"){
      const cashBox=[...document.querySelectorAll("[data-cash-confirm]")].find(node=>node.dataset.cashConfirm===id);
      if(cashBox&&!cashBox.checked)throw new Error("Confirm cash collection before completing delivery");
      const input=[...document.querySelectorAll("[data-delivery-otp-input]")].find(node=>node.dataset.deliveryOtpInput===id);
      const code=input?.value.trim()||"";
      if(!/^\d{6}$/.test(code))throw new Error("Enter the 6-digit OTP from the customer's Notifications");
      setTaskButtonBusy(task,true,"Verifying…");
      setTaskFeedback(id,"Verifying delivery OTP…");
      await api(`/api/assignments/${id}/deliver`,{method:"POST",body:JSON.stringify({code,remarks:"OTP verified",cash_collected:Boolean(cashBox?.checked)})});
      state.taskNotice="Delivery verified — delivery completed.";
      navigate("tasks");
      return;
    }
  }catch(err){
    setTaskFeedback(id,err.message,true);
    if(action==="otp")setTaskButtonBusy(task,false,"Request OTP");
    if(action==="deliver-confirm")setTaskButtonBusy(task,false,"Confirm delivery");
  }
}
document.addEventListener("click",(e)=>{
  if(e.target.closest("[data-customer-services-toggle]")){e.preventDefault();setCustomerBookingGuidance(false);return}
  const staffReset=e.target.closest("[data-staff-password-reset]");
  if(staffReset){const form=$("#staff-password-form");form.dataset.staffId=staffReset.dataset.staffPasswordReset;$("#staff-password-account").textContent=`${staffReset.dataset.staffName} · ${staffReset.dataset.staffRole} · ${staffReset.dataset.staffEmail}`;$("#staff-password-dialog").showModal();$("#staff-new-password").focus();return}
  if(e.target.closest("[data-customer-logout]")){e.preventDefault();$("#logout-button").click();return}
  if(e.target.closest("#customer-delete-account")){e.preventDefault();$("#delete-account-button").click();return}
  const useAddress=e.target.closest("[data-use-address]");
  if(useAddress){state.pendingAddress=customerAddresses[Number(useAddress.dataset.useAddress)];navigate("booking");return}
  if(e.target.closest("[data-auth-close]")){e.preventDefault();closePublicAuth();return}
  const landingAction=e.target.closest("[data-landing-action]")?.dataset.landingAction;
  if(landingAction){
    e.preventDefault();
    if(landingAction==="register")openPublicAuth("register");
    else if(landingAction==="booking")scrollToLandingSection("#landing-booking-form","#landing-booking-form input");
    else if(landingAction==="tracking")scrollToLandingSection("#public-tracking","#public-track-input");
    else openPublicAuth("login");
    return;
  }
  const shipmentRow=e.target.closest("[data-shipment-detail-row]");
  if(shipmentRow){e.preventDefault();openShipmentDetails(shipmentRow.dataset.shipmentDetailRow,e.target.closest("[data-shipment-detail]")||shipmentRow);return}
  const view=e.target.closest("[data-view]")?.dataset.view;
  if(view){e.preventDefault();if($("#shipment-detail-dialog")?.open)$("#shipment-detail-dialog").close();navigate(view)}
  const auth=e.target.closest("[data-auth-mode]")?.dataset.authMode;
  if(auth)renderAuth(auth);
  const shipmentDetail=e.target.closest("[data-shipment-detail]");
  if(shipmentDetail){e.preventDefault();openShipmentDetails(shipmentDetail.dataset.shipmentDetail,shipmentDetail);return}
  const track=e.target.closest("[data-track]")?.dataset.track;
  if(track){navigate("tracking").then(()=>{if($("#track-input")){ $("#track-input").value=track;$("#track-form").requestSubmit()}})}
  const task=e.target.closest("[data-task-action]");
  if(task)handleTaskAction(task);
});
document.addEventListener("keydown",(event)=>{
  const shipmentRow=event.target.closest("[data-shipment-detail-row]");
  if(shipmentRow&&(event.key==="Enter"||event.key===" ")){event.preventDefault();openShipmentDetails(shipmentRow.dataset.shipmentDetailRow,shipmentRow);return}
  const authShell=$("#auth-shell");
  if(authShell.classList.contains("hidden"))return;
  if(event.key==="Escape"){closePublicAuth();return}
  if(event.key!=="Tab")return;
  const focusable=[...authShell.querySelectorAll('button:not([disabled]),a[href],input:not([disabled])')].filter(node=>node.getClientRects().length>0);
  const first=focusable[0],last=focusable[focusable.length-1];
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}
});
function startLandingBooking(form){
  if(!form)return;
  if(!form.checkValidity()){form.querySelector(":invalid")?.focus();return}
  state.pendingBooking=Object.fromEntries(new FormData(form));
  openPublicAuth("register");
  showAuthMessage("Create an account or sign in to complete your booking.",true);
}
document.addEventListener("click",(e)=>{const read=e.target.closest("[data-notification-read]");if(read){(async()=>{try{await api(`/api/notifications/${read.dataset.notificationRead}/read`,{method:"POST"});await notifications();toast("Notification marked as read")}catch(err){toast(err.message,true)}})()}const update=e.target.closest("[data-complaint-update]");if(update){const select=document.querySelector(`[data-complaint-status="${CSS.escape(update.dataset.complaintUpdate)}"]`);(async()=>{try{await api(`/api/complaints/${update.dataset.complaintUpdate}`,{method:"PATCH",body:JSON.stringify({status_code:select.value})});await complaints();toast("Complaint status updated")}catch(err){toast(err.message,true)}})()}});
document.addEventListener("submit",async(e)=>{
  const authForms=["login-form","register-form","forgot-request-form","forgot-confirm-form"];
  if(!authForms.includes(e.target.id))return;
  e.preventDefault();
  const form=e.target, button=form.querySelector('[type="submit"]'), fields=new FormData(form);
  button.disabled=true;
  showAuthMessage("Connecting to OptiGo…",true);
  try{
    await startupReady;
    $("#auth-error").classList.remove("show");
    let result;
    if(form.id==="forgot-request-form"){
      const payload=Object.fromEntries(fields);
      result=await api("/api/auth/password-reset/request",{method:"POST",body:JSON.stringify(payload)});
      renderAuth("reset");
      $("#forgot-confirm-form [name=email]").value=payload.email.trim().toLowerCase();
      showAuthMessage(result.message,true);
      return;
    }
    if(form.id==="forgot-confirm-form"){
      const payload=Object.fromEntries(fields);
      result=await api("/api/auth/password-reset/confirm",{method:"POST",body:JSON.stringify(payload)});
      renderAuth("login");
      $("#login-form [name=email]").value=payload.email.trim().toLowerCase();
      showAuthMessage(result.message,true);
      $("#login-form [name=password]").focus();
      return;
    }
    const path=form.id==="login-form"?"/api/auth/login":"/api/auth/register";
    result=await api(path,{method:"POST",body:JSON.stringify(Object.fromEntries(fields))});
    if(form.id==="register-form"){
      const email=fields.get("email");
      renderAuth("login");
      $("#login-form [name=email]").value=email;
      showAuthMessage("Account created. Sign in with your email address and password to continue.",true);
      $("#login-form [name=password]").focus();
      return;
    }
    state.account=result.account;
    showShell();
    toast("Signed in successfully");
  }catch(err){showAuthError(err.message||"Unable to sign in")}
  finally{button.disabled=false}
});
document.addEventListener("submit",async(e)=>{if(e.target.id==="complaint-form"){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target));if(!payload.shipment_id)delete payload.shipment_id;try{await api("/api/complaints",{method:"POST",body:JSON.stringify(payload)});e.target.reset();$("#complaint-result").innerHTML=`<div class="result-card"><h4>Complaint submitted</h4><div>Support will review your request.</div></div>`;await complaints();toast("Complaint submitted")}catch(err){$("#complaint-result").innerHTML=`<div class="error-text">${esc(err.message)}</div>`}}});
document.addEventListener("submit",async event=>{
  const form=event.target.closest("[data-complaint-message]");
  if(!form)return;
  event.preventDefault();
  const button=form.querySelector("button"), message=new FormData(form).get("message").trim();
  button.disabled=true;
  try{await api(`/api/complaints/${form.dataset.complaintMessage}/messages`,{method:"POST",body:JSON.stringify({message,audience:new FormData(form).get("audience")||"CUSTOMER"})});await complaints();}
  catch(error){toast(error.message,true)}
  finally{button.disabled=false}
});
function closeLogoutModal(){$("#logout-modal").classList.add("hidden")}
$("#logout-button").onclick=()=>{$("#logout-modal").classList.remove("hidden");$("#cancel-logout").focus()};$("#cancel-logout").onclick=closeLogoutModal;$("#logout-modal").onclick=(e)=>{if(e.target.id==="logout-modal")closeLogoutModal()};$("#confirm-logout").onclick=async()=>{const button=$("#confirm-logout");button.disabled=true;try{await api("/api/auth/logout",{method:"POST"});state.account=null;forgetAccount();closeLogoutModal();$("#app-shell").classList.add("hidden");$("#auth-shell").classList.remove("hidden");renderAuth("login")}catch(err){closeLogoutModal();toast(err.message,true)}finally{button.disabled=false}};function closeDeleteModal(){$("#delete-account-modal").classList.add("hidden")}$("#delete-account-button").onclick=()=>{$("#delete-account-modal").classList.remove("hidden");$("#cancel-delete-account").focus()};$("#cancel-delete-account").onclick=closeDeleteModal;$("#delete-account-modal").onclick=(e)=>{if(e.target.id==="delete-account-modal")closeDeleteModal()};$("#confirm-delete-account").onclick=async()=>{const button=$("#confirm-delete-account");button.disabled=true;try{await api("/api/auth/account",{method:"DELETE"});state.account=null;forgetAccount();closeDeleteModal();$("#app-shell").classList.add("hidden");$("#auth-shell").classList.remove("hidden");renderAuth("login");showAuthMessage("Account deleted successfully.",true)}catch(err){closeDeleteModal();toast(err.message,true)}finally{button.disabled=false}};$("#menu-button").onclick=()=>{$("#sidebar").classList.toggle("open");$("#sidebar-overlay").classList.toggle("show")};$("#sidebar-overlay").onclick=()=>{$("#sidebar").classList.remove("open");$("#sidebar-overlay").classList.remove("show")};
renderAuth("login");
const rememberedAccount=cachedAccount();
const localCustomerPreview=["localhost","127.0.0.1"].includes(window.location.hostname)&&new URLSearchParams(window.location.search).get("preview")==="customer";
if(localCustomerPreview){
  state.account={name:"Preview customer",email:"preview@optigo.local",role:"CUSTOMER"};
  sessionStorage.removeItem("optigo-view");
  showShell();
}else if(rememberedAccount){state.account=rememberedAccount;showShell(true);}
startupReady=api("/api/auth/me").then(session=>{
  if(session.authenticated&&session.account){
    const identityChanged=(state.account?.staff_id||state.account?.email)!==(session.account.staff_id||session.account.email);
    state.account=session.account;
    rememberAccount(session.account);
    if(!rememberedAccount||identityChanged)showShell(true);
  }else if(rememberedAccount){
    state.account=null;
    forgetAccount();
    $("#app-shell").classList.add("hidden");
    $("#auth-shell").classList.remove("hidden");
    renderAuth("login");
  }
  return session;
}).catch(()=>null);
document.addEventListener("click",event=>{
  const view=event.target.closest("[data-view]")?.dataset.view;
  if(view)sessionStorage.setItem("optigo-view",view);
});
$("#landing-booking-form").onsubmit=(event)=>{event.preventDefault();startLandingBooking(event.currentTarget)};
(()=>{const form=$("#landing-booking-form"),price=$("#landing-price");let timer;async function quote(){const sender=form.elements.sender_postal_code.value,receiver=form.elements.receiver_postal_code.value,weight=Number(form.elements.weight_kg.value);if(!/^\d{6}$/.test(sender)||!/^\d{6}$/.test(receiver)||!Number.isFinite(weight)||weight<=0){price.textContent="Enter both 6-digit PIN codes and parcel weight to see the exact charge.";return}price.textContent="Calculating exact charge…";try{const response=await fetch(`${API}/api/public/pricing/quote`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({weight_kg:weight,delivery_type_code:form.elements.delivery_type_code.value,destination_zone:"LOCAL"})});const data=await response.json();if(!response.ok)throw new Error(data.detail||"Charge unavailable");const quote={subtotal:data.subtotal??data.total??data.amount,discount:data.discount??"0.00",discounts:data.discounts||[],currency:data.currency};price.innerHTML=`Exact payable charge: <strong>${money(data.total??data.amount,data.currency)}</strong><small>${sender} → ${receiver} · all eligible offers are applied.</small>${pricingSavingsMarkup(quote)}`}catch(error){price.textContent="Exact charge is unavailable right now. Please try again."}}function schedule(){clearTimeout(timer);timer=setTimeout(quote,300)}["sender_postal_code","receiver_postal_code","weight_kg","delivery_type_code"].forEach(name=>form.elements[name].addEventListener(name==="delivery_type_code"?"change":"input",schedule));})();
$("#public-track-form").onsubmit=async(event)=>{
  event.preventDefault();
  const input=$("#public-track-input"),result=$("#public-track-result"),button=event.currentTarget.querySelector("button");
  const trackingId=input.value.trim().toUpperCase();
  input.value=trackingId;
  button.disabled=true;
  result.innerHTML='<div class="public-track-loading">Looking up the latest shipment movement…</div>';
  try{
    const trackingData=await api(`/api/track/${encodeURIComponent(trackingId)}`);
    result.innerHTML=trackingResultMarkup(trackingData,true);
  }catch(error){
    result.innerHTML=`<div class="public-track-error"><strong>Tracking ID not found</strong><span>${esc(error.message)}</span><small>Check the ID on your booking confirmation and try again.</small></div>`;
  }finally{button.disabled=false}
};
