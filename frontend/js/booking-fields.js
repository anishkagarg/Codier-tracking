function locationFields(prefix, person) {
  const locations = window.OPTIGO_INDIA_LOCATIONS || {};
  const states = Object.keys(locations).sort();
  const stateOptions = states.map((state) => '<option value="' + esc(state) + '">' + esc(state) + '</option>').join('');
  return '<div class="form-grid"><div class="field"><label>House / apartment number<input name="' + prefix + '_house_number" autocomplete="address-line2" placeholder="e.g. Flat 12, Building A" required></label></div>' +
    '<div class="field address-field"><label>Street / area<input name="' + prefix + '_line1" data-address-input="' + prefix + '" autocomplete="address-line1" placeholder="Start typing a street or area" required><div class="address-suggestions" data-address-suggestions="' + prefix + '"></div></label></div>' +
    '<div class="field"><label>' + person + "'s name" + '<input name="' + prefix + '_contact_name" required></label></div>' +
    '<div class="field"><label>State<select name="' + prefix + '_state" data-location-state="' + prefix + '" required><option value="">Select state</option>' + stateOptions + '</select></label></div>' +
    '<div class="field"><label>City<select name="' + prefix + '_city" data-location-city="' + prefix + '" required disabled><option value="">Select state first</option></select></label></div>' +
    '<div class="field" data-location-area-wrap="' + prefix + '" hidden><label>Delivery area / post office<select data-location-area="' + prefix + '" disabled><option value="">Choose your area</option></select></label></div>' +
    '<div class="field"><label>Postal code<input name="' + prefix + '_postal_code" data-location-postal="' + prefix + '" inputmode="numeric" placeholder="Auto-filled from city or area" readonly required></label></div>' +
    '<div class="field"><label>Phone<input name="' + prefix + '_contact_phone" type="tel" inputmode="numeric" required></label></div></div>';
}

async function loadCitiesForState(prefix) {
  const state = document.querySelector('[data-location-state="' + prefix + '"]');
  const city = document.querySelector('[data-location-city="' + prefix + '"]');
  const postal = document.querySelector('[data-location-postal="' + prefix + '"]');
  const area = document.querySelector('[data-location-area="' + prefix + '"]');
  const areaWrap = document.querySelector('[data-location-area-wrap="' + prefix + '"]');
  const fallback = Object.keys(((window.OPTIGO_INDIA_LOCATIONS || {})[state.value] || {})).sort();
  city.innerHTML = '<option value="">Loading cities…</option>';
  city.disabled = true;
  postal.value = '';
  areaWrap.hidden = true;
  area.disabled = true;
  area.innerHTML = '<option value="">Choose your area</option>';
  try {
    const response = await fetch((window.OPTIGO_API_BASE || 'http://127.0.0.1:8000') + '/api/locations/cities?state=' + encodeURIComponent(state.value));
    const data = await response.json();
    const cities = Array.isArray(data.cities) ? data.cities : (Array.isArray(data.data) ? data.data : fallback);
    city.innerHTML = '<option value="">Select city</option>' + [...new Set(cities)].sort().map((name) => '<option value="' + esc(name) + '">' + esc(name) + '</option>').join('');
  } catch {
    city.innerHTML = '<option value="">Select city</option>' + fallback.map((name) => '<option value="' + esc(name) + '">' + esc(name) + '</option>').join('');
  }
  city.disabled = false;
}

function setSelectedCity(city, value) {
  if (!value) return;
  if (![...city.options].some((option) => option.value.toLowerCase() === value.toLowerCase())) city.add(new Option(value, value));
  city.value = [...city.options].find((option) => option.value.toLowerCase() === value.toLowerCase())?.value || value;
}

