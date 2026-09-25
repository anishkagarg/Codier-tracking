function locationFields(prefix, person) {
  const locations = window.OPTIGO_INDIA_LOCATIONS || {};
  const states = Object.keys(locations).sort();
  const stateOptions = states.map((state) => '<option value="' + esc(state) + '">' + esc(state) + '</option>').join('');
  return '<div class="form-grid"><div class="field"><label>Address<input name="' + prefix + '_line1" required></label></div>' +
    '<div class="field"><label>' + person + "'s name" + '<input name="' + prefix + '_contact_name" required></label></div>' +
    '<div class="field"><label>State<select name="' + prefix + '_state" data-location-state="' + prefix + '" required><option value="">Select state</option>' + stateOptions + '</select></label></div>' +
    '<div class="field"><label>City<select name="' + prefix + '_city" data-location-city="' + prefix + '" required disabled><option value="">Select state first</option></select></label></div>' +
    '<div class="field"><label>Postal code<select name="' + prefix + '_postal_code" data-location-postal="' + prefix + '" required disabled><option value="">Select city first</option></select></label></div>' +
    '<div class="field"><label>Phone<input name="' + prefix + '_contact_phone" type="tel" inputmode="numeric" required></label></div></div>';
}

function wireLocationFields(prefix) {
  const state = document.querySelector('[data-location-state="' + prefix + '"]');
  const city = document.querySelector('[data-location-city="' + prefix + '"]');
  const postal = document.querySelector('[data-location-postal="' + prefix + '"]');
  state.onchange = () => {
    const cities = (window.OPTIGO_INDIA_LOCATIONS || {})[state.value] || {};
    city.innerHTML = '<option value="">Select city</option>' + Object.keys(cities).sort().map((name) => '<option value="' + esc(name) + '">' + esc(name) + '</option>').join('');
    city.disabled = false;
    postal.innerHTML = '<option value="">Select city first</option>';
    postal.disabled = true;
  };
  city.onchange = () => {
    const codes = ((window.OPTIGO_INDIA_LOCATIONS || {})[state.value] || {})[city.value] || [];
    postal.innerHTML = '<option value="">Select postal code</option>' + codes.map((code) => '<option value="' + code + '">' + code + '</option>').join('');
    postal.disabled = false;
  };
}
