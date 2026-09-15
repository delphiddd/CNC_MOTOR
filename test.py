import re
import serial
import time

# timeout=1 กัน readline ค้างตาย ถ้าเครื่องไม่ตอบ (send() ยังรอ ok ได้เรื่อย ๆ เหมือนเดิม)
ser = serial.Serial('COM4', 115200, timeout=1)
time.sleep(2)
ser.write(b"\r\n\r\n")
time.sleep(2)
ser.reset_input_buffer()
print("เชื่อมต่อแล้ว")

AXES = ("X", "Y", "Z")
UNIT = {"X": "องศา", "Y": "mm", "Z": "mm"}

LAST_REPORT = ""        # status report ดิบล่าสุด เอาไว้ดูตอน debug


# ============================================================
# 1. ส่งคำสั่งเข้า CNC
# ============================================================
def send(cmd):
    """ส่งคำสั่งแล้วรอจนเครื่องตอบ ok / error"""
    ser.write((cmd + "\n").encode())
    while True:
        line = ser.readline().decode(errors="ignore").strip()
        if line == "ok" or line.startswith("error"):
            print(f"{cmd} -> {line}")
            return line


# ============================================================
# 2. homing — ส่ง $H ให้ Grbl วิ่งหา home เอง
# ============================================================
def homing():
    """สั่ง $H (ตั้งค่า homing ในเครื่องไว้แล้ว)

    $H จะตอบ ok ก็ต่อเมื่อวิ่งเสร็จ เลยรอได้เลยไม่ต้องทำอะไรเพิ่ม
    """
    print("\nกำลัง homing ... (รอจนกว่าเครื่องจะวิ่งเสร็จ)")
    if send("$H").startswith("error"):
        print("[!] homing ไม่ผ่าน — เช็คว่าตั้ง $22=1 ไว้หรือยัง")
        return False

    send("G21")             # ตั้งหน่วย/โหมดใหม่หลัง homing
    send("G91")
    print("[OK] homing เสร็จแล้ว")
    return True


# ============================================================
# 3. เช็ค limit switch
# ============================================================
def parse_lim(line):
    """แกะช่อง Lim: ออกจากบรรทัดเดียว  "...|Lim:101>" -> [1, 0, 1]

    ไม่เจอช่อง Lim: (เป็นบรรทัด ok หรือบรรทัดว่าง) -> คืน None
    """
    m = re.search(r"Lim:(\d+)", line)
    if m:
        bits = [int(b) for b in m.group(1)]
        if len(bits) == 3:
            return bits
    return None


def check_limit():
    """
    ถาม Grbl แล้วคืนสถานะสวิตช์เป็น list 3 ตัว [X, Y, Z]
    1 = ชน, 0 = ไม่ชน   เช่น [1, 0, 1]

    ต้องตั้ง $10=19 ไว้ก่อน Grbl ถึงจะส่งช่อง Lim: มาให้
    ห้ามเรียกตอนมอเตอร์กำลังเดิน! reset_input_buffer() จะล้าง ok ทิ้ง
    ตอนนั้นให้ใช้ parse_lim() กับบรรทัดที่อ่านมาเองแทน
    """
    global LAST_REPORT
    ser.reset_input_buffer()
    ser.write(b"?")

    for _ in range(10):                     # อ่านหลายบรรทัดเผื่อมีขยะปน
        line = ser.readline().decode(errors="ignore").strip()
        if line.startswith("<"):
            LAST_REPORT = line
        lim = parse_lim(line)
        if lim:
            return lim

    print("[check_limit] อ่านค่าไม่ได้ - ตั้ง $10=19 หรือยัง?")
    return [0, 0, 0]


def stop():
    """หยุดมอเตอร์ทันที แล้วตั้งค่าเครื่องใหม่"""
    ser.write(b"!")             # feed hold เบรกทันที
    time.sleep(0.3)
    ser.write(b"\x18")          # soft reset ล้างคำสั่งที่ยังค้างในเครื่อง
    time.sleep(2)               # รอ Grbl บูทใหม่
    ser.reset_input_buffer()
    send("$X")
    send("G21")
    send("G91")


# ============================================================
# สั่งเดินหน้า / ถอยหลัง
# ============================================================
def move():
    """ถามแกน / ทิศ / ระยะ / ความเร็ว แล้วสั่งเดิน

    ระหว่างเดินคอยถาม '?' ไปเรื่อย ๆ ถ้าแกน Y ชนสวิตช์ -> หยุดทันที
    (ดูแค่ตัวกลาง เพราะ X กับ Z ยังไม่ได้ใส่สวิตช์ ค่ามันลอยเป็น 1 ตลอด)
    """
    axis = input("เลือกแกน (X / Y / Z): ").upper()
    if axis not in AXES:
        print("พิมพ์ X, Y, Z เท่านั้น")
        return

    print("1 = เดินหน้า(+) | 2 = ถอยหลัง(-)")
    direction = input("เลือกทิศ: ")
    if direction not in ("1", "2"):
        print("พิมพ์ 1 หรือ 2 เท่านั้น")
        return

    try:
        amount = float(input(f"ระยะ ({UNIT[axis]}): "))
        feed = float(input("ความเร็ว (F): "))
    except ValueError:
        print("ต้องเป็นตัวเลขเท่านั้น!")
        return

    if direction == "2":
        amount = -amount

    # ค้างอยู่บนสวิตช์ตั้งแต่แรก -> ต้อง homing ก่อน ไม่งั้นดันเข้าไปอีก
    if check_limit()[1] == 1:
        print("[!] แกน Y ค้างอยู่บนสวิตช์ — เลือก 1 (homing) ก่อน")
        return

    ser.reset_input_buffer()
    ser.write(f"G1 {axis}{amount} F{feed}\n".encode())
    print(f"G1 {axis}{amount} F{feed} -> กำลังเดิน ...")

    while True:
        ser.write(b"?")                     # ขอสถานะระหว่างเดิน
        line = ser.readline().decode(errors="ignore").strip()

        lim = parse_lim(line)
        if lim and lim[1] == 1:             # ตัวกลาง = แกน Y
            stop()
            print("[ชน] แกน Y ชนสวิตช์ -> หยุดแล้ว (เลือก 1 เพื่อ homing)")
            return

        if line == "ok":                    # เดินจบพอดี ไม่ชนอะไร
            print("เดินเสร็จ")
            return

        time.sleep(0.2)                     # อย่ายิง '?' ถี่เกิน Grbl จะตอบไม่ทัน


# ============================================================
# เริ่มโปรแกรม
# ============================================================
send("$X")              # ปลดล็อก
send("G21")             # หน่วย mm
send("G91")             # relative

while True:
    lim = check_limit()
    print("\n==============================")
    print(f"  limit [X, Y, Z] : {lim}      <- ดูแค่ตัวกลาง (Y)")
    print(f"  แกน Y           : {'ชน' if lim[1] == 1 else 'ไม่ชน'}")
    print(f"  เครื่องส่งมา     : {LAST_REPORT}")
    print("==============================")
    print("  1 = homing ($H)")
    print("  2 = สั่งเดินหน้า / ถอยหลัง")
    print("  q = ออก")

    choice = input("เลือก: ").lower()
    if choice == "q":
        break
    elif choice == "1":
        homing()
    elif choice == "2":
        move()
    else:
        print("พิมพ์ 1, 2 หรือ q เท่านั้น")

ser.close()
print("\nปิดการเชื่อมต่อแล้ว")
