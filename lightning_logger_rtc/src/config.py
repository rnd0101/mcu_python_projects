CFG = {
    # I2C
    "I2C_ID": 0,
    "I2C_SDA": 22,
    "I2C_SCL": 23,
    "I2C_FREQ": 100000,

    # DS3231
    "RTC_ENABLE": True,

    # AS3935
    "AS3935_ADDR": 0x03,
    "AS3935_IRQ_PIN": 2,
    "AS3935_INDOORS": True,
    "AS3935_TUNING_CAP_PF": 96,
    "AS3935_NOISE": 2,
    "AS3935_WDTH": 2,
    "AS3935_SREJ": 2,

    # Wi-Fi
    "WIFI_SSID": None,
    "WIFI_PASSWORD": None,
    "WIFI_TIMEOUT_MS": 10000,

    # MQTT
    "MQTT_ENABLE": True,
    "MQTT_HOST": None,
    "MQTT_PORT": 1883,
    "MQTT_CLIENT_ID": "esp32-as3935",
    "MQTT_USER": None,
    "MQTT_PASSWORD": None,
    "MQTT_BASE_TOPIC": "sensors/as3935",
    "MQTT_KEEPALIVE": 60,
    "MQTT_SSL": False,
}

# Optional local overrides (git-ignored). If present, it should define CFG_UPDATES = {...}
try:
    from config_local import CFG_UPDATES
    CFG.update(CFG_UPDATES)
except Exception:
    pass
