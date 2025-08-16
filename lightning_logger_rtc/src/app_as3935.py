from machine import I2C, Pin
import time
from lib.as3935 import AS3935
try:
    from umqtt.simple import MQTTClient  # only for type presence
except Exception:
    MQTTClient = None


def _iso8601_utc():
    t = time.gmtime()
    y, m, d, hh, mm, ss = t[0], t[1], t[2], t[3], t[4], t[5]
    return "{}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(y, m, d, hh, mm, ss)


class AS3935App:
    def __init__(self):
        # core
        self.i2c = None
        self.sensor = None
        self._running = False

        # irq/log
        self._irq_pin = None
        self._irq_pending = False
        self._irq_last_ms = 0
        self._log = []
        self._log_cap = 256

        # mqtt/state
        self._mqtt = None
        self._mqtt_topic = "home/thunderstorm"  # base topic (you can override in start())
        self._last_src = 0
        self._last_dist_ms = 0
        self._last_noise_ms = 0
        self._last_keepalive_ms = 0
        self._throttle_dist_ms = 10 * 60 * 1000
        self._throttle_noise_ms = 10 * 60 * 1000
        self._keepalive_ms = 15 * 60 * 1000

    # public API
    def start(self, cfg: dict, i2c: I2C = None, irq_pin: Pin = None,
              mqtt_client: "MQTTClient" = None, base_topic: str = None):
        """
        Build + configure AS3935 using cfg and optional objects passed in.
        cfg keys used here: AS3935_* and optionally AS3935_IRQ_PIN.
        """
        # I2C
        if i2c is None:
            i2c = I2C(
                cfg.get("I2C_ID", 0),
                sda=Pin(cfg.get("I2C_SDA", 22)),
                scl=Pin(cfg.get("I2C_SCL", 23)),
                freq=cfg.get("I2C_FREQ", 100_000),
            )
        self.i2c = i2c

        # sensor
        self.sensor = AS3935.from_config(self.i2c, cfg)
        self.sensor.enable_logging(self._log_cap)  # use driver’s ring too

        # IRQ
        if irq_pin is None and cfg.get("AS3935_IRQ_PIN") is not None:
            irq_pin = Pin(cfg["AS3935_IRQ_PIN"], Pin.IN, Pin.PULL_UP)
        if irq_pin is not None:
            self.attach_irq(irq_pin)

        # MQTT (optional)
        if mqtt_client is not None:
            self.use_mqtt(mqtt_client, base_topic or cfg.get("MQTT_BASE_TOPIC", self._mqtt_topic))

        # reset state timers and publish neutral state
        self._last_src = 0
        now = time.ticks_ms()
        self._last_dist_ms = now
        self._last_noise_ms = now
        self._last_keepalive_ms = now
        self._publish_state(False, 0, 0, False, False, retain=True)

        return self.sensor

    def stop(self):
        self._running = False
        return True

    def status(self):
        self._ensure_sensor()
        return self.sensor.status()

    def tail(self, n=10):
        self._ensure_sensor()
        return self.sensor.get_log(n)

    def step(self):
        """Handle at most one batch of pending events once."""
        self._ensure_sensor()
        if self._irq_pin:
            evs = self.service()
        else:
            ev = self.sensor.poll()
            evs = [ev] if ev else []
        return evs

    def run(self, sleep_ms=20, print_events=True):
        self._ensure_sensor()
        self._running = True
        try:
            while self._running:
                events = self.service() if self._irq_pin else []
                if not events:
                    ev = self.sensor.poll()
                    if ev:
                        events = [ev]

                now_ms = time.ticks_ms()
                for ev in events:
                    if not ev:
                        continue
                    if ev["type"] == "lightning":
                        d = ev.get("distance_km") or 0
                        e = ev.get("energy") or 0
                        self._publish_state(True, d, e, False, False, retain=True)
                        self._last_src = 1
                        if print_events:
                            print(self.sensor.format_event(ev))
                    elif ev["type"] == "disturber":
                        if time.ticks_diff(now_ms, self._last_dist_ms) >= self._throttle_dist_ms or self._last_src != 2:
                            self._publish_state(False, 0, 0, True, False, retain=True)
                            self._last_dist_ms = now_ms
                            self._last_src = 2
                            if print_events:
                                print(self.sensor.format_event(ev))
                    elif ev["type"] == "noise":
                        if time.ticks_diff(now_ms, self._last_noise_ms) >= self._throttle_noise_ms or self._last_src != 3:
                            self._publish_state(False, 0, 0, False, True, retain=True)
                            self._last_noise_ms = now_ms
                            self._last_src = 3
                            if print_events:
                                print(self.sensor.format_event(ev))

                # keepalive
                if time.ticks_diff(now_ms, self._last_keepalive_ms) >= self._keepalive_ms:
                    self._publish_state(False, 0, 0, False, False, retain=True)
                    self._last_keepalive_ms = now_ms

                time.sleep_ms(sleep_ms)
        except KeyboardInterrupt:
            self._running = False
            print("stopped")

    # extras / configuration
    def use_mqtt(self, client, base_topic=None):
        self._mqtt = client
        if base_topic:
            self._mqtt_topic = base_topic
        return True

    def set_throttle(self, disturber_ms=None, noise_ms=None):
        if disturber_ms is not None:
            self._throttle_dist_ms = int(disturber_ms)
        if noise_ms is not None:
            self._throttle_noise_ms = int(noise_ms)
        return True

    def set_keepalive(self, keepalive_ms):
        self._keepalive_ms = int(keepalive_ms)
        return True

    # irq / logging helpers
    def attach_irq(self, pin: Pin):
        self._irq_pin = pin
        self._irq_pending = False
        self._irq_last_ms = 0

        def _isr(p):
            now = time.ticks_ms()
            if not self._irq_pending or time.ticks_diff(now, self._irq_last_ms) > 3:
                self._irq_pending = True
                self._irq_last_ms = now

        pin.irq(trigger=Pin.IRQ_RISING, handler=_isr)
        self.sensor.attach_irq(pin)  # keep driver’s internal flow aligned
        return self

    def service(self, max_events=8):
        events = []
        for _ in range(max_events):
            if not self._irq_pending:
                break
            if time.ticks_diff(time.ticks_ms(), self._irq_last_ms) < 2:
                break
            self._irq_pending = False
            ev = self.sensor.read_event(wait_ms=0)  # already clears IRQ inside
            if ev:
                self._append_log(ev)
                events.append(ev)
        return events

    def _append_log(self, ev):
        self._log.append(ev)
        if len(self._log) > self._log_cap:
            del self._log[0]

    # internal
    def _publish_state(self, alert_on, distance, energy, is_disturber, is_noise, retain=True):
        if not self._mqtt:
            return
        topic = self._mqtt_topic + "/state"
        payload = '{{"alert":"{}","distance":{},"energy":{},"disturber":{},"noise":{},"timestamp":"{}"}}'.format(
            "ON" if alert_on else "OFF",
            int(distance) if distance is not None else 0,
            int(energy) if energy is not None else 0,
            "true" if is_disturber else "false",
            "true" if is_noise else "false",
            _iso8601_utc(),
        )
        try:
            self._mqtt.publish(topic, payload, retain)
        except Exception as e:
            print("[as3935] mqtt publish error:", e)

    def _ensure_sensor(self):
        if not self.sensor:
            raise RuntimeError("AS3935App not started; call start(cfg, ...) first")


# singleton and convenience functions
app = AS3935App()

def start(cfg, i2c=None, irq_pin=None, mqtt_client=None, base_topic=None):
    return app.start(cfg, i2c=i2c, irq_pin=irq_pin, mqtt_client=mqtt_client, base_topic=base_topic)

def stop(): return app.stop()
def status(): return app.status()
def tail(n=10): return app.tail(n)
def step(): return app.step()
def run(sleep_ms=20, print_events=True): return app.run(sleep_ms=sleep_ms, print_events=print_events)
def use_mqtt(client, base_topic=None): return app.use_mqtt(client, base_topic)
def set_throttle(disturber_ms=None, noise_ms=None): return app.set_throttle(disturber_ms, noise_ms)
def set_keepalive(ms): return app.set_keepalive(ms)
