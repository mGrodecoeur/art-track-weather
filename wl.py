import requests
from prettytable import PrettyTable
from flask import Flask, render_template_string
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
from matplotlib.dates import DateFormatter

# Met.no API base URL
metno_url = "https://api.met.no/weatherapi/locationforecast/2.0/complete"

# Set your user-agent (required by Met.no API)
headers = {
    "User-Agent": "ART_Weather_App/1.0 (matth@example.com)"
}

# Constants for Penman-Monteith equation and air density
gamma = 0.066  # Psychrometric constant (kPa/°C)
albedo = 0.23  # Albedo constant for reference crop
R_d = 287.05  # Specific gas constant for dry air (J/(kg·K))
R_v = 461.495  # Specific gas constant for water vapor (J/(kg·K))
solar_constant = 0.082  # MJ/m²/min, solar constant

# Coordinates for your racetrack (replace with actual values)
latitude = -38.50127075081525
longitude = 145.2318360831406

# Automatically determine the timezone based on GPS coordinates
tf = TimezoneFinder()
local_timezone_str = tf.timezone_at(lng=longitude, lat=latitude)  # Automatically find timezone
local_timezone = pytz.timezone(local_timezone_str)  # Set local timezone

app = Flask(__name__)

weatherlink_api_url = "https://api.weatherlink.com/v2"
weatherlink_api_key = "u8wy2k5q3plcb7vluv3xduw5hjbw4yfn"
weatherlink_api_secret = "lee3admas91icuc8xgeuydtsyl8a2sa2"
station_id = 205802  # Updated to the integer station ID

historical_data = []
data_lock = threading.Lock()

