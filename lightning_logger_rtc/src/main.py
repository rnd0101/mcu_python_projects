from machine import I2C, Pin
import time
import rtc_ds3231 as rtcmod
from config import CFG

def make_i2c():
    return I2C(
        CFG["I2C_ID"],
        sda=Pin(CFG["I2C_SDA"]),
        scl=Pin(CFG["I2C_SCL"]),
        freq=CFG["I2C_FREQ"],
    )

def main():
    try:
        i2c = make_i2c()
    except Exception as e:
        print("I2C init failed:", e)
        i2c = None

    if i2c:
        try:
            addrs = i2c.scan()
            print("I2C scan:", [hex(a) for a in addrs])
        except Exception as e:
            print("I2C scan failed:", e)

    if CFG.get("RTC_ENABLE", True):
        try:
            now = rtcmod.sync_system_from_ds3231(i2c=i2c)
            print("Boot: system time synced ->", now)
        except Exception as e:
            print("Boot: RTC sync failed:", e)

        try:
            dev = rtcmod.detect(i2c=i2c)
            print("DS3231 temp (°C):", dev.temperature_c())
            print("OSF flag:", dev.osf(), "(1 means time may have been lost)")
        except Exception as e:
            print("RTC health check failed:", e)

    print("localtime() ->", time.localtime())

main()
