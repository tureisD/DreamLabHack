const form = document.getElementById('workspace');
const keyField = document.getElementById('api-key');
const status = document.getElementById('status');
const button = form.querySelector('button');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  status.textContent = 'Checking your Dream Labs connection…';
  try {
    const response = await fetch('/hosted/workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: keyField.value.trim() }),
    });
    if (!response.ok) {
      const reply = await response.json().catch(() => ({}));
      throw new Error(reply.detail ?? 'DreamCoach could not create a workspace.');
    }
    keyField.value = '';
    for (const name of Object.keys(sessionStorage)) {
      if (name.startsWith('coach-')) sessionStorage.removeItem(name);
    }
    location.replace('/');
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
  }
});
