#!/usr/bin/env python3
"""
Print Studio v3 — редактор страниц, печать, поддержка PDF/Excel/Word/ODT/изображений
"""

import sys
import os
import math
import shutil
import tempfile
import subprocess
from pathlib import Path
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QGroupBox,
    QFileDialog, QMessageBox, QFormLayout, QSplitter,
    QScrollArea, QSizePolicy, QProgressDialog, QDialog,
    QDialogButtonBox, QCheckBox
)
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QThread
from PySide6.QtGui import (
    QPixmap, QImage, QFont, QPainter, QPen, QBrush, QColor,
)

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

try:
    import fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

PAPER_SIZES = ["A4", "A3", "A5", "Letter", "Legal", "Tabloid", "B5", "C5"]
PAPER_MM = {
    "A4": (210, 297), "A3": (297, 420), "A5": (148, 210),
    "Letter": (216, 279), "Legal": (216, 356), "Tabloid": (279, 432),
    "B5": (176, 250), "C5": (162, 229),
}
QUALITY_PRESETS = {3: "Черновик", 4: "Нормальное", 5: "Высокое"}
COLOR_MODES = {"color": "Цветная", "grayscale": "Ч/б"}
DUPLEX_MODES = {"none": "Нет", "duplex": "Двустор."}
ORIENTATIONS = {3: "Портрет", 4: "Ландшафт"}

HANDLE_SIZE = 10
MIN_ITEM_SIZE = 20

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.gif', '.webp', '.ico', '.ppm', '.pgm'}
PDF_EXTS = {'.pdf'}
OFFICE_EXTS = {'.xlsx', '.xls', '.docx', '.doc', '.pptx', '.ppt',
               '.odt', '.ods', '.odp', '.rtf', '.csv'}


class FileConverter(QThread):
    progress = Signal(str)
    page_ready = Signal(str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        try:
            ext = Path(self.filepath).suffix.lower()
            self.progress.emit(f"Открытие: {Path(self.filepath).name}")

            if ext in IMAGE_EXTS:
                self.page_ready.emit(self.filepath)
                self.finished.emit([self.filepath])

            elif ext in PDF_EXTS:
                pages = self._render_pdf()
                self.finished.emit(pages)

            elif ext in OFFICE_EXTS:
                pages = self._render_office()
                self.finished.emit(pages)

            else:
                pages = self._render_office()
                self.finished.emit(pages)

        except Exception as e:
            self.error.emit(str(e))

    def _render_pdf(self):
        if not HAS_FITZ:
            self.error.emit("pymupdf не установлен. sudo pacman -S python-pymupdf")
            return []
        pages = []
        doc = fitz.open(self.filepath)
        tmpdir = tempfile.mkdtemp(prefix="ps_pdf_")
        for i in range(len(doc)):
            self.progress.emit(f"PDF страница {i+1}/{len(doc)}...")
            page = doc.load_page(i)
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            out = os.path.join(tmpdir, f"pdf_page_{i+1}.png")
            pix.save(out)
            pages.append(out)
        doc.close()
        return pages

    def _render_office(self):
        tmpdir = tempfile.mkdtemp(prefix="ps_office_")
        out_pdf = os.path.join(tmpdir, "converted.pdf")
        ext = Path(self.filepath).suffix.lower()

        self.progress.emit("Конвертация через LibreOffice...")
        cmd = [
            "libreoffice", "--headless", "--convert-to", "pdf",
            "--outdir", tmpdir, self.filepath
        ]
        try:
            subprocess.run(cmd, timeout=120, capture_output=True, check=True)
        except FileNotFoundError:
            self.error.emit("LibreOffice не установлен. sudo pacman -S libreoffice-fresh")
            return []
        except subprocess.CalledProcessError as e:
            if ext == '.csv':
                return self._render_csv()
            self.error.emit(f"Ошибка конвертации: {e.stderr.decode()[:200] if e.stderr else str(e)}")
            return []
        except subprocess.TimeoutExpired:
            self.error.emit("Конвертация заняла >120 сек. Файл слишком большой.")
            return []

        pdf_name = Path(self.filepath).stem + ".pdf"
        pdf_path = os.path.join(tmpdir, pdf_name)
        if not os.path.exists(pdf_path):
            self.error.emit("Не удалось сконвертировать документ.")
            return []

        if HAS_FITZ:
            pages = []
            doc = fitz.open(pdf_path)
            for i in range(len(doc)):
                self.progress.emit(f"Страница {i+1}/{len(doc)}...")
                page = doc.load_page(i)
                mat = fitz.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=mat)
                out = os.path.join(tmpdir, f"page_{i+1}.png")
                pix.save(out)
                pages.append(out)
            doc.close()
            return pages
        else:
            return [pdf_path]

    def _render_csv(self):
        tmpdir = tempfile.mkdtemp(prefix="ps_csv_")
        out = os.path.join(tmpdir, "table.png")
        try:
            import csv as csvmod
            with open(self.filepath, 'r') as f:
                reader = list(csvmod.reader(f))
            if not reader:
                return []
            from PIL import Image, ImageDraw, ImageFont
            font = ImageFont.load_default()
            col_w = 120
            row_h = 24
            margin = 16
            ncols = max(len(r) for r in reader)
            nrows = len(reader)
            if ncols == 0 or nrows == 0:
                return []
            w = ncols * col_w + 2 * margin
            h = nrows * row_h + 2 * margin
            img = Image.new('RGB', (max(100, w), max(100, h)), 'white')
            draw = ImageDraw.Draw(img)
            for ri, row in enumerate(reader):
                for ci, cell in enumerate(row):
                    x = margin + ci * col_w
                    y = margin + ri * row_h
                    draw.rectangle([x, y, x + col_w, y + row_h],
                                   outline='#cccccc', fill='#f8f8f8' if ri == 0 else 'white')
                    draw.text((x + 4, y + 4), str(cell)[:50], fill='black', font=font)
            img.save(out)
            return [out]
        except Exception:
            return []


