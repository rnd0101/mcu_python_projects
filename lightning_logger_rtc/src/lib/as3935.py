from machine import I2C, Pin
import time
from i2cflow import I2CFlow

# Register addresses
REG_AFE_GAIN       = 0x00
REG_NOISE_WATCHDOG = 0x01
REG_SREJ_MINSTRK   = 0x02
REG_IRQ_MASK_SRC   = 0x03
REG_ENERGY_LSB     = 0x04
REG_ENERGY_MID     = 0x05
REG_ENERGY_MSB     = 0x06
REG_DISTANCE       = 0x07
REG_DISPLAY_TUNING = 0x08
REG_PRESET_DEFAULT = 0x3C
REG_CALIB_RCO      = 0x3D

# Bit masks / fields
BIT_POWERDOWN   = 0x01
MASK_AFE_GAIN   = 0b11111 << 1

MASK_NOISE_FLOOR = 0b111 << 4
MASK_WATCHDOG    = 0b1111

BIT_CLEAR_STATS  = 1 << 6
MASK_MIN_STRIKES = 0b11 << 4
MASK_SPIKE_REJ   = 0b1111

MASK_LCO_DIVIDER = 0b11 << 6
BIT_MASK_DIST    = 1 << 5
MASK_IRQ_SRC     = 0b1111

MASK_DISTANCE    = 0b111111

BIT_DISP_LCO     = 1 << 7
BIT_DISP_SRCO    = 1 << 6
BIT_DISP_TRCO    = 1 << 5
MASK_TUN_CAP     = 0b1111

# AFE presets
AFE_GAIN_INDOOR  = 0b10010
AFE_GAIN_OUTDOOR = 0b01110

# Convenience maps
MIN_LIGHTNING_MAP = {1: 0b00, 5: 0b01, 9: 0b10, 16: 0b11}
DIVIDER_MAP       = {16: 0b00, 32: 0b01, 64: 0b10, 128: 0b11}

def _int_code_to_src(v):
    if v & 0x8: return 1     # lightning
    if v & 0x4: return 2     # disturber
    if v & 0x1: return 3     # noise
    return 0

