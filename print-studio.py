#!/usr/bin/env python3
"""
Print Studio - GUI программа для печати с гибкими настройками
Поддержка HP, Epson и других принтеров через CUPS
"""

import sys
import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QCheckBox, QGroupBox,
    QFileDialog, QMessageBox, QTabWidget, QFormLayout, QListWidget,
    QListWidgetItem, QSlider, QRadioButton, QButtonGroup, QProgressBar,
    QTextEdit, QSplitter, QFrame, QScrollArea, QGridLayout
)
from PySide6.QtCore import Qt, QSize, Signal, Slot, QThread
from PySide6.QtGui import QPixmap, QImage, QFont, QIcon

try:
    import cups
    HAS_CUPS = True
except ImportError:
    HAS_CUPS = False

try:
    from PIL import Image, ImageQt
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


PAPER_SIZES = [
    "A4", "A3", "A5", "Letter", "Legal", "Tabloid",
    "Envelope", "Executive", "B5", "C5"
]

QUALITY_PRESETS = {
    3: "Черновик ( draft)",
    4: "Нормальное (normal)",
    5: "Высокое (high)",
}

COLOR_MODES = {
    "color": "Цветная",
    "grayscale": "Чёрно-белая",
}

DUPLEX_MODES = {
    "none": "Нет",
    "duplex": "Двусторонняя",
}

ORIENTATIONS = {
    3: "Портрет",
    4: "Ландшафт",
}

SCALING_OPTIONS = [
    "По размеру страницы", "По ширине", "По высоте",
    "Вручную (%)", "Без масштабирования"
]