@dataclass
class ImageItem:
    path: str
    x: float = 0
    y: float = 0
    w: float = 200
    h: float = 200
    rotation: float = 0
    crop_l: float = 0.0
    crop_t: float = 0.0
    crop_r: float = 1.0
    crop_b: float = 1.0
    visible: bool = True
    z: int = 0

    def copy(self):
        return ImageItem(self.path, self.x, self.y, self.w, self.h,
                         self.rotation, self.crop_l, self.crop_t,
                         self.crop_r, self.crop_b, self.visible, self.z)

    def crop_rect(self):
        return (min(self.crop_l, self.crop_r), min(self.crop_t, self.crop_b),
                max(self.crop_l, self.crop_r), max(self.crop_t, self.crop_b))


class PageCanvas(QWidget):
    item_changed = Signal()
    item_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(500, 600)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.paper = "A4"
        self.items: list[ImageItem] = []
        self.selected_idx = -1
        self.dragging = False
        self.resizing = False
        self.rotating = False
        self.drag_start = QPointF()
        self.item_start = None
        self.handle_pos = -1
        self.hover_handle = -1
        self.margin = 30
        self.bg_color = QColor(255, 255, 255)
        self.dpi = 96

    def paper_size_px(self):
        pw, ph = PAPER_MM.get(self.paper, (210, 297))
        return pw * self.dpi / 25.4, ph * self.dpi / 25.4

    def page_rect(self):
        pw, ph = self.paper_size_px()
        cw = self.width() - 2 * self.margin
        ch = self.height() - 2 * self.margin
        scale = min(cw / pw, ch / ph)
        w = pw * scale
        h = ph * scale
        x = (self.width() - w) / 2
        y = (self.height() - h) / 2
        return QRectF(x, y, w, h)

    def to_page_coords(self, pos):
        page = self.page_rect()
        pw, ph = self.paper_size_px()
        sx = (pos.x() - page.x()) / page.width()
        sy = (pos.y() - page.y()) / page.height()
        return sx * pw, sy * ph

    def to_widget_coords(self, px, py):
        page = self.page_rect()
        pw, ph = self.paper_size_px()
        wx = page.x() + (px / pw) * page.width()
        wy = page.y() + (py / ph) * page.height()
        return wx, wy

    def to_widget_size(self, pw, ph):
        page = self.page_rect()
        ppw, pph = self.paper_size_px()
        return (pw / ppw) * page.width(), (ph / pph) * page.height()

    def add_image_path(self, path):
        pil = Image.open(path)
        w, h = pil.size
        pw, ph = self.paper_size_px()
        scale = 0.5
        nw = w * scale
        nh = h * scale
        if nw > pw * 0.9:
            s2 = pw * 0.9 / nw
            nw *= s2
            nh *= s2
        if nh > ph * 0.9:
            s2 = ph * 0.9 / nh
            nw *= s2
            nh *= s2
        item = ImageItem(path=path, x=(pw - nw) / 2, y=(ph - nh) / 2,
                         w=nw, h=nh, z=len(self.items))
        self.items.append(item)
        self.selected_idx = len(self.items) - 1
        self.item_changed.emit()
        self.item_selected.emit(item)
        self.update()

    def delete_selected(self):
        if 0 <= self.selected_idx < len(self.items):
            del self.items[self.selected_idx]
            self.selected_idx = min(self.selected_idx, len(self.items) - 1)
            self.item_changed.emit()
            self.item_selected.emit(self.items[self.selected_idx] if self.selected_idx >= 0 else None)
            self.update()

    def move_selected_up(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            item.z += 1
            for it in self.items:
                if it is not item and it.z >= item.z:
                    it.z -= 1
            self.item_changed.emit(); self.update()

    def move_selected_down(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            item.z -= 1
            for it in self.items:
                if it is not item and it.z <= item.z:
                    it.z += 1
            self.item_changed.emit(); self.update()

    def rotate_selected(self, deg):
        if 0 <= self.selected_idx < len(self.items):
            self.items[self.selected_idx].rotation = (self.items[self.selected_idx].rotation + deg) % 360
            self.item_changed.emit(); self.update()

    def flip_selected_h(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            item.crop_l, item.crop_r = item.crop_r, item.crop_l
            self.item_changed.emit(); self.update()

    def flip_selected_v(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            item.crop_t, item.crop_b = item.crop_b, item.crop_t
            self.item_changed.emit(); self.update()

    def reset_crop(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            item.crop_l = 0; item.crop_t = 0; item.crop_r = 1; item.crop_b = 1
            self.item_changed.emit(); self.update()

    def find_item_at(self, pos):
        px, py = self.to_page_coords(pos)
        best, best_z = -1, -999999
        for i, item in enumerate(self.items):
            if not item.visible:
                continue
            if item.x <= px <= item.x + item.w and item.y <= py <= item.y + item.h:
                if item.z > best_z:
                    best_z, best = item.z, i
        return best

    def get_handles(self, item):
        rect = self.item_widget_rect(item)
        c = rect.center()
        return {
            0: rect.topLeft(), 1: rect.topRight(),
            2: rect.bottomRight(), 3: rect.bottomLeft(),
            4: QPointF((rect.left() + rect.right()) / 2, rect.top()),
            5: QPointF((rect.left() + rect.right()) / 2, rect.bottom()),
            6: QPointF(rect.left(), (rect.top() + rect.bottom()) / 2),
            7: QPointF(rect.right(), (rect.top() + rect.bottom()) / 2),
            8: QPointF(c.x(), rect.top() - 30),
        }

    def hit_test_handle(self, pos):
        if self.selected_idx < 0:
            return -1
        handles = self.get_handles(self.items[self.selected_idx])
        for idx, pt in handles.items():
            if abs(pos.x() - pt.x()) < HANDLE_SIZE and abs(pos.y() - pt.y()) < HANDLE_SIZE:
                return idx
        return -1

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        h = self.hit_test_handle(event.position())
        if h >= 0:
            self.handle_pos = h
            self.rotating = (h == 8)
            self.resizing = (h != 8)
            self.drag_start = event.position()
            self.item_start = self.items[self.selected_idx].copy()
            return
        idx = self.find_item_at(event.position())
        if idx >= 0:
            self.selected_idx = idx
            self.item_selected.emit(self.items[idx])
            self.dragging = True
            self.drag_start = event.position()
            self.item_start = self.items[idx].copy()
        else:
            self.selected_idx = -1
            self.item_selected.emit(None)
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self.dragging and self.item_start:
            page = self.page_rect()
            pw, ph = self.paper_size_px()
            dx = (pos.x() - self.drag_start.x()) / page.width() * pw
            dy = (pos.y() - self.drag_start.y()) / page.height() * ph
            item = self.items[self.selected_idx]
            item.x = max(0, min(pw - item.w, self.item_start.x + dx))
            item.y = max(0, min(ph - item.h, self.item_start.y + dy))
            self.item_changed.emit(); self.update()
        elif self.resizing and self.item_start:
            px, py = self.to_page_coords(pos)
            item = self.items[self.selected_idx]
            start = self.item_start
            if self.handle_pos in (0, 3, 6):
                nx = min(px, start.x + start.w - MIN_ITEM_SIZE)
                item.x = max(0, nx)
                item.w = max(MIN_ITEM_SIZE, start.x + start.w - nx)
            elif self.handle_pos in (1, 2, 7):
                item.w = max(MIN_ITEM_SIZE, px - start.x)
            if self.handle_pos in (0, 1, 4):
                ny = min(py, start.y + start.h - MIN_ITEM_SIZE)
                item.y = max(0, ny)
                item.h = max(MIN_ITEM_SIZE, start.y + start.h - ny)
            elif self.handle_pos in (2, 3, 5):
                item.h = max(MIN_ITEM_SIZE, py - start.y)
            self.item_changed.emit(); self.update()
        elif self.rotating and self.item_start:
            cw, cy = self.to_widget_coords(
                self.items[self.selected_idx].x + self.items[self.selected_idx].w / 2,
                self.items[self.selected_idx].y + self.items[self.selected_idx].h / 2)
            item = self.items[self.selected_idx]
            item.rotation = math.degrees(math.atan2(pos.x() - cw, -(pos.y() - cy)))
            self.item_changed.emit(); self.update()
        else:
            self.hover_handle = self.hit_test_handle(pos)
            self.setCursor(Qt.OpenHandCursor if self.hover_handle >= 0 or self.find_item_at(pos) >= 0 else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.dragging = self.resizing = self.rotating = False
        self.item_start = None; self.handle_pos = -1
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        if self.selected_idx >= 0 and event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y() / 120.0
            item = self.items[self.selected_idx]
            scale = 1.0 + delta * 0.05
            cx, cy = item.x + item.w / 2, item.y + item.h / 2
            item.w *= scale; item.h *= scale
            item.x = cx - item.w / 2; item.y = cy - item.h / 2
            self.item_changed.emit(); self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        page = self.page_rect()
        painter.setPen(QPen(QColor(100, 100, 100), 2))
        painter.setBrush(QBrush(self.bg_color))
        painter.drawRect(page)
        painter.setClipRect(page)
        sorted_items = sorted(self.items, key=lambda it: it.z)
        for item in sorted_items:
            if not item.visible or not HAS_PIL:
                continue
            try:
                pil = Image.open(item.path)
                if pil.mode == 'RGBA':
                    bg = Image.new('RGBA', pil.size, (255, 255, 255, 255))
                    pil = Image.alpha_composite(bg, pil)
                elif pil.mode != 'RGB' and pil.mode != 'RGBA':
                    pil = pil.convert('RGBA')
            except Exception:
                continue
            cl, ct, cr, cb = item.crop_rect()
            ow, oh = pil.size
            cx1, cy1 = int(cl * ow), int(ct * oh)
            cx2, cy2 = int(cr * ow), int(cb * oh)
            if cx2 <= cx1 or cy2 <= cy1:
                continue
            cropped = pil.crop((cx1, cy1, cx2, cy2))
            qimg = ImageQt.ImageQt(cropped)
            pixmap = QPixmap.fromImage(qimg)
            rect = self.item_widget_rect(item)
            painter.save()
            painter.translate(rect.center())
            if item.rotation != 0:
                painter.rotate(item.rotation)
            target = QRectF(-rect.width() / 2, -rect.height() / 2,
                            rect.width(), rect.height())
            painter.drawPixmap(target.toRect(), pixmap)
            if item is self.items[self.selected_idx]:
                painter.setPen(QPen(QColor(0, 120, 255), 2, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(target)
            painter.restore()
        painter.setClipRect(QRectF(0, 0, self.width(), self.height()))
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            handles = self.get_handles(item)
            for idx, pt in handles.items():
                if idx == 8:
                    painter.setPen(QPen(QColor(0, 120, 255), 2))
                    cw, cy = self.to_widget_coords(
                        item.x + item.w / 2, item.y + item.h / 2)
                    painter.drawLine(QPointF(int(cw), int(cy)), pt)
                painter.setBrush(QBrush(QColor(0, 120, 255)))
                painter.setPen(QPen(Qt.white, 1))
                painter.drawRect(QRectF(pt.x() - 5, pt.y() - 5, 10, 10))
        painter.end()

    def page_to_image(self):
        if not HAS_PIL:
            return None
        pw, ph = self.paper_size_px()
        img = Image.new('RGB', (int(pw), int(ph)),
                        (self.bg_color.red(), self.bg_color.green(), self.bg_color.blue()))
        for item in sorted(self.items, key=lambda it: it.z):
            if not item.visible:
                continue
            try:
                pil = Image.open(item.path)
            except Exception:
                continue
            cl, ct, cr, cb = item.crop_rect()
            ow, oh = pil.size
            cx1, cy1 = max(0, int(cl * ow)), max(0, int(ct * oh))
            cx2, cy2 = min(ow, int(cr * ow)), min(oh, int(cb * oh))
            if cx2 <= cx1 or cy2 <= cy1:
                continue
            cropped = pil.crop((cx1, cy1, cx2, cy2))
            cropped = cropped.resize((max(1, int(item.w)), max(1, int(item.h))),
                                     Image.LANCZOS)
            if item.rotation != 0:
                cropped = cropped.rotate(item.rotation, expand=True,
                                        resample=Image.BICUBIC,
                                        fillcolor=(255, 255, 255, 0))
            paste_pos = (max(0, int(item.x)), max(0, int(item.y)))
            if cropped.mode == 'RGBA':
                img.paste(cropped, paste_pos, cropped.split()[3])
            else:
                img.paste(cropped, paste_pos)
        return img

    def clear_page(self):
        self.items = []
        self.selected_idx = -1
        self.item_changed.emit()
        self.item_selected.emit(None)
        self.update()


class PrintWorker(QThread):
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, conn, printer_name, page_images, options, copies):
        super().__init__()
        self.conn = conn
        self.printer_name = printer_name
        self.page_images = page_images
        self.options = options
        self.copies = copies

    def run(self):
        try:
            tmpdir = tempfile.mkdtemp(prefix="ps_out_")
            files = []
            for i, img in enumerate(self.page_images):
                fpath = os.path.join(tmpdir, f"page_{i+1}.png")
                img.save(fpath, "PNG")
                files.append(fpath)
            for ci in range(self.copies):
                self.progress.emit(f"Копия {ci+1}/{self.copies}...")
                for fi, fpath in enumerate(files):
                    self.conn.printFile(self.printer_name, fpath,
                                        f"page_{fi+1}", self.options)
            for f in files:
                os.unlink(f)
            os.rmdir(tmpdir)
            self.finished.emit(True, f"Отправлено ({len(files)} стр., {self.copies} копий)")
        except Exception as e:
            self.finished.emit(False, str(e))


class ImportDialog(QDialog):
    def __init__(self, num_pages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Импорт страниц")
        self.result_pages = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Документ содержит {num_pages} стр."))
        self.all_pages = QCheckBox("Все страницы (новые)")
        self.all_pages.setChecked(True)
        layout.addWidget(self.all_pages)
        self.first_page = QCheckBox("Только первую на текущую")
        layout.addWidget(self.first_page)
        self.all_to_current = QCheckBox("Все на текущую страницу")
        layout.addWidget(self.all_to_current)
        self.all_pages.toggled.connect(lambda: self.first_page.setChecked(False) or self.all_to_current.setChecked(False))
        self.first_page.toggled.connect(lambda: self.all_pages.setChecked(False) or self.all_to_current.setChecked(False))
        self.all_to_current.toggled.connect(lambda: self.all_pages.setChecked(False) or self.first_page.setChecked(False))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def mode(self):
        if self.first_page.isChecked():
            return "first"
        if self.all_to_current.isChecked():
            return "all_current"
        return "all"


class PrintStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Print Studio v3")
        self.setMinimumSize(1100, 750)
        self.conn = None
        self.printer_attrs = {}
        self.page_idx = 0
        self.pages = [PageCanvas()]
        self.converter = None

        self.setup_ui()
        self.connect_cups()
        self.current_page().item_changed.connect(self.on_item_changed)

    def current_page(self):
        return self.pages[self.page_idx]

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        left_panel = QWidget()
        left_panel.setMaximumWidth(360)
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(8, 8, 8, 8)

        # Файлы
        files_grp = QGroupBox("Файлы")
        fl = QVBoxLayout(files_grp)
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Добавить")
        self.add_btn.clicked.connect(self.add_file)
        self.add_multi_btn = QPushButton("+Несколько")
        self.add_multi_btn.clicked.connect(self.add_files)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.add_multi_btn)
        fl.addLayout(btn_row)
        self.delete_img_btn = QPushButton("Удалить")
        self.delete_img_btn.clicked.connect(lambda: self.current_page().delete_selected())
        fl.addWidget(self.delete_img_btn)
        left.addWidget(files_grp)

        # Слой
        layer_grp = QGroupBox("Слой")
        ll = QVBoxLayout(layer_grp)
        lr1 = QHBoxLayout()
        self.up_btn = QPushButton("▲")
        self.up_btn.clicked.connect(lambda: self.current_page().move_selected_up())
        self.down_btn = QPushButton("▼")
        self.down_btn.clicked.connect(lambda: self.current_page().move_selected_down())
        lr1.addWidget(self.up_btn); lr1.addWidget(self.down_btn)
        ll.addLayout(lr1)
        lr2 = QHBoxLayout()
        self.rot_l_btn = QPushButton("↺ -90")
        self.rot_l_btn.clicked.connect(lambda: self.current_page().rotate_selected(-90))
        self.rot_r_btn = QPushButton("↻ +90")
        self.rot_r_btn.clicked.connect(lambda: self.current_page().rotate_selected(90))
        lr2.addWidget(self.rot_l_btn); lr2.addWidget(self.rot_r_btn)
        ll.addLayout(lr2)
        lr3 = QHBoxLayout()
        self.flip_h_btn = QPushButton("↔ Гор.")
        self.flip_h_btn.clicked.connect(lambda: self.current_page().flip_selected_h())
        self.flip_v_btn = QPushButton("↕ Верт.")
        self.flip_v_btn.clicked.connect(lambda: self.current_page().flip_selected_v())
        lr3.addWidget(self.flip_h_btn); lr3.addWidget(self.flip_v_btn)
        ll.addLayout(lr3)
        self.reset_crop_btn = QPushButton("Сброс обрезки")
        self.reset_crop_btn.clicked.connect(lambda: self.current_page().reset_crop())
        ll.addWidget(self.reset_crop_btn)
        left.addWidget(layer_grp)

        # Страницы
        page_grp = QGroupBox("Страницы")
        pl = QVBoxLayout(page_grp)
        pg_nav = QHBoxLayout()
        self.prev_btn = QPushButton("◀")
        self.prev_btn.clicked.connect(self.prev_page)
        self.page_label = QLabel("1 / 1")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.next_btn = QPushButton("▶")
        self.next_btn.clicked.connect(self.next_page)
        pg_nav.addWidget(self.prev_btn); pg_nav.addWidget(self.page_label); pg_nav.addWidget(self.next_btn)
        pl.addLayout(pg_nav)
        pg_nav2 = QHBoxLayout()
        self.add_page_btn = QPushButton("+ Страница")
        self.add_page_btn.clicked.connect(self.add_page)
        self.del_page_btn = QPushButton("− Страница")
        self.del_page_btn.clicked.connect(self.delete_page)
        pg_nav2.addWidget(self.add_page_btn); pg_nav2.addWidget(self.del_page_btn)
        pl.addLayout(pg_nav2)
        self.dup_page_btn = QPushButton("Копировать страницу")
        self.dup_page_btn.clicked.connect(self.duplicate_page)
        pl.addWidget(self.dup_page_btn)
        left.addWidget(page_grp)

        # Принтер
        printer_grp = QGroupBox("Принтер")
        prl = QVBoxLayout(printer_grp)
        prr = QHBoxLayout()
        self.printer_combo = QComboBox()
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.clicked.connect(self.refresh_printers)
        prr.addWidget(self.printer_combo, 1); prr.addWidget(self.refresh_btn)
        prl.addLayout(prr)
        left.addWidget(printer_grp)

        # Настройки
        set_grp = QGroupBox("Печать")
        sl = QFormLayout(set_grp)
        self.copies_spin = QSpinBox(); self.copies_spin.setRange(1, 999); self.copies_spin.setValue(1)
        sl.addRow("Копии:", self.copies_spin)
        self.orient_combo = QComboBox()
        for k, v in ORIENTATIONS.items():
            self.orient_combo.addItem(v, k)
        sl.addRow("Ориентация:", self.orient_combo)
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(PAPER_SIZES)
        self.paper_combo.setCurrentText("A4")
        self.paper_combo.currentTextChanged.connect(self.on_paper_changed)
        sl.addRow("Бумага:", self.paper_combo)
        self.color_combo = QComboBox()
        for k, v in COLOR_MODES.items():
            self.color_combo.addItem(v, k)
        sl.addRow("Цвет:", self.color_combo)
        self.qual_combo = QComboBox()
        for k, v in QUALITY_PRESETS.items():
            self.qual_combo.addItem(v, k)
        sl.addRow("Качество:", self.qual_combo)
        self.dup_combo = QComboBox()
        for k, v in DUPLEX_MODES.items():
            self.dup_combo.addItem(v, k)
        sl.addRow("Дуплекс:", self.dup_combo)
        left.addWidget(set_grp)

        self.print_btn = QPushButton("🖨  Напечатать")
        self.print_btn.setMinimumHeight(48)
        self.print_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; font-size: 15px;
            font-weight: bold; border-radius: 6px; padding: 8px; }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.print_btn.clicked.connect(self.print_document)
        left.addWidget(self.print_btn)
        self.status_label = QLabel("Готов. Добавьте файлы (изображения, PDF, Excel, Word...).")
        self.status_label.setWordWrap(True)
        left.addWidget(self.status_label)
        left.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.page_stack = QWidget()
        self.page_stack_layout = QVBoxLayout(self.page_stack)
        self.page_stack_layout.setContentsMargins(0, 0, 0, 0)
        self.page_stack_layout.addWidget(self.current_page())
        scroll.setWidget(self.page_stack)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(scroll)
        splitter.setSizes([360, 740])
        main_layout.addWidget(splitter)

    def on_paper_changed(self, text):
        self.current_page().paper = text
        self.current_page().update()

    def on_item_changed(self):
        pass

    def switch_page(self, idx):
        if idx == self.page_idx:
            return
        old = self.current_page()
        self.page_stack_layout.removeWidget(old); old.hide()
        old.item_changed.disconnect()
        self.page_idx = idx
        new_page = self.current_page()
        self.page_stack_layout.addWidget(new_page); new_page.show()
        new_page.item_changed.connect(self.on_item_changed)
        self.page_label.setText(f"{self.page_idx + 1} / {len(self.pages)}")

    def prev_page(self):
        if self.page_idx > 0:
            self.switch_page(self.page_idx - 1)

    def next_page(self):
        if self.page_idx < len(self.pages) - 1:
            self.switch_page(self.page_idx + 1)

    def add_page(self):
        p = PageCanvas()
        p.paper = self.paper_combo.currentText()
        p.item_changed.connect(self.on_item_changed)
        self.pages.append(p)
        self.switch_page(len(self.pages) - 1)
        self.page_label.setText(f"{self.page_idx + 1} / {len(self.pages)}")

    def delete_page(self):
        if len(self.pages) <= 1:
            return
        self.page_stack_layout.removeWidget(self.current_page())
        self.current_page().hide()
        del self.pages[self.page_idx]
        self.page_idx = min(self.page_idx, len(self.pages) - 1)
        new_page = self.current_page()
        self.page_stack_layout.addWidget(new_page); new_page.show()
        new_page.item_changed.connect(self.on_item_changed)
        self.page_label.setText(f"{self.page_idx + 1} / {len(self.pages)}")

    def duplicate_page(self):
        src = self.current_page()
        p = PageCanvas()
        p.paper = src.paper; p.bg_color = src.bg_color
        p.items = [it.copy() for it in src.items]
        p.item_changed.connect(self.on_item_changed)
        self.pages.append(p)
        self.switch_page(len(self.pages) - 1)
        self.page_label.setText(f"{self.page_idx + 1} / {len(self.pages)}")

    def add_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл", "",
            "Все поддерживаемые (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif *.webp "
            "*.pdf *.xlsx *.xls *.docx *.doc *.pptx *.ppt *.odt *.ods *.odp *.rtf *.csv);;"
            "Изображения (*.png *.jpg *.jpeg *.bmp *.tiff *.gif *.webp);;"
            "PDF (*.pdf);;"
            "Документы Office (*.xlsx *.xls *.docx *.doc *.pptx *.ppt *.odt *.ods *.odp *.rtf *.csv);;"
            "Все файлы (*)"
        )
        if path:
            self._import_file(path)

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы", "",
            "Все поддерживаемые (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif *.webp "
            "*.pdf *.xlsx *.xls *.docx *.doc *.pptx *.ppt *.odt *.ods *.odp *.rtf *.csv);;"
            "Изображения (*.png *.jpg *.jpeg *.bmp *.tiff *.gif *.webp);;"
            "PDF (*.pdf);;"
            "Документы Office (*.xlsx *.xls *.docx *.doc *.pptx *.ppt *.odt *.ods *.odp *.rtf *.csv);;"
            "Все файлы (*)"
        )
        for path in paths:
            self._import_file(path)

    def _import_file(self, path):
        ext = Path(path).suffix.lower()
        self.status_label.setText(f"Открытие: {Path(path).name}")

        if ext in IMAGE_EXTS:
            self.current_page().add_image_path(path)
            self.status_label.setText(f"Добавлено: {Path(path).name}")
            return

        self.progress_dlg = QProgressDialog("Конвертация...", None, 0, 0, self)
        self.progress_dlg.setWindowModality(Qt.WindowModal)
        self.progress_dlg.setCancelButton(None)
        self.progress_dlg.show()

        self.converter = FileConverter(path)
        self.converter.progress.connect(self.progress_dlg.setLabelText)
        self.converter.finished.connect(lambda pages: self._on_import_done(path, pages))
        self.converter.error.connect(self._on_import_error)
        self.converter.start()

    def _on_import_done(self, path, pages):
        self.progress_dlg.close()
        if not pages:
            self.status_label.setText(f"Не удалось: {Path(path).name}")
            return

        num_pages = len(pages)
        if num_pages == 1:
            self.current_page().add_image_path(pages[0])
            self.status_label.setText(f"Добавлено: {Path(path).name}")
            return

        dlg = ImportDialog(num_pages, self)
        if dlg.exec() == QDialog.Rejected:
            return

        mode = dlg.mode()
        page = self.current_page()
        if mode == "first":
            page.add_image_path(pages[0])
        elif mode == "all_current":
            for p in pages:
                page.add_image_path(p)
        else:
            page.add_image_path(pages[0])
            for p in pages[1:]:
                new_page = self.add_page()
                self.current_page().add_image_path(p)

        self.status_label.setText(f"Импортировано: {Path(path).name} ({num_pages} стр.)")

    def _on_import_error(self, msg):
        self.progress_dlg.close()
        QMessageBox.warning(self, "Ошибка импорта", msg)
        self.status_label.setText(f"Ошибка: {msg[:80]}")

    def connect_cups(self):
        if HAS_CUPS:
            try:
                self.conn = cups.Connection()
                self.refresh_printers()
            except Exception:
                self.conn = None
        else:
            self.conn = None

    def refresh_printers(self):
        self.printer_combo.clear()
        if not self.conn:
            self.printer_combo.addItem("CUPS не доступен")
            return
        try:
            printers = self.conn.getPrinters()
            if not printers:
                self.printer_combo.addItem("— Нет принтеров —")
                return
            for name in sorted(printers.keys()):
                self.printer_combo.addItem(name, name)
        except Exception:
            self.printer_combo.addItem("— Ошибка —")

    def build_options(self):
        opts = {}
        orient = self.orient_combo.currentData()
        if orient:
            opts["orientation-requested"] = str(orient)
        opts["PageSize"] = self.paper_combo.currentText()
        color = self.color_combo.currentData()
        opts["print-color-mode"] = "monochrome" if color == "grayscale" else "color"
        qual = self.qual_combo.currentData()
        if qual:
            opts["print-quality"] = str(qual)
        dup = self.dup_combo.currentData()
        if dup and dup != "none":
            opts["sides"] = dup
        opts["fit-to-page"] = "True"
        return opts

    def print_document(self):
        if not self.conn:
            QMessageBox.warning(self, "Ошибка", "CUPS не подключён.")
            return
        printer = self.printer_combo.currentData()
        if not printer:
            QMessageBox.warning(self, "Ошибка", "Выберите принтер.")
            return

        self.status_label.setText("Подготовка страниц...")
        QApplication.processEvents()

        page_images = []
        for page in self.pages:
            img = page.page_to_image()
            if img is None:
                QMessageBox.critical(self, "Ошибка",
                    "Pillow не установлен. pip install Pillow")
                return
            page_images.append(img)

        options = self.build_options()
        copies = self.copies_spin.value()

        self.print_btn.setEnabled(False)
        self.worker = PrintWorker(self.conn, printer, page_images, options, copies)
        self.worker.progress.connect(lambda m: self.status_label.setText(m))
        self.worker.finished.connect(self.on_print_done)
        self.worker.start()

    def on_print_done(self, success, msg):
        self.print_btn.setEnabled(True)
        self.status_label.setText(msg)
        if not success:
            QMessageBox.critical(self, "Ошибка", msg)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Print Studio")
    app.setFont(QFont("Sans", 10))
    w = PrintStudio()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
