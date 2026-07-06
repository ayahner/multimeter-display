CONTROL_HTML = """

<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>SquatchLab OWON XDM1241 Control</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; background:#111; color:#eee; }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 28px; }
    .header { display:flex; align-items:center; gap:16px; margin-bottom: 12px; flex-wrap:wrap; }
    .header img { height: 48px; width: auto; }
    h1 { margin: 0; font-size: 30px; }
    .sub { color:#aaa; margin-bottom: 24px; }
    .topRow { display:flex; flex-wrap:wrap; gap:12px; margin-bottom: 20px; }
    .functionBar { display:flex; flex-wrap:wrap; gap:8px; padding: 16px; background:#1b1b1b; border:1px solid #333; border-radius:18px; box-shadow: 0 12px 36px rgba(0,0,0,.35); }
    .settingsGrid { display:grid; grid-template-columns: repeat(2, minmax(300px, 1fr)); gap: 20px; }
    .card { background:#1b1b1b; border:1px solid #333; border-radius: 18px; padding: 22px; box-shadow: 0 12px 36px rgba(0,0,0,.35); }
    .reading { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 72px; letter-spacing:-3px; color:#69ff9a; line-height:1; }
    .unit { font-size: 30px; color:#bafccd; margin-left: 10px; }
    .mode { color:#ddd; font-size: 22px; margin: 14px 0 4px; }
    .row { color:#888; font-family: monospace; margin: 4px 0; }
    button { border:0; border-radius: 12px; padding: 11px 14px; margin: 6px 6px 6px 0; background:#2a2a2a; color:#eee; cursor:pointer; font-size:15px; }
    button:hover { background:#3a3a3a; }
    button.active { background:#9b5b00; color:white; }
    .buttons { display:flex; flex-wrap:wrap; margin-left:-6px; }
    .note { margin-top:12px; color:#ffd27d; min-height: 22px; }
    .err { color:#ff7777; white-space:pre-wrap; margin-top:10px; }
    .danger { background:#5a1b1b; color:#ffd0d0; }
    .danger:hover { background:#7a2525; }
    .action { background:#16405f; color:#d8f0ff; }
    .action:hover { background:#215a85; }
    .toggle { display:inline-flex; align-items:center; gap:8px; padding: 8px 12px; border-radius:999px; background:#2a2a2a; color:#eee; cursor:pointer; border:1px solid #444; }
    .toggle.on { background:#9b5b00; color:white; }
    select, input { background:#222; color:#eee; border:1px solid #444; border-radius:10px; padding:10px; margin-top:8px; font-size:15px; width:100%; box-sizing:border-box; }
    label { display:block; margin-top:12px; font-size:13px; color:#aaa; }
    .inline { display:flex; gap: 10px; align-items:center; }
    .inline input { width: 110px; }
    a { color:#79b8ff; }
    code { background:#282828; padding:2px 6px; border-radius:6px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <a href="https://squatchcode.com" target="_blank" rel="noopener noreferrer">
        <img src="/images/squatchlab-logo-and-name-320x132.png" alt="SquatchLab logo">
      </a>
      <div>
        <h1>OWON XDM1241 Control</h1>
      </div>
    </div>
    <div class="sub">
      OBS overlay: <a href="/overlay">/overlay</a> ·
      Graph: <a href="/graph">/graph</a> ·
      JSON: <a href="/api/status">/api/status</a> ·
      Log: <code>~/.owon/owon.log</code>
    </div>

    <div class="topRow">
      <div class="functionBar">
        {% for key, mode in modes.items() %}
        <button id="btn-{{key}}" onclick="setMode('{{key}}')">{{mode.label}}</button>
        {% endfor %}
      </div>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <div><span id="display" class="reading">----</span><span id="unit" class="unit"></span></div>
      <div id="mode" class="mode">---</div>
      <div class="row">Raw: <span id="raw">---</span></div>
      <div class="row">Function: <span id="function_raw">---</span></div>
      <div class="row">Speed: <span id="speed">---</span></div>
      <div class="row">OWON Range: <span id="range">---</span></div>
      <div class="row">Graph Display: <span id="graph_display">---</span></div>
      <div class="row">Port: <span id="port">---</span></div>
      <div class="row">Device: <span id="identity">---</span></div>
      <div class="note">Changing function clears the graph and rereads the slow settings once.</div>
      <button class="action" onclick="rereadSettings()">Reread OWON Settings</button>
      <button class="danger" onclick="shutdownApp()">Exit App</button>
      <div id="note" class="note"></div>
      <div id="error" class="err"></div>
    </div>

    <div class="settingsGrid">
      <div class="card">
        <h2>Overlay Settings</h2>
        <button class="action" onclick="resetOverlayDefaults()">Default Settings</button>
        <div class="toggle" id="overlayToggle" onclick="toggleOverlayToggle()">Auto decimals: <span id="overlayToggleLabel">ON</span></div>
        <label>Specific decimals</label>
        <div class="inline">
          <input id="overlayDecimals" type="number" min="0" max="9" step="1" value="3" onchange="saveOverlaySettings()">
        </div>
        <div class="note">These settings only affect the digital overlay view.</div>
      </div>

      <div class="card">
        <h2>Graph Settings</h2>
        <button class="action" onclick="resetGraphDefaults()">Default Settings</button>
        <div class="toggle" id="graphToggle" onclick="toggleGraphToggle()">Auto decimals: <span id="graphToggleLabel">ON</span></div>
        <label>Range mode</label>
        <select id="graphRangeMode" onchange="saveGraphSettings()">
          <option value="window">Window autoscale</option>
          <option value="preset">Preset range</option>
          <option value="custom">Custom range</option>
        </select>
        <label>Preset range</label>
        <select id="graphRangeKey" onchange="saveGraphSettings()"></select>
        <label>Custom min</label>
        <input id="graphCustomMin" type="number" step="any" onchange="saveGraphSettings()">
        <label>Custom max</label>
        <input id="graphCustomMax" type="number" step="any" onchange="saveGraphSettings()">
        <label>Specific decimals</label>
        <div class="inline">
          <input id="graphDecimals" type="number" min="0" max="9" step="1" value="3" onchange="saveGraphSettings()">
        </div>
        <button class="action" onclick="resetGraph()">Reset Graph</button>
        <div class="note">Reset Graph only clears the graph window; Reread OWON Settings is separate.</div>
      </div>
    </div>
  </div>
<script>
async function setMode(mode) {
  await fetch('/api/mode', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mode})
  });
  await refresh();
}

async function rereadSettings() {
  await fetch('/api/reread-settings', { method: 'POST' });
  await refresh();
}

async function resetGraph() {
  await fetch('/api/reset-graph', { method: 'POST' });
  await refresh();
}

async function toggleOverlayToggle() {
  const el = document.getElementById('overlayToggle');
  const on = !el.classList.contains('on');
  el.classList.toggle('on', on);
  document.getElementById('overlayToggleLabel').textContent = on ? 'ON' : 'OFF';
  await saveOverlaySettings();
}

async function toggleGraphToggle() {
  const el = document.getElementById('graphToggle');
  const on = !el.classList.contains('on');
  el.classList.toggle('on', on);
  document.getElementById('graphToggleLabel').textContent = on ? 'ON' : 'OFF';
  await saveGraphSettings();
}

async function saveOverlaySettings() {
  const on = document.getElementById('overlayToggle').classList.contains('on');
  const body = {
    auto_decimals: on,
    decimals: document.getElementById('overlayDecimals').value,
  };
  await fetch('/api/overlay-settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  await refresh();
}

async function saveGraphSettings() {
  const on = document.getElementById('graphToggle').classList.contains('on');
  const body = {
    range_mode: document.getElementById('graphRangeMode').value,
    range_key: document.getElementById('graphRangeKey').value,
    custom_min: document.getElementById('graphCustomMin').value,
    custom_max: document.getElementById('graphCustomMax').value,
    auto_decimals: on,
    decimals: document.getElementById('graphDecimals').value,
  };
  await fetch('/api/graph-settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  await refresh();
}

async function resetOverlayDefaults() {
  await fetch('/api/overlay-settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({auto_decimals: true, decimals: 3})
  });
  await refresh();
}

async function resetGraphDefaults() {
  await fetch('/api/graph-settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({range_mode: 'window', range_key: 'window', custom_min: '', custom_max: '', auto_decimals: true, decimals: 3})
  });
  await refresh();
}

async function shutdownApp() {
  const ok = confirm('Exit the OWON meter app?');
  if (!ok) return;
  await fetch('/api/shutdown', { method: 'POST' });
  document.body.innerHTML = '<div style="font-family:sans-serif;padding:40px;color:#eee;background:#111;height:100vh"><h1>OWON app exited</h1><p>You can close this window.</p></div>';
}

function updateRangeSelect(s) {
  const sel = document.getElementById('graphRangeKey');
  sel.innerHTML = '';
  for (const opt of s.graph_view_options || []) {
    const o = document.createElement('option');
    o.value = opt.key;
    o.textContent = opt.label;
    if (opt.key === s.graph_range_key) o.selected = true;
    sel.appendChild(o);
  }
}

async function refresh() {
  const res = await fetch('/api/status?ts=' + Date.now());
  const s = await res.json();

  document.getElementById('display').textContent = s.display_value;
  document.getElementById('unit').textContent = s.unit;
  document.getElementById('mode').textContent = s.mode_label;
  document.getElementById('raw').textContent = s.raw || '---';
  document.getElementById('function_raw').textContent = s.function_raw || '---';
  document.getElementById('speed').textContent = s.speed_label || '---';
  document.getElementById('range').textContent = (s.range_label || '---') + (s.range_raw ? ' (' + s.range_raw + ')' : '');
  document.getElementById('graph_display').textContent = s.graph_display_label || '---';
  // Show graph-precision current in the small graph display label area
  const graphCurrent = s.graph_display_value != null ? s.graph_display_value : s.display_value;
  const graphDisplayEl = document.getElementById('graph_display');
  if (graphDisplayEl) graphDisplayEl.textContent = `${s.graph_display_label || '---'} (Current: ${graphCurrent})`;
  document.getElementById('port').textContent = s.port || '---';
  document.getElementById('identity').textContent = s.identity || '---';
  document.getElementById('note').textContent = s.safety_note || '';
  document.getElementById('error').textContent = s.error ? ('Error: ' + s.error) : '';

  const overlayOn = !!s.overlay_auto_decimals;
  const graphOn = !!s.graph_auto_decimals;
  document.getElementById('overlayToggle').classList.toggle('on', overlayOn);
  document.getElementById('overlayToggleLabel').textContent = overlayOn ? 'ON' : 'OFF';
  document.getElementById('overlayDecimals').value = s.overlay_decimals ?? 3;
  document.getElementById('graphToggle').classList.toggle('on', graphOn);
  document.getElementById('graphToggleLabel').textContent = graphOn ? 'ON' : 'OFF';
  document.getElementById('graphDecimals').value = s.graph_decimals ?? 3;
  document.getElementById('graphRangeMode').value = s.graph_range_mode || 'window';
  document.getElementById('graphCustomMin').value = s.graph_custom_min ?? '';
  document.getElementById('graphCustomMax').value = s.graph_custom_max ?? '';
  updateRangeSelect(s);

  document.querySelectorAll('button').forEach(b => b.classList.remove('active'));
  const active = document.getElementById('btn-' + s.mode_key);
  if (active) active.classList.add('active');
}

setInterval(refresh, 250);
refresh();
</script>
</body>
</html>

"""

