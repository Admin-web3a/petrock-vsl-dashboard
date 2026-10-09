#!/usr/bin/env python3
"""
PetRock VSL Funnel Dashboard Generator
Embeds raw lead data as JSON; all filtering and chart rendering is client-side.
Charts: daily leads, daily payments, deal cycle, funnel (with UTM Content filter),
UTM Source, UTM Term.
Run hourly via GitHub Actions.
"""

import urllib.request
import json
import os
import datetime

# ── Config ─────────────────────────────────────────────────────────────────────

TOKEN  = os.environ["AMO_TOKEN"]
DOMAIN = "simmihur.amocrm.ru"

PIPELINE_ID           = 11376958
UTM_SOURCE_FIELD_ID   = 1323539
UTM_CONTENT_FIELD_ID  = 1323545
UTM_TERM_FIELD_ID     = 1323547
VSL_TEST_RUN_FIELD_ID = 1324559

# 2026-10-07 00:00 МСК
CREATED_FROM = 1791320400

FUNNEL_STAGES = [
    (89144274, "Посетил лендинг"),
    (89144278, "Открыл форму"),
    (89144282, "Оставил email"),
    (89144286, "Перешёл в Telegram"),
    (89144290, "Запустил бота"),
    (89144294, "Открыл видео"),
    (89144298, "Начал просмотр"),
    (89144302, "Дошёл до 25% видео"),
    (89144306, "Дошёл до 50% видео"),
    (89144310, "Дошёл до 75% видео"),
    (89144314, "Досмотрел до оффера"),
    (89144318, "Получил оффер в боте"),
    (89144322, "Открыл оплату"),
    (89144326, "Заполнил данные оплаты"),
    (89144330, "Платёж создан"),
    (89144334, "Форма оплаты готова"),
    (142,      "Оплачено · доступ выдан"),
]

STATUS_INDEX = {sid: i for i, (sid, _) in enumerate(FUNNEL_STAGES)}

# Тупиковые статусы не лежат на пути к оплате: считаем лид дошедшим
# до последнего этапа, который гарантированно был пройден.
STATUS_INDEX[89144338] = STATUS_INDEX[89144334]  # Оплата не прошла → Форма оплаты готова
STATUS_INDEX[89144342] = STATUS_INDEX[89144318]  # Срок предложения истёк → Получил оффер в боте

PAID_IDX = STATUS_INDEX[142]

EXCLUDED_STATUSES = {
    89144270,  # Неразобранное
    143,       # Закрыто без оплаты
}

# ── AMO helpers ────────────────────────────────────────────────────────────────

def amo_get(path, params=None):
    url = f"https://{DOMAIN}{path}"
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def fetch_all_leads():
    leads = []
    page = 1
    while True:
        data = amo_get("/api/v4/leads", {
            "page": page,
            "limit": 250,
            "filter[pipeline_id]": PIPELINE_ID,
            "filter[created_at][from]": CREATED_FROM,
        })
        batch = (data.get("_embedded") or {}).get("leads", [])
        if not batch:
            break
        leads.extend(batch)
        if len(batch) < 250:
            break
        page += 1
    return leads


def get_custom_field(lead, field_id):
    for cf in lead.get("custom_fields_values") or []:
        if cf["field_id"] == field_id:
            vals = cf.get("values") or []
            if vals:
                return str(vals[0].get("value") or "").strip()
    return None


def is_test_lead(lead):
    if (get_custom_field(lead, VSL_TEST_RUN_FIELD_ID) or "").lower() == "yes":
        return True
    return (get_custom_field(lead, UTM_SOURCE_FIELD_ID) or "").lower() == "test"


def build_lead_record(lead):
    if lead.get("status_id") in EXCLUDED_STATUSES or is_test_lead(lead):
        return None
    status_idx = STATUS_INDEX.get(lead.get("status_id"))
    if status_idx is None:
        return None
    return {
        "c":  lead.get("created_at", 0),                              # created_at unix ts
        "s":  status_idx,                                              # funnel stage index
        "u":  get_custom_field(lead, UTM_SOURCE_FIELD_ID) or "",       # utm_source
        "t":  get_custom_field(lead, UTM_CONTENT_FIELD_ID) or "",      # utm_content
        "m":  get_custom_field(lead, UTM_TERM_FIELD_ID) or "",         # utm_term
        "p":  lead.get("price") or 0,                                  # budget (price field)
        "d":  lead.get("closed_at") or 0,                              # closed_at (won date)
        "ua": lead.get("updated_at") or 0,                             # updated_at (fallback)
    }


