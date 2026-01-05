// IMPORTANT:
// Open the website from Flask: http://127.0.0.1:5001/
// Not from Live Server 5500.

const API = "http://127.0.0.1:5001";

const textarea = document.getElementById("mealInput");
const btn = document.getElementById("countBtn");
const resultBox = document.getElementById("result");

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderTotals(t) {
  return `
    <div style="margin-top:12px">
      <h4 style="margin:0 0 8px 0">Totals</h4>
      <ul style="margin:0;padding-left:18px">
        <li>Calories: <b>${escapeHtml(t.calories_kcal)}</b> kcal</li>
        <li>Protein: <b>${escapeHtml(t.protein_g)}</b> g</li>
        <li>Fat: <b>${escapeHtml(t.fat_g)}</b> g</li>
        <li>Carbs: <b>${escapeHtml(t.carbs_g)}</b> g</li>
      </ul>
    </div>
  `;
}

function renderMissing(missing) {
  return `
    <div style="margin-top:12px">
      <p style="margin:0 0 8px 0"><b>Missing info:</b></p>
      <ul style="margin:0;padding-left:18px">
        ${missing.map(x => `<li>${escapeHtml(x)}</li>`).join("")}
      </ul>
      <p style="opacity:0.85;margin-top:10px">
        Tip: Try adding grams like <b>"50 g egg"</b>, or if it’s pieces/slices we can estimate.
      </p>
    </div>
  `;
}

function renderBreakdown(breakdown) {
  return `
    <details style="margin-top:14px">
      <summary style="cursor:pointer"><b>Breakdown</b></summary>
      <pre style="white-space:pre-wrap;margin-top:10px">${escapeHtml(
        JSON.stringify(breakdown, null, 2)
      )}</pre>
    </details>
  `;
}

async function postJson(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify(payload),
  });

  // Read as text first to avoid "Unexpected end of JSON"
  const raw = await res.text();

  let data = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch (e) {
    data = null;
  }

  return { ok: res.ok, status: res.status, raw, data };
}

btn.addEventListener("click", async () => {
  const text = textarea.value.trim();

  if (!text) {
    resultBox.innerHTML = `<p>Please write your meal first 🙂</p>`;
    return;
  }

  resultBox.innerHTML = `<p>Counting...</p>`;

  try {
    const r = await postJson(`${API}/macros`, { text });

    // If server returned non-OK
    if (!r.ok) {
      resultBox.innerHTML = `
        <p><b>Error</b> (HTTP ${escapeHtml(r.status)})</p>
        <pre style="white-space:pre-wrap">${escapeHtml(r.raw)}</pre>
      `;
      return;
    }

    // If empty or invalid JSON
    if (!r.data) {
      resultBox.innerHTML = `
        <p><b>Error:</b> Server returned invalid/empty JSON.</p>
        <pre style="white-space:pre-wrap">${escapeHtml(r.raw)}</pre>
      `;
      return;
    }

    const data = r.data;

    // Always show entered text
    let html = `<p><b>You entered:</b> ${escapeHtml(text)}</p>`;

    // If missing info exists
    if (data.missing_info && data.missing_info.length) {
      html += renderMissing(data.missing_info);
      resultBox.innerHTML = html;
      return;
    }

    // Totals
    if (data.totals) html += renderTotals(data.totals);

    // Breakdown
    if (data.breakdown) html += renderBreakdown(data.breakdown);

    resultBox.innerHTML = html;
  } catch (e) {
    resultBox.innerHTML = `<p><b>Error:</b> ${escapeHtml(e.message)}</p>`;
  }
});
