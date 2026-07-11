const state = {
  status: null,
  menu: [],
  inventory: [],
  settings: null,
  activeJob: null,
  pollTimer: null,
};

const elements = Object.fromEntries(
  [
    "machine-pill",
    "motion-state",
    "motion-position",
    "motion-realtime",
    "queue-count",
    "position-select",
    "move-select",
    "job-panel",
    "job-title",
    "job-status",
    "job-progress",
    "job-instruction",
    "continue-button",
    "cancel-button",
    "drink-grid",
    "menu-search",
    "inventory-list",
    "settings-form",
    "toast",
  ].map((id) => [id, document.getElementById(id)]),
);

for (let slot = 0; slot < 12; slot += 1) {
  const label = `Slot ${slot + 1}`;
  elements["position-select"].add(new Option(label, String(slot)));
  elements["move-select"].add(new Option(label, String(slot)));
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => showView(tab.dataset.view));
}

document.getElementById("stop-button").addEventListener("click", () => action("/api/machine/stop"));
document.getElementById("arm-button").addEventListener("click", () => action("/api/machine/arm"));
document
  .getElementById("disarm-button")
  .addEventListener("click", () => action("/api/machine/disarm"));
document
  .getElementById("reset-button")
  .addEventListener("click", () => action("/api/machine/reset"));
document
  .getElementById("position-button")
  .addEventListener("click", () =>
    action("/api/machine/position", { slot: Number(elements["position-select"].value) }),
  );
document
  .getElementById("move-button")
  .addEventListener("click", () =>
    action("/api/machine/move", { slot: Number(elements["move-select"].value) }),
  );
document.getElementById("continue-button").addEventListener("click", continueJob);
elements["cancel-button"].addEventListener("click", cancelJob);
elements["menu-search"].addEventListener("input", renderMenu);
document.getElementById("add-bottle").addEventListener("click", () => addInventory("bottle"));
document.getElementById("add-pantry").addEventListener("click", () => addInventory("pantry"));
document.getElementById("save-inventory").addEventListener("click", saveInventory);
document.getElementById("sync-recipes").addEventListener("click", syncRecipes);
elements["settings-form"].addEventListener("submit", saveSettings);

await refreshAll();
state.pollTimer = window.setInterval(refreshStatus, 1_500);
window.addEventListener("unhandledrejection", (event) => {
  toast(event.reason instanceof Error ? event.reason.message : String(event.reason), true);
});

async function refreshAll() {
  await Promise.all([refreshStatus(), refreshMenu(), refreshInventory(), refreshSettings()]);
}

async function refreshStatus() {
  try {
    state.status = await api("/api/status");
    state.activeJob = state.status.activeJob;
    renderStatus();
    renderJob();
  } catch (error) {
    state.status = null;
    renderStatus();
  }
}

async function refreshMenu() {
  state.menu = await api("/api/menu");
  renderMenu();
}

async function refreshInventory() {
  state.inventory = await api("/api/inventory");
  renderInventory();
}

async function refreshSettings() {
  state.settings = await api("/api/settings");
  for (const [key, value] of Object.entries(state.settings)) {
    const field = elements["settings-form"].elements.namedItem(key);
    if (field) field.value = value;
  }
}

function renderStatus() {
  const motion = state.status?.motion ?? { state: "offline", armed: false, position: null };
  elements["machine-pill"].textContent = motion.armed ? `${motion.state} · armed` : motion.state;
  elements["machine-pill"].className = `machine-pill ${motion.state}`;
  elements["motion-state"].textContent = motion.state;
  elements["motion-position"].textContent =
    motion.position === null ? "Unknown" : `Slot ${motion.position + 1}`;
  elements["motion-realtime"].textContent = motion.realtime ? "RT scheduled" : "Standard";
  elements["queue-count"].textContent = String(state.status?.queuedJobs ?? 0);
}