# ── HTML generation ────────────────────────────────────────────────────────────

def build_html(leads_raw):
    updated_str = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
                   .strftime("%d.%m.%Y %H:%M МСК"))

    records = [r for r in (build_lead_record(l) for l in leads_raw) if r]
    leads_json  = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    stages_json = json.dumps([name for _, name in FUNNEL_STAGES], ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="3600">
<title>PetRock VSL Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:     #0f0f0f;
    --card:   #1a1a1a;
    --border: #2a2a2a;
    --text:   #e8e8e8;
    --sub:    #888;
    --accent: #ff7043;
    --green:  #4caf50;
    --orange: #ff9800;
    --blue:   #42a5f5;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    padding: 24px 20px;
  }}
  h1 {{ text-align: center; font-size: 1.5rem; margin-bottom: 4px; }}
  .subtitle {{ text-align: center; color: var(--sub); font-size: .85rem; margin-bottom: 20px; }}

  /* ── Date filter ── */
  .filter-bar {{
    display: flex; flex-wrap: wrap; justify-content: center;
    align-items: center; gap: 8px; margin-bottom: 28px;
  }}
  .preset-btn {{
    background: var(--card); border: 1px solid var(--border);
    color: var(--sub); border-radius: 6px; padding: 6px 14px;
    font-size: .85rem; cursor: pointer; transition: border-color .15s, color .15s;
  }}
  .preset-btn:hover {{ border-color: var(--accent); color: var(--text); }}
  .preset-btn.active {{ border-color: var(--accent); color: var(--accent); background: #2a1a14; }}
  .src-btn {{
    background: var(--card); border: 1px solid var(--border);
    color: var(--sub); border-radius: 6px; padding: 5px 12px;
    font-size: .82rem; cursor: pointer; transition: border-color .15s, color .15s;
  }}
  .src-btn:hover {{ border-color: var(--accent); color: var(--text); }}
  .src-btn.active {{ border-color: var(--accent); color: var(--accent); background: #2a1a14; }}
  .date-sep {{ color: var(--sub); font-size: .85rem; }}
  input[type=date] {{
    background: var(--card); border: 1px solid var(--border);
    color: var(--text); border-radius: 6px; padding: 5px 10px;
    font-size: .85rem; cursor: pointer;
  }}
  input[type=date]:focus {{ outline: none; border-color: var(--accent); }}

  /* ── Stats ── */
  .stat-row {{
    display: flex; justify-content: center; gap: 16px;
    flex-wrap: wrap; margin-bottom: 32px;
  }}
  .stat {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 24px; text-align: center; min-width: 140px;
  }}
  .stat .val {{ font-size: 2rem; font-weight: 700; color: var(--accent); }}
  .stat .lbl {{ font-size: .8rem; color: var(--sub); margin-top: 4px; }}

  /* ── Cards & charts ── */
  .charts {{ display: flex; flex-direction: column; gap: 28px; max-width: 1000px; margin: 0 auto; }}
  .card {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px 24px;
  }}
  .card h2 {{
    font-size: 1rem; margin-bottom: 16px; color: var(--text);
    padding-bottom: 10px; border-bottom: 1px solid var(--border);
  }}

  .footer {{ text-align: center; color: var(--sub); font-size: .75rem; margin-top: 32px; }}
</style>
</head>
<body>

<h1>🎬 PetRock VSL Dashboard</h1>
<p class="subtitle">Обновлено: {updated_str}</p>

<div class="filter-bar">
  <button class="preset-btn" data-preset="today">Сегодня</button>
  <button class="preset-btn" data-preset="7d">7 дней</button>
  <button class="preset-btn active" data-preset="30d">30 дней</button>
  <button class="preset-btn" data-preset="all">Весь период</button>
  <span class="date-sep">|</span>
  <input type="date" id="dateFrom">
  <span class="date-sep">—</span>
  <input type="date" id="dateTo">
</div>

<div class="filter-bar" style="margin-top:-18px;margin-bottom:20px;justify-content:flex-start;padding-left:8px">
  <span class="date-sep" style="white-space:nowrap">UTM Source:</span>
  <div id="globalSourceBar" style="display:flex;flex-wrap:wrap;gap:6px"></div>
</div>

<div class="stat-row">
  <div class="stat"><div class="val" id="statTotal">—</div><div class="lbl">Всего лидов</div></div>
  <div class="stat"><div class="val" id="statPaid" style="color:var(--green)">—</div><div class="lbl">Оплатили</div></div>
  <div class="stat"><div class="val" id="statConv" style="color:var(--orange)">—</div><div class="lbl">Конверсия в оплату</div></div>
  <div class="stat"><div class="val" id="statRev" style="color:var(--green)">—</div><div class="lbl">Выручка</div></div>
  <div class="stat"><div class="val" id="statAvgCycle" style="color:var(--blue)">—</div><div class="lbl">Средний цикл</div></div>
  <div class="stat"><div class="val" id="statMedCycle" style="color:var(--blue)">—</div><div class="lbl">Медиана цикла</div></div>
</div>

<div class="charts">

  <div class="card">
    <h2>Лиды по дням</h2>
    <div style="position:relative;height:260px"><canvas id="dailyChart"></canvas></div>
  </div>

  <div class="card">
    <h2>Оплаты по дням</h2>
    <div style="position:relative;height:260px"><canvas id="paidChart"></canvas></div>
  </div>

  <div class="card">
    <h2>Цикл сделки: от регистрации до оплаты</h2>
    <div id="cycleStats" style="font-size:13px;color:var(--sub);margin-bottom:10px"></div>
    <div style="position:relative;height:260px"><canvas id="cycleChart"></canvas></div>
  </div>

  <div class="card">
    <h2>Воронка: сколько лидов прошли через каждый этап</h2>
    <div id="contentFilterBar" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px"></div>
    <div style="position:relative;height:480px"><canvas id="funnelChart"></canvas></div>
  </div>

  <div class="card">
    <h2>Распределение по UTM Source</h2>
    <div style="position:relative;height:300px"><canvas id="utmChart"></canvas></div>
  </div>

  <div class="card">
    <h2>Распределение по UTM Term</h2>
    <div style="position:relative;height:300px"><canvas id="termChart"></canvas></div>
  </div>

</div>

<p class="footer">Данные из amoCRM · автообновление каждый час</p>

<script>
const ALL_LEADS   = {leads_json};
const STAGE_NAMES = {stages_json};
const DATA_FROM   = {CREATED_FROM};
const PAID_IDX    = {PAID_IDX};

const C = {{
  teal:   'rgba(0,188,212,0.85)',  green:  'rgba(76,175,80,0.85)',
  blue:   'rgba(33,150,243,0.85)', orange: 'rgba(255,152,0,0.85)',
  pink:   'rgba(233,30,99,0.85)',  purple: 'rgba(108,99,255,0.85)',
  coral:  'rgba(255,112,67,0.85)',
}};
const PALETTE = [C.coral, C.blue, C.green, C.orange, C.pink, C.purple, C.teal,
  'rgba(255,235,59,.85)','rgba(121,85,72,.85)','rgba(96,125,139,.85)',
  'rgba(244,67,54,.85)','rgba(156,39,176,.85)','rgba(3,169,244,.85)'];

Chart.defaults.color = '#888';
Chart.defaults.borderColor = '#2a2a2a';

// ── Chart instances ───────────────────────────────────────────────────────────

const dailyChart = new Chart(document.getElementById('dailyChart'), {{
  type: 'bar',
  data: {{ labels: [], datasets: [{{ label: 'Лидов создано', data: [], backgroundColor: C.coral, borderRadius: 4 }}] }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.parsed.y}} лидов` }} }} }},
    scales: {{ y: {{ beginAtZero: true, ticks: {{ precision: 0 }}, grid: {{ color: '#2a2a2a' }} }}, x: {{ grid: {{ display: false }} }} }}
  }}
}});

const paidChart = new Chart(document.getElementById('paidChart'), {{
  type: 'bar',
  data: {{ labels: [], datasets: [{{ label: 'Оплат', data: [], backgroundColor: C.green, borderRadius: 4 }}] }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.parsed.y}} оплат` }} }} }},
    scales: {{ y: {{ beginAtZero: true, ticks: {{ precision: 0 }}, grid: {{ color: '#2a2a2a' }} }}, x: {{ grid: {{ display: false }} }} }}
  }}
}});