OVERLAY_HTML = """

<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {
      margin: 0;
      background: rgba(0,0,0,0);
      overflow: hidden;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    .box {
      box-sizing: border-box;
      width: 100vw;
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 14px;
      padding: 4px 12px 4px 6px;
      color: #ffb347;
      text-shadow: 0 0 10px rgba(255,179,71,.55);
      background: rgba(0,0,0,.72);
      border: 2px solid rgba(255,179,71,.45);
      border-radius: 12px;
    }
    .value {
      font-family: "DSEG7 Classic", "DSEG7Classic-Regular", "Digital-7", "Segment7", "DS-Digital", ui-monospace, monospace;
      font-size: 96px;
      font-weight: 400;
      line-height: .92;
      letter-spacing: 2px;
      min-width: 420px;
      text-align: right;
      font-variant-numeric: tabular-nums;
      -webkit-text-stroke: 1px rgba(255, 217, 145, .35);
      text-shadow:
        0 0 5px rgba(255,179,71,.9),
        0 0 14px rgba(255,128,0,.65),
        0 0 28px rgba(255,96,0,.35);
    }
    .right { display:flex; flex-direction:column; gap:2px; align-items:flex-start; min-width: 90px; }
    .unit {
      font-family: "DSEG7 Classic", "Digital-7", "Segment7", "DS-Digital", ui-monospace, monospace;
      font-size: 30px;
      color:#ffd7a1;
      line-height: 1;
      text-shadow: 0 0 8px rgba(255,179,71,.7);
    }
    .mode { font-size: 16px; color:#d8b58a; text-transform: uppercase; letter-spacing: 1px; line-height: 1; }
  </style>
</head>
<body>
  <div class="box">
    <div style="display:flex; align-items:center; margin-left:auto; gap:14px;">
      <div id="value" class="value">----</div>
      <div class="right">
        <div id="unit" class="unit"></div>
        <div id="mode" class="mode"></div>
      </div>
    </div>
  </div>
<script>
async function refresh() {
  const res = await fetch('/api/status?ts=' + Date.now());
  const s = await res.json();
  document.getElementById('value').textContent = s.error ? 'ERROR' : s.display_value;
  document.getElementById('unit').textContent = s.error ? '' : s.unit;
  document.getElementById('mode').textContent = s.error ? s.error : s.mode_label;
}
setInterval(refresh, 200);
refresh();
</script>
</body>
</html>

"""

