# rain_dec.py → V2 NIGHT MODE - SINGLE PAGE - RACING FOCUSED
import requests
from flask import Flask, render_template_string, request
from datetime import datetime, timedelta
import pytz
import pandas as pd
import pvlib
import time
import math
from timezonefinder import TimezoneFinder
import threading
import base64
from io import BytesIO
import matplotlib.pyplot as plt
import csv
import os

# ==== CONFIG ====
latitude = 36.710211448928376
longitude = -6.032784622192833
TRACK_SVG_PATH = "spa-info.svg"
tf = TimezoneFinder()
local_timezone_str = tf.timezone_at(lng=longitude, lat=latitude)
local_timezone = pytz.timezone(local_timezone_str)

metno_url = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
headers = {"User-Agent": "ART_Weather_App/2.0 (matth@example.com)"}

weatherlink_api_key = "u8wy2k5q3plcb7vluv3xduw5hjbw4yfn"
weatherlink_api_secret = "lee3admas91icuc8xgeuydtsyl8a2sa2"
station_id = 205802

data_file = 'historical_weather_data.csv'
historical_data = []
data_lock = threading.Lock()

app = Flask(__name__)


# ==== BACKGROUND DATA FETCHER ====
def load_historical_data():
    if os.path.exists(data_file):
        with open(data_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                metrics = {}
                for k, v in row.items():
                    if k == 'timestamp':
                        metrics[k] = datetime.fromisoformat(v).astimezone(local_timezone)
                    elif v in ('', 'None'):
                        metrics[k] = None
                    else:
                        try:
                            metrics[k] = float(v)
                        except:
                            metrics[k] = v
                historical_data.append(metrics)
        historical_data.sort(key=lambda x: x['timestamp'])

def get_track_svg():
    if os.path.exists(TRACK_SVG_PATH):
        with open(TRACK_SVG_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        # Fallback bonito si no encuentra el archivo
        return '''
        <svg viewBox="0 0 1200 800" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#0d1117"/>
            <text x="600" y="400" text-anchor="middle" fill="#58a6ff" font-size="48" font-family="Arial">
                track.svg not found
            </text>
            <text x="600" y="460" text-anchor="middle" fill="#aaa" font-size="28">
                Put your track SVG in /static/track.svg
            </text>
        </svg>
        '''

def save_historical_data():
    with open(data_file, 'w', newline='') as f:
        if historical_data:
            fieldnames = ['timestamp'] + [k for k in historical_data[0].keys() if k != 'timestamp']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for d in historical_data:
                row = {k: ('' if v is None else v) for k, v in d.items()}
                writer.writerow(row)


def get_live_weather_data():
    url = f"https://api.weatherlink.com/v2/current/{station_id}?api-key={weatherlink_api_key}"
    try:
        r = requests.get(url, headers={"X-Api-Secret": weatherlink_api_secret}, timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None


def fetch_and_store():
    load_historical_data()
    while True:
        data = get_live_weather_data()
        if data:
            metrics = {'timestamp': datetime.now(local_timezone)}
            for sensor in data.get('sensors', []):
                st = sensor.get('sensor_type')
                if st == 55 and sensor['data']:
                    t_f = sensor['data'][0].get('temp')
                    if t_f is not None:
                        metrics['temp_55'] = round((t_f - 32) * 5 / 9, 2)
                if st == 43 and sensor['data']:
                    d = sensor['data'][0]
                    t_f = d.get('temp')
                    if t_f is not None:
                        metrics['temp_43'] = round((t_f - 32) * 5 / 9, 2)
                    metrics['hum_43'] = d.get('hum')
                    ws_mph = d.get('wind_speed_hi_last_2_min')
                    if ws_mph is not None:
                        metrics['wind_speed_43'] = round(ws_mph * 0.44704, 2)
                    metrics['wind_dir_43'] = d.get('wind_dir_at_hi_speed_last_2_min')
            if any(k in metrics for k in ['temp_55', 'temp_43']):
                with data_lock:
                    historical_data.append(metrics)
                    save_historical_data()
        time.sleep(300)


# ==== WEATHER ICONS (simple text-based) ====
def get_weather_icon(symbol, precip=0):
    icons = {
        "clear": "☀️", "sun": "☀️", "partlycloudy": "⛅", "cloudy": "☁️",
        "rain": "🌧️", "lightrain": "🌦️", "heavyrain": "⛈️", "fog": "🌫️"
    }
    if precip > 2: return icons["heavyrain"]
    if precip > 0.5: return icons["rain"]
    if precip > 0: return icons["lightrain"]
    if "cloud" in symbol: return icons["cloudy"]
    if "partly" in symbol: return icons["partlycloudy"]
    return icons["clear"]


# ==== FORECAST HELPERS ====
def get_metno_weather():
    try:
        r = requests.get(f"{metno_url}?lat={latitude}&lon={longitude}", headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()['properties']['timeseries']
    except:
        return []


def estimate_asphalt_temperature(air_temp, cloud_cover, wind_speed, dt):
    solar = pvlib.location.Location(latitude, longitude, tz=local_timezone_str).get_clearsky(pd.DatetimeIndex([dt]))[
        'ghi'].iloc[0]
    solar *= (1 - cloud_cover / 100)
    return round(air_temp + (1 - 0.23) * solar / 30 - wind_speed * 0.4, 1)


def wind_direction_cardinal(deg):
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    return dirs[int((deg + 11.25) / 22.5) % 16]


# ==== MAIN PAGE ====
html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="300">
    <title>ART Track Weather</title>
    <style>
        :root { --bg:#0d1117; --card:#161b22; --text:#f0f6fc; --accent:#58a6ff; --orange:#ffa657; }
        body { margin:0; font-family:'Segoe UI',sans-serif; background:var(--bg); color:var(--text); }
        .container { max-width:1480px; margin:0 auto; padding:15px; }

        /* HERO: Track + Current Weather */
.hero {
    background: linear-gradient(135deg, #1a2332, #0f1a2e);
    border-radius: 24px;
    overflow: hidden;
    box-shadow: 0 20px 50px rgba(0,0,0,0.8);
    margin-bottom: 30px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    min-height: 520px;
    position: relative;
    isolation: isolate;
}
@media (max-width:1100px) {
    .hero { grid-template-columns: 1fr; min-height: 740px; }
}

.track-container {
    position: relative;
    background: #0a0e17;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
}

/* CANVAS DE VIENTO DEBAJO DEL SVG PARA QUE NO TAPE LOS ICONOS */
#wind-particles {
    position: absolute;
    top: 0; left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    opacity: 0.65;
    z-index: 1;                  /* ← debajo del SVG y de los iconos */
}

#track-svg {
    position: relative;
    width: 88%;
    max-width: 680px;
    filter: drop-shadow(0 20px 50px rgba(0,0,0,0.9));
    transform: perspective(1000px) rotateX(24deg);
    transform-origin: center center;
    z-index: 2;                  /* ← encima del canvas */
}

.current-weather {
padding: 40px 50px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    color: white;
    z-index: 9999;                     
    position: relative;
    transform: translateZ(0);          
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
}
        .current-temp { font-size:6.8rem; font-weight:900; margin:0; line-height:1; }
        .current-desc { font-size:1.9rem; opacity:0.9; margin:10px 0 5px; }
        .track-temp-big { font-size:3.4rem; color:var(--orange); font-weight:bold; margin:20px 0; text-shadow:0 0 20px #ffa65788; }
        .details-grid {
            display:grid;
            grid-template-columns:repeat(2,1fr);
            gap:18px;
            margin-top:30px;
            font-size:1.3rem;
        }
        .detail {
            background:rgba(255,255,255,0.1);
            padding:16px;
            border-radius:14px;
            backdrop-filter:blur(8px);
            border:1px solid rgba(255,255,255,0.05);
        }
        .detail b { font-size:1.55rem; }

        /* GRAPHS → VOLVEMOS AL LAYOUT PERFECTO ANTERIOR */
        .graphs {
            display:grid;
            grid-template-columns:repeat(auto-fit, minmax(380px,1fr));
            gap:20px;
        }
        .graph-card {
            background:#161b22;
            padding:15px;
            border-radius:12px;
            border:1px solid #30363d;
        }
        .graph-card img { width:100%; border-radius:8px; background:#0d1117; }
        .graph-card h3 {
            text-align:center;
            margin:12px 0 8px;
            color:{{ '#ffa657' if metric == 'temp_55' else '#58a6ff' }};
            font-size:1.35rem;
        }

        /* Resto igual */
        .section { background:var(--card); border-radius:16px; padding:25px; margin-bottom:25px; box-shadow:0 8px 30px rgba(0,0,0,0.5); border:1px solid #30363d; }
        .section h2 { margin:0 0 20px; color:var(--accent); font-size:1.8rem; border-bottom:1px solid #30363d; padding-bottom:10px; }
        table { width:100%; border-collapse:collapse; font-size:0.95rem; }
        th { background:#21262d; padding:12px; font-size:0.8rem; letter-spacing:0.8px; text-transform:uppercase; }
        td { padding:10px; text-align:center; border-bottom:1px solid #30363d; }
        tr:hover { background:#58a6ff11; }
        .selector { text-align:center; margin:30px 0; }
        select { padding:12px 24px; font-size:1.1rem; border-radius:10px; background:#21262d; color:white; border:1px solid #30363d; }
    </style>
</head>
<body>
<div class="container">

    <!-- HERO -->
<div class="hero">
    <div class="track-container">
        <canvas id="wind-particles"></canvas>
        <div id="track-svg">{{ track_svg|safe }}</div>
    </div>

        <div class="current-weather">
            <div class="current-temp">{{ current_temp }}°C</div>
            <div class="current-desc">{{ current_icon }} {{ current_summary }}</div>
            <div class="track-temp-big">Track: {{ track_temp }}°C</div>
            <div style="opacity:0.9; margin:10px 0;">Feels like {{ feels_like }}°C</div>

            <div class="details-grid">
                <div class="detail">💧 Humidity<br><b>{{ humidity }}%</b></div>
                <div class="detail">💨 Wind<br><b>{{ wind_speed }} m/s {{ wind_dir }}</b></div>
                <div class="detail">🌧️ Next Hour<br><b>{{ precip_next_hour }} mm</b></div>
                <div class="detail">🌀 Pressure<br><b>{{ pressure }} hPa</b></div>
                <div class="detail">🌫️ Density<br><b>{{ air_density }} kg/m³</b></div>
                <div class="detail">☁️ Clouds<br><b>{{ cloud_cover }}%</b></div>
            </div>
        </div>
    </div>

    <!-- SELECTOR + GRAPHS + TABLE (todo igual que antes, pero gráficos perfectos) -->
    <div class="selector">
        <form method="get">
            <strong>Compare with:</strong>
            <select name="day" onchange="this.form.submit()">
                {% for d in available_days %}
                    <option value="{{ d }}" {% if d == selected_day %}selected{% endif %}>{{ d }}</option>
                {% endfor %}
            </select>
        </form>
    </div>

    <div class="section">
        <h2>24h Evolution • Today vs {{ selected_day or "Previous Day" }}</h2>
        <div class="graphs">
            {% for metric, img in plots.items() %}
                <div class="graph-card">
                    <h3>{% if metric == 'temp_55' %}TRACK TEMPERATURE (°C){% else %}{{ metric.replace('_43',' Air').replace('_55',' Track').replace('_',' ').title() }}{% endif %}</h3>
                    <img src="data:image/png;base64,{{ img }}" alt="{{ metric }}">
                </div>
            {% endfor %}
        </div>
    </div>

    <div class="section">
        <h2>Next 12 Hours Forecast</h2>
        <table>
            <thead><tr><th>Time</th><th></th><th>Air</th><th>Track</th><th>Rain</th><th>Acc</th><th>Evap</th><th>Wind</th><th>Dir</th><th>Hum</th><th>Cloud</th><th>Density</th></tr></thead>
            <tbody>{{ forecast_table|safe }}</tbody>
        </table>
    </div>

</div>

<script>
document.addEventListener("DOMContentLoaded", function () {
    const canvas = document.getElementById("wind-particles");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    let particles = [];

    const windSpeed = {{ wind_speed|default(5) }};
    const windDirDeg = {{ wind_dir_deg|default(0) }};

    function createWindLines() {
        particles = [];

        const lines = 7;
        const spacing = canvas.height / (lines + 2);

        for (let i = 1; i <= lines; i++) {
            const baseY = spacing * i;
            for (let j = 0; j < 16; j++) {
                const offsetX = (canvas.width + 600) / 15 * j;
                particles.push({
                    baseY: baseY,
                    x: -300 + offsetX,
                    y: baseY + (Math.random() - 0.5) * 40,
                    size: Math.random() * 1.3 + 1.0,
                    speed: windSpeed * 0.35 + Math.random() * 0.8,
                    trail: []
                });
            }
        }

        // partículas libres extra
        for (let i = 0; i < 20; i++) {
            const a = (windDirDeg + 180) * Math.PI / 180;
            const d = 500;
            particles.push({
                baseY: Math.random() * canvas.height,
                x: canvas.width/2 + Math.cos(a) * d,
                y: canvas.height/2 + Math.sin(a) * d,
                size: Math.random() * 1.5 + 0.9,
                speed: windSpeed * 0.1,
                trail: []
            });
        }
    }

    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const angle = windDirDeg * Math.PI / 180;
        const vx = Math.cos(angle);
        const vy = Math.sin(angle);

        particles.forEach(p => {
            // trail
            p.trail.push({x: p.x, y: p.y});
            if (p.trail.length > 14) p.trail.shift();

            // movimiento
            p.x += vx * p.speed;
            p.y += vy * p.speed;

            // dibujar trail
            if (p.trail.length > 1) {
                ctx.strokeStyle = "rgba(88, 166, 255, 0.4)";
                ctx.lineWidth = p.size;
                ctx.beginPath();
                p.trail.forEach((pt, i) => i === 0 ? ctx.moveTo(pt.x, pt.y) : ctx.lineTo(pt.x, pt.y));
                ctx.stroke();
            }

            // dibujar partícula
            ctx.globalAlpha = 0.95;
            ctx.fillStyle = "#58a6ff";
            ctx.shadowBlur = 10;
            ctx.shadowColor = "#58a6ff";
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
            ctx.fill();

            // respawn manteniendo su carril
            if (p.x < -400 || p.x > canvas.width + 400 || p.y < -400 || p.y > canvas.height + 400) {
                const backAngle = (windDirDeg + 180) * Math.PI / 180;
                const dist = 500;
                p.x = canvas.width/2 + Math.cos(backAngle) * dist;
                p.y = p.baseY + (Math.random() - 0.5) * 40;
                p.trail = [];
            }
        });

        requestAnimationFrame(animate);
    }

    function resize() {
        canvas.width = canvas.offsetWidth;
        canvas.height = canvas.offsetHeight;
        createWindLines();
    }

    resize();
    animate();
    window.addEventListener("resize", resize);
});
</script>
</body>
</html>
"""


def create_plots(selected_day_str):
    with data_lock:
        data = historical_data.copy()

    now = datetime.now(local_timezone)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    available_days = sorted({d['timestamp'].strftime('%Y-%m-%d') for d in data if d['timestamp'] < today_start},
                            reverse=True)
    selected_day = selected_day_str if selected_day_str in available_days else (
        available_days[0] if available_days else None)

    metrics = ['temp_55', 'temp_43', 'hum_43', 'wind_speed_43']
    plots = {}

    plt.style.use('dark_background')
    for metric in metrics:
        today_pts = []
        comp_pts = []
        for entry in data:
            if metric not in entry or entry[metric] is None:
                continue
            ts = entry['timestamp']
            hours = (ts - ts.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600
            if today_start <= ts <= now:
                today_pts.append((hours, entry[metric]))
            elif selected_day and ts.strftime('%Y-%m-%d') == selected_day:
                comp_pts.append((hours, entry[metric]))

        if not today_pts and not comp_pts:
            continue

        fig, ax = plt.subplots(figsize=(10, 5.5))
        if today_pts:
            x, y = zip(*sorted(today_pts))
            ax.plot(x, y, 'o-', color='#ffa657', linewidth=3, label='Today')
        if comp_pts:
            x, y = zip(*sorted(comp_pts))
            ax.plot(x, y, 'o--', color='#58a6ff', alpha=0.8, label=selected_day or 'Prev')

        ax.set_title(metric.replace('temp_55', 'TRACK TEMPERATURE').replace('_', ' ').title(), color='white',
                     fontsize=14, pad=20)
        ax.set_xlabel('Hours from midnight')
        ax.set_ylabel('Value')
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 4))

        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', dpi=150, facecolor='#0d1117')
        plots[metric] = base64.b64encode(buf.getvalue()).decode()
        plt.close(fig)

    return plots, available_days, selected_day


@app.route("/")
def index():
    weather_data = get_metno_weather()
    live_data = get_live_weather_data()

    # === Current conditions (best of live + forecast) ===
    now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
    current_entry = min(weather_data, key=lambda x: abs(
        datetime.fromisoformat(x['time'].rstrip('Z')).replace(tzinfo=pytz.utc) - now_utc))
    details = current_entry['data']['instant']['details']
    next1h = current_entry['data'].get('next_1_hours', {}).get('details', {})

    air_temp = details.get('air_temperature', 0)
    humidity = details.get('relative_humidity', 0)
    wind_speed = details.get('wind_speed', 0)
    wind_dir_deg = details.get('wind_from_direction', 0)
    wind_dir = wind_direction_cardinal(wind_dir_deg)
    cloud_cover = details.get('cloud_area_fraction', 0)
    pressure = details.get('air_pressure_at_sea_level', 1013)
    precip_next = next1h.get('precipitation_amount', 0)
    symbol = current_entry['data'].get('next_1_hours', {}).get('summary', {}).get('symbol_code', 'clear')

    track_svg = get_track_svg()
    wind_dir_deg = details.get('wind_from_direction', 0)

    # Prefer live sensor data if available
    track_temp_live = None
    if live_data:
        for s in live_data.get('sensors', []):
            if s.get('sensor_type') == 55 and s['data']:
                t_f = s['data'][0].get('temp')
                if t_f is not None:
                    track_temp_live = round((t_f - 32) * 5 / 9, 1)

    track_temp = track_temp_live or estimate_asphalt_temperature(air_temp, cloud_cover, wind_speed, now_utc)
    feels_like = round(air_temp - ((wind_speed * 3.6) - 10) * 0.5, 1)  # rough wind chill / heat index

    # Accumulation + evaporation
    accumulation = 0.0
    for entry in weather_data[:12]:
        dt = datetime.fromisoformat(entry['time'].rstrip('Z')).replace(tzinfo=pytz.utc)
        if dt > now_utc: break
        precip = entry['data'].get('next_1_hours', {}).get('details', {}).get('precipitation_amount', 0)
        t_asph = estimate_asphalt_temperature(details['air_temperature'], cloud_cover, wind_speed, dt)
        evap = max(0, 0.05 * (t_asph - 15))  # simplified
        accumulation = max(0, accumulation + precip - evap / 24)

    forecast_table = ""
    for entry in weather_data[:13]:
        t = entry['time']
        dt = datetime.fromisoformat(t.rstrip('Z')).replace(tzinfo=pytz.utc)
        if now_utc - timedelta(hours=1) > dt: continue
        if dt > now_utc + timedelta(hours=12): break

        local_t = dt.astimezone(local_timezone).strftime('%H:%M')
        d = entry['data']['instant']['details']
        n1 = entry['data'].get('next_1_hours', {})
        precip = n1.get('details', {}).get('precipitation_amount', 0)
        symbol_code = n1.get('summary', {}).get('symbol_code', 'clear')
        icon = get_weather_icon(symbol_code, precip)

        asphalt = estimate_asphalt_temperature(d['air_temperature'], d.get('cloud_area_fraction', 0), d['wind_speed'],
                                               dt)
        accumulation += precip
        evap_rate = max(0.01, 0.08 * (asphalt - 10) / 40)
        accumulation = round(max(0, accumulation - evap_rate), 2)
        density = round(pressure * 100 / (287.05 * (d['air_temperature'] + 273.15)) * (1 - 0.378 * humidity / 100), 3)

        forecast_table += f"""
        <tr>
            <td>{local_t}</td><td>{icon}</td>
            <td>{d.get('air_temperature', '—')}</td>
            <td><b>{asphalt}</b></td>
            <td>{precip}</td><td>{accumulation}</td><td>{round(evap_rate, 2)}</td>
            <td>{d.get('wind_speed', '—')}</td><td>{wind_direction_cardinal(d.get('wind_from_direction', 0))}</td>
            <td>{d.get('relative_humidity', '—')}</td><td>{d.get('cloud_area_fraction', '—')}</td>
            <td>{density}</td>
        </tr>"""

    plots, available_days, selected_day = create_plots(request.args.get('day'))

    return render_template_string(html_template,
                                  current_temp=round(air_temp, 1),
                                  track_temp=track_temp,
                                  current_icon=get_weather_icon(symbol, precip_next),
                                  current_summary=symbol.replace('_', ' ').title(),
                                  feels_like=feels_like,
                                  humidity=round(humidity),
                                  wind_speed=round(wind_speed, 1),
                                  wind_dir=wind_dir,
                                  precip_next_hour=precip_next,
                                  pressure=round(pressure),
                                  air_density=round(pressure * 100 / (287.05 * (air_temp + 273.15)), 3),
                                  cloud_cover=round(cloud_cover),
                                  forecast_table=forecast_table,
                                  plots=plots,
                                  available_days=available_days or ["No past data"],
                                  selected_day=selected_day or "No selection",
                                  track_svg=track_svg,
                                  wind_dir_deg = wind_dir_deg
                                  )


# Start background thread
threading.Thread(target=fetch_and_store, daemon=True).start()

# Global flag to ensure thread starts only once (prevents Gunicorn duplicates)
_thread_started = False
_thread_lock = threading.Lock()

def start_background_thread():
    global _thread_started
    with _thread_lock:
        if _thread_started:
            print("Background thread already running — skipping duplicate start.")
            return
        print("Starting background data fetcher thread...")
        t = threading.Thread(target=fetch_and_store, daemon=False)  # Non-daemon: Survives in Gunicorn
        t.start()
        _thread_started = True
        print("Background thread started successfully!")

# Start the thread on module import (works with Gunicorn)
start_background_thread()

# Your existing if __name__ block (keep for local testing)
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)