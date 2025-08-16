# src/netmqtt.py
import time, network
try:
    from umqtt.simple import MQTTClient
except ImportError:
    MQTTClient = None


def wifi_connect(cfg, ssid=None, password=None, timeout_ms=None):
    """
    Connect to Wi-Fi using values from cfg (or explicit args).
    Expected cfg keys: WIFI_SSID, WIFI_PASSWORD, WIFI_TIMEOUT_MS.
    Returns the WLAN object or None on failure.
    """
    ssid = ssid if ssid is not None else cfg.get("WIFI_SSID")
    password = password if password is not None else cfg.get("WIFI_PASSWORD")
    timeout_ms = timeout_ms if timeout_ms is not None else cfg.get("WIFI_TIMEOUT_MS", 10_000)

    if not ssid or not password:
        print("[wifi] SSID/PASSWORD not set")
        return None

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("[wifi] connecting to", ssid)
        wlan.connect(ssid, password)
        t0 = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                print("[wifi] connect timeout")
                return None
            time.sleep_ms(200)

    print("[wifi] connected:", wlan.ifconfig())
    return wlan


def mqtt_connect(cfg,
                 host=None, port=None,
                 client_id=None, user=None, password=None,
                 keepalive=None, ssl=None):
    """
    Create & connect an MQTTClient using values from cfg (or explicit args).
    Expected cfg keys:
      MQTT_ENABLE, MQTT_HOST, MQTT_PORT, MQTT_CLIENT_ID,
      MQTT_USER, MQTT_PASSWORD, MQTT_KEEPALIVE, MQTT_SSL
    Returns MQTTClient or None (disabled/missing lib/host).
    """
    if MQTTClient is None:
        print("[mqtt] umqtt.simple not available")
        return None

    if not cfg.get("MQTT_ENABLE", True):
        print("[mqtt] disabled in cfg")
        return None

    host = host or cfg.get("MQTT_HOST")
    if not host:
        print("[mqtt] host not set")
        return None

    client = MQTTClient(
        client_id or cfg.get("MQTT_CLIENT_ID", "esp32"),
        host,
        port=port if port is not None else cfg.get("MQTT_PORT", 1883),
        user=user if user is not None else cfg.get("MQTT_USER"),
        password=password if password is not None else cfg.get("MQTT_PASSWORD"),
        keepalive=keepalive if keepalive is not None else cfg.get("MQTT_KEEPALIVE", 60),
        ssl=ssl if ssl is not None else cfg.get("MQTT_SSL", False),
    )
    client.connect()
    print("[mqtt] connected to", host)
    return client
