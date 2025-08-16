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
    "AS3935_NOISE": 0,
    "AS3935_WDTH": 0,
    "AS3935_SREJ": 0,
}

# Optional local overrides (git-ignored). If present, it should define CFG_UPDATES = {...}
try:
    from config_local import CFG_UPDATES
    CFG.update(CFG_UPDATES)
except Exception:
    pass
