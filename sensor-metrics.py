#!/usr/bin/env python3

import time

from bme280 import BME280

from pms5003 import PMS5003, ReadTimeoutError, ChecksumMismatchError
from prometheus_client import Gauge, start_http_server
from systemd.journal import JournalHandler
from enviroplus import gas

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus

import logging

# Setup logging to the Systemd Journal
log = logging.getLogger('bme280_sensor')
log.addHandler(JournalHandler())
log.setLevel(logging.INFO)

# Initialize the BME280 sensor
bus = SMBus(1)
bme280 = BME280(i2c_dev=bus)

# Create PMS5003 instance
pms5003 = PMS5003()

# Create Prometheus gauges for measurements
gt = Gauge('shop_temperature', 'Temperature measured by the BME280 Sensor')
gh = Gauge('shop_humidity', 'Humidity measured by the BME280 Sensor')
gp = Gauge('shop_pressure', 'Pressure measured by the PMS5003 Sensor')
gp2 = Gauge('shop_PM2', 'PM2.5 ug/m3 (combustion particles, organic compounds, metals)')
gp10 = Gauge('shop_PM10', 'PM10 ug/m3')
go = Gauge('shop_oxidised', 'ko (gas oxidised)')
gr = Gauge('shop_reduced', 'ko (gas reduced)')
gn = Gauge('shop_nh3', 'ko (gas nh3)')

# Tuning factor for compensation. Decrease this number to adjust the
# temperature down, and increase to adjust up
temp_factor = 4.5

# Calculate the compensated temp to 1dp
def comp_temp(factor):
    cpu_temp = get_cpu_temperature()
    raw_temp = bme280.get_temperature()
    comp_temp = raw_temp - ((cpu_temp - raw_temp) / factor)
    return round(comp_temp, 1)

# Humidity is based on the raw temperature, as we have had to compensate
# that we need to also compensate the humidity value. Factor determined from an external hygrometer
# TODO: find a way to use the compensated temp for this, probably have to read the bus directly
humidity_factor = 20

# Calculate the compensated humidity to 1dp
def comp_humidity(factor):
    comp_humidity = (bme280.get_humidity() + factor)
    return round(comp_humidity, 1)

# Read values from BME280 and PMS5003, take the 5s average
def read_values():
    temps = []
    humidities = []
    pressures = []
    pm10s = []
    pm2s = []
    gos = []
    grs = []
    gns = []
    
    for i in range(5):
        # Read the gas data
        gas_data = gas.read_all()
        gos.append(gas_data.oxidising / 1000)
        grs.append(gas_data.reducing / 1000)
        gns.append(gas_data.nh3 / 1000)
        
        # read temp etc
        temps.append(comp_temp(temp_factor))
        humidities.append(comp_humidity(humidity_factor))
        pressures.append(bme280.get_pressure() * 100)
        
        # Read particle data       
        try:
            pm_values = pms5003.read()
            pm10s.append(pm_values.pm_ug_per_m3(10))
            pm2s.append(pm_values.pm_ug_per_m3(2.5))
            
        except(ReadTimeoutError, ChecksumMismatchError):
            logging.info("Failed to read PMS5003. Reseting and retrying.")
            pms5003.reset()
            pm_values = pms5003.read()
            pm10s.append(pm_values.pm_ug_per_m3(10))
            pm2s.append(pm_values.pm_ug_per_m3(2.5))
        
        time.sleep(1)
    
    # Calculate 5s averages and report
    gt.set(sum(temps)/len(temps))
    gh.set(sum(humidities)/len(humidities))
    gp.set(sum(pressures)/len(pressures))
    gp2.set(sum(pm2s)/len(pm2s))
    gp10.set(sum(pm10s)/len(pm10s))

# Get the temperature of the CPU for compensation
def get_cpu_temperature():
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = f.read()
        temp = int(temp) / 1000.0
    return temp

if __name__ == "__main__":
    # Expose metrics
    metrics_port = 8000
    start_http_server(metrics_port)
    print("Serving sensor metrics on :{}".format(metrics_port))
    log.info("Serving sensor metrics on :{}".format(metrics_port))

    while True:
        read_values()
