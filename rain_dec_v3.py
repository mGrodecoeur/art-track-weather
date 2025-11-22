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
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <style>
        :root { --bg: #0d1117; --card: #161b22; --text: #f0f6fc; --accent: #58a6ff; --green: #238636; }
        body { margin:0; font-family: 'Segoe UI', sans-serif; background:#0d1117; color:#f0f6fc; line-height:1.5; }
        .container { max-width: 1480px; margin: 0 auto; padding: 15px; }
        h1 { text-align:center; font-size:2.8rem; margin:20px 0; color:#58a6ff; text-shadow: 0 0 10px #58a6ff44; }
        .current-box { background: linear-gradient(135deg, #1f6feb, #238636); padding:30px; border-radius:20px; text-align:center; box-shadow:0 10px 30px rgba(0,0,0,0.6); margin-bottom:25px; color:white; }
        .current-main { font-size:5rem; font-weight:bold; margin:10px 0; }
        .current-desc { font-size:1.8rem; opacity:0.95; }
        .current-details { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr)); gap:20px; margin-top:25px; font-size:1.3rem; }
        .detail-item { background:rgba(255,255,255,0.15); padding:15px; border-radius:12px; backdrop-filter:blur(5px); }

        .section { background:var(--card); border-radius:16px; padding:20px; margin-bottom:25px; box-shadow:0 8px 25px rgba(0,0,0,0.4); border:1px solid #30363d; }
        .section h2 { margin-top:0; color:#58a6ff; border-bottom:1px solid #30363d; padding-bottom:10px; }

        table { width:100%; border-collapse:collapse; font-size:0.95rem; }
        th { background:#21262d; padding:12px; text-transform:uppercase; font-size:0.8rem; letter-spacing:0.8px; }
        td { padding:10px; text-align:center; border-bottom:1px solid #30363d; }
        tr:hover { background:#1f6feb22; }
        .track-temp { color:#ffa657; font-weight:bold; }

        .graphs { display:grid; grid-template-columns: repeat(auto-fit, minmax(380px,1fr)); gap:20px; }
        .graph-card { background:#161b22; padding:15px; border-radius:12px; border:1px solid #30363d; }
        .graph-card img { width:100%; border-radius:8px; background:#0d1117; }

        .selector { text-align:center; margin:20px 0; }
        select { padding:10px 20px; font-size:1rem; border-radius:8px; background:#21262d; color:white; border:1px solid #30363d; }

        @media (max-width: 900px) {
            .current-main { font-size:3.5rem; }
            .current-details { grid-template-columns: 1fr 1fr; }
        }
    </style>
</head>
<body>
<div class="container">

    <!-- CURRENT CONDITIONS -->
    <div class="current-box">
        <div class="current-main">{{ current_temp }}°C</div>
        <div class="current-desc">{{ current_icon }} {{ current_summary }} • Feels {{ feels_like }}°C</div>
        <div style="margin:20px 0; font-size:2rem;">Track: <span class="track-temp">{{ track_temp }}°C</span></div>

        <div class="current-details">
            <div class="detail-item">💧 Humidity<br><b>{{ humidity }}%</b></div>
            <div class="detail-item">💨 Wind<br><b>{{ wind_speed }} m/s {{ wind_dir }}</b></div>
            <div class="detail-item">🌧️ Next Hour<br><b>{{ precip_next_hour }} mm</b></div>
            <div class="detail-item">🌀 Pressure<br><b>{{ pressure }} hPa</b></div>
            <div class="detail-item">🌫️ Density<br><b>{{ air_density }} kg/m³</b></div>
            <div class="detail-item">☁️ Cloud Cover<br><b>{{ cloud_cover }}%</b></div>
        </div>
    </div>

    <!-- DAY COMPARISON SELECTOR -->
    <div class="selector">
        <form method="get">
            <label for="day">Compare with:</label>
            <select name="day" id="day" onchange="this.form.submit()">
                {% for d in available_days %}
                    <option value="{{ d }}" {% if d == selected_day %}selected{% endif %}>{{ d }}</option>
                {% endfor %}
            </select>
        </form>
    </div>

    <!-- GRAPHS -->
    <div class="section">
        <h2>24h Evolution • Today vs {{ selected_day or "Previous Day" }}</h2>
        <div class="graphs">
            {% for metric, img in plots.items() %}
                <div class="graph-card">
                    <h3 style="text-align:center; margin:10px 0; color:#ffa657;">
                        {% if metric == 'temp_55' %}Track Temperature (°C){% else %}
                        {{ metric.replace('_43', ' Air').replace('_55', ' Track').replace('_', ' ').title() }}{% endif %}
                    </h3>
                    <img src="data:image/png;base64,{{ img }}" alt="{{ metric }}">
                </div>
            {% endfor %}
        </div>
    </div>

    <!-- NEXT 12 HOURS FORECAST -->
    <div class="section">
        <h2>Next 12 Hours Detailed Forecast</h2>
        <table>
            <thead>
                <tr>
                    <th>Time</th><th>Condition</th><th>Air °C</th><th>Track °C</th><th>Rain mm</th><th>Acc mm</th><th>Evap mm/h</th>
                    <th>Wind m/s</th><th>Dir</th><th>Hum %</th><th>Cloud %</th><th>Density</th>
                </tr>
            </thead>
            <tbody>{{ forecast_table|safe }}</tbody>
        </table>
    </div>

</div>
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
                                  selected_day=selected_day or "No selection"
                                  )


# Start background thread
threading.Thread(target=fetch_and_store, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)