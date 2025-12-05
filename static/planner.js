const adminPinInput = document.getElementById('adminPin');
const bandTableBody = document.querySelector('#bandTable tbody');
const queueTableBody = document.querySelector('#queueTable tbody');
const historyTableBody = document.querySelector('#historyTable tbody');

const addVehicleForm = document.getElementById('addVehicleForm');
const vehicleNameInput = document.getElementById('vehicleName');
const vehicleHoursInput = document.getElementById('vehicleHours');
const vehicleEmployeesInput = document.getElementById('vehicleEmployees');

const advanceBtn = document.getElementById('advanceBtn');
const refreshBtn = document.getElementById('refreshBtn');

const windowStartInput = document.getElementById('windowStart');
const windowEndInput = document.getElementById('windowEnd');
const windowDaysInput = document.getElementById('windowDays');
const breaksInput = document.getElementById('breaksInput');
const holidaysInput = document.getElementById('holidaysInput');
const employeesInput = document.getElementById('employeesInput');
const configForm = document.getElementById('configForm');

function adminHeaders() {
  const pin = adminPinInput.value.trim();
  return pin ? { 'X-Admin-Pin': pin } : {};
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function renderBand(band) {
  bandTableBody.innerHTML = '';
  band.forEach((slot) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${slot.station}</td>
      <td>${slot.vehicle ? slot.vehicle.name : '<span class="muted">—</span>'}</td>
      <td>${slot.vehicle ? slot.vehicle.hours : ''}</td>
      <td>${slot.vehicle ? slot.vehicle.employees : ''}</td>
    `;
    bandTableBody.appendChild(tr);
  });
}

function renderQueue(queue) {
  queueTableBody.innerHTML = '';
  queue.forEach((vehicle, idx) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${idx + 1}</td>
      <td>${vehicle?.name || ''}</td>
      <td>${vehicle?.hours ?? ''}</td>
      <td>${vehicle?.employees ?? ''}</td>
    `;
    queueTableBody.appendChild(tr);
  });
}

function renderHistory(history) {
  historyTableBody.innerHTML = '';
  history.forEach((entry) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${new Date(entry.finished_at).toLocaleString()}</td>
      <td>${entry.vehicle_name}</td>
      <td>${entry.hours}</td>
      <td>${entry.employees}</td>
      <td>${entry.band_employees}</td>
      <td>${entry.station}</td>
    `;
    historyTableBody.appendChild(tr);
  });
}

function fillConfig(config) {
  windowStartInput.value = config.window.start;
  windowEndInput.value = config.window.end;
  windowDaysInput.value = (config.window.days || []).join(',');
  breaksInput.value = (config.breaks || []).map((b) => `${b.start}-${b.end}`).join('\n');
  holidaysInput.value = (config.freeDays || []).join('\n');
  employeesInput.value = config.employees;
}

async function loadAll() {
  try {
    const [plan, config, history] = await Promise.all([
      fetchJson('/api/plan'),
      fetchJson('/api/config'),
      fetchJson('/api/history?limit=20'),
    ]);
    renderBand(plan.band || []);
    renderQueue(plan.queue || []);
    renderHistory(history || []);
    fillConfig(config);
  } catch (err) {
    alert(`Fehler beim Laden: ${err.message}`);
  }
}

addVehicleForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const payload = {
      vehicle: {
        name: vehicleNameInput.value,
        hours: parseFloat(vehicleHoursInput.value || '0'),
        employees: parseInt(vehicleEmployeesInput.value || '1', 10),
      },
    };
    await fetchJson('/api/queue', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...adminHeaders(),
      },
      body: JSON.stringify(payload),
    });
    vehicleNameInput.value = '';
    await loadAll();
  } catch (err) {
    alert(`Fehler beim Hinzufügen: ${err.message}`);
  }
});

advanceBtn.addEventListener('click', async () => {
  try {
    await fetchJson('/api/band/advance', {
      method: 'POST',
      headers: { ...adminHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    await loadAll();
  } catch (err) {
    alert(`Fehler beim Bandvorschub: ${err.message}`);
  }
});

configForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const breaks = (breaksInput.value || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [start, end] = line.split('-');
      return { start: start?.trim(), end: end?.trim() };
    })
    .filter((b) => b.start && b.end);

  const holidays = (holidaysInput.value || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

  const payload = {
    window: {
      start: windowStartInput.value,
      end: windowEndInput.value,
      days: windowDaysInput.value.split(',').map((v) => parseInt(v.trim(), 10)).filter((n) => !Number.isNaN(n)),
    },
    breaks,
    freeDays: holidays,
    employees: parseInt(employeesInput.value || '1', 10),
  };

  try {
    await fetchJson('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...adminHeaders() },
      body: JSON.stringify(payload),
    });
    await loadAll();
  } catch (err) {
    alert(`Fehler beim Speichern: ${err.message}`);
  }
});

refreshBtn.addEventListener('click', loadAll);

loadAll();