const CYCLE_BUCKETS = [
  {{ label: '< 1 ч',   min: 0,   max: 1    }},
  {{ label: '1–6 ч',   min: 1,   max: 6    }},
  {{ label: '6–24 ч',  min: 6,   max: 24   }},
  {{ label: '1–3 д',   min: 24,  max: 72   }},
  {{ label: '3–7 д',   min: 72,  max: 168  }},
  {{ label: '7–30 д',  min: 168, max: 720  }},
];

const cycleChart = new Chart(document.getElementById('cycleChart'), {{
  type: 'bar',
  data: {{
    labels: CYCLE_BUCKETS.map(b => b.label),
    datasets: [{{ label: 'Оплат', data: new Array(CYCLE_BUCKETS.length).fill(0),
      backgroundColor: C.blue, borderRadius: 4 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.parsed.y}} оплат` }} }} }},
    scales: {{ y: {{ beginAtZero: true, ticks: {{ precision: 0 }}, grid: {{ color: '#2a2a2a' }} }},
               x: {{ grid: {{ display: false }} }} }}
  }}
}});

const funnelChart = new Chart(document.getElementById('funnelChart'), {{
  type: 'bar',
  data: {{ labels: STAGE_NAMES, datasets: [{{ label: 'Лидов прошло через этап', data: [], backgroundColor: C.coral, borderRadius: 4 }}] }},
  options: {{
    indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.parsed.x}} лидов` }} }} }},
    scales: {{ x: {{ beginAtZero: true, grid: {{ color: '#2a2a2a' }} }}, y: {{ grid: {{ display: false }} }} }}
  }}
}});