def get_live_weather_data(station_id, api_key, api_secret):
    if not station_id:
        return None
    url = f"{weatherlink_api_url}/current/{station_id}?api-key={api_key}"
    headers = {
        "X-Api-Secret": api_secret,
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching current data: {response.status_code} - {response.text}")
        return None

def fetch_and_store():
    while True:
        live_data = get_live_weather_data(station_id, weatherlink_api_key, weatherlink_api_secret)
        if live_data:
            metrics = {}
            for sensor in live_data['sensors']:
                sensor_type = sensor.get('sensor_type')
                if sensor_type == 55:
                    for data_point in sensor['data']:
                        temp_f = data_point.get('temp')
                        if temp_f is not None:
                            metrics['temp_55'] = round((temp_f - 32) * 5 / 9, 2)
                elif sensor_type == 43:
                    for data_point in sensor['data']:
                        temp_f = data_point.get('temp')
                        if temp_f is not None:
                            metrics['temp_43'] = round((temp_f - 32) * 5 / 9, 2)
                        hum = data_point.get('hum')
                        if hum is not None:
                            metrics['hum_43'] = hum
                        wind_speed_mph = data_point.get('wind_speed_hi_last_2_min')
                        if wind_speed_mph is not None:
                            metrics['wind_speed_43'] = round(wind_speed_mph * 0.44704, 2)
                        wind_dir = data_point.get('wind_dir_at_hi_speed_last_2_min')
                        if wind_dir is not None:
                            metrics['wind_dir_43'] = wind_dir
            if metrics:
                now = datetime.now(local_timezone)  # Use local timezone for timestamps
                metrics['timestamp'] = now
                with data_lock:
                    historical_data.append(metrics)
                    # Keep only last 48 hours to cover yesterday and today
                    two_days_ago = now - timedelta(days=2)
                    historical_data[:] = [d for d in historical_data if d['timestamp'] > two_days_ago]
        time.sleep(300)  # 5 minutes

# Human-readable mapping for common keys (expand as needed based on your sensors)
param_map = {
    "temp": "Temperature (°C)",  # We'll convert to °C
    "hum": "Humidity (%)",
    "wind_speed_hi_last_2_min": "Wind Speed Hi Last 2 Min (m/s)",
    "wind_dir_at_hi_speed_last_2_min": "Wind Dir At Hi Speed Last 2 Min (°)",
    # Add more mappings based on your sensor data fields
}


def format_live_data(data):
    if data and 'sensors' in data:
        live_data_table = ""
        for sensor in data['sensors']:
            sensor_type = sensor.get('sensor_type', 'Unknown')
            if sensor_type not in [55, 43]:
                continue  # Skip other sensors
            live_data_table += f"<tr><th colspan='2'>Sensor Type: {sensor_type}</th></tr>"
            for data_point in sensor['data']:
                for key, value in data_point.items():
                    if key == 'ts':
                        continue  # Skip timestamp
                    # Filter specific keys
                    if (sensor_type == 55 and key == 'temp') or \
                       (sensor_type == 43 and key in ['hum', 'wind_speed_hi_last_2_min', 'wind_dir_at_hi_speed_last_2_min', 'temp']):
                        if key == 'temp' and value is not None:
                            # Convert °F to °C
                            value = round((value - 32) * 5 / 9, 2)
                        if key == 'wind_speed_hi_last_2_min' and value is not None:
                            # Convert mph to m/s
                            value = round(value * 0.44704, 2)
                        display_key = param_map.get(key, key.replace('_', ' ').title())
                        live_data_table += f"<tr><td>{display_key}</td><td>{value}</td></tr>"
        return live_data_table if live_data_table else "<tr><td>No Data</td><td>Available</td></tr>"
    return "<tr><td>No Data</td><td>Available</td></tr>"


# Function to fetch weather data from Met.no API
def get_metno_weather(lat, lon):
    response = requests.get(f"{metno_url}?lat={lat}&lon={lon}", headers=headers)
    response.raise_for_status()  # Raise error if not 200
    data = response.json()
    return data['properties']['timeseries']

# Function to calculate the slope of the saturation vapor pressure curve (Δ)
def slope_saturation_vapor_pressure_curve(temp):
    return 4098 * (0.6108 * math.exp((17.27 * temp) / (temp + 237.3))) / (temp + 237.3) ** 2

def calculate_solar_radiation(latitude, longitude, time_obj):
    location = pvlib.location.Location(latitude, longitude, tz=local_timezone_str)
    times = pd.DatetimeIndex([time_obj.astimezone(pytz.timezone(location.tz))])
    clearsky_model = location.get_clearsky(times)
    return clearsky_model['ghi'].iloc[0]

def calculate_solar_radiation2(latitude, longitude, time_obj):
    location = pvlib.location.Location(latitude, longitude, tz=local_timezone_str)
    times = pd.DatetimeIndex([time_obj.astimezone(pytz.timezone(location.tz))])
    clearsky_model = location.get_clearsky(times)
    return clearsky_model['dhi'].iloc[0]

# Function to calculate saturation vapor pressure (e_s) and actual vapor pressure (e_a)
def vapor_pressure(temp, humidity):
    es = 0.6108 * math.exp(17.27 * temp / (temp + 237.3))  # Saturation vapor pressure (kPa)
    ea = es * humidity / 100  # Actual vapor pressure (kPa)
    return es, ea

# Penman-Monteith Evaporation Rate Calculation (in mm/hour, 2 decimal places) using asphalt temperature
def penman_monteith(temp_asphalt, wind_speed, humidity, local_time):
    delta = slope_saturation_vapor_pressure_curve(temp_asphalt)
    es, ea = vapor_pressure(temp_asphalt, humidity)
    net_radiation = calculate_solar_radiation2(latitude, longitude, local_time)
    evapotranspiration_mm_day = (
        (0.408 * delta * net_radiation) + (
            gamma * (900 / (temp_asphalt + 273)) * wind_speed * (es - ea))
    ) / (delta + gamma * (1 + 0.34 * wind_speed))
    evapotranspiration_mm_hour = evapotranspiration_mm_day / 24
    return round(max(evapotranspiration_mm_hour, 0), 2)

# Function to estimate asphalt temperature based on air temperature, cloud cover, and wind speed
def estimate_asphalt_temperature(temp_air, cloud_cover, wind_speed, local_time):
    albedo = 0.23
    c = 30
    solar_radiation = calculate_solar_radiation(latitude, longitude, local_time) * (1 - cloud_cover / 100)
    temp_asphalt = temp_air + (1 - albedo) * solar_radiation / c
    temp_asphalt -= wind_speed * 0.5
    return round(temp_asphalt, 2)

# Function to calculate air density (kg/m³) considering humidity
def calculate_air_density(temp, pressure, humidity):
    temp_kelvin = temp + 273.15
    pressure_pascals = pressure * 100
    es = 610.94 * math.exp((17.625 * temp) / (temp + 243.04))
    ea = humidity / 100 * es
    P_d = pressure_pascals - ea
    air_density = (P_d / (R_d * temp_kelvin)) + (ea / (R_v * temp_kelvin))
    return round(air_density, 2)

# Function to convert wind direction from degrees to cardinal direction
def wind_direction_to_cardinal(degrees):
    directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    idx = int((degrees + 11.25) / 22.5) % 16
    return directions[idx]

def convert_to_local_time(utc_time):
    utc_time = datetime.strptime(utc_time, '%Y-%m-%dT%H:%M:%SZ')
    utc_time = pytz.utc.localize(utc_time)
    local_time = utc_time.astimezone(local_timezone)
    return local_time.strftime('%H:%M')

# Function to create weather data table
def create_weather_table(weather_data):
    previous_accumulation = 0
    rows = ""
    current_time = pytz.utc.localize(datetime.utcnow())
    past_4_hours = current_time - timedelta(hours=4)
    next_12_hours = current_time + timedelta(hours=12)

    for entry in weather_data:
        time = entry['time']
        time_obj = pytz.utc.localize(datetime.strptime(time, '%Y-%m-%dT%H:%M:%SZ'))
        if past_4_hours <= time_obj <= next_12_hours:
            local_time = convert_to_local_time(time)
            details = entry['data']['instant']['details']
            temp_air = details.get('air_temperature', 0)
            humidity = details.get('relative_humidity', 0)
            wind_speed = details.get('wind_speed', 0)
            wind_direction_degrees = details.get('wind_from_direction', 0)
            wind_direction = wind_direction_to_cardinal(wind_direction_degrees)
            cloud_cover_l = details.get('cloud_area_fraction_low', 0)
            cloud_cover_m = details.get('cloud_area_fraction_medium', 0)
            cloud_cover = details.get('cloud_area_fraction', 0)
            pressure = details.get('air_pressure_at_sea_level', 1013)
            temp_asphalt = estimate_asphalt_temperature(temp_air, cloud_cover, wind_speed, time_obj)
            precipitation = entry['data'].get('next_1_hours', {}).get('details', {}).get('precipitation_amount', 0)
            evap_rate = penman_monteith(temp_asphalt, wind_speed, humidity, time_obj)
            if precipitation > 0:
                previous_accumulation += precipitation
            previous_accumulation -= evap_rate
            previous_accumulation = max(previous_accumulation, 0)
            previous_accumulation = round(previous_accumulation, 2)
            air_density = calculate_air_density(temp_air, pressure, humidity)

            rows += f"""
            <tr>
                <td>{local_time}</td> 
                <td>{temp_air}</td>
                <td>{humidity}</td>
                <td>{precipitation}</td>
                <td>{wind_speed}</td>
                <td>{wind_direction}</td>
                <td>{cloud_cover_l}</td>
                <td>{cloud_cover_m}</td>
                <td>{pressure}</td>
                <td>{air_density}</td>
                <td>{temp_asphalt}</td>
                <td>{previous_accumulation}</td>
                <td>{evap_rate}</td>
            </tr>
            """
    return rows

# HTML template moved outside of the function for better scoping
html_template = """
<html>
<head>
    <meta http-equiv="refresh" content="300">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 0; background-color: #f4f7f9; }
        .container { max-width: 1400px; margin: 20px auto; padding: 0 20px; }
        .tabs { overflow: hidden; border: 1px solid #ccc; background-color: #f1f1f1; }
        .tabs button { background-color: inherit; border: none; outline: none; cursor: pointer; padding: 14px 16px; transition: 0.3s; font-size: 17px; }
        .tabs button:hover { background-color: #ddd; }
        .tabs button.active { background-color: #ccc; }
        .tabcontent { display: none; padding: 6px 12px; border: 1px solid #ccc; border-top: none; }
        table { width: 100%; border-collapse: collapse; background-color: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        th, td { padding: 6px 10px; text-align: left; font-size: 14px; color: #333; border-bottom: 1px solid #ddd; }
        th { background-color: #4CAF50; color: white; text-transform: uppercase; letter-spacing: 0.05em; font-size: 12px; }
        tr:hover { background-color: #f1f1f1; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        h2 { font-size: 24px; color: #333; margin-bottom: 20px; }
        #map { height: 400px; width: 100%; margin-top: 20px; }
        .compass-overlay { position: absolute; top: 20px; right: 20px; pointer-events: none; z-index: 1000; }
        img { max-width: 100%; height: auto; margin-bottom: 20px; }
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
</head>
<body>
    <div class="container">
        <div class="tabs">
            <button class="tablinks" onclick="openTab(event, 'Forecast')">Forecast</button>
            <button class="tablinks" onclick="openTab(event, 'Live')">Live Data</button>
        </div>

        <div id="Forecast" class="tabcontent">
            <h2>Track Weather Table (Current Time + Next 12 Hours)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Local Time</th>
                        <th>Temperature (°C)</th>
                        <th>Humidity (%)</th>
                        <th>Precipitation (mm)</th>
                        <th>Wind Speed (m/s)</th>
                        <th>Wind Direction</th>
                        <th>Cloud Low (%)</th>
                        <th>Cloud Mid. (%)</th>
                        <th>Air Pressure (hPa)</th>
                        <th>Air Density (kg/m³)</th>
                        <th>Asphalt Temperature (°C)</th>
                        <th>Accumulation (mm)</th>
                        <th>Evaporation Rate (mm/hr)</th>
                    </tr>
                </thead>
                <tbody>
                    {{ forecast_table|safe }}
                </tbody>
            </table>
        </div>

        <div id="Live" class="tabcontent">
            <h2>Live Weather Data</h2>
            <table>
                <thead>
                    <tr>
                        <th>Parameter</th>
                        <th>Value</th>
                    </tr>
                </thead>
                <tbody>
                    {{ live_data_table|safe }}
                </tbody>
            </table>
            <h2>Metrics History</h2>
            {% for metric, plot in plots.items() %}
                {% if plot %}
                <h3>{{ metric.replace('_', ' ').title() }}</h3>
                <img src="data:image/png;base64,{{ plot }}" alt="{{ metric }} Plot">
                {% endif %}
            {% endfor %}
            {% if not plots %}
            <p>No data available yet for plotting.</p>
            {% endif %}
        </div>
    </div>

    <div id="map">
        <img src="/static/compass.png" alt="Compass" class="compass-overlay" width="100" height="100">
    </div>

    <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
    <script>
        function openTab(evt, tabName) {
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tabcontent");
            for (i = 0; i < tabcontent.length; i++) {
                tabcontent[i].style.display = "none";
            }
            tablinks = document.getElementsByClassName("tablinks");
            for (i = 0; i < tablinks.length; i++) {
                tablinks[i].className = tablinks[i].className.replace(" active", "");
            }
            document.getElementById(tabName).style.display = "block";
            evt.currentTarget.className += " active";
        }
        document.getElementsByClassName("tablinks")[0].click(); // Show the first tab by default

        window.onload = function() {
            var map = L.map('map').setView([{{ latitude }}, {{ longitude }}], 13);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: 'Map data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }).addTo(map);
        };
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    weather_data = get_metno_weather(latitude, longitude)
    forecast_table = create_weather_table(weather_data)
    live_data = get_live_weather_data(station_id, weatherlink_api_key, weatherlink_api_secret)
    live_data_table = format_live_data(live_data)

    # Generate plots for each metric
    with data_lock:
        data_copy = historical_data.copy()
    plots = {}
    metrics = ['temp_55', 'temp_43', 'hum_43', 'wind_speed_43', 'wind_dir_43']
    now = datetime.now(local_timezone)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    ylims = {
        'temp_55': (10, 70),
        'temp_43': (0, 50),
        'hum_43': (0, 100),
        'wind_speed_43': (0, 30),
        'wind_dir_43': (0, 360)
    }

    units = {
        'temp_55': '°C',
        'temp_43': '°C',
        'hum_43': '%',
        'wind_speed_43': 'm/s',
        'wind_dir_43': '°'
    }

    for metric in metrics:
        today_data = []
        yesterday_data = []
        for d in data_copy:
            if metric in d and d[metric] is not None:
                ts = d['timestamp']
                if yesterday_start <= ts < today_start:
                    hours_past_midnight = (ts - yesterday_start).total_seconds() / 3600
                    yesterday_data.append((hours_past_midnight, d[metric]))
                elif today_start <= ts <= now:
                    hours_past_midnight = (ts - today_start).total_seconds() / 3600
                    today_data.append((hours_past_midnight, d[metric]))

        if today_data or yesterday_data:
            fig, ax = plt.subplots(figsize=(10, 5))
            if today_data:
                today_data.sort()  # Sort by hours_past_midnight
                x, y = zip(*today_data)
                ax.plot(x, y, label='Today', marker='o')
            if yesterday_data:
                yesterday_data.sort()
                x, y = zip(*yesterday_data)
                ax.plot(x, y, label='Yesterday', marker='o', linestyle='--')
            ax.legend()
            ax.set_xlabel('Hours Past Midnight (00:00 to 24:00)')
            ax.set_ylabel(f"{metric.replace('_', ' ').title()} ({units.get(metric, '')})")
            ax.set_title(f'{metric.replace("_", " ").title()} Over Day')
            ax.set_xlim(0, 24)
            ax.set_xticks(range(0, 25, 2))  # Ticks every 2 hours
            if metric in ylims:
                ax.set_ylim(ylims[metric])

            buf = BytesIO()
            fig.savefig(buf, format='png')
            buf.seek(0)
            plots[metric] = base64.b64encode(buf.read()).decode('utf-8')
            plt.close(fig)

    return render_template_string(html_template,
                                  forecast_table=forecast_table,
                                  live_data_table=live_data_table,
                                  latitude=latitude,
                                  longitude=longitude,
                                  plots=plots)

# Start the background thread
threading.Thread(target=fetch_and_store, daemon=True).start()

# Run the Flask app
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)