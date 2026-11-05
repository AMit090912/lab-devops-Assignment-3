(function () {
  "use strict";

  const list = document.getElementById("item-list");
  const form = document.getElementById("item-form");
  const input = document.getElementById("item-name");
  const message = document.getElementById("form-message");
  const health = document.getElementById("health-status");

  function setMessage(text, isError) {
    message.textContent = text;
    message.className = isError ? "error" : "ok";
  }

  function render(items) {
    list.replaceChildren();
    items.forEach(function (item) {
      const li = document.createElement("li");
      li.className = "item";
      li.textContent = item.name; // textContent => no XSS
      list.appendChild(li);
    });
  }

  async function loadItems() {
    const res = await fetch("/api/items");
    const data = await res.json();
    render(data.items);
  }

  async function checkHealth() {
    try {
      const res = await fetch("/health");
      const data = await res.json();
      health.textContent = data.status;
      health.className = "healthy";
    } catch (e) {
      health.textContent = "unreachable";
      health.className = "unhealthy";
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const name = input.value.trim();
    if (!name) {
      setMessage("Please enter an item name.", true);
      return;
    }
    const res = await fetch("/api/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name })
    });
    const data = await res.json();
    if (!res.ok) {
      setMessage(data.error || "Request failed", true);
      return;
    }
    input.value = "";
    setMessage("Added “" + data.name + "”", false);
    await loadItems();
  });

  checkHealth();
  loadItems();
})();