const utmChart = new Chart(document.getElementById('utmChart'), {{
  type: 'bar',
  data: {{ labels: [], datasets: [{{ label: 'Лидов', data: [], backgroundColor: [], borderRadius: 4 }}] }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.parsed.y}} лидов` }} }} }},
    scales: {{ y: {{ beginAtZero: true, grid: {{ color: '#2a2a2a' }} }}, x: {{ grid: {{ display: false }} }} }}
  }}
}});

const termChart = new Chart(document.getElementById('termChart'), {{
  type: 'bar',
  data: {{ labels: [], datasets: [{{ label: 'Лидов', data: [], backgroundColor: [], borderRadius: 4 }}] }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.parsed.y}} лидов` }} }} }},
    scales: {{ y: {{ beginAtZero: true, ticks: {{ precision: 0 }}, grid: {{ color: '#2a2a2a' }} }}, x: {{ grid: {{ display: false }} }} }}
  }}
}});

// ── State ─────────────────────────────────────────────────────────────────────
let currentLeads      = [];
let activeContent     = '__all__';
let activeGlobalSrc   = '__all__';
let filterFromTs      = DATA_FROM;
let filterToTs        = Math.floor(Date.now()/1000);

// ── Helpers ───────────────────────────────────────────────────────────────────
function toMidnightTs(dateStr) {{
  const [y,m,d] = dateStr.split('-').map(Number);
  return Date.UTC(y, m-1, d) / 1000 - 3*3600;
}}
function todayStr() {{
  return new Date().toLocaleDateString('sv-SE', {{timeZone:'Europe/Moscow'}});
}}
function nDaysAgoStr(n) {{
  const d = new Date();
  d.setDate(d.getDate() - n + 1);
  return d.toLocaleDateString('sv-SE', {{timeZone:'Europe/Moscow'}});
}}
function mskDate(ts) {{
  return new Date((ts + 3*3600)*1000).toISOString().slice(0,10);
}}
function paidTs(l) {{
  return l.d > 0 ? l.d : l.ua;
}}

// ── Filter buttons builder ────────────────────────────────────────────────────
function buildFilterButtons(containerId, leads, keyFn, activeVal, onSelect, minCount = 0) {{
  const counts = {{}};
  leads.forEach(l => {{ const k = keyFn(l); if (k) counts[k] = (counts[k]||0)+1; }});
  const values = Object.keys(counts).filter(k => counts[k] >= minCount).sort();
  const bar = document.getElementById(containerId);
  bar.innerHTML = '';
  ['__all__', ...values].forEach(val => {{
    const btn = document.createElement('button');
    btn.className = 'preset-btn' + (val === activeVal ? ' active' : '');
    btn.textContent = val === '__all__' ? 'Все' : val;
    btn.dataset.val = val;
    btn.addEventListener('click', () => {{
      bar.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      onSelect(val);
    }});
    bar.appendChild(btn);
  }});
}}

