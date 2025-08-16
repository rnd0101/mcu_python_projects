from machine import I2C, Pin
import time
import rtc_ds3231 as rtcmod

# Provide your own bus (change pins per board)
def make_i2c():
    # ESP32-ish defaults; adjust for STM32/ESP32-Cx as needed
    return I2C(0, sda=Pin(22), scl=Pin(23), freq=100_000)

def main():
    # Init I2C (rtcmod will SoftI2C-fallback if you pass None)
    try:
        i2c = make_i2c()
    except Exception as e:
        print("I2C init failed:", e)
        i2c = None

    # Optional: show scan so you know 0x68 is present
    if i2c:
        try:
            addrs = i2c.scan()
            print("I2C scan:", [hex(a) for a in addrs])
        except Exception as e:
            print("I2C scan failed:", e)

    # Sync system RTC from DS3231
    try:
        now = rtcmod.sync_system_from_ds3231(i2c=i2c)
        print("Boot: system time synced ->", now)
    except Exception as e:
        print("Boot: RTC sync failed:", e)

    # Quick health check (temperature + OSF flag)
    try:
        dev = rtcmod.detect(i2c=i2c)
        print("DS3231 temp (°C):", dev.temperature_c())
        print("OSF flag:", dev.osf(), "(1 means time may have been lost)")
    except Exception as e:
        print("RTC health check failed:", e)

    # Example: set a specific time on the DS3231, then resync system
    if False:
        new_dt = (2025, 8, 14, 14, 34, 56)
        try:
            rtcmod.write_datetime(new_dt, i2c=i2c)
            now = rtcmod.sync_system_from_ds3231(i2c=i2c)
            print("RTC updated, system resynced ->", now)
        except Exception as e:
            print("Write failed:", e)

    print("localtime() ->", time.localtime())

main()