function renderMenu() {
  const query = elements["menu-search"].value.trim().toLowerCase();
  const cards = state.menu
    .filter(({ recipe }) => recipe.name.toLowerCase().includes(query))
    .map(({ recipe, makeable, reason }) => {
      const ingredients = recipe.ingredients.map((item) => escapeHtml(item.name)).join(" · ");
      const image = recipe.imageUrl
        ? `<img class="drink-image" src="${escapeAttribute(recipe.imageUrl)}" alt="" />`
        : '<div class="drink-image"></div>';
      return `
        <article class="drink-card">
          ${image}
          <div class="drink-body">
            <h3>${escapeHtml(recipe.name)}</h3>
            <p>${ingredients}</p>
            ${makeable ? "" : `<p>${escapeHtml(reason ?? "Unavailable")}</p>`}
            <button class="button" data-recipe-id="${escapeAttribute(recipe.id)}" ${makeable ? "" : "disabled"}>
              ${makeable ? "Make drink" : "Unavailable"}
            </button>
          </div>
        </article>`;
    });
  elements["drink-grid"].innerHTML = cards.join("") || '<p class="muted">No drinks match.</p>';
  for (const button of elements["drink-grid"].querySelectorAll("[data-recipe-id]")) {
    button.addEventListener("click", () => submitJob(button.dataset.recipeId));
  }
}

function renderJob() {
  const job = state.activeJob;
  elements["job-panel"].classList.toggle("hidden", !job);
  if (!job) return;
  elements["job-title"].textContent = job.plan.recipeName;
  elements["job-status"].textContent = job.status.replace("_", " ");
  const progress =
    job.plan.steps.length === 0 ? 0 : (job.currentStep / job.plan.steps.length) * 100;
  elements["job-progress"].style.width = `${progress}%`;
  const step = job.plan.steps[job.currentStep];
  elements["job-instruction"].textContent =
    job.status === "waiting_manual" && step?.kind === "manual"
      ? step.instruction
      : step
        ? `${step.kind === "automatic" ? "Dispensing" : "Preparing"} ${step.ingredientName}`
        : "Finishing drink";
  elements["continue-button"].classList.toggle("hidden", job.status !== "waiting_manual");
}

function renderInventory() {
  elements["inventory-list"].innerHTML = state.inventory
    .map(
      (item) => `
      <article class="inventory-row" data-id="${escapeAttribute(item.id)}" data-mode="${item.mode}">
        <label>Name<input data-field="name" value="${escapeAttribute(item.name)}" /></label>
        <label>Aliases<input data-field="aliases" value="${escapeAttribute(item.aliases.join(", "))}" /></label>
        <label>Mode<select data-field="mode">
          <option value="bottle" ${item.mode === "bottle" ? "selected" : ""}>Bottle</option>
          <option value="pantry" ${item.mode === "pantry" ? "selected" : ""}>Pantry</option>
        </select></label>
        <label>Slot<input data-field="slot" type="number" min="1" max="12" value="${item.slot === null ? "" : item.slot + 1}" ${item.mode === "pantry" ? "disabled" : ""} /></label>
        <label>ml / press<input data-field="mlPerPress" type="number" min="0.1" step="0.1" value="${item.mlPerPress ?? ""}" ${item.mode === "pantry" ? "disabled" : ""} /></label>
        <button class="button danger" data-remove="${escapeAttribute(item.id)}">Remove</button>
      </article>`,
    )
    .join("");
  for (const select of elements["inventory-list"].querySelectorAll('[data-field="mode"]')) {
    select.addEventListener("change", () => toggleInventoryMode(select.closest(".inventory-row")));
  }
  for (const button of elements["inventory-list"].querySelectorAll("[data-remove]")) {
    button.addEventListener("click", () => {
      state.inventory = state.inventory.filter((item) => item.id !== button.dataset.remove);
      renderInventory();
    });
  }
}

function toggleInventoryMode(row) {
  const pantry = row.querySelector('[data-field="mode"]').value === "pantry";
  row.querySelector('[data-field="slot"]').disabled = pantry;
  row.querySelector('[data-field="mlPerPress"]').disabled = pantry;
}