function renderDistribution(chart, leads, keyFn) {{
  const map = {{}};
  leads.forEach(l => {{ const k = keyFn(l) || '(не указан)'; map[k] = (map[k]||0)+1; }});
  const sorted = Object.entries(map).sort((a,b) => b[1]-a[1]);
  chart.data.labels = sorted.map(e => e[0]);
  chart.data.datasets[0].data = sorted.map(e => e[1]);
  chart.data.datasets[0].backgroundColor = sorted.map((_,i) => PALETTE[i%PALETTE.length]);
  chart.update();
}}

// ── Main render ───────────────────────────────────────────────────────────────
function render(leads) {{
  currentLeads = leads;
  const paidLeads = leads.filter(l => l.s >= PAID_IDX);

  // Daily chart — все дни в пределах фильтра, включая нулевые
  const dayMap = {{}};
  leads.forEach(l => {{ const day = mskDate(l.c); dayMap[day] = (dayMap[day]||0) + 1; }});
  const startDay = mskDate(filterFromTs);
  const endDay   = mskDate(filterToTs);
  const days = [];
  for (let d = new Date(startDay + 'T00:00:00Z'); d.toISOString().slice(0,10) <= endDay; d.setUTCDate(d.getUTCDate()+1)) {{
    days.push(d.toISOString().slice(0,10));
  }}
  dailyChart.data.labels = days.map(d => d.slice(5));
  dailyChart.data.datasets[0].data = days.map(d => dayMap[d] || 0);
  dailyChart.update();

  // Daily paid chart — по дате перевода в «Оплачено»
  const paidMap = {{}};
  paidLeads.forEach(l => {{
    const day = mskDate(paidTs(l));
    paidMap[day] = (paidMap[day]||0) + 1;
  }});
  paidChart.data.labels = days.map(d => d.slice(5));
  paidChart.data.datasets[0].data = days.map(d => paidMap[d] || 0);
  paidChart.update();

  // Cycle chart — цикл сделки в часах
  (function() {{
    const rawCycles = [];
    paidLeads.forEach(l => {{
      const h = (paidTs(l) - l.c) / 3600;
      if (h > 0) rawCycles.push(h);
    }});
    const over = rawCycles.filter(h => h > 720).length;
    const cycles = (over / (rawCycles.length || 1) < 0.05)
      ? rawCycles.filter(h => h <= 720)
      : rawCycles;
    function fmtH(h) {{
      if (h === null || isNaN(h)) return '—';
      return h < 24 ? h.toFixed(1) + ' ч' : (h/24).toFixed(1) + ' д';
    }}
    const avg = cycles.length ? cycles.reduce((a,b)=>a+b,0)/cycles.length : null;
    const sorted = [...cycles].sort((a,b)=>a-b);
    const med = sorted.length ? (sorted.length%2===0
      ? (sorted[sorted.length/2-1]+sorted[sorted.length/2])/2
      : sorted[Math.floor(sorted.length/2)]) : null;
    document.getElementById('statAvgCycle').textContent = fmtH(avg);
    document.getElementById('statMedCycle').textContent = fmtH(med);
    const note = over > 0 && over/rawCycles.length < 0.05
      ? `Исключено ${{over}} сд. > 30 дней (< 5%)` : '';
    document.getElementById('cycleStats').textContent =
      cycles.length ? `${{cycles.length}} оплат · среднее ${{fmtH(avg)}} · медиана ${{fmtH(med)}}${{note ? '  |  ' + note : ''}}` : 'Нет данных';
    const buckets = new Array(CYCLE_BUCKETS.length).fill(0);
    cycles.forEach(h => {{
      const i = CYCLE_BUCKETS.findIndex(b => h >= b.min && h < b.max);
      if (i >= 0) buckets[i]++;
    }});
    cycleChart.data.datasets[0].data = buckets;
    cycleChart.update();
  }})();

  // Summary
  const n    = leads.length;
  const paid = paidLeads.length;
  const rev  = paidLeads.reduce((a, l) => a + (l.p || 0), 0);
  document.getElementById('statTotal').textContent = n;
  document.getElementById('statPaid').textContent  = paid;
  document.getElementById('statConv').textContent  = n ? (paid/n*100).toFixed(1)+'%' : '—';
  document.getElementById('statRev').textContent   = rev ? rev.toLocaleString('ru-RU') + ' ₽' : '—';

  renderDistribution(utmChart, leads, l => l.u);
  renderDistribution(termChart, leads, l => l.m);

  // UTM Content filter (funnel)
  buildFilterButtons('contentFilterBar', leads, l => l.t, activeContent, val => {{
    activeContent = val;
    renderFunnel(leads);
  }}, 5);
  renderFunnel(leads);
}}

