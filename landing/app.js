'use strict';
const form = document.getElementById('signup-form');
const button = document.getElementById('submit');
const status = document.getElementById('form-status');
const available = form.dataset.available === 'true';
button.disabled = !available;
status.textContent = available ? '' : 'Signups are unavailable in this preview. The operator must configure a private signup directory.';
const fields = ['email', 'tool', 'problem', 'consent'];
for (const name of fields) {
  document.getElementById(name).addEventListener('input', () => {
    document.getElementById(name).removeAttribute('aria-invalid');
    document.getElementById(`${name}-error`).textContent = '';
  });
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!available || button.disabled) return;
  let firstInvalid = null;
  const payload = {};
  for (const name of fields) {
    const input = document.getElementById(name);
    payload[name] = name === 'consent' ? input.checked : input.value.trim();
    const valid = input.checkValidity() && Boolean(payload[name]);
    input.setAttribute('aria-invalid', String(!valid));
    document.getElementById(`${name}-error`).textContent = valid ? '' :
      name === 'email' ? 'Enter a valid email address.' :
      name === 'consent' ? 'Please give consent before submitting.' : 'Please complete this field.';
    if (!valid && !firstInvalid) firstInvalid = input;
  }
  if (firstInvalid) {
    status.textContent = 'Please check the highlighted fields.';
    firstInvalid.focus();
    return;
  }
  button.disabled = true;
  status.textContent = 'Saving your interest…';
  try {
    const response = await fetch('/api/signup', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-SCOP-Token': document.querySelector('meta[name="signup-token"]').content},
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok || result.saved !== true) throw new Error('Submission failed');
    status.textContent = 'Your interest has been saved. Thank you for helping shape SCOP.';
    form.reset();
  } catch {
    status.textContent = 'We could not confirm your submission. Please try again later. No confirmation email has been sent.';
  } finally {
    button.disabled = false;
  }
});