class AS3935:
    def __init__(self, i2c_or_flow, addr=0x03):
        if isinstance(i2c_or_flow, I2C):
            self.bus = I2CFlow(i2c_or_flow)
        else:
            self.bus = i2c_or_flow
        self.addr = addr
        # optional conveniences
        self._log = None
        self._log_cap = 0
        self._cb = None
        self._irq_pin = None
        self._irq_pending = False
        self._irq_last_ms = 0

    def enable_logging(self, capacity=128):
        """Enable in-memory ring logging of events (list of dicts)."""
        self._log_cap = max(1, int(capacity))
        self._log = []
        return self

    def clear_log(self):
        if self._log is not None:
            self._log.clear()
        return self

    def get_log(self, count=None):
        """Return last N events (default: all)."""
        if self._log is None:
            return []
        if count is None or count >= len(self._log):
            return self._log[:]
        return self._log[-int(count):]

    def set_callback(self, cb):
        """Set a function(event_dict) called when events are serviced."""
        self._cb = cb
        return self

    def attach_irq(self, pin):
        """
        Connect an IRQ Pin (open-drain active-high). ISR sets a flag;
        call service() in your loop to handle events safely.
        """
        self._irq_pin = pin
        self._irq_pending = False
        self._irq_last_ms = 0

        def _isr(p):
            # keep ISR tiny: set a flag and timestamp, debounce 3ms
            now = time.ticks_ms()
            if not self._irq_pending or time.ticks_diff(now, self._irq_last_ms) > 3:
                self._irq_pending = True
                self._irq_last_ms = now

        pin.irq(trigger=Pin.IRQ_RISING, handler=_isr)
        return self

    def service(self, max_events=8):
        """
        Drain pending IRQ(s). Returns a list of event dicts.
        Safe to call in your main loop.
        """
        events = []
        for _ in range(max_events):
            if not self._irq_pending:
                break
            # let IRQ latch properly
            if time.ticks_diff(time.ticks_ms(), self._irq_last_ms) < 2:
                break
            self._irq_pending = False
            ev = self.read_event()  # also clears the IRQ source internally
            if ev:
                self._append_log(ev)
                if self._cb:
                    try:
                        self._cb(ev)
                    except Exception as _e:
                        # avoid throwing from callbacks
                        pass
                events.append(ev)
        return events

    def poll(self):
        """
        Polling fallback (no IRQ pin). If an event is latched, consume it.
        Returns event dict or None.
        """
        ev = self.read_event(wait_ms=0)
        if ev:
            self._append_log(ev)
            if self._cb:
                try: self._cb(ev)
                except Exception: pass
        return ev

    def read_event(self, wait_ms=2):
        """
        Read and classify an interrupt and return a dict:
          {"ts": ms, "type": "lightning|disturber|noise",
           "distance_km": int|None, "energy": int|None, "src_code": int}
        Returns None if no event present.
        """
        code_raw = self._at().read1(REG_IRQ_MASK_SRC).last & MASK_IRQ_SRC if wait_ms == 0 else None
        if wait_ms:
            time.sleep_ms(wait_ms)
            code_raw = self._at().read1(REG_IRQ_MASK_SRC).last & MASK_IRQ_SRC
        src = _int_code_to_src(code_raw)
        if src == 0:
            return None

        ts = time.ticks_ms()
        if src == 1:
            d = self.getLightningDistKm()
            e = self.getStrikeEnergyRaw()
            return {"ts": ts, "type": "lightning", "distance_km": d, "energy": e, "src_code": code_raw}
        elif src == 2:
            return {"ts": ts, "type": "disturber", "distance_km": None, "energy": None, "src_code": code_raw}
        else:
            return {"ts": ts, "type": "noise", "distance_km": None, "energy": None, "src_code": code_raw}

    def format_event(self, ev):
        """Human-readable one-liner for REPL/logs."""
        t = ev["type"][0].upper()
        if ev["type"] == "lightning":
            return "t={}ms L d={}km e={}".format(ev["ts"], ev["distance_km"], ev["energy"])
        elif ev["type"] == "disturber":
            return "t={}ms D".format(ev["ts"])
        else:
            return "t={}ms N".format(ev["ts"])

    def format_mqtt(self, ev, base_topic="sensors/as3935"):
        """
        Return (topic, payload_str). payload is compact JSON.
        """
        try:
            import ujson as json
        except Exception:
            json = None
        topic = "{}/event".format(base_topic)
        payload_obj = {
            "ts": ev["ts"],
            "type": ev["type"],
            "distance_km": ev["distance_km"],
            "energy": ev["energy"],
        }
        if json:
            payload = json.dumps(payload_obj)
        else:
            # minimal JSON formatter
            d = payload_obj["distance_km"]
            e = payload_obj["energy"]
            payload = '{{"ts":{},"type":"{}","distance_km":{},"energy":{}}}'.format(
                payload_obj["ts"], payload_obj["type"],
                "null" if d is None else d,
                "null" if e is None else e,
            )
        return topic, payload

    def status(self):
        """
        Snapshot of useful settings (dict). Good for REPL checks.
        """
        # Read back fields
        # AFE gain
        # (We read full regs and decode with masks.)
        r0 = self._at().read1(REG_AFE_GAIN).last
        r1 = self._at().read1(REG_NOISE_WATCHDOG).last
        r2 = self._at().read1(REG_SREJ_MINSTRK).last
        r3 = self._at().read1(REG_IRQ_MASK_SRC).last
        r8 = self._at().read1(REG_DISPLAY_TUNING).last

        return {
            "powerdown": 1 if (r0 & BIT_POWERDOWN) else 0,
            "indoors": 1 if ((r0 & MASK_AFE_GAIN) >> 1) == AFE_GAIN_INDOOR else 0,
            "noise": (r1 & MASK_NOISE_FLOOR) >> 4,
            "watchdog": (r1 & MASK_WATCHDOG) >> 0,
            "spike_rej": (r2 & MASK_SPIKE_REJ) >> 0,
            "min_strikes": {v:k for k,v in MIN_LIGHTNING_MAP.items()}.get((r2 & MASK_MIN_STRIKES) >> 4, None),
            "mask_dist": 1 if (r3 & BIT_MASK_DIST) else 0,
            "lco_div": {v:k for k,v in DIVIDER_MAP.items()}.get((r3 & MASK_LCO_DIVIDER) >> 6, None),
            "tuning_cap_steps": (r8 & MASK_TUN_CAP),
            "tuning_cap_pf": ((r8 & MASK_TUN_CAP) * 8),
        }

    # internal
    def _append_log(self, ev):
        if self._log is None: return
        self._log.append(ev)
        if len(self._log) > self._log_cap:
            del self._log[0]

    # ---------------- original driver API (unchanged) ----------------

    @classmethod
    def from_config(cls, i2c_or_flow, cfg: dict):
        addr = cfg.get("AS3935_ADDR", 0x03)
        dev = cls(i2c_or_flow, addr=addr)
        if dev.begin() != 0:
            return dev
        dev.defInit().powerUp()
        dev.setIndoors() if cfg.get("AS3935_INDOORS", True) else dev.setOutdoors()
        dev.setIRQOutputSource(0)
        dev.setTuningCaps(int(cfg.get("AS3935_TUNING_CAP_PF", 96)))
        dev.setNoiseFloorLvl(int(cfg.get("AS3935_NOISE", 2)))
        dev.setWatchdogThreshold(int(cfg.get("AS3935_WDTH", 2)))
        dev.setSpikeRejection(int(cfg.get("AS3935_SREJ", 2)))
        mn = int(cfg.get("AS3935_MIN_N", 1))
        if mn in MIN_LIGHTNING_MAP:
            dev.setMinNumLightnings(mn)
        maskd = bool(cfg.get("AS3935_MASK_DIST", False))
        dev.disturberEn(not maskd)
        return dev

    def apply_config(self, cfg: dict):
        if "AS3935_ADDR" in cfg: self.setI2CAddress(int(cfg["AS3935_ADDR"]))
        self.setIndoors() if cfg.get("AS3935_INDOORS", True) else self.setOutdoors()
        if "AS3935_TUNING_CAP_PF" in cfg: self.setTuningCaps(int(cfg["AS3935_TUNING_CAP_PF"]))
        if "AS3935_NOISE" in cfg: self.setNoiseFloorLvl(int(cfg["AS3935_NOISE"]))
        if "AS3935_WDTH" in cfg: self.setWatchdogThreshold(int(cfg["AS3935_WDTH"]))
        if "AS3935_SREJ" in cfg: self.setSpikeRejection(int(cfg["AS3935_SREJ"]))
        mn = int(cfg.get("AS3935_MIN_N", 1))
        if mn in MIN_LIGHTNING_MAP: self.setMinNumLightnings(mn)
        if "AS3935_MASK_DIST" in cfg: self.disturberEn(not bool(cfg["AS3935_MASK_DIST"]))
        return self

    def _at(self): return self.bus.at(self.addr)
    def _rmw(self, reg, mask, shift, value): return self._at().rmw(reg, mask, shift, value).last
    def _get(self, reg, mask, shift): return self._at().field_get(reg, mask, shift).last

    def setI2CAddress(self, addr): self.addr = addr; return self

    def begin(self):
        try:
            _ = self._at().read1(REG_DISTANCE).last
            return 0
        except Exception:
            return -1

    def defInit(self):
        self._at().write1(REG_PRESET_DEFAULT, 0x96)
        self._at().write1(REG_CALIB_RCO, 0x96)
        time.sleep_ms(3)
        self.setIRQOutputSource(0)
        return self

    def powerUp(self):
        v = self._at().read1(REG_AFE_GAIN).last
        v &= ~BIT_POWERDOWN
        self._at().write1(REG_AFE_GAIN, v)
        return self

    def powerDown(self):
        v = self._at().read1(REG_AFE_GAIN).last
        v |= BIT_POWERDOWN
        self._at().write1(REG_AFE_GAIN, v)
        return self

    def setIndoors(self): self._rmw(REG_AFE_GAIN, MASK_AFE_GAIN, 1, AFE_GAIN_INDOOR); return self
    def setOutdoors(self): self._rmw(REG_AFE_GAIN, MASK_AFE_GAIN, 1, AFE_GAIN_OUTDOOR); return self
    def disturberEn(self, enable=True): self._rmw(REG_IRQ_MASK_SRC, BIT_MASK_DIST, 5, 0 if enable else 1); return self

    def setIRQOutputSource(self, src):
        self._rmw(REG_DISPLAY_TUNING, BIT_DISP_LCO, 7, 0)
        self._rmw(REG_DISPLAY_TUNING, BIT_DISP_SRCO, 6, 0)
        self._rmw(REG_DISPLAY_TUNING, BIT_DISP_TRCO, 5, 0)
        if src == 1: self._rmw(REG_DISPLAY_TUNING, BIT_DISP_LCO, 7, 1)
        elif src == 2: self._rmw(REG_DISPLAY_TUNING, BIT_DISP_SRCO, 6, 1)
        elif src == 3: self._rmw(REG_DISPLAY_TUNING, BIT_DISP_TRCO, 5, 1)
        return self

    def setTuningCaps(self, cap_pf):
        steps = max(0, min(15, (cap_pf // 8)))
        self._rmw(REG_DISPLAY_TUNING, MASK_TUN_CAP, 0, steps)
        return self

    def setNoiseFloorLvl(self, level):
        if not 0 <= level <= 7: raise ValueError("noise level 0..7")
        self._rmw(REG_NOISE_WATCHDOG, MASK_NOISE_FLOOR, 4, level); return self

    def setWatchdogThreshold(self, level):
        if not 0 <= level <= 15: raise ValueError("watchdog 0..15")
        self._rmw(REG_NOISE_WATCHDOG, MASK_WATCHDOG, 0, level); return self

    def setSpikeRejection(self, level):
        if not 0 <= level <= 15: raise ValueError("spike rejection 0..15")
        self._rmw(REG_SREJ_MINSTRK, MASK_SPIKE_REJ, 0, level); return self

    def setMinNumLightnings(self, n):
        if n not in MIN_LIGHTNING_MAP: raise ValueError("n must be one of 1,5,9,16")
        self._rmw(REG_SREJ_MINSTRK, MASK_MIN_STRIKES, 4, MIN_LIGHTNING_MAP[n]); return self

    def clearStatistics(self):
        self._rmw(REG_SREJ_MINSTRK, BIT_CLEAR_STATS, 6, 1)
        self._rmw(REG_SREJ_MINSTRK, BIT_CLEAR_STATS, 6, 0)
        self._rmw(REG_SREJ_MINSTRK, BIT_CLEAR_STATS, 6, 1)
        return self

    def antennaDivider(self, div):
        if div not in DIVIDER_MAP: raise ValueError("div must be 16,32,64,128")
        self._rmw(REG_IRQ_MASK_SRC, MASK_LCO_DIVIDER, 6, DIVIDER_MAP[div]); return self

    def getInterruptSrc(self, wait_ms=2):
        if wait_ms: time.sleep_ms(wait_ms)
        code = self._at().read1(REG_IRQ_MASK_SRC).last & MASK_IRQ_SRC
        return _int_code_to_src(code)

    def getLightningDistKm(self): return self._at().read1(REG_DISTANCE).last & MASK_DISTANCE
    def getStrikeEnergyRaw(self):
        l = self._at().read1(REG_ENERGY_LSB).last
        m = self._at().read1(REG_ENERGY_MID).last
        h = self._at().read1(REG_ENERGY_MSB).last & 0x1F
        return (h << 16) | (m << 8) | l

    def calibrate(self): self._at().write1(REG_CALIB_RCO, 0x96); time.sleep_ms(3)
    def indoors(self, enable=True): return self.setIndoors() if enable else self.setOutdoors()