function renderFunnel(leads) {{
  const filtered = activeContent === '__all__'
    ? leads
    : leads.filter(l => l.t === activeContent);
  const data = STAGE_NAMES.map((_,i) => filtered.filter(l => l.s >= i).length);
  funnelChart.data.datasets[0].data = data;
  funnelChart.update();
}}

// ── UTM Source global filter ──────────────────────────────────────────────────
function buildGlobalSourceFilter() {{
  const counts = {{}};
  ALL_LEADS.forEach(l => {{
    const k = l.u || '(не указан)';
    counts[k] = (counts[k] || 0) + 1;
  }});
  const bar = document.getElementById('globalSourceBar');
  bar.innerHTML = '';
  const sources = ['__all__', ...Object.keys(counts).sort((a,b) => counts[b]-counts[a])];
  sources.forEach(src => {{
    const btn = document.createElement('button');
    btn.className = 'src-btn' + (src === activeGlobalSrc ? ' active' : '');
    btn.textContent = src === '__all__'
      ? `Все (${{ALL_LEADS.length}})`
      : `${{src}} (${{counts[src]}})`;
    btn.dataset.src = src;
    btn.addEventListener('click', () => {{
      bar.querySelectorAll('.src-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeGlobalSrc = src;
      applyFilter();
    }});
    bar.appendChild(btn);
  }});
}}

// ── Date presets ──────────────────────────────────────────────────────────────
function applyFilter() {{
  filterFromTs = toMidnightTs(document.getElementById('dateFrom').value);
  filterToTs   = toMidnightTs(document.getElementById('dateTo').value) + 86399;
  let filtered = ALL_LEADS.filter(l => l.c >= filterFromTs && l.c <= filterToTs);
  if (activeGlobalSrc !== '__all__') {{
    filtered = filtered.filter(l => (l.u || '(не указан)') === activeGlobalSrc);
  }}
  render(filtered);
}}

document.querySelectorAll('.filter-bar .preset-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter-bar .preset-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const today = todayStr();
    const p = btn.dataset.preset;
    if (p === 'today') {{
      document.getElementById('dateFrom').value = today;
      document.getElementById('dateTo').value   = today;
    }} else if (p === '7d') {{
      document.getElementById('dateFrom').value = nDaysAgoStr(7);
      document.getElementById('dateTo').value   = today;
    }} else if (p === '30d') {{
      document.getElementById('dateFrom').value = nDaysAgoStr(30);
      document.getElementById('dateTo').value   = today;
    }} else {{
      const d = new Date(DATA_FROM * 1000);
      document.getElementById('dateFrom').value = d.toLocaleDateString('sv-SE', {{timeZone:'Europe/Moscow'}});
      document.getElementById('dateTo').value   = today;
    }}
    applyFilter();
  }});
}});

['dateFrom','dateTo'].forEach(id => {{
  document.getElementById(id).addEventListener('change', () => {{
    document.querySelectorAll('.filter-bar .preset-btn').forEach(b => b.classList.remove('active'));
    applyFilter();
  }});
}});

buildGlobalSourceFilter();
document.querySelector('[data-preset="30d"]').click();
</script>
</body>
</html>"""


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Fetching leads from AMO…")
    leads = fetch_all_leads()
    print(f"  Total fetched: {len(leads)}")

    os.makedirs("docs", exist_ok=True)
    html = build_html(leads)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved docs/index.html ({len(html):,} bytes)")
