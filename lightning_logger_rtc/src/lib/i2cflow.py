"""Minimal fluent I2C helper for MicroPython (fluent/builder style)"""
from machine import I2C
import time

class I2CError(Exception):
    pass

class I2CFlow:
    def __init__(self, i2c: I2C):
        self.i2c = i2c
        self._addr = None
        self._retries = 0
        self._backoff_ms = 0
        self.last = None  # result of last op

    def at(self, addr: int):
        self._addr = addr
        return self

    def retry(self, times=2, backoff_ms=2):
        self._retries, self._backoff_ms = times, backoff_ms
        return self

    def wait_ms(self, ms: int):
        time.sleep_ms(ms)
        return self

    def read1(self, reg: int):
        self.last = self._with_retry(lambda:
            self.i2c.readfrom_mem(self._addr, reg, 1)[0]
        )
        return self

    def readn(self, reg: int, n: int):
        self.last = self._with_retry(lambda:
            self.i2c.readfrom_mem(self._addr, reg, n)
        )
        return self

    def write1(self, reg: int, val: int):
        self._with_retry(lambda:
            self.i2c.writeto_mem(self._addr, reg, bytes([val & 0xFF]))
        )
        self.last = None
        return self

    def writen(self, reg: int, data: bytes):
        self._with_retry(lambda:
            self.i2c.writeto_mem(self._addr, reg, data)
        )
        self.last = None
        return self

    def rmw(self, reg: int, mask: int, shift: int, value: int):
        """Read-Modify-Write: replace 'mask<<shift' field with 'value'."""
        def op():
            v = self.i2c.readfrom_mem(self._addr, reg, 1)[0]
            v = (v & ~mask) | ((value << shift) & mask)
            self.i2c.writeto_mem(self._addr, reg, bytes([v & 0xFF]))
            return v
        self.last = self._with_retry(op)
        return self

    def field_get(self, reg: int, mask: int, shift: int):
        def op():
            v = self.i2c.readfrom_mem(self._addr, reg, 1)[0]
            return (v & mask) >> shift
        self.last = self._with_retry(op)
        return self

    def _with_retry(self, fn):
        attempts = self._retries + 1
        last_exc = None
        for k in range(attempts):
            try:
                return fn()
            except OSError as e:
                last_exc = e
                if k < attempts - 1 and self._backoff_ms:
                    time.sleep_ms(self._backoff_ms)
        raise I2CError(f"I2C op failed after {attempts} attempt(s): {last_exc}")
