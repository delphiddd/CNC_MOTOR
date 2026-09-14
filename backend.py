# backend.py
# ส่วนส่งข้อมูลไปยัง CNC (GRBL) ผ่าน serial อย่างเดียว — ไม่มีตรรกะอะไรทั้งนั้น
# แยก thread ออกมาเพราะ readline() มัน block ถ้าใส่ใน main thread หน้าเเอพจะค้าง

import re
import time
from queue import Queue, Empty

import serial
import serial.tools.list_ports
from PyQt5.QtCore import QObject, QThread, pyqtSignal

BAUDRATES = [9600, 19200, 38400, 57600, 115200, 250000]

# setting ของ GRBL ที่เก็บ "steps ต่อหนึ่งหน่วย" ของแต่ละแกน (ตัวที่ calibrate)
STEPS_PARAM = {"X": "$100", "Y": "$101", "Z": "$102"}

# บรรทัดค่า setting ที่ GRBL ตอบกลับตอนสั่ง $$  เช่น  $100=250.000
RE_SETTING = re.compile(r"^\$(\d+)\s*=\s*([-\d.]+)")


def list_ports():
    """คืน list ของ port ที่เสียบอยู่ตอนนี้ [(device, description), ...]"""
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


def calc_new_steps(old_steps, commanded, actual):
    """ค่าใหม่ = ค่าเดิม × (ระยะที่สั่ง ÷ ระยะที่วิ่งจริง)

    วิ่งจริงน้อยกว่าที่สั่ง -> steps ต้องเพิ่ม, วิ่งเกิน -> steps ต้องลด
    """
    if actual == 0:
        raise ValueError("ระยะที่วิ่งจริงเป็น 0 ไม่ได้")
    return old_steps * (commanded / actual)