GRAPH_HTML = """

<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>SquatchLab OWON XDM1241 Graph</title>
<style>
html, body {
  margin: 0;
  padding: 0;
  background: #000;
  overflow: hidden;
  color: #ff8a00;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
#wrap {
  width: 100vw;
  height: 100vh;
  box-sizing: border-box;
  padding: 2vh 1.6vw;
  position: relative;
  background: #000;
}
.title {
  text-align: center;
  font-size: clamp(14px, 3.3vh, 34px);
  font-weight: 700;
  height: 6vh;
  line-height: 6vh;
  letter-spacing: 0.08em;
  white-space: nowrap;
}
.top, .logging {
  position: absolute;
  top: 2vh;
  border: 1px solid #ff8a00;
  border-radius: 0.8vh;
  padding: 1vh 1vw;
  font-size: clamp(10px, 1.9vh, 18px);
  line-height: 1.35;
}
.top { left: 1.6vw; }
.logging { right: 1.6vw; }
.chartBox {
  position: absolute;
  left: 1.6vw;
  right: 1.6vw;
  top: 13vh;
  bottom: 20vh;
  border: 1px solid #ff8a00;
  border-radius: 0.8vh;
  padding: 1.2vh 1vw;
  box-sizing: border-box;
}
canvas { width: 100%; height: 100%; }
.bottom {
  position: absolute;
  left: 1.6vw;
  right: 1.6vw;
  bottom: 5vh;
  height: 12vh;
  display: grid;
  grid-template-columns: 1.2fr 1fr 1.35fr 1.1fr 1.1fr 2.2fr;
  gap: 0.6vw;
}
.panel {
  border: 1px solid #ff8a00;
  border-radius: 0.8vh;
  padding: 1.2vh 1vw;
  box-sizing: border-box;
  font-size: clamp(9px, 1.75vh, 17px);
  line-height: 1.3;
  overflow: hidden;
  white-space: nowrap;
}
.big {
  font-size: clamp(12px, 2.6vh, 25px);
  font-weight: 700;
}
.footer {
  position: absolute;
  left: 1.6vw;
  right: 1.6vw;
  bottom: 1.5vh;
  font-size: clamp(8px, 1.4vh, 14px);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
</head>
<body>
<div id="wrap">
  <div class="title">SQUATCHLAB OWON XDM1241 METER GRAPH</div>

  <div class="top">
    MODE<br>
    <span id="mode">UNKNOWN</span><br>
    <span id="unitTop"></span>
  </div>

  <div class="logging">
    GRAPH ●<br>
    <span id="runtime">00:00:00</span>
  </div>

  <div class="chartBox">
    <canvas id="chart"></canvas>
  </div>

  <div class="bottom">
    <div class="panel">METER SPEED<br><span id="speed">UNKNOWN</span></div>
    <div class="panel">RANGE<br><span id="range">UNKNOWN</span></div>
    <div class="panel">LATEST<br><span class="big" id="latest">----</span></div>
    <div class="panel">MIN<br><span class="big" id="min">--</span></div>
    <div class="panel">MAX<br><span class="big" id="max">--</span></div>
    <div class="panel">DISPLAY<br><span id="displayRange">--</span></div>
  </div>

  <div class="footer" id="footer">● CONNECTED</div>
</div>

<script>
const ORANGE = "#ff8a00";
const ORANGE_DIM = "#8a4a00";
const BLACK = "#000000";

const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.floor(rect.width * window.devicePixelRatio);
  canvas.height = Math.floor(rect.height * window.devicePixelRatio);
  ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
}

window.addEventListener("resize", resizeCanvas);
resizeCanvas();

function axisLabel(v, decimals) {
  return Number(v).toFixed(decimals);
}

function draw(data) {
  resizeCanvas();

  const rect = canvas.getBoundingClientRect();
  const w = rect.width;
  const h = rect.height;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = BLACK;
  ctx.fillRect(0, 0, w, h);

  const left = Math.max(52, w * 0.095);
  const right = Math.max(12, w * 0.025);
  const top = Math.max(18, h * 0.08);
  const bottom = Math.max(24, h * 0.12);

  const plotW = w - left - right;
  const plotH = h - top - bottom;

  let yMin = Number(data.graph_y_min);
  let yMax = Number(data.graph_y_max);
  if (!Number.isFinite(yMin)) yMin = 0;
  if (!Number.isFinite(yMax)) yMax = 1;
  if (yMax < yMin) {
    const tmp = yMax;
    yMax = yMin;
    yMin = tmp;
  }
  if (yMax === yMin) {
    const pad = Math.max(Math.abs(yMin) * 0.1, 0.1);
    yMin -= pad;
    yMax += pad;
  }
  const xMax = data.graph_window_seconds;
  const decimals = data.graph_decimals;

  const axisFont = Math.max(9, Math.min(18, h * 0.045));
  const labelFont = Math.max(10, Math.min(18, h * 0.048));

  ctx.strokeStyle = ORANGE_DIM;
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);

  ctx.font = axisFont + "px monospace";
  ctx.fillStyle = ORANGE;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";

  for (let i = 0; i <= 5; i++) {
    const t = i / 5;
    const yVal = yMin + (yMax - yMin) * (1 - t);
    const y = top + plotH * t;

    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + plotW, y);
    ctx.stroke();

    ctx.setLineDash([]);
    ctx.fillText(axisLabel(yVal, decimals), left - 8, y);
    ctx.setLineDash([4, 4]);
  }

  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  for (let i = 0; i <= 6; i++) {
    const t = i / 6;
    const xVal = xMax * t;
    const x = left + plotW * t;

    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotH);
    ctx.stroke();

    ctx.setLineDash([]);
    ctx.fillText(Math.round(xVal).toString(), x, top + plotH + 8);
    ctx.setLineDash([4, 4]);
  }

  ctx.setLineDash([]);
  ctx.strokeStyle = ORANGE;
  ctx.lineWidth = 1.5;
  ctx.strokeRect(left, top, plotW, plotH);

  ctx.fillStyle = ORANGE;
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.font = labelFont + "px monospace";
  ctx.fillText(data.mode_label.toUpperCase() + " (" + data.base_unit + ")", left + 14, top + 10);
  ctx.fillText(data.graph_display_label, left + 14, top + 10 + labelFont * 1.35);

  const points = data.graph_points || [];
  if (points.length > 1 && yMax !== yMin) {
    const newest = points[points.length - 1][0];
    const xStart = Math.max(0, newest - xMax);

    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, plotW, plotH);
    ctx.clip();

    ctx.beginPath();
    ctx.strokeStyle = ORANGE;
    ctx.lineWidth = Math.max(1.5, h * 0.008);

    let started = false;

    for (const p of points) {
      const elapsed = p[0];
      const val = p[1];

      if (val === null || val === undefined) continue;

      const x = left + ((elapsed - xStart) / xMax) * plotW;
      const y = top + (1 - ((val - yMin) / (yMax - yMin))) * plotH;

      if (x < left || x > left + plotW) continue;

      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }

    ctx.stroke();
    ctx.restore();
  }

  document.getElementById("mode").textContent = data.mode_label;
  document.getElementById("unitTop").textContent = data.base_unit || "";
  document.getElementById("runtime").textContent = data.graph_runtime || "00:00:00";
  document.getElementById("speed").textContent = data.speed_label || "UNKNOWN";
  document.getElementById("range").textContent = data.range_label ? (data.range_label + (data.range_is_auto ? " / AUTO" : "")) : "UNKNOWN";
  document.getElementById("latest").textContent = data.display_value + (data.unit ? " " + data.unit : "");
  document.getElementById("min").textContent = data.graph_min === null ? "--" : Number(data.graph_min).toFixed(data.graph_decimals);
  document.getElementById("max").textContent = data.graph_max === null ? "--" : Number(data.graph_max).toFixed(data.graph_decimals);
  document.getElementById("displayRange").textContent = data.graph_display_label || "--";
  document.getElementById("footer").textContent =
    "● CONNECTED   Port: " + data.port +
    "   |   BAUD: " + data.baud +
    "   |   RAW: " + data.raw;
}

async function refresh() {
  try {
    const res = await fetch('/api/status?ts=' + Date.now(), {cache: 'no-store'});
    const data = await res.json();
    draw(data);
  } catch (e) {
  }
}

setInterval(refresh, 100);
refresh();
</script>
</body>
</html>

"""
