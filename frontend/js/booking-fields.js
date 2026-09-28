function locationFields(prefix, person) {
  const locations = window.OPTIGO_INDIA_LOCATIONS || {};
  const states = Object.keys(locations).sort();
  const stateOptions = states.map((state) => '<option value="' + esc(state) + '"></option>').join('');
  return '<div class="form-grid"><div class="field"><label>House / apartment number<input name="' + prefix + '_house_number" autocomplete="address-line2" placeholder="e.g. Flat 12, Building A" required></label></div>' +
    '<div class="field address-field"><label>Street / area<input name="' + prefix + '_line1" data-address-input="' + prefix + '" autocomplete="address-line1" placeholder="Start typing a street or area" required><div class="address-suggestions" data-address-suggestions="' + prefix + '"></div></label></div>' +
    '<div class="field"><label>' + person + "'s name" + '<input name="' + prefix + '_contact_name" required></label></div>' +
    '<div class="field"><label>State<input name="' + prefix + '_state" data-location-state="' + prefix + '" list="' + prefix + '-states" autocomplete="address-level1" placeholder="Select or type a state" required><datalist id="' + prefix + '-states">' + stateOptions + '</datalist></label></div>' +
    '<div class="field"><label>City<input name="' + prefix + '_city" data-location-city="' + prefix + '" list="' + prefix + '-cities" autocomplete="address-level2" placeholder="Select or type a city" required><datalist id="' + prefix + '-cities"></datalist></label></div>' +
    '<div class="field"><label>Postal code<input name="' + prefix + '_postal_code" data-location-postal="' + prefix + '" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="postal-code" placeholder="Select, auto-fill, or type a 6-digit PIN" required><small class="location-hint" data-location-hint="' + prefix + '"></small></label></div>' +
    '<div class="field"><label>Phone<input name="' + prefix + '_contact_phone" type="tel" inputmode="numeric" required></label></div></div>';
}

async function loadCitiesForState(prefix) {
  const state = document.querySelector('[data-location-state="' + prefix + '"]');
  const cities = document.getElementById(prefix + '-cities');
  const fallback = Object.keys(((window.OPTIGO_INDIA_LOCATIONS || {})[state.value] || {})).sort();
  if (!state.value.trim()) { cities.innerHTML = ''; return; }
  try {
    const response = await fetch((window.OPTIGO_API_BASE || 'http://127.0.0.1:8000') + '/api/locations/cities?state=' + encodeURIComponent(state.value));
    const data = await response.json();
    const values = Array.isArray(data.cities) ? data.cities : (Array.isArray(data.data) ? data.data : fallback);
    cities.innerHTML = [...new Set(values)].sort().map((name) => '<option value="' + esc(name) + '"></option>').join('');
  } catch { cities.innerHTML = fallback.map((name) => '<option value="' + esc(name) + '"></option>').join(''); }
}

async function suggestPostalCode(prefix) {
  const state = document.querySelector('[data-location-state="' + prefix + '"]');
  const city = document.querySelector('[data-location-city="' + prefix + '"]');
  const postal = document.querySelector('[data-location-postal="' + prefix + '"]');
  const hint = document.querySelector('[data-location-hint="' + prefix + '"]');
  const pinData = window.OPTIGO_INDIA_LOCATIONS?.[state.value]?.[city.value];
  const knownPins = Array.isArray(pinData) ? pinData : (pinData ? [pinData] : []);
  if (knownPins.length && !postal.value) { postal.value = String(knownPins[0]); hint.textContent = 'Suggested PIN for this city; you can edit it if needed.'; return; }
  if (city.value && state.value) hint.textContent = 'Type any valid 6-digit Indian PIN if your area is not in the suggestions.';
}

function wireAddressLookup(prefix) {
  const input = document.querySelector('[data-address-input="' + prefix + '"]');
  const suggestions = document.querySelector('[data-address-suggestions="' + prefix + '"]');
  const state = document.querySelector('[data-location-state="' + prefix + '"]');
  const city = document.querySelector('[data-location-city="' + prefix + '"]');
  const postal = document.querySelector('[data-location-postal="' + prefix + '"]');
  let timer; let results = [];
  input.addEventListener('input', () => {
    clearTimeout(timer); const query = input.value.trim();
    if (query.length < 4) { suggestions.innerHTML = ''; return; }
    timer = setTimeout(async () => {
      try {
        const response = await fetch((window.OPTIGO_API_BASE || 'http://127.0.0.1:8000') + '/api/locations/search?q=' + encodeURIComponent(query + ', ' + (state.value || '') + ', India'));
        const data = await response.json(); results = (data.features || []).filter((feature) => feature.properties && feature.properties.country === 'India');
        suggestions.innerHTML = results.map((feature, index) => '<button type="button" class="address-suggestion" data-address-index="' + index + '">' + esc(feature.properties.name || feature.properties.street || 'Address') + '<small>' + esc(feature.properties.state || '') + (feature.properties.postcode ? ' · ' + esc(feature.properties.postcode) : '') + '</small></button>').join('');
      } catch { suggestions.innerHTML = '<div class="address-suggestion-message">Address search is temporarily unavailable. You can still enter the address manually.</div>'; }
    }, 500);
  });
  suggestions.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-address-index]'); if (!button) return;
    const properties = results[Number(button.dataset.addressIndex)]?.properties || {};
    input.value = properties.street || properties.name || ''; suggestions.innerHTML = '';
    if (properties.state) { state.value = properties.state; await loadCitiesForState(prefix); }
    city.value = properties.city || properties.town || properties.village || properties.locality || properties.county || '';
    if (properties.postcode) postal.value = properties.postcode; else await suggestPostalCode(prefix);
  });
}

function wireLocationFields(prefix) {
  const state = document.querySelector('[data-location-state="' + prefix + '"]');
  const city = document.querySelector('[data-location-city="' + prefix + '"]');
  const postal = document.querySelector('[data-location-postal="' + prefix + '"]');
  state.addEventListener('change', () => loadCitiesForState(prefix));
  state.addEventListener('input', () => loadCitiesForState(prefix));
  city.addEventListener('change', () => suggestPostalCode(prefix));
  city.addEventListener('input', () => suggestPostalCode(prefix));
  postal.addEventListener('input', () => { const hint = document.querySelector('[data-location-hint="' + prefix + '"]'); if (postal.value) hint.textContent = 'PIN entered manually.'; });
  wireAddressLookup(prefix);
}
