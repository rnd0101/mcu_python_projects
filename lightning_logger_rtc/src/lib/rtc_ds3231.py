from machine import I2C, Pin, RTC, SoftI2C
import time
from i2cflow import I2CFlow, I2CError

ADDR = 0x68

REG_SEC      = 0x00  # ss
REG_MIN      = 0x01  # mm
REG_HOUR     = 0x02  # hh (12/24h)
REG_DOW      = 0x03  # day of week (1..7)
REG_DATE     = 0x04  # day (1..31)
REG_MONTH    = 0x05  # month (1..12) + century bit (bit7)
REG_YEAR     = 0x06  # year (00..99)
REG_CONTROL  = 0x0E
REG_STATUS   = 0x0F  # OSF bit (bit7)
REG_TEMP_MSB = 0x11
REG_TEMP_LSB = 0x12

def bcd2bin(x): return ((x >> 4) * 10) + (x & 0x0F)
def bin2bcd(x): return ((x // 10) << 4) | (x % 10)

def _make_default_i2c(freq=100_000, sda=22, scl=23):
    try:
        return I2C(0, sda=Pin(sda), scl=Pin(scl), freq=freq)
    except Exception:
        return SoftI2C(sda=Pin(sda), scl=Pin(scl), freq=freq)

class DS3231:
    """
    Fluent I2C-backed DS3231 RTC.
    """
    def __init__(self, i2c: I2C, addr: int = ADDR):
        self.bus = I2CFlow(i2c).at(addr).retry(2, backoff_ms=2)

    # --- raw block read/write ---
    def _read_datetime_regs(self):
        # 7 bytes starting at 0x00
        return self.bus.readn(REG_SEC, 7).last

    def _write_datetime_regs(self, buf: bytes):
        # expects 7 bytes: sec..year
        self.bus.writen(REG_SEC, buf)

    # --- high-level datetime ---
    def read_datetime(self):
        """
        Returns (year, month, day, hour, minute, second)
        """
        regs = self._read_datetime_regs()
        ss = bcd2bin(regs[0] & 0x7F)
        mm = bcd2bin(regs[1] & 0x7F)

        hr = regs[2]
        if hr & 0x40:  # 12-hour mode
            # bit5 = AM/PM, bits4..0 = 1..12
            h12 = bcd2bin(hr & 0x1F)
            pm = 1 if (hr & 0x20) else 0
            hh = (h12 % 12) + (12 if pm else 0)
        else:          # 24-hour mode
            hh = bcd2bin(hr & 0x3F)

        date = bcd2bin(regs[4] & 0x3F)
        month = bcd2bin(regs[5] & 0x1F)
        year = 2000 + bcd2bin(regs[6])
        # (Optional) century bit in month register (bit7) would add +100 years.

        return (year, month, date, hh, mm, ss)

    def write_datetime(self, dt):
        """
        dt = (year, month, day, hour, minute, second)
        Writes 24-hour format, leaves control bits sane.
        """
        y, m, d, hh, mm, ss = dt
        buf = bytes([
            bin2bcd(ss & 0x7F),
            bin2bcd(mm & 0x7F),
            bin2bcd(hh & 0x3F),      # 24h
            1,                       # day-of-week placeholder (1..7)
            bin2bcd(d & 0x3F),
            bin2bcd(m & 0x1F),       # century bit not handled
            bin2bcd((y - 2000) & 0xFF),
        ])
        self._write_datetime_regs(buf)

    def osf(self):
        """Return Oscillator Stop Flag (1 means time may be invalid)."""
        return (self.bus.read1(REG_STATUS).last >> 7) & 1

    def clear_osf(self):
        v = self.bus.read1(REG_STATUS).last
        self.bus.write1(REG_STATUS, v & ~(1 << 7))

    def temperature_c(self):
        msb = self.bus.read1(REG_TEMP_MSB).last
        lsb = self.bus.read1(REG_TEMP_LSB).last
        return msb + (lsb >> 6) * 0.25


def detect(i2c=None, addr=ADDR):
    i2c = i2c or _make_default_i2c()
    if addr in i2c.scan():
        return DS3231(i2c, addr)
    raise I2CError("DS3231 not found at 0x%02X" % addr)

def read_datetime(i2c=None, addr=ADDR):
    """Return (year, month, day, hour, minute, second) from DS3231."""
    return detect(i2c, addr).read_datetime()

def write_datetime(dt, i2c=None, addr=ADDR):
    """Write (year, month, day, hour, minute, second) to DS3231."""
    dev = detect(i2c, addr)
    dev.write_datetime(dt)
    dev.clear_osf()
    return dev.read_datetime()

def sync_system_from_ds3231(i2c=None, addr=ADDR):
    """
    Read DS3231 and set MicroPython RTC(). Returns tuple set.
    """
    dev = detect(i2c, addr)
    y, m, d, hh, mm, ss = dev.read_datetime()
    rtc = RTC()
    # weekday (0..6, Monday=0) – we’ll pass 0 to keep it simple.
    rtc.datetime((y, m, d, 0, hh, mm, ss, 0))
    return (y, m, d, hh, mm, ss)

def sync_ds3231_from_system(i2c=None, addr=ADDR):
    """
    Write DS3231 from current MicroPython time.localtime().
    """
    lt = time.localtime()
    dt = (lt[0], lt[1], lt[2], lt[3], lt[4], lt[5])
    dev = detect(i2c, addr)
    dev.write_datetime(dt)
    dev.clear_osf()
    return dev.read_datetime()
