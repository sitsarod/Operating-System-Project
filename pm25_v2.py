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

# ### ส่วนที่เพิ่ม 1: เรียกใช้ Library InfluxDB ###
from influxdb import InfluxDBClient

# ### ส่วนที่เพิ่ม 2: ตั้งค่าการเชื่อมต่อ InfluxDB ###
INFLUX_DB_NAME = 'pm25_data'
try:
    # เชื่อมต่อกับ Database ที่เราสร้างไว้
    client = InfluxDBClient(host='localhost', port=8086, database=INFLUX_DB_NAME)
    print(f"✓ เชื่อมต่อ InfluxDB ({INFLUX_DB_NAME}) สำเร็จ")
except Exception as e:
    print(f"✗ เชื่อมต่อ InfluxDB ไม่ได้: {e}")

# ตั้งค่า Telegram Bot (โค้ดเดิม)
TELEGRAM_BOT_TOKEN = "8592352462:AAEy3gNRMhWk8nIX4-0oaGxc8C5BVNaELXE"
TELEGRAM_CHAT_ID = "5630438332"

# ตั้งค่า GPIO สำหรับ LED ของเซ็นเซอร์ (โค้ดเดิม)
LED_PIN = 24
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)
GPIO.output(LED_PIN, GPIO.HIGH)

# ตั้งค่า I2C สำหรับ ADS1115 (โค้ดเดิม)
i2c_bus = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c_bus)
chan = AnalogIn(ads, 0)

# ตั้งค่าจอ OLED SH1106 (โค้ดเดิม)
serial = i2c(port=1, address=0x3C)
device = sh1106(serial)

# โหลดฟอนต์ (โค้ดเดิม)
try:
    font_normal = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 10)
    font_large = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 16)
except:
    font_normal = ImageFont.load_default()
    font_large = ImageFont.load_default()

# ฟังก์ชันเดิม
def get_status(dust):
    if dust <= 12: return "EXCELLENT", "★★★★★"
    elif dust <= 35.4: return "GOOD", "★★★★"
    elif dust <= 55.4: return "MODERATE", "★★★"
    elif dust <= 150.4: return "UNHEALTHY", "★★"
    elif dust <= 250.4: return "VERY BAD", "★"
    else: return "HAZARDOUS!", ":["

# ฟังก์ชันเดิม
def read_dust():
    GPIO.output(LED_PIN, GPIO.LOW)
    time.sleep(0.00028)
    voltage = chan.voltage
    time.sleep(0.00004)
    GPIO.output(LED_PIN, GPIO.HIGH)
    time.sleep(0.00968)
    
    zero_dust_voltage = -0.17
    if voltage > zero_dust_voltage:
        dust_density = (voltage - zero_dust_voltage) * 180
    else:
        dust_density = 0
    return dust_density, voltage

# ฟังก์ชันเดิม
def moving_average(readings, new_value, window_size=10):
    readings.append(new_value)
    if len(readings) > window_size:
        readings.pop(0)
    return sum(readings) / len(readings)

# ### ส่วนที่เพิ่ม 3: ฟังก์ชันส่งข้อมูลเข้า Database ###
def send_to_influx(dust_val, voltage_val, status_text):
    try:
        json_body = [
            {
                "measurement": "air_quality",  # ชื่อตารางข้อมูล
                "tags": {
                    "location": "home"         # แท็กระบุสถานที่
                },
                "fields": {
                    "pm25": float(dust_val),       # ค่าฝุ่น
                    "voltage": float(voltage_val)  # ค่าไฟ
                }
            }
        ]
        client.write_points(json_body)
    except Exception as e:
        print(f"Error sending to DB: {e}")

# ฟังก์ชันเดิม
def send_telegram_alert(dust_value, status):
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"⚠️ *คำเตือนคุณภาพอากาศ!* ⚠️\n\n"
        message += f"📊 ค่า PM2.5: *{dust_value:.1f} µg/m³*\n"
        message += f"📍 สถานะ: *{status}*\n"
        message += f"⏰ เวลา: {current_time}\n\n"
        
        if status == "UNHEALTHY": message += "🏠 แนะนำ: หลีกเลี่ยงการออกกลางแจ้งนาน"
        elif status == "VERY BAD": message += "🚨 แนะนำ: อยู่ในบ้าน ปิดหน้าต่าง"
        elif status == "HAZARDOUS!": message += "☠️ แนะนำ: อยู่ในบ้านเท่านั้น!"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, data=payload, timeout=10)
        return True
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False

# Main Loop เดิม
try:
    print("=" * 50)
    print("เครื่องวัดฝุ่น PM2.5 + InfluxDB เริ่มทำงาน!")
    print("=" * 50)
    
    dust_readings = []
    alert_sent = False
    alert_cooldown = 0
    ALERT_COOLDOWN_TIME = 300
    
    while True:
        # อ่านค่าฝุ่น (เดิม)
        dust_raw, volt = read_dust()
        dust = moving_average(dust_readings, dust_raw, window_size=10)
        status, stars = get_status(dust)
        
        # ### ส่วนที่เพิ่ม 4: เรียกใช้ฟังก์ชันส่งข้อมูลตรงนี้ ###
        send_to_influx(dust, volt, status)
        
        # Telegram Logic (เดิม)
        if status in ["UNHEALTHY", "VERY BAD", "HAZARDOUS!"]:
            if not alert_sent and alert_cooldown <= 0:
                print(f"\n🚨 ส่งการแจ้งเตือน Telegram...")
                if send_telegram_alert(dust, status):
                    alert_sent = True
                    alert_cooldown = ALERT_COOLDOWN_TIME
        else:
            if alert_sent: alert_sent = False
        
        if alert_cooldown > 0: alert_cooldown -= 1
        
        # แสดงผลจอ OLED (เดิม)
        with canvas(device) as draw:
            draw.rectangle((0, 0, 128, 12), fill="white")
            draw.text((10, 0), "PM2.5 MONITOR", fill="black", font=font_normal)
            draw.text((5, 18), f"{dust:.1f}", fill="white", font=font_large)
            draw.text((70, 22), "AQI", fill="white", font=font_normal)
            draw.text((5, 38), f"{status}", fill="white", font=font_normal)
            draw.text((5, 50), f"{stars}", fill="white", font=font_normal)
        
        # Print ลง Terminal (ปรับนิดหน่อยให้รู้ว่าส่ง DB แล้ว)
        print(f"PM2.5: {dust:6.1f} | Volt: {volt:.3f} | {status} -> DB OK")
        
        time.sleep(1)

except KeyboardInterrupt:
    print("\nหยุดการทำงาน")
    GPIO.cleanup()
