const state = { strategy: "iron_condor" };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function setStatus(text, error = false) {
  const node = $("#status");
  node.textContent = text;
  node.style.color = error ? "var(--warning)" : "";
}

function setBusy(busy) {
  $$("button").forEach((button) => { button.disabled = busy; });
  if (busy) setStatus("正在获取行情并计算");
}

function paramsFromForm() {
  const minYield = Number($("#yield-min").value) / 100;
  const maxYield = Number($("#yield-max").value) / 100;
  const dteMin = Number($("#dte-min").value);
  const dteMax = Number($("#dte-max").value);
  if (minYield > maxYield) throw new Error("最低收益率不能大于最高收益率");
  if (dteMin >= dteMax) throw new Error("最小 DTE 必须小于最大 DTE");
  return {
    quantile: Number($("#quantile").value) / 100,
    timeframe: $("#timeframe").value,
    range_pad: Number($("#range-pad").value),
    dte_min: dteMin,
    dte_max: dteMax,
    expiry_count: 2,
    min_yield: minYield,
    max_yield: maxYield,
    max_wing_steps: 6,
    symbols: ["510050", "510300"],
  };
}

function fillForm(params) {
  $("#quantile").value = Math.round(params.quantile * 100);
  $("#quantile-value").value = `P${Math.round(params.quantile * 100)}`;
  $("#timeframe").value = params.timeframe;
  $("#range-pad").value = params.range_pad.toFixed(2);
  $("#dte-min").value = params.dte_min;
  $("#dte-max").value = params.dte_max;
  $("#yield-min").value = (params.min_yield * 100).toFixed(1);
  $("#yield-max").value = (params.max_yield * 100).toFixed(1);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false && payload.error) {
    throw new Error(payload.error || `请求失败 (${response.status})`);
  }
  return payload;
}

async function run(path, outputSelector, extra = {}) {
  try {
    setBusy(true);
    const payload = await api(path, { params: paramsFromForm(), ...extra });
    $(outputSelector).className = "";
    $(outputSelector).innerHTML = payload.html;
    setStatus(payload.ok ? "计算完成" : "部分行情获取失败", !payload.ok);
  } catch (error) {
    $(outputSelector).className = "placeholder error";
    $(outputSelector).textContent = error.message;
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
}

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    state.strategy = tab.dataset.strategy;
    $("#strategy-title").textContent =
      state.strategy === "iron_condor" ? "铁鹰策略建议" : "宽跨策略建议";
    $("#advice-output").className = "placeholder";
    $("#advice-output").textContent = "点击“当前交易策略”获取建议";
  });
});

$("#quantile").addEventListener("input", (event) => {
  $("#quantile-value").value = `P${event.target.value}`;
});
$("#forecast-button").addEventListener("click", () => run("/api/forecast", "#forecast-output"));
$("#advice-button").addEventListener("click", () =>
  run("/api/advice", "#advice-output", { strategy: state.strategy })
);
$("#save-button").addEventListener("click", async () => {
  try {
    setBusy(true);
    const payload = await api("/api/config", { strategy: paramsFromForm() });
    fillForm(payload.strategy);
    setStatus("参数已保存，下次启动自动加载");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});

api("/api/config")
  .then((payload) => {
    fillForm(payload.strategy);
    setStatus("参数已加载");
  })
  .catch((error) => setStatus(error.message, true));
