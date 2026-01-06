#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from luma.oled.device import sh1106
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from PIL import ImageFont
import RPi.GPIO as GPIO
import requests
from datetime import datetime
from influxdb import InfluxDBClient

# ===================== Telegram =====================
TELEGRAM_BOT_TOKEN = "YOUR_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

# ===================== InfluxDB =====================
INFLUXDB_HOST = "localhost"
INFLUXDB_PORT = 8086
INFLUXDB_DB = "pm25"
INFLUXDB_USER = "sensor"
INFLUXDB_PASS = "sensor123"

# ===================== GPIO =====================
LED_PIN = 24
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)
GPIO.output(LED_PIN, GPIO.HIGH)

# ===================== ADS1115 =====================
i2c_bus = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c_bus)
ads.gain = 1
chan = AnalogIn(ads, ADS.P0)

# ===================== OLED =====================
serial = i2c(port=1, address=0x3C)
device = sh1106(serial)

# ===================== InfluxDB Connect =====================
try:
    influx_client = InfluxDBClient(
        host=INFLUXDB_HOST,
        port=INFLUXDB_PORT,
        username=INFLUXDB_USER,
        password=INFLUXDB_PASS,
        database=INFLUXDB_DB
    )
    print("✓ เชื่อมต่อ InfluxDB สำเร็จ")
except Exception as e:
    print(f"✗ InfluxDB error: {e}")
    influx_client = None

# ===================== Fonts =====================
try:
    font_normal = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10
    )
    font_large = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16
    )
except:
    font_normal = ImageFont.load_default()
    font_large = ImageFont.load_default()

# ===================== Functions =====================
def get_status(dust):
    if dust <= 12: return "EXCELLENT", "★★★★★"
    elif dust <= 35.4: return "GOOD", "★★★★☆"
    elif dust <= 55.4: return "MODERATE", "★★★☆☆"
    elif dust <= 150.4: return "UNHEALTHY", "★★☆☆☆"
    elif dust <= 250.4: return "VERY BAD", "★☆☆☆☆"
    else: return "HAZARDOUS!", "☠☠☠"

def get_aqi_number(dust):
    if dust <= 12: return 1
    elif dust <= 35.4: return 2
    elif dust <= 55.4: return 3
    elif dust <= 150.4: return 4
    elif dust <= 250.4: return 5
    else: return 6

def read_dust():
    GPIO.output(LED_PIN, GPIO.LOW)
    time.sleep(0.00028)

    voltage = chan.voltage

    GPIO.output(LED_PIN, GPIO.HIGH)
    time.sleep(0.00972)

    zero_dust_voltage = 0.4
    if voltage > zero_dust_voltage:
        dust = (voltage - zero_dust_voltage) * 180
    else:
        dust = 0

    return dust, voltage

def moving_average(buf, value, size=10):
    buf.append(value)
    if len(buf) > size:
        buf.pop(0)
    return sum(buf) / len(buf)

def send_telegram_alert(dust, status):
    try:
        msg = (
            f"⚠️ PM2.5 ALERT\n\n"
            f"ค่า: {dust:.1f} µg/m³\n"
            f"สถานะ: {status}\n"
            f"เวลา: {datetime.now():%Y-%m-%d %H:%M:%S}"
        )
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10
        )
        return r.status_code == 200
    except:
        return False

def save_to_influxdb(dust, voltage, status):
    if not influx_client:
        return False

    json_body = [{
        "measurement": "dust",
        "tags": {"location": "home"},
        "fields": {
            "value": float(dust),
            "voltage": float(voltage),
            "aqi": get_aqi_number(dust),
            "status": status
        }
    }]
    try:
        influx_client.write_points(json_body)
        return True
    except Exception as e:
        print(f"✗ InfluxDB write error: {e}")
        return False

# ===================== MAIN =====================
try:
    print("PM2.5 Monitor Started")
    dust_buf = []

    alert_sent = False
    alert_cooldown = 0
    ALERT_COOLDOWN_TIME = 300

    last_write = 0

    while True:
        dust_raw, volt = read_dust()
        dust = moving_average(dust_buf, dust_raw)
        status, stars = get_status(dust)

        if status in ["UNHEALTHY", "VERY BAD", "HAZARDOUS!"]:
            if not alert_sent and alert_cooldown <= 0:
                if send_telegram_alert(dust, status):
                    alert_sent = True
                    alert_cooldown = ALERT_COOLDOWN_TIME
        else:
            alert_sent = False

        if alert_cooldown > 0:
            alert_cooldown -= 1

        with canvas(device) as draw:
            draw.rectangle((0, 0, 128, 12), fill="white")
            draw.text((10, 0), "PM2.5 MONITOR", fill="black", font=font_normal)
            draw.text((5, 18), f"{dust:.1f}", fill="white", font=font_large)
            draw.text((70, 22), "ug/m3", fill="white", font=font_normal)
            draw.text((5, 38), status, fill="white", font=font_normal)
            draw.text((5, 50), stars, fill="white", font=font_normal)

        print(f"PM2.5 {dust:6.1f} | {volt:.3f}V | {status}")

        if time.time() - last_write >= 10:
            if save_to_influxdb(dust, volt, status):
                print("→ Saved to InfluxDB")
            last_write = time.time()

        time.sleep(1)

except KeyboardInterrupt:
    print("\nStopped")
    if influx_client:
        influx_client.close()
    GPIO.cleanup()