async function loadPostOffices(prefix) {
  const state = document.querySelector('[data-location-state="' + prefix + '"]');
  const city = document.querySelector('[data-location-city="' + prefix + '"]');
  const postal = document.querySelector('[data-location-postal="' + prefix + '"]');
  const area = document.querySelector('[data-location-area="' + prefix + '"]');
  const areaWrap = document.querySelector('[data-location-area-wrap="' + prefix + '"]');
  postal.value = '';
  area.innerHTML = '<option value="">Choose your area</option>';
  area.disabled = true;
  areaWrap.hidden = true;
  if (!city.value || !state.value) return;

  const pinData = window.OPTIGO_INDIA_LOCATIONS?.[state.value]?.[city.value];
  const knownPins = Array.isArray(pinData) ? pinData : (pinData ? [pinData] : []);
  if (knownPins.length) {
    postal.value = String(knownPins[0]);
    return;
  }

  areaWrap.hidden = false;
  area.disabled = false;
  area.innerHTML = '<option value="">Loading matching post offices…</option>';
  try {
    const base = window.OPTIGO_API_BASE || 'http://127.0.0.1:8000';
    const url = base + '/api/locations/post-offices?city=' + encodeURIComponent(city.value) + '&state=' + encodeURIComponent(state.value);
    const response = await fetch(url);
    const data = await response.json();
    const offices = data.post_offices || [];
    area.innerHTML = '<option value="">Choose your area / post office</option>' + offices.map((office, index) => '<option value="' + index + '" data-pincode="' + esc(office.pincode) + '">' + esc(office.name) + ' · ' + esc(office.pincode) + (office.district ? ' · ' + esc(office.district) : '') + '</option>').join('');
    if (!offices.length) area.innerHTML = '<option value="">No PIN match; try selecting an address suggestion</option>';
    else if (offices.length === 1) { area.selectedIndex = 1; postal.value = offices[0].pincode; }
  } catch {
    area.innerHTML = '<option value="">Area lookup unavailable; select an address suggestion</option>';
  }
}

function wireAddressLookup(prefix) {
  const input = document.querySelector('[data-address-input="' + prefix + '"]');
  const suggestions = document.querySelector('[data-address-suggestions="' + prefix + '"]');
  const state = document.querySelector('[data-location-state="' + prefix + '"]');
  const city = document.querySelector('[data-location-city="' + prefix + '"]');
  const postal = document.querySelector('[data-location-postal="' + prefix + '"]');
  let timer;
  let results = [];
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < 4) { suggestions.innerHTML = ''; return; }
    timer = setTimeout(async () => {
      try {
        const response = await fetch((window.OPTIGO_API_BASE || 'http://127.0.0.1:8000') + '/api/locations/search?q=' + encodeURIComponent(query + ', ' + (state.value || '') + ', India'));
        const data = await response.json();
        results = (data.features || []).filter((feature) => feature.properties && feature.properties.country === 'India');
        suggestions.innerHTML = results.map((feature, index) => '<button type="button" class="address-suggestion" data-address-index="' + index + '">' + esc(feature.properties.name || feature.properties.street || 'Address') + '<small>' + esc(feature.properties.state || '') + (feature.properties.postcode ? ' · ' + esc(feature.properties.postcode) : '') + '</small></button>').join('');
      } catch { suggestions.innerHTML = '<div class="address-suggestion-message">Address search is temporarily unavailable.</div>'; }
    }, 500);
  });
  suggestions.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-address-index]');
    if (!button) return;
    const properties = results[Number(button.dataset.addressIndex)]?.properties || {};
    input.value = properties.street || properties.name || '';
    suggestions.innerHTML = '';
    const matchedState = Object.keys(window.OPTIGO_INDIA_LOCATIONS || {}).find((name) => name.toLowerCase() === String(properties.state || '').toLowerCase());
    if (matchedState) { state.value = matchedState; await loadCitiesForState(prefix); }
    const selectedCity = properties.city || properties.town || properties.village || properties.locality || properties.county || '';
    setSelectedCity(city, selectedCity);
    await loadPostOffices(prefix);
    if (properties.postcode) postal.value = properties.postcode;
  });
}

function wireLocationFields(prefix) {
  const state = document.querySelector('[data-location-state="' + prefix + '"]');
  const city = document.querySelector('[data-location-city="' + prefix + '"]');
  const area = document.querySelector('[data-location-area="' + prefix + '"]');
  state.onchange = () => loadCitiesForState(prefix);
  city.onchange = () => loadPostOffices(prefix);
  area.onchange = () => {
    const pincode = area.selectedOptions[0]?.dataset.pincode;
    document.querySelector('[data-location-postal="' + prefix + '"]').value = pincode || '';
  };
  wireAddressLookup(prefix);
}
