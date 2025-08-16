
from machine import I2C, Pin
import time
import rtc_ds3231 as rtcmod
from config import CFG
import netmqtt

try:
    import app_as3935 as asapp
except Exception:
    asapp = None


def make_i2c():
    return I2C(
        CFG.get("I2C_ID", 0),
        sda=Pin(CFG.get("I2C_SDA", 22)),
        scl=Pin(CFG.get("I2C_SCL", 23)),
        freq=CFG.get("I2C_FREQ", 100_000),
    )


def main():
    # Wi-Fi + MQTT
    wlan = netmqtt.wifi_connect(CFG)
    mqtt = netmqtt.mqtt_connect(CFG) if wlan else None

    # I2C + DS3231
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

    if CFG.get("RTC_ENABLE", True) and i2c:
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

    # AS3935 app
    if asapp is None:
        print("[as3935] app_as3935.py not found; skipping run")
    elif not CFG.get("AS3935_ENABLE", True):
        print("[as3935] disabled via CFG['AS3935_ENABLE']=False; skipping run")
    else:
        sensor = asapp.start(CFG)
        print("[as3935] status:", sensor.status())

        if mqtt and hasattr(asapp, "app"):
            if hasattr(asapp.app, "use_mqtt"):
                asapp.app.use_mqtt(mqtt, base_topic="home/thunderstorm")
            else:
                asapp.app._mqtt = mqtt
                asapp.app._mqtt_topic = "home/thunderstorm"
            print("[as3935] mqtt bridged to home/thunderstorm")

        try:
            loop_ms = CFG.get("AS3935_LOOP_MS", 20)
            print("[as3935] running… Ctrl+C to stop")
            asapp.run(sleep_ms=loop_ms, print_events=True)
        except KeyboardInterrupt:
            print("[as3935] stopped by user")
            asapp.stop()

    # Clean up MQTT on exit
    if mqtt:
        try:
            mqtt.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