function addInventory(mode) {
  state.inventory.push({
    id: crypto.randomUUID(),
    name: "",
    aliases: [],
    mode,
    enabled: true,
    slot: mode === "bottle" ? firstOpenSlot() : null,
    mlPerPress: mode === "bottle" ? 30 : null,
    pressDurationMs: 600,
    releaseDurationMs: 200,
  });
  renderInventory();
}

function firstOpenSlot() {
  const used = new Set(
    state.inventory.filter((item) => item.slot !== null).map((item) => item.slot),
  );
  for (let slot = 0; slot < 12; slot += 1) if (!used.has(slot)) return slot;
  return 0;
}

async function saveInventory() {
  const inventory = [...elements["inventory-list"].querySelectorAll(".inventory-row")].map(
    (row) => {
      const mode = row.querySelector('[data-field="mode"]').value;
      return {
        id: row.dataset.id,
        name: row.querySelector('[data-field="name"]').value,
        aliases: row
          .querySelector('[data-field="aliases"]')
          .value.split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        mode,
        enabled: true,
        slot: mode === "bottle" ? Number(row.querySelector('[data-field="slot"]').value) - 1 : null,
        mlPerPress:
          mode === "bottle" ? Number(row.querySelector('[data-field="mlPerPress"]').value) : null,
        pressDurationMs: 600,
        releaseDurationMs: 200,
      };
    },
  );
  state.inventory = await api("/api/inventory", { method: "PUT", body: inventory });
  toast("Inventory saved");
  await refreshMenu();
}

async function saveSettings(event) {
  event.preventDefault();
  const form = new FormData(elements["settings-form"]);
  const settings = {
    cocktailDbApiKey: String(form.get("cocktailDbApiKey") ?? "1"),
    motionSocket: String(form.get("motionSocket") ?? ""),
    maxDoseErrorPercent: Number(form.get("maxDoseErrorPercent")),
    listenHost: String(form.get("listenHost") ?? "127.0.0.1"),
    listenPort: Number(form.get("listenPort")),
  };
  state.settings = await api("/api/settings", { method: "PUT", body: settings });
  toast("Settings saved");
  await refreshMenu();
}

async function syncRecipes() {
  toast("Synchronizing recipes…");
  await api("/api/recipes/sync", { method: "POST" });
  await refreshMenu();
  toast("Recipe catalogue synchronized");
}

async function submitJob(recipeId) {
  const job = await api("/api/jobs", { method: "POST", body: { recipeId } });
  state.activeJob = job;
  showView("dashboard");
  renderJob();
  toast(`${job.plan.recipeName} queued`);
}

async function continueJob() {
  if (!state.activeJob) return;
  await api(`/api/jobs/${encodeURIComponent(state.activeJob.id)}/continue`, { method: "POST" });
  await refreshStatus();
}

async function cancelJob() {
  if (!state.activeJob) return;
  await api(`/api/jobs/${encodeURIComponent(state.activeJob.id)}/cancel`, { method: "POST" });
  await refreshStatus();
}

async function action(path, body) {
  try {
    await api(path, { method: "POST", ...(body === undefined ? {} : { body }) });
    await refreshStatus();
    toast("Machine command completed");
  } catch (error) {
    toast(error.message, true);
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers: options.body === undefined ? {} : { "content-type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.message ?? `HTTP ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

function showView(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.view === name);
  }
  for (const view of document.querySelectorAll(".view")) {
    view.classList.toggle("active", view.id === `view-${name}`);
  }
}

function toast(message, error = false) {
  elements.toast.textContent = message;
  elements.toast.className = `toast${error ? " error" : ""}`;
  window.setTimeout(() => elements.toast.classList.add("hidden"), 4_000);
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

function escapeAttribute(value) {
  return escapeHtml(String(value)).replaceAll('"', "&quot;");
}
