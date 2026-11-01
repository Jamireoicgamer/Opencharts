// SPDX-License-Identifier: AGPL-3.0-or-later
// The window shows this page while the database and service start. If they
// fail, the app puts the reason in the URL fragment (#error=…).
function showError() {
  const reason = new URLSearchParams(location.hash.slice(1)).get('error');
  if (!reason) return;
  document.body.classList.add('failed');
  document.getElementById('status').textContent = 'OpenChart couldn’t start.';
  document.getElementById('message').textContent = reason;
  document.getElementById('problem').hidden = false;
}
window.addEventListener('hashchange', showError);
showError();
