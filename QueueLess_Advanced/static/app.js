(function () {
  // ---- Customer: live token tracking (polls the REST API every 5 s) ----
  const box = document.getElementById("live-token");
  if (box) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    let last = document.getElementById("status").textContent.trim();
    async function tick() {
      try {
        const r = await fetch("/api/queues/status/?token_id=" + box.dataset.id, { credentials: "same-origin" });
        if (!r.ok) return;
        const d = await r.json(), p = d.prediction;
        const label = d.status.charAt(0) + d.status.slice(1).toLowerCase().replace("_", "-");
        set("status", label); set("position", p.position); set("eta", p.minutes);
        set("range", p.low + "\u2013" + p.high); set("confidence", p.confidence);
        document.getElementById("status").className = "pill status-" + d.status;
        const why = document.getElementById("why");
        if (why) why.innerHTML = p.explanation.map(t => "<li></li>").join("");
        if (why) p.explanation.forEach((t, i) => why.children[i].textContent = t);
        document.getElementById("called-banner").hidden = d.status !== "CALLED";
        document.title = d.status === "WAITING" ? "~" + p.minutes + " min | QueueLess AI" : label + " | QueueLess AI";
        if (label !== last && d.status === "CALLED" && navigator.vibrate) navigator.vibrate([200, 100, 200]);
        last = label;
      } catch (e) { /* offline: try again next tick */ }
    }
    setInterval(tick, 5000);
  }

  // ---- Provider: auto-refresh the live queue panel without losing page state ----
  const live = document.getElementById("staff-live");
  if (live) {
    setInterval(async () => {
      const a = document.activeElement;
      if (a && ["SELECT", "INPUT", "TEXTAREA"].includes(a.tagName)) return;
      try {
        const r = await fetch(location.href, { credentials: "same-origin" });
        const doc = new DOMParser().parseFromString(await r.text(), "text/html");
        const fresh = doc.getElementById("staff-live");
        if (fresh) live.innerHTML = fresh.innerHTML;
      } catch (e) {}
    }, 8000);
  }
})();
