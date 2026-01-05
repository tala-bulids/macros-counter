const mealInput = document.getElementById("mealInput");
const countBtn = document.getElementById("countBtn");
const resultBox = document.getElementById("result");

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMissing(missing) {
  return `
    <div style="margin-top:10px">
      <p><b>Missing info:</b></p>
      <ul>
        ${missing.map(x => `<li>${escapeHtml(x)}</li>`).join("")}
      </ul>
      <p style="opacity:0.85;margin-top:8px">
        Tip: add grams like <b>70 g egg</b> or <b>120 g chicken breast</b>.
      </p>
    </div>
  `;
}

function renderTotals(totals) {
  return `
    <div style="margin-top:12px">
      <h4 style="margin:0 0 8px 0">Totals</h4>
      <ul style="margin:0;padding-left:18px">
        <li>Calories: <b>${totals.calories_kcal}</b></li>
        <li>Protein: <b>${totals.protein_g}</b> g</li>
        <li>Fat: <b>${totals.fat_g}</b> g</li>
        <li>Carbs: <b>${totals.carbs_g}</b> g</li>
      </ul>
    </div>
  `;
}

function renderBreakdown(breakdown) {
  return `
    <details style="margin-top:14px">
      <summary style="cursor:pointer"><b>Breakdown</b></summary>
      <pre style="white-space:pre-wrap;margin-top:10px">${escapeHtml(JSON.stringify(breakdown, null, 2))}</pre>
    </details>
  `;
}

countBtn.addEventListener("click", async () => {
  const text = mealInput.value.trim();

  if (!text) {
    resultBox.innerHTML = `<p>Please write your meal first 🙂</p>`;
    return;
  }

  resultBox.innerHTML = `<p>Counting...</p>`;

  try {
    // ✅ relative URL so it works locally AND on Render
    const res = await fetch(`/macros`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ text })
    });

    const data = await res.json();

    if (!res.ok) {
      resultBox.innerHTML = `
        <p><b>Error</b></p>
        <pre style="white-space:pre-wrap">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      `;
      return;
    }

    let html = `<p><b>You entered:</b> ${escapeHtml(text)}</p>`;

    if (data.missing_info && data.missing_info.length) {
      html += renderMissing(data.missing_info);
      resultBox.innerHTML = html;
      return;
    }

    html += renderTotals(data.totals);
    html += renderBreakdown(data.breakdown);

    resultBox.innerHTML = html;

  } catch (e) {
    resultBox.innerHTML = `<p><b>Error:</b> ${escapeHtml(e.message)}</p>`;
  }
});
