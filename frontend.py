# frontend.py
# หน้าตาแอพทั้งหมด (PyQt5)
# ไม่ยุ่งกับ serial ตรง ๆ เรียกผ่าน CNCController

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QMainWindow, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QTextEdit, QGroupBox, QRadioButton, QButtonGroup, QMessageBox,
)

from backend import CNCController, BAUDRATES, STEPS_PARAM, calc_new_steps, list_ports

# ---------- ค่าคงที่ฝั่ง GUI ----------
# หน่วยของแต่ละแกน (X = หมุน/องศา, Y/Z = เส้นตรง/mm)
UNIT = {"X": "องศา", "Y": "mm", "Z": "mm"}


# ============================================================
# หน้า 1 : เลือก port + baudrate
# ============================================================
class ConnectPage(QWidget):
    def __init__(self, ctrl, goto_menu):
        super().__init__()
        self.ctrl = ctrl
        self.goto_menu = goto_menu

        title = QLabel("เชื่อมต่อเครื่อง CNC")
        title.setFont(QFont("", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)

        self.cb_port = QComboBox()
        self.cb_port.setMinimumWidth(280)

        self.cb_baud = QComboBox()
        for b in BAUDRATES:
            self.cb_baud.addItem(str(b))
        self.cb_baud.setCurrentText("115200")

        btn_refresh = QPushButton("รีเฟรช")
        btn_refresh.clicked.connect(self.refresh_ports)

        self.btn_connect = QPushButton("เชื่อมต่อ")
        self.btn_connect.setMinimumHeight(45)
        self.btn_connect.clicked.connect(self.do_connect)

        self.lb_status = QLabel("ยังไม่ได้เชื่อมต่อ")
        self.lb_status.setAlignment(Qt.AlignCenter)

        grid = QGridLayout()
        grid.addWidget(QLabel("Port :"), 0, 0)
        grid.addWidget(self.cb_port, 0, 1)
        grid.addWidget(btn_refresh, 0, 2)
        grid.addWidget(QLabel("Baudrate :"), 1, 0)
        grid.addWidget(self.cb_baud, 1, 1, 1, 2)

        box = QGroupBox("การเชื่อมต่อ")
        box.setLayout(grid)

        lay = QVBoxLayout(self)
        lay.addStretch()
        lay.addWidget(title)
        lay.addSpacing(20)
        lay.addWidget(box)
        lay.addWidget(self.btn_connect)
        lay.addWidget(self.lb_status)
        lay.addStretch()

        self.refresh_ports()
        self.ctrl.connection_changed.connect(self.on_connection_changed)

    def refresh_ports(self):
        self.cb_port.clear()
        ports = list_ports()
        if not ports:
            self.cb_port.addItem("— ไม่พบ port —", None)
            return
        for dev, desc in ports:
            self.cb_port.addItem(f"{dev}  ({desc})", dev)

    def do_connect(self):
        port = self.cb_port.currentData()
        if port is None:
            QMessageBox.warning(self, "ไม่พบ port", "เสียบสาย USB แล้วกดรีเฟรชก่อน")
            return
        self.btn_connect.setEnabled(False)
        self.lb_status.setText("กำลังเชื่อมต่อ ...")
        self.ctrl.connect(port, self.cb_baud.currentText())

    def on_connection_changed(self, ok):
        self.btn_connect.setEnabled(not ok)
        if ok:
            self.lb_status.setText("เชื่อมต่อสำเร็จ")
            self.goto_menu()
        else:
            self.lb_status.setText("ยังไม่ได้เชื่อมต่อ")


# ============================================================
# หน้า 2 : เมนูหลัก 2 ปุ่ม
# ============================================================
class MenuPage(QWidget):
    def __init__(self, ctrl, goto_calibrate, goto_connect):
        super().__init__()
        self.ctrl = ctrl

        title = QLabel("เลือกโหมดการทำงาน")
        title.setFont(QFont("", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)

        btn_cal = QPushButton("1.  Calibrate")
        btn_cal.setMinimumHeight(80)
        btn_cal.setFont(QFont("", 14))
        btn_cal.clicked.connect(goto_calibrate)

        btn_exp = QPushButton("2.  ทดลอง")
        btn_exp.setMinimumHeight(80)
        btn_exp.setFont(QFont("", 14))
        btn_exp.clicked.connect(self.not_ready)

        btn_back = QPushButton("ตัดการเชื่อมต่อ")
        btn_back.clicked.connect(lambda: (self.ctrl.disconnect(), goto_connect()))

        lay = QVBoxLayout(self)
        lay.addStretch()
        lay.addWidget(title)
        lay.addSpacing(20)
        lay.addWidget(btn_cal)
        lay.addWidget(btn_exp)
        lay.addSpacing(20)
        lay.addWidget(btn_back)
        lay.addStretch()

    def not_ready(self):
        QMessageBox.information(self, "ทดลอง", "โหมดนี้ยังไม่ได้ทำอะไร")


# ============================================================
# หน้า 3 : Calibrate (เลือกแกน / ทิศ / ระยะ / ความเร็ว + ปรับค่า steps)
# ============================================================
class CalibratePage(QWidget):
    def __init__(self, ctrl, goto_menu):
        super().__init__()
        self.ctrl = ctrl
        self.settings = {}      # ค่า $$ ล่าสุดที่อ่านมาจากเครื่อง

        title = QLabel("Calibrate")
        title.setFont(QFont("", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)

        # ----- เลือกแกน -----
        self.cb_axis = QComboBox()
        self.cb_axis.addItems(["X", "Y", "Z"])
        self.cb_axis.currentTextChanged.connect(self.on_axis_changed)

        # ----- ทิศทาง -----
        self.rb_fwd = QRadioButton("เดินหน้า (+)")
        self.rb_bwd = QRadioButton("ถอยหลัง (-)")
        self.rb_fwd.setChecked(True)
        self.grp_dir = QButtonGroup(self)
        self.grp_dir.addButton(self.rb_fwd)
        self.grp_dir.addButton(self.rb_bwd)
        dir_lay = QHBoxLayout()
        dir_lay.addWidget(self.rb_fwd)
        dir_lay.addWidget(self.rb_bwd)

        # ----- ระยะทาง -----
        self.sp_amount = QDoubleSpinBox()
        self.sp_amount.setRange(0.0, 9999.0)
        self.sp_amount.setDecimals(2)
        self.sp_amount.setSingleStep(1.0)
        self.sp_amount.setValue(10.0)
        self.lb_unit = QLabel(UNIT["X"])

        amt_lay = QHBoxLayout()
        amt_lay.addWidget(self.sp_amount)
        amt_lay.addWidget(self.lb_unit)

        # ----- ความเร็ว -----
        self.sp_feed = QDoubleSpinBox()
        self.sp_feed.setRange(1.0, 10000.0)
        self.sp_feed.setDecimals(0)
        self.sp_feed.setValue(500)

        grid = QGridLayout()
        grid.addWidget(QLabel("แกน :"), 0, 0)
        grid.addWidget(self.cb_axis, 0, 1)
        grid.addWidget(QLabel("ทิศ :"), 1, 0)
        grid.addLayout(dir_lay, 1, 1)
        grid.addWidget(QLabel("ระยะทาง :"), 2, 0)
        grid.addLayout(amt_lay, 2, 1)
        grid.addWidget(QLabel("ความเร็ว (F) :"), 3, 0)
        grid.addWidget(self.sp_feed, 3, 1)

        box_ctrl = QGroupBox("สั่งเดิน")
        box_ctrl.setLayout(grid)

        btn_move = QPushButton("สั่งเดิน")
        btn_move.setMinimumHeight(45)
        btn_move.clicked.connect(self.do_move)

        # ----------------------------------------------------
        # กล่องปรับค่า steps :  ค่าใหม่ = ค่าเดิม × (สั่ง ÷ จริง)
        # ----------------------------------------------------
        self.lb_cur = QLabel("—")
        self.lb_cur.setFont(QFont("", 12, QFont.Bold))

        btn_read = QPushButton("อ่านค่าจากเครื่อง")
        btn_read.clicked.connect(self.read_settings)

        cur_lay = QHBoxLayout()
        cur_lay.addWidget(self.lb_cur)
        cur_lay.addStretch()
        cur_lay.addWidget(btn_read)

        # ระยะที่สั่ง (เติมให้อัตโนมัติทุกครั้งที่กดสั่งเดิน)
        self.sp_cmd = QDoubleSpinBox()
        self.sp_cmd.setRange(0.001, 9999.0)
        self.sp_cmd.setDecimals(3)
        self.sp_cmd.setValue(10.0)
        self.lb_cmd_unit = QLabel(UNIT["X"])
        cmd_lay = QHBoxLayout()
        cmd_lay.addWidget(self.sp_cmd)
        cmd_lay.addWidget(self.lb_cmd_unit)

        # ระยะที่วัดได้จริงจากเครื่อง
        self.sp_real = QDoubleSpinBox()
        self.sp_real.setRange(0.001, 9999.0)
        self.sp_real.setDecimals(3)
        self.sp_real.setValue(10.0)
        self.lb_real_unit = QLabel(UNIT["X"])
        real_lay = QHBoxLayout()
        real_lay.addWidget(self.sp_real)
        real_lay.addWidget(self.lb_real_unit)

        self.lb_new = QLabel("—")
        self.lb_new.setFont(QFont("", 12, QFont.Bold))
        self.sp_cmd.valueChanged.connect(self.update_preview)
        self.sp_real.valueChanged.connect(self.update_preview)

        btn_apply = QPushButton("คำนวณ & บันทึกค่าใหม่ลงเครื่อง")
        btn_apply.setMinimumHeight(40)
        btn_apply.clicked.connect(self.do_apply)

        gcal = QGridLayout()
        gcal.addWidget(QLabel("ค่าปัจจุบัน :"), 0, 0)
        gcal.addLayout(cur_lay, 0, 1)
        gcal.addWidget(QLabel("ระยะที่สั่ง :"), 1, 0)
        gcal.addLayout(cmd_lay, 1, 1)
        gcal.addWidget(QLabel("ระยะที่วิ่งจริง :"), 2, 0)
        gcal.addLayout(real_lay, 2, 1)
        gcal.addWidget(QLabel("ค่าใหม่ :"), 3, 0)
        gcal.addWidget(self.lb_new, 3, 1)
        gcal.addWidget(btn_apply, 4, 0, 1, 2)

        box_cal = QGroupBox("ปรับค่า steps  (ค่าใหม่ = ค่าเดิม × ระยะที่สั่ง ÷ ระยะที่วิ่งจริง)")
        box_cal.setLayout(gcal)

        btn_back = QPushButton("< กลับเมนู")
        btn_back.clicked.connect(goto_menu)

        lay = QVBoxLayout(self)
        lay.addWidget(title)
        lay.addWidget(box_ctrl)
        lay.addWidget(btn_move)
        lay.addWidget(box_cal)
        lay.addStretch()
        lay.addWidget(btn_back)

        self.ctrl.settings.connect(self.on_settings)
        self.on_axis_changed("X")

    # ---------- อัปเดตหน้าจอ ----------
    def on_axis_changed(self, axis):
        unit = UNIT[axis]
        self.lb_unit.setText(unit)
        self.lb_cmd_unit.setText(unit)
        self.lb_real_unit.setText(unit)
        self.show_current()
        self.update_preview()

    def on_settings(self, settings):
        """ได้ค่า $$ กลับมาจากเครื่องแล้ว"""
        self.settings = settings
        self.show_current()
        self.update_preview()

    def current_steps(self):
        """ค่า steps ต่อหน่วยของแกนที่เลือกอยู่ (None ถ้ายังไม่ได้อ่านมา)"""
        return self.settings.get(STEPS_PARAM[self.cb_axis.currentText()])

    def show_current(self):
        axis = self.cb_axis.currentText()
        old = self.current_steps()
        if old is None:
            self.lb_cur.setText(f"{STEPS_PARAM[axis]} = ยังไม่ได้อ่าน")
        else:
            self.lb_cur.setText(f"{STEPS_PARAM[axis]} = {old:.3f} steps/{UNIT[axis]}")

    def update_preview(self):
        """โชว์ค่าใหม่ให้ดูก่อน ยังไม่เขียนลงเครื่อง"""
        old = self.current_steps()
        real = self.sp_real.value()
        if old is None or real <= 0:
            self.lb_new.setText("—")
            return
        new = calc_new_steps(old, self.sp_cmd.value(), real)
        self.lb_new.setText(f"{new:.3f}   (เดิม {old:.3f})")

    def read_settings(self):
        self.ctrl.read_settings()

    # ---------- ปุ่ม ----------
    def do_move(self):
        axis = self.cb_axis.currentText()
        amount = self.sp_amount.value()
        self.sp_cmd.setValue(amount)      # เติมช่อง "ระยะที่สั่ง" ให้อัตโนมัติ
        if self.rb_bwd.isChecked():
            amount = -amount
        self.ctrl.move(axis, amount, self.sp_feed.value())

    def do_apply(self):
        axis = self.cb_axis.currentText()
        old = self.current_steps()
        if old is None:
            QMessageBox.warning(self, "ยังไม่มีค่าเดิม",
                                "กด 'อ่านค่าจากเครื่อง' ก่อน ถึงจะรู้ค่าเดิมของแกนนี้")
            return

        commanded, real = self.sp_cmd.value(), self.sp_real.value()
        if real <= 0:
            QMessageBox.warning(self, "ค่าไม่ถูกต้อง", "ระยะที่วิ่งจริงต้องมากกว่า 0")
            return

        new = calc_new_steps(old, commanded, real)
        ans = QMessageBox.question(
            self, "ยืนยันการบันทึก",
            f"แกน {axis}  ({STEPS_PARAM[axis]})\n\n"
            f"ค่าเดิม  : {old:.3f}\n"
            f"ค่าใหม่ : {new:.3f}\n"
            f"          = {old:.3f} × ({commanded:g} ÷ {real:g})\n\n"
            "บันทึกลงเครื่องเลยไหม (ค่าจะถูกเขียนถาวรลง EEPROM ของ GRBL)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return

        if self.ctrl.set_steps(axis, new):
            self.ctrl.read_settings()     # อ่านกลับมายืนยันว่าเขียนติดจริง


# ============================================================
# หน้าต่างหลัก : stack 3 หน้า + ปุ่มหยุดฉุกเฉิน + log ด้านล่าง
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CNC Motor Control")
        self.resize(560, 820)

        self.ctrl = CNCController(self)

        # ----- กล่อง log ใช้ร่วมกันทุกหน้า (สร้างก่อน เพราะหน้าอื่นต้องใช้) -----
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(180)
        box_log = QGroupBox("Log")
        log_lay = QVBoxLayout()
        log_lay.addWidget(self.txt_log)
        box_log.setLayout(log_lay)

        # ----- ปุ่มหยุดฉุกเฉิน อยู่นอก stack เพื่อให้กดได้จากทุกหน้า -----
        self.btn_stop = QPushButton("⛔  หยุดฉุกเฉิน / เบรกมอเตอร์  (Esc)")
        self.btn_stop.setMinimumHeight(55)
        self.btn_stop.setFont(QFont("", 14, QFont.Bold))
        self.btn_stop.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; border-radius: 6px; }"
            "QPushButton:pressed { background-color: #7f2418; }"
            "QPushButton:disabled { background-color: #bdbdbd; color: #efefef; }"
        )
        self.btn_stop.setShortcut("Esc")
        self.btn_stop.setEnabled(False)                 # ต่อเครื่องแล้วค่อยกดได้
        self.btn_stop.clicked.connect(self.ctrl.emergency_stop)

        self.stack = QStackedWidget()
        self.page_connect = ConnectPage(self.ctrl, self.goto_menu)
        self.page_menu = MenuPage(self.ctrl, self.goto_calibrate, self.goto_connect)
        self.page_cal = CalibratePage(self.ctrl, self.goto_menu)
        for p in (self.page_connect, self.page_menu, self.page_cal):
            self.stack.addWidget(p)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addWidget(self.stack)
        lay.addWidget(self.btn_stop)
        lay.addWidget(box_log)
        self.setCentralWidget(central)

        self.ctrl.log.connect(self.append_log)
        self.ctrl.connection_changed.connect(self.btn_stop.setEnabled)
        self.append_log("พร้อมใช้งาน — เลือก port แล้วกดเชื่อมต่อ")

    def append_log(self, msg):
        self.txt_log.append(msg)
        self.txt_log.verticalScrollBar().setValue(
            self.txt_log.verticalScrollBar().maximum()
        )

    def goto_connect(self):
        self.stack.setCurrentWidget(self.page_connect)
        self.page_connect.refresh_ports()

    def goto_menu(self):
        self.stack.setCurrentWidget(self.page_menu)

    def goto_calibrate(self):
        self.stack.setCurrentWidget(self.page_cal)
        self.page_cal.read_settings()     # ดึงค่า steps ล่าสุดมาโชว์

    def closeEvent(self, event):
        self.ctrl.disconnect()
        event.accept()
