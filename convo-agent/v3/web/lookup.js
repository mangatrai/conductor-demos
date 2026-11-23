// v3 extra on top of v2's page (app.js is served from v2/web).
// When a chat turn ran the portfolio Sub Workflow, the response carries `lookup`:
// show a "looked up" card above the reply, linking to that sub-workflow execution.
(function () {
  let uiBase = "";
  const realFetch = window.fetch.bind(window);

  realFetch("api/config").then(r => r.json()).then(c => { uiBase = c.conductorUiUrl || ""; }).catch(() => {});

  function money(v) {
    return typeof v === "number" ? "$" + v.toLocaleString("en-US") : "";
  }

  function renderCard(lk) {
    const box = document.getElementById("messages");
    if (!box || !lk) return;
    const card = document.createElement("div");
    card.className = "lookup-card" + (lk.found ? "" : " miss");
    const what = lk.error ? "unavailable" : (lk.found ? "total value " + money(lk.totalValue) : "not found");
    card.textContent = "🔎 looked up: " + (lk.clientName || "?") + " - " + what;
    if (lk.subWorkflowId && uiBase) {
      const a = document.createElement("a");
      a.href = uiBase.replace(/\/$/, "") + "/execution/" + lk.subWorkflowId;
      a.target = "_blank";
      a.textContent = "sub workflow ↗";
      card.appendChild(a);
    }
    box.appendChild(card);
  }

  window.fetch = async function (input, init) {
    const res = await realFetch(input, init);
    const url = typeof input === "string" ? input : (input && input.url) || "";
    if (/\/chat(\?|$)/.test(url) && res.ok) {
      try { renderCard((await res.clone().json()).lookup); } catch (e) { /* not JSON: ignore */ }
    }
    return res;
  };
})();
