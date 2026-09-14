# CNC_MOTOR

โปรแกรมควบคุมเครื่อง CNC (GRBL) ผ่าน serial — GUI ด้วย PyQt5

- **สั่งเดินมอเตอร์** เลือกแกน / ทิศ / ระยะ / ความเร็ว
- **Calibrate** ปรับค่า steps ต่อหน่วยของ GRBL (`$100`/`$101`/`$102`) จากระยะที่วัดได้จริง
- **ปุ่มหยุดฉุกเฉิน** เบรกมอเตอร์ทันที (กด Esc ก็ได้) กดได้จากทุกหน้า

---

## โครงสร้างไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `main.py` | จุดเริ่มโปรแกรม |
| `backend.py` | คุย serial กับ GRBL (แยก thread ไม่ให้ GUI ค้าง) |
| `frontend.py` | หน้าตาแอพทั้งหมด (PyQt5) |
| `requirements.txt` | โมดูลที่ต้องลง |

---

## ติดตั้งบน Windows

ต้องมี **Python 3.9 ขึ้นไป** ก่อน (ตอนลงติ๊ก *Add Python to PATH* ด้วย) — เช็คว่ามีรึยัง:

```cmd
python --version
```

### 1. เปิด Command Prompt ที่โฟลเดอร์โปรเจกต์

```cmd
cd C:\path\to\CNC_MOTOR
```

### 2. สร้าง venv

```cmd
python -m venv .venv
```

จะได้โฟลเดอร์ `.venv` โผล่มา (ไม่ต้อง push ขึ้น git — อยู่ใน `.gitignore` แล้ว)

### 3. เข้า venv

**Command Prompt (cmd):**
```cmd
.venv\Scripts\activate
```

**PowerShell:**
```powershell
.\.venv\Scripts\Activate.ps1
```

> ถ้า PowerShell ฟ้อง `running scripts is disabled on this system` ให้สั่งบรรทัดนี้ครั้งเดียวก่อน แล้วค่อย activate ใหม่
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

เข้าสำเร็จจะมี `(.venv)` นำหน้าบรรทัด prompt

### 4. ลงโมดูล

```cmd
python -m pip install --upgrade pip
pip install -r requirements.txt
```

ได้ `pyserial` (คุย serial) กับ `PyQt5` (GUI)

### 5. รัน

```cmd
python main.py
```

ออกจาก venv เมื่อเลิกใช้:

```cmd
deactivate
```

ครั้งต่อ ๆ ไปไม่ต้องสร้าง venv ใหม่ แค่ทำข้อ 3 แล้วข้าม 4 ไปข้อ 5 ได้เลย

---

## ติดตั้งบน macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## การเชื่อมต่อเครื่อง

1. เสียบสาย USB จากบอร์ด CNC (Arduino + GRBL)
2. เปิดโปรแกรม → กด **รีเฟรช** → เลือก port
   - **Windows** จะเป็น `COM3`, `COM4`, ... (ดูเลขที่แน่นอนได้จาก Device Manager → Ports)
   - **macOS** จะเป็น `/dev/cu.usbserial-xxxx` หรือ `/dev/cu.usbmodem-xxxx`
3. Baudrate ปกติใช้ **115200**
4. กด **เชื่อมต่อ** แล้วรอ ~4 วิให้ GRBL บูท

> **Windows: ถ้าไม่เห็น COM port** ส่วนใหญ่เป็นเพราะยังไม่ได้ลงไดรเวอร์ของชิป USB บนบอร์ด
> — บอร์ดจีนมักใช้ **CH340/CH341**, บางรุ่นใช้ **CP2102** ลงไดรเวอร์แล้วเสียบใหม่

---

## วิธี Calibrate

สูตร:

```
ค่าใหม่ = ค่าเดิม × (ระยะที่สั่ง ÷ ระยะที่วิ่งจริง)
```

ขั้นตอน:

1. เข้าหน้า **Calibrate** เลือกแกนที่จะปรับ (ค่าเดิมจากเครื่องจะถูกอ่านมาโชว์ให้เอง)
2. ตั้งระยะ เช่น 10 แล้วกด **สั่งเดิน**
3. **วัดระยะที่เครื่องวิ่งจริง** แล้วกรอกลงช่อง *ระยะที่วิ่งจริง*
   (ช่อง *ระยะที่สั่ง* ถูกเติมให้อัตโนมัติตอนกดสั่งเดิน)
4. ดูค่าใหม่ที่คำนวณได้ → กด **คำนวณ & บันทึกค่าใหม่ลงเครื่อง** → ยืนยันใน dialog
5. ทดลองสั่งเดินซ้ำเพื่อเช็คว่าตรงแล้ว

> ค่าจะถูกเขียนถาวรลง EEPROM ของ GRBL (`$100`=X, `$101`=Y, `$102`=Z)
> **เช็คชื่อแกนบนหัว dialog ก่อนกดยืนยันทุกครั้ง** โปรแกรมยึดแกนตาม dropdown ที่เลือกอยู่ตอนนั้น

---

## ปุ่มหยุดฉุกเฉิน

กดปุ่มแดง หรือ **Esc** — ทำงานตามลำดับนี้:

1. ทิ้งคำสั่งที่ค้างในคิวทั้งหมด
2. ส่ง `!` (feed hold) เบรกแบบชะลอ ไม่กระชากมอเตอร์
3. ส่ง `Ctrl-X` (soft reset) ล้างคิวฝั่งเครื่อง แล้วตั้งค่าเริ่มต้นใหม่ให้อัตโนมัติ

> หลังหยุดฉุกเฉิน **ตำแหน่งเดิมจะหาย** เพราะเครื่องถูกรีเซ็ต