class DriverInstaller(QThread):
    progress = Signal(str)
    finished = Signal(bool, str)
    output = Signal(str)

    def run(self):
        try:
            pkgs = []

            self.progress.emit("Проверка пакетов...")

            # HP драйверы
            self.output.emit("> HP: hplip, hplip-gui, hpijs-ppds")
            pkgs.extend(["hplip", "hplip-gui", "hpijs-ppds",
                         "printer-driver-hpijs"])

            # Epson драйверы
            self.output.emit("> Epson: epson-inkjet-printer-escpr, epson-printer-utility")
            pkgs.extend(["epson-inkjet-printer-escpr",
                         "printer-driver-escpr"])

            # Общие драйверы
            self.output.emit("> Gutenprint, CUPS, cups-filters")
            pkgs.extend(["cups", "cups-filters", "cups-backend-driver",
                         "foomatic-db", "foomatic-db-engine",
                         "foomatic-db-hpijs", "gutenprint",
                         "printer-driver-gutenprint"])

            # Python CUPS биндинг
            self.output.emit("> python3-cups")
            pkgs.append("python3-cups")

            pkgs_str = " ".join(pkgs)

            if os.geteuid() != 0:
                self.output.emit("\n⚠ Требуются права root. Запускаю sudo apt install...\n")

            cmd = f"apt-get install -y {pkgs_str}"
            self.output.emit(f"$ sudo {cmd}\n")

            proc = subprocess.Popen(
                ["sudo", "bash", "-c", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in proc.stdout:
                line = line.strip()
                if line:
                    self.output.emit(line)

            proc.wait()

            if proc.returncode == 0:
                self.finished.emit(True, "Драйверы успешно установлены!")
            else:
                self.finished.emit(False, f"Ошибка установки (код: {proc.returncode})")

        except Exception as e:
            self.finished.emit(False, str(e))


class PrintWorker(QThread):
    progress = Signal(str)
    finished = Signal(bool, str)
    page_printed = Signal(int)

    def __init__(self, conn, printer_name, file_path, options, copies):
        super().__init__()
        self.conn = conn
        self.printer_name = printer_name
        self.file_path = file_path
        self.options = options
        self.copies = copies

    def run(self):
        try:
            for i in range(self.copies):
                self.progress.emit(f"Печать копии {i+1}/{self.copies}...")
                job_id = self.conn.printFile(
                    self.printer_name,
                    self.file_path,
                    Path(self.file_path).name,
                    self.options
                )
                self.page_printed.emit(i + 1)

            self.finished.emit(True, f"Отправлено на печать ({self.copies} копий)")
        except Exception as e:
            self.finished.emit(False, str(e))


class PrintPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.preview_label = QLabel("Предпросмотр")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(400, 500)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.preview_label)

    def show_preview(self, file_path):
        if not HAS_PIL:
            self.preview_label.setText("PIL не установлен\nУстановите: pip install Pillow")
            return

        try:
            img = Image.open(file_path)

            if img.mode == 'RGBA':
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            preview_size = (380, 480)
            img.thumbnail(preview_size, Image.LANCZOS)

            qimg = ImageQt.ImageQt(img)
            pixmap = QPixmap.fromImage(qimg)

            self.preview_label.setPixmap(pixmap)

        except Exception as e:
            self.preview_label.setText(f"Ошибка предпросмотра:\n{str(e)}")


class PrintStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Print Studio")
        self.setMinimumSize(900, 700)

        self.conn = None
        self.selected_file = None
        self.printer_attrs = {}

        self.setup_ui()
        self.connect_cups()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Левая панель - настройки
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(450)

        # Выбор файла
        file_group = QGroupBox("Файл для печати")
        file_layout = QVBoxLayout(file_group)
        file_btn_layout = QHBoxLayout()
        self.file_btn = QPushButton("Выбрать файл...")
        self.file_btn.clicked.connect(self.select_file)
        self.file_label = QLabel("Файл не выбран")
        file_btn_layout.addWidget(self.file_btn)
        file_btn_layout.addWidget(self.file_label, 1)
        file_layout.addLayout(file_btn_layout)
        left_layout.addWidget(file_group)

        # Выбор принтера
        printer_group = QGroupBox("Принтер")
        printer_layout = QVBoxLayout(printer_group)
        printer_row = QHBoxLayout()
        self.printer_combo = QComboBox()
        self.printer_combo.currentIndexChanged.connect(self.on_printer_changed)
        self.refresh_btn = QPushButton("🔄")
        self.refresh_btn.setToolTip("Обновить список принтеров")
        self.refresh_btn.clicked.connect(self.refresh_printers)
        printer_row.addWidget(self.printer_combo, 1)
        printer_row.addWidget(self.refresh_btn)
        printer_layout.addLayout(printer_row)
        left_layout.addWidget(printer_group)

        # Настройки печати
        settings_group = QGroupBox("Настройки печати")
        settings_layout = QFormLayout(settings_group)

        # Количество копий
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 999)
        self.copies_spin.setValue(1)
        settings_layout.addRow("Копии:", self.copies_spin)

        # Ориентация
        self.orientation_combo = QComboBox()
        for k, v in ORIENTATIONS.items():
            self.orientation_combo.addItem(v, k)
        settings_layout.addRow("Ориентация:", self.orientation_combo)

        # Размер бумаги
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(PAPER_SIZES)
        self.paper_combo.setCurrentText("A4")
        settings_layout.addRow("Бумага:", self.paper_combo)

        # Цвет
        self.color_combo = QComboBox()
        for k, v in COLOR_MODES.items():
            self.color_combo.addItem(v, k)
        settings_layout.addRow("Цветность:", self.color_combo)

        # Качество
        self.quality_combo = QComboBox()
        for k, v in QUALITY_PRESETS.items():
            self.quality_combo.addItem(v, k)
        settings_layout.addRow("Качество:", self.quality_combo)

        # Дуплекс
        self.duplex_combo = QComboBox()
        for k, v in DUPLEX_MODES.items():
            self.duplex_combo.addItem(v, k)
        settings_layout.addRow("Двусторонняя:", self.duplex_combo)

        # Масштабирование
        self.scaling_combo = QComboBox()
        self.scaling_combo.addItems(SCALING_OPTIONS)
        settings_layout.addRow("Масштаб:", self.scaling_combo)

        # Процент масштаба (для ручного режима)
        scale_row = QHBoxLayout()
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(10, 500)
        self.scale_slider.setValue(100)
        self.scale_slider.setEnabled(False)
        self.scale_label = QLabel("100%")
        self.scale_slider.valueChanged.connect(
            lambda v: self.scale_label.setText(f"{v}%")
        )
        self.scaling_combo.currentTextChanged.connect(
            lambda t: self.scale_slider.setEnabled(t == "Вручную (%)")
        )
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_label)
        settings_layout.addRow("", scale_row)

        # Количество страниц на листе
        self.pages_per_sheet = QSpinBox()
        self.pages_per_sheet.setRange(1, 16)
        self.pages_per_sheet.setValue(1)
        settings_layout.addRow("Стр./лист:", self.pages_per_sheet)

        left_layout.addWidget(settings_group)

        # Кнопка печати
        self.print_btn = QPushButton("🖨  Напечатать")
        self.print_btn.setMinimumHeight(50)
        self.print_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.print_btn.clicked.connect(self.print_file)
        self.print_btn.setEnabled(False)
        left_layout.addWidget(self.print_btn)

        # Прогресс
        self.progress_label = QLabel("")
        left_layout.addWidget(self.progress_label)

        # Правая панель - предпросмотр + драйверы + лог
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Предпросмотр
        self.preview = PrintPreview()
        right_layout.addWidget(self.preview, 2)

        # Таб с установкой драйверов и логом
        tabs = QTabWidget()

        # Вкладка драйверов
        driver_tab = QWidget()
        driver_layout = QVBoxLayout(driver_tab)

        driver_info = QLabel(
            "Установка драйверов для HP и Epson принтеров.\n"
            "Требуются права root (будет запрошен пароль sudo)."
        )
        driver_info.setWordWrap(True)
        driver_layout.addWidget(driver_info)

        driver_btn_layout = QHBoxLayout()
        self.install_hp_btn = QPushButton("Установить HP")
        self.install_hp_btn.clicked.connect(lambda: self.install_drivers("hp"))
        self.install_epson_btn = QPushButton("Установить Epson")
        self.install_epson_btn.clicked.connect(lambda: self.install_drivers("epson"))
        self.install_all_btn = QPushButton("Установить всё")
        self.install_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 8px;
            }
            QPushButton:hover { background-color: #F57C00; }
        """)
        self.install_all_btn.clicked.connect(lambda: self.install_drivers("all"))

        driver_btn_layout.addWidget(self.install_hp_btn)
        driver_btn_layout.addWidget(self.install_epson_btn)
        driver_btn_layout.addWidget(self.install_all_btn)
        driver_layout.addLayout(driver_btn_layout)

        self.driver_progress = QProgressBar()
        self.driver_progress.setVisible(False)
        driver_layout.addWidget(self.driver_progress)

        self.driver_output = QTextEdit()
        self.driver_output.setReadOnly(True)
        self.driver_output.setMaximumHeight(150)
        self.driver_output.setPlaceholderText("Лог установки драйверов...")
        driver_layout.addWidget(self.driver_output)

        tabs.addTab(driver_tab, "Драйверы")

        # Вкладка лога
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Лог печати...")
        log_layout.addWidget(self.log_output)

        tabs.addTab(log_tab, "Лог")

        right_layout.addWidget(tabs, 1)

        # Разделитель
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 500])
        main_layout.addWidget(splitter)

    def log(self, msg):
        self.log_output.append(msg)

    def progress(self, msg):
        self.progress_label.setText(msg)

    def connect_cups(self):
        if HAS_CUPS:
            try:
                self.conn = cups.Connection()
                self.log("✓ CUPS подключён")
                self.refresh_printers()
            except Exception as e:
                self.log(f"✗ CUPS: {e}")
                QMessageBox.warning(self, "CUPS",
                    "Не удалось подключиться к CUPS.\n"
                    "Убедитесь, что CUPS запущен:\n"
                    "  sudo systemctl start cups\n"
                    "Или установите: sudo apt install cups")
                self.conn = None
        else:
            self.log("✗ python3-cups не установлен")
            QMessageBox.warning(self, "CUPS",
                "python3-cups не найден.\n"
                "Установите: pip install pycups  или  sudo apt install python3-cups")
            self.conn = None

    def refresh_printers(self):
        if not self.conn:
            return

        self.printer_combo.clear()
        try:
            printers = self.conn.getPrinters()
            if not printers:
                self.printer_combo.addItem("— Принтеры не найдены —")
                self.print_btn.setEnabled(False)
                self.log("ℹ Принтеры не обнаружены")
                return

            for name, attrs in sorted(printers.items()):
                status = attrs.get("printer-state", 0)
                status_map = {3: "🟢", 4: "🟡", 5: "🔴"}
                icon = status_map.get(status, "⚪")
                info = attrs.get("printer-info", "")
                self.printer_combo.addItem(f"{icon} {name} ({info})", name)
                self.printer_attrs[name] = attrs

            self.print_btn.setEnabled(bool(self.selected_file))
            self.log(f"✓ Найдено принтеров: {len(printers)}")

        except Exception as e:
            self.log(f"✗ Ошибка получения принтеров: {e}")

    def on_printer_changed(self, idx):
        if idx >= 0 and self.printer_combo.currentData():
            name = self.printer_combo.currentData()
            attrs = self.printer_attrs.get(name, {})
            self.log(f"Выбран принтер: {name}")

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл для печати", "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.tiff *.gif);;"
            "PDF (*.pdf);;"
            "Все файлы (*)"
        )
        if file_path:
            self.selected_file = file_path
            self.file_label.setText(Path(file_path).name)
            self.print_btn.setEnabled(bool(self.printer_combo.count() > 0
                                          and self.printer_combo.currentData()))
            self.preview.show_preview(file_path)
            self.log(f"✓ Выбран файл: {file_path}")

    def build_options(self):
        opts = {}

        orient = self.orientation_combo.currentData()
        if orient:
            opts["orientation-requested"] = str(orient)

        paper = self.paper_combo.currentText()
        if paper:
            opts["PageSize"] = paper

        color = self.color_combo.currentData()
        if color == "grayscale":
            opts["print-color-mode"] = "monochrome"
        else:
            opts["print-color-mode"] = "color"

        quality = self.quality_combo.currentData()
        if quality:
            opts["print-quality"] = str(quality)

        duplex = self.duplex_combo.currentData()
        if duplex and duplex != "none":
            opts["sides"] = duplex

        scaling = self.scaling_combo.currentText()
        if scaling == "Вручную (%)":
            opts["scaling"] = str(self.scale_slider.value())
        elif scaling == "По размеру страницы":
            opts["fit-to-page"] = "True"
        elif scaling == "По ширине":
            opts["fit-to-page"] = "True"
            opts["fit-to-page"] = "True"
        elif scaling == "Без масштабирования":
            opts["scaling"] = "100"

        pps = self.pages_per_sheet.value()
        if pps > 1:
            opts["number-up"] = str(pps)

        opts["media-source"] = "auto"

        return opts

    def print_file(self):
        if not self.conn:
            QMessageBox.warning(self, "Ошибка",
                "CUPS не подключён. Установите драйверы и перезапустите программу.")
            return

        if not self.selected_file:
            QMessageBox.warning(self, "Ошибка", "Выберите файл для печати")
            return

        printer_name = self.printer_combo.currentData()
        if not printer_name:
            QMessageBox.warning(self, "Ошибка", "Выберите принтер")
            return

        options = self.build_options()
        copies = self.copies_spin.value()

        self.log(f"\n{'='*40}")
        self.log(f"Печать: {Path(self.selected_file).name}")
        self.log(f"Принтер: {printer_name}")
        self.log(f"Копии: {copies}")
        self.log(f"Параметры: {options}")
        self.log(f"{'='*40}")

        self.print_btn.setEnabled(False)
        self.progress_label.setText("Печать...")

        self.worker = PrintWorker(
            self.conn, printer_name, self.selected_file, options, copies
        )
        self.worker.progress.connect(lambda m: self.progress_label.setText(m))
        self.worker.page_printed.connect(
            lambda n: self.log(f"  ✓ Копия {n} отправлена")
        )
        self.worker.finished.connect(self.on_print_finished)
        self.worker.start()

    def on_print_finished(self, success, message):
        self.print_btn.setEnabled(True)
        self.progress_label.setText(message)

        if success:
            self.log(f"✓ {message}")
        else:
            self.log(f"✗ {message}")
            QMessageBox.critical(self, "Ошибка печати", message)

    def install_drivers(self, target="all"):
        self.installer = DriverInstaller()
        self.installer.progress.connect(lambda m: self.driver_progress.setVisible(True))
        self.installer.output.connect(lambda m: self.driver_output.append(m))
        self.installer.finished.connect(self.on_driver_install_finished)

        self.driver_output.clear()
        self.driver_output.append("🔄 Установка драйверов...\n")
        self.install_hp_btn.setEnabled(False)
        self.install_epson_btn.setEnabled(False)
        self.install_all_btn.setEnabled(False)

        self.installer.start()

    def on_driver_install_finished(self, success, message):
        self.install_hp_btn.setEnabled(True)
        self.install_epson_btn.setEnabled(True)
        self.install_all_btn.setEnabled(True)
        self.driver_progress.setVisible(False)

        self.driver_output.append(f"\n{'='*40}")
        if success:
            self.driver_output.append(f"✅ {message}")
            self.driver_output.append("\n⚠ Перезапустите программу для подключения CUPS.")
            QMessageBox.information(self, "Готово",
                "Драйверы установлены!\n\n"
                "Подключите принтер и перезапустите программу.")
            self.connect_cups()
        else:
            self.driver_output.append(f"❌ {message}")
            QMessageBox.critical(self, "Ошибка", message)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Print Studio")

    font = QFont()
    font.setPointSize(10)
    app.setFont(font)

    window = PrintStudio()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
