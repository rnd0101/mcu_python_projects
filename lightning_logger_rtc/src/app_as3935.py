# src/app_as3935.py
from machine import I2C, Pin
import time
from config import CFG
from lib.as3935 import AS3935
try:
    from umqtt.simple import MQTTClient
except Exception:
    MQTTClient = None


class AS3935App:
    def __init__(self):
        self.i2c = None
        self.sensor = None
        self.irq_pin = None
        self._running = False
        self._mqtt = None
        self._mqtt_topic = "sensors/as3935"  # base topic

    # --- lifecycle ---
    def start(self):
        if self.sensor:
            return self.sensor

        self.i2c = I2C(
            CFG["I2C_ID"],
            sda=Pin(CFG["I2C_SDA"]),
            scl=Pin(CFG["I2C_SCL"]),
            freq=CFG["I2C_FREQ"],
        )
        self.sensor = AS3935.from_config(self.i2c, CFG)
        # attach IRQ if configured
        if CFG.get("AS3935_IRQ_PIN") is not None:
            self.irq_pin = Pin(CFG["AS3935_IRQ_PIN"], Pin.IN, Pin.PULL_UP)
            self.sensor.attach_irq(self.irq_pin)
        # enable in-memory ring log
        self.sensor.enable_logging(256)
        return self.sensor

    def stop(self):
        self._running = False
        return True

    # --- info / logging ---
    def status(self):
        self._ensure()
        return self.sensor.status()

    def tail(self, n=10):
        self._ensure()
        return self.sensor.get_log(n)

    # --- single step / run loop ---
    def step(self):
        """
        Handle any pending event once (IRQ or polling fallback).
        Returns list of events handled (0..N).
        """
        self._ensure()
        if self.irq_pin:
            return self.sensor.service()
        ev = self.sensor.poll()
        return [ev] if ev else []

    def run(self, sleep_ms=20, print_events=True):
        """
        Loop forever, draining events and optionally printing/publishing.
        Ctrl+C to stop.
        """
        self._ensure()
        self._running = True
        try:
            while self._running:
                events = self.sensor.service() if self.irq_pin else ([self.sensor.poll()] if self.sensor.poll() else [])
                for ev in events:
                    if not ev:
                        continue
                    if print_events:
                        print(self.sensor.format_event(ev))
                    if self._mqtt:
                        topic, payload = self.sensor.format_mqtt(ev, base_topic=self._mqtt_topic)
                        try:
                            self._mqtt.publish(topic, payload)
                        except Exception as e:
                            # keep loop alive even if broker hiccups
                            print("mqtt publish error:", e)
                time.sleep_ms(sleep_ms)
        except KeyboardInterrupt:
            self._running = False
            print("stopped")

    # --- mqtt (optional) ---
    def connect_mqtt(self, host, client_id="as3935", user=None, password=None, base_topic=None, keepalive=60, port=1883, ssl=False):
        if MQTTClient is None:
            raise RuntimeError("umqtt.simple not available on this firmware")
        self._mqtt = MQTTClient(client_id, host, port=port, user=user, password=password, keepalive=keepalive, ssl=ssl)
        self._mqtt.connect()
        if base_topic:
            self._mqtt_topic = base_topic
        return True

    def disconnect_mqtt(self):
        if self._mqtt:
            try:
                self._mqtt.disconnect()
            except Exception:
                pass
            self._mqtt = None
        return True

    # --- helpers ---
    def _ensure(self):
        if not self.sensor:
            self.start()


# singleton convenience
app = AS3935App()

# convenience top-level functions (so you can: from app_as3935 import start, run, ...)
def start(): return app.start()
def stop(): return app.stop()
def status(): return app.status()
def tail(n=10): return app.tail(n)
def step(): return app.step()
def run(sleep_ms=20, print_events=True): return app.run(sleep_ms=sleep_ms, print_events=print_events)
def connect_mqtt(host, client_id="as3935", user=None, password=None, base_topic=None, keepalive=60, port=1883, ssl=False):
    return app.connect_mqtt(host, client_id, user, password, base_topic, keepalive, port, ssl)
def disconnect_mqtt(): return app.disconnect_mqtt()