class SerialWorker(QThread):
    """thread ที่ถือ serial object จริง ๆ รับคำสั่งจาก queue แล้วรอ ok/error"""

    log = pyqtSignal(str)
    connected = pyqtSignal(bool, str)      # (สำเร็จไหม, ข้อความ)
    command_done = pyqtSignal(str, str)    # (คำสั่ง, คำตอบ)
    settings = pyqtSignal(dict)            # ผลจากการสั่ง $$  {'$100': 250.0, ...}
    estopped = pyqtSignal()                # หยุดฉุกเฉินเสร็จ + รีเซ็ตเครื่องแล้ว

    def __init__(self, port, baud, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.ser = None
        self._queue = Queue()
        self._running = True
        self._abort = False     # ธงหยุดฉุกเฉิน — ให้ loop ที่รอคำตอบอยู่เลิกรอ

    # ---------- API ที่เรียกจาก main thread ----------
    def send(self, cmd):
        """โยนคำสั่งเข้า queue (ไม่ block GUI)"""
        self._queue.put(cmd)

    def stop(self):
        self._running = False
        self._queue.put(None)   # ปลุก queue ให้ตื่นมาเช็ค flag

    def emergency_stop(self):
        """หยุดฉุกเฉิน — เรียกจาก main thread ได้เลย

        ต้องเขียนลงพอร์ตตรง ๆ ไม่ผ่าน queue เพราะตอนนั้น thread กำลังติดรอ readline
        ของคำสั่งที่วิ่งค้างอยู่ ถ้าเข้าคิวจะได้ทำก็ต่อเมื่อเดินเสร็จแล้ว = ไม่ทันกิน
        '!' เป็น realtime command ของ GRBL แทรกคิวได้ทันทีอยู่แล้ว
        """
        self._drain_queue()            # ทิ้งคำสั่งที่ยังไม่ได้ส่งทั้งหมด
        self._abort = True
        try:
            self.ser.write(b"!")       # feed hold — เบรกแบบชะลอ ไม่กระชากมอเตอร์
        except Exception as e:
            self.log.emit(f"!! สั่งหยุดไม่สำเร็จ: {e}")

    # ---------- ทำงานใน thread ----------
    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
        except Exception as e:
            self.connected.emit(False, f"เปิด {self.port} ไม่ได้: {e}")
            return

        # ปลุก GRBL แบบเดียวกับสคริปต์เดิม
        time.sleep(2)
        self.ser.write(b"\r\n\r\n")
        time.sleep(2)
        self.ser.reset_input_buffer()
        self.connected.emit(True, f"เชื่อมต่อ {self.port} @ {self.baud} แล้ว")

        while self._running:
            if self._abort:
                self._recover_from_abort()
                continue
            try:
                cmd = self._queue.get(timeout=0.1)
            except Empty:
                continue
            if cmd is None:
                break
            self._send_and_wait(cmd)

        try:
            self.ser.close()
        except Exception:
            pass
        self.log.emit("ปิดการเชื่อมต่อแล้ว")

    def _drain_queue(self):
        """เทคำสั่งที่ค้างในคิวทิ้งให้หมด"""
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                return

    def _recover_from_abort(self):
        """ต่อจาก feed hold: soft reset ล้างคำสั่งที่ค้างใน GRBL แล้วตั้งค่าเริ่มต้นใหม่"""
        self.log.emit("!! หยุดฉุกเฉิน — เบรกมอเตอร์แล้ว")
        time.sleep(0.5)                     # รอให้ชะลอจนนิ่งก่อนค่อยรีเซ็ต
        try:
            self.ser.write(b"\x18")         # Ctrl-X soft reset ล้างคิวฝั่งเครื่อง
            time.sleep(2)                   # รอ GRBL บูทใหม่
            self.ser.reset_input_buffer()
        except Exception as e:
            self.log.emit(f"!! รีเซ็ตเครื่องไม่สำเร็จ: {e}")
        self._abort = False
        self.log.emit("รีเซ็ตเครื่องแล้ว — ตั้งค่าเริ่มต้นใหม่ (ตำแหน่งเดิมหายนะ)")
        for c in ("$X", "G21", "G91"):      # ปลดล็อก + mm + relative เหมือนตอนต่อ
            self._send_and_wait(c)
        self.estopped.emit()

    def _send_and_wait(self, cmd):
        """ส่งคำสั่ง แล้ววนอ่านจนเจอ ok / error / ALARM"""
        try:
            self.ser.write((cmd + "\n").encode())
        except Exception as e:
            self.command_done.emit(cmd, f"error: เขียนไม่ได้ ({e})")
            return

        lines = []                       # เก็บบรรทัดระหว่างทางไว้ (ใช้ตอนอ่าน $$)
        deadline = time.time() + 120     # กันค้างถ้าเครื่องไม่ตอบ
        while self._running and not self._abort and time.time() < deadline:
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
            except Exception as e:
                self.command_done.emit(cmd, f"error: อ่านไม่ได้ ({e})")
                return
            if not line:
                continue
            if line == "ok" or line.startswith("error") or line.startswith("ALARM"):
                if cmd.strip() == "$$":
                    self.settings.emit(self._parse_settings(lines))
                self.command_done.emit(cmd, line)
                return
            lines.append(line)
            if not RE_SETTING.match(line):
                self.log.emit(f"   [grbl] {line}")   # ข้อความอื่น ๆ เช่น banner
                                                     # (บรรทัด $n=... ไม่ต้องรก log)

        if self._abort:
            self.command_done.emit(cmd, "ยกเลิก (หยุดฉุกเฉิน)")
            return
        self.command_done.emit(cmd, "error: timeout ไม่มีคำตอบจากเครื่อง")

    @staticmethod
    def _parse_settings(lines):
        """แปลงบรรทัด $n=value ที่ได้จาก $$ เป็น dict"""
        out = {}
        for ln in lines:
            m = RE_SETTING.match(ln)
            if m:
                out["$" + m.group(1)] = float(m.group(2))
        return out


class CNCController(QObject):
    """ตัวกลางระหว่าง GUI กับ SerialWorker — เปิด/ปิดพอร์ต + ส่งคำสั่ง เท่านั้น"""

    log = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)      # ต่อ/หลุด
    settings = pyqtSignal(dict)                # ค่า $$ ที่อ่านมาได้
    estopped = pyqtSignal()                    # หยุดฉุกเฉินเสร็จแล้ว

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None

    # ---------- เชื่อมต่อ ----------
    def connect(self, port, baud):
        if self.worker is not None:
            self.log.emit("ต่ออยู่แล้ว")
            return
        self.log.emit(f"กำลังเชื่อมต่อ {port} @ {baud} ... (รอ ~4 วิ ให้ GRBL บูท)")
        self.worker = SerialWorker(port, int(baud))
        self.worker.log.connect(self.log)
        self.worker.connected.connect(self._on_connected)
        self.worker.command_done.connect(self._on_command_done)
        self.worker.settings.connect(self.settings)
        self.worker.estopped.connect(self.estopped)
        self.worker.start()

    def disconnect(self):
        if self.worker is None:
            return
        self.worker.stop()
        self.worker.wait(3000)
        self.worker = None
        self.connection_changed.emit(False)

    def is_connected(self):
        return self.worker is not None and self.worker.isRunning()

    def _on_connected(self, ok, msg):
        self.log.emit(msg)
        if not ok:
            self.worker = None
            self.connection_changed.emit(False)
            return
        # เตรียมเครื่อง (เหมือนสคริปต์เดิม)
        self.worker.send("$X")     # ปลดล็อก
        self.worker.send("G21")    # หน่วย mm
        self.worker.send("G91")    # relative
        self.worker.send("$$")     # ดูดค่า setting มาเก็บไว้ให้หน้า calibrate
        self.connection_changed.emit(True)

    def _on_command_done(self, cmd, resp):
        self.log.emit(f"{cmd} -> {resp}")

    # ---------- ส่งคำสั่ง ----------
    def send(self, cmd):
        """ส่ง G-code ดิบ ๆ ไปเข้าคิว"""
        if not self.is_connected():
            self.log.emit("ยังไม่ได้เชื่อมต่อ")
            return False
        self.worker.send(cmd)
        return True

    def move(self, axis, amount, feed):
        """สั่งเดินแบบ relative (G91 ถูกตั้งไว้ตอนต่อแล้ว)"""
        return self.send(f"G1 {axis}{amount} F{feed}")

    def read_settings(self):
        """ขอค่า $$ ทั้งหมด — ผลจะกลับมาทาง signal settings"""
        return self.send("$$")

    def set_steps(self, axis, value):
        """เขียนค่า steps ต่อหน่วยใหม่ลงเครื่อง ($100/$101/$102 — เก็บถาวรใน EEPROM)"""
        return self.send(f"{STEPS_PARAM[axis]}={value:.3f}")

    def emergency_stop(self):
        """เบรกมอเตอร์ทันที ทิ้งคำสั่งที่ค้างทั้งหมด แล้วรีเซ็ตเครื่อง"""
        if not self.is_connected():
            self.log.emit("ยังไม่ได้เชื่อมต่อ")
            return False
        self.worker.emergency_stop()
        return True
