#!/usr/bin/env python3
"""
Print Studio v3.1 — редактор + обрезка + PDF/Office + печать
"""

import sys, os, math, tempfile, subprocess
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
    import cups; HAS_CUPS = True
except ImportError:
    HAS_CUPS = False
try:
    from PIL import Image, ImageQt; HAS_PIL = True
except ImportError:
    HAS_PIL = False
try:
    import fitz; HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

PAPER_SIZES = ["A4","A3","A5","Letter","Legal","Tabloid","B5","C5"]
PAPER_MM = {"A4":(210,297),"A3":(297,420),"A5":(148,210),
            "Letter":(216,279),"Legal":(216,356),"Tabloid":(279,432),
            "B5":(176,250),"C5":(162,229)}
QUALITY_PRESETS = {3:"Черновик",4:"Нормальное",5:"Высокое"}
COLOR_MODES = {"color":"Цветная","grayscale":"Ч/б"}
DUPLEX_MODES = {"none":"Нет","duplex":"Двустор."}
ORIENTATIONS = {3:"Портрет",4:"Ландшафт"}

HANDLE_SIZE = 9
MIN_ITEM_SIZE = 15
IMAGE_EXTS = {'.png','.jpg','.jpeg','.bmp','.tiff','.tif','.gif','.webp','.ico','.ppm','.pgm'}
PDF_EXTS = {'.pdf'}
OFFICE_EXTS = {'.xlsx','.xls','.docx','.doc','.pptx','.ppt','.odt','.ods','.odp','.rtf','.csv'}


class FileConverter(QThread):
    progress = Signal(str)
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
                self.finished.emit([self.filepath])
            elif ext in PDF_EXTS:
                self.finished.emit(self._render_pdf())
            else:
                self.finished.emit(self._render_office())
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
            self.progress.emit(f"PDF стр. {i+1}/{len(doc)}...")
            pix = doc.load_page(i).get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            out = os.path.join(tmpdir, f"pdf_p{i+1}.png")
            pix.save(out)
            pages.append(out)
        doc.close()
        return pages

    def _render_office(self):
        tmpdir = tempfile.mkdtemp(prefix="ps_office_")
        try:
            subprocess.run(["libreoffice","--headless","--convert-to","pdf",
                           "--outdir",tmpdir,self.filepath],
                          timeout=120, capture_output=True, check=True)
        except FileNotFoundError:
            self.error.emit("Нет LibreOffice. sudo pacman -S libreoffice-fresh")
            return []
        except subprocess.CalledProcessError as e:
            if Path(self.filepath).suffix.lower() == '.csv':
                return self._csv_fallback(tmpdir)
            stderr = e.stderr.decode()[:200] if e.stderr else str(e)
            self.error.emit(f"Ошибка LibreOffice: {stderr}")
            return []
        except subprocess.TimeoutExpired:
            self.error.emit("Конвертация >120 сек.")
            return []

        pdf_path = os.path.join(tmpdir, Path(self.filepath).stem + ".pdf")
        if not os.path.exists(pdf_path):
            self.error.emit("Не удалось сконвертировать.")
            return []

        if HAS_FITZ:
            pages = []
            doc = fitz.open(pdf_path)
            for i in range(len(doc)):
                self.progress.emit(f"Стр. {i+1}/{len(doc)}...")
                pix = doc.load_page(i).get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                out = os.path.join(tmpdir, f"p{i+1}.png")
                pix.save(out)
                pages.append(out)
            doc.close()
            return pages
        return [pdf_path]

    def _csv_fallback(self, tmpdir):
        try:
            import csv as csvmod
            with open(self.filepath, 'r') as f:
                rows = list(csvmod.reader(f))
            if not rows:
                return []
            from PIL import Image, ImageDraw, ImageFont
            font = ImageFont.load_default()
            cw, rh, mg = 120, 24, 16
            ncols = max(len(r) for r in rows)
            w = ncols * cw + 2 * mg
            h = len(rows) * rh + 2 * mg
            img = Image.new('RGB', (max(100, w), max(100, h)), 'white')
            draw = ImageDraw.Draw(img)
            for ri, row in enumerate(rows):
                for ci, cell in enumerate(row):
                    x, y = mg + ci * cw, mg + ri * rh
                    fill = '#f0f0f0' if ri == 0 else 'white'
                    draw.rectangle([x, y, x + cw, y + rh], outline='#ccc', fill=fill)
                    draw.text((x + 4, y + 4), str(cell)[:50], fill='black', font=font)
            out = os.path.join(tmpdir, "table.png")
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
        self.setMinimumSize(400, 500)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.paper = "A4"
        self.items: list[ImageItem] = []
        self.selected_idx = -1
        self.dragging = False
        self.resizing = False
        self.rotating = False
        self.cropping = False
        self.drag_start = QPointF()
        self.item_start = None
        self.handle_pos = -1
        self.hover_handle = -1
        self.margin = 25
        self.bg_color = QColor(255, 255, 255)
        self.dpi = 96

    def paper_size_px(self):
        pw, ph = PAPER_MM.get(self.paper, (210, 297))
        return pw * self.dpi / 25.4, ph * self.dpi / 25.4

    def page_rect(self):
        pw, ph = self.paper_size_px()
        cw = self.width() - 2 * self.margin
        ch = self.height() - 2 * self.margin
        s = min(cw / pw, ch / ph)
        w, h = pw * s, ph * s
        x, y = (self.width() - w) / 2, (self.height() - h) / 2
        return QRectF(x, y, w, h)

    def to_page_coords(self, pos):
        p = self.page_rect()
        pw, ph = self.paper_size_px()
        return ((pos.x() - p.x()) / p.width() * pw,
                (pos.y() - p.y()) / p.height() * ph)

    def to_widget_coords(self, px, py):
        p = self.page_rect()
        pw, ph = self.paper_size_px()
        return (p.x() + (px / pw) * p.width(),
                p.y() + (py / ph) * p.height())

    def to_widget_size(self, pw, ph):
        p = self.page_rect()
        ppw, pph = self.paper_size_px()
        return (pw / ppw) * p.width(), (ph / pph) * p.height()

    def item_widget_rect(self, item):
        px, py = self.to_widget_coords(item.x, item.y)
        pw, ph = self.to_widget_size(item.w, item.h)
        return QRectF(px, py, pw, ph)

    def add_image_path(self, path):
        pil = Image.open(path)
        w, h = pil.size
        pw, ph = self.paper_size_px()
        s = 0.5
        nw, nh = w * s, h * s
        if nw > pw * 0.85:
            s2 = pw * 0.85 / nw; nw *= s2; nh *= s2
        if nh > ph * 0.85:
            s2 = ph * 0.85 / nh; nw *= s2; nh *= s2
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
            self.item_changed.emit()
            self.update()

    def move_selected_down(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            item.z -= 1
            for it in self.items:
                if it is not item and it.z <= item.z:
                    it.z += 1
            self.item_changed.emit()
            self.update()

    def rotate_selected(self, deg):
        if 0 <= self.selected_idx < len(self.items):
            self.items[self.selected_idx].rotation = (self.items[self.selected_idx].rotation + deg) % 360
            self.item_changed.emit()
            self.update()

    def flip_selected_h(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            item.crop_l, item.crop_r = item.crop_r, item.crop_l
            self.item_changed.emit()
            self.update()

    def flip_selected_v(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            item.crop_t, item.crop_b = item.crop_b, item.crop_t
            self.item_changed.emit()
            self.update()

    def reset_crop(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            item.crop_l = 0; item.crop_t = 0
            item.crop_r = 1; item.crop_b = 1
            self.item_changed.emit()
            self.update()

    def apply_crop(self):
        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            cl, ct, cr, cb = item.crop_rect()
            if cr <= cl or cb <= ct:
                return
            cw = item.w * (cr - cl)
            ch = item.h * (cb - ct)
            item.x += item.w * cl
            item.y += item.h * ct
            item.w = cw
            item.h = ch
            item.crop_l = 0; item.crop_t = 0
            item.crop_r = 1; item.crop_b = 1
            self.cropping = False
            self.item_changed.emit()
            self.update()

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

    def _crop_handle_positions(self, item):
        rect = self.item_widget_rect(item)
        cl, ct, cr, cb = item.crop_rect()
        x1 = rect.x() + rect.width() * cl
        y1 = rect.y() + rect.height() * ct
        x2 = rect.x() + rect.width() * cr
        y2 = rect.y() + rect.height() * cb
        return {
            0: QPointF(x1, y1),
            1: QPointF(x2, y1),
            2: QPointF(x2, y2),
            3: QPointF(x1, y2),
            4: QPointF((x1 + x2) / 2, y1),
            5: QPointF((x1 + x2) / 2, y2),
            6: QPointF(x1, (y1 + y2) / 2),
            7: QPointF(x2, (y1 + y2) / 2),
        }

    def _normal_handle_positions(self, item):
        rect = self.item_widget_rect(item)
        c = rect.center()
        return {
            0: rect.topLeft(), 1: rect.topRight(),
            2: rect.bottomRight(), 3: rect.bottomLeft(),
            4: QPointF((rect.left() + rect.right()) / 2, rect.top()),
            5: QPointF((rect.left() + rect.right()) / 2, rect.bottom()),
            6: QPointF(rect.left(), (rect.top() + rect.bottom()) / 2),
            7: QPointF(rect.right(), (rect.top() + rect.bottom()) / 2),
            8: QPointF(c.x(), rect.top() - 28),
        }

    def get_handles(self, item):
        if self.cropping:
            return self._crop_handle_positions(item)
        return self._normal_handle_positions(item)

    def hit_test_handle(self, pos):
        if self.selected_idx < 0:
            return -1
        handles = self.get_handles(self.items[self.selected_idx])
        for idx, pt in handles.items():
            if abs(pos.x() - pt.x()) < HANDLE_SIZE and abs(pos.y() - pt.y()) < HANDLE_SIZE:
                return idx
        return -1

    def _crop_handle_to_fraction(self, item, hx, hy):
        rect = self.item_widget_rect(item)
        if rect.width() == 0 or rect.height() == 0:
            return 0, 0
        fx = (hx - rect.x()) / rect.width()
        fy = (hy - rect.y()) / rect.height()
        return max(0.0, min(1.0, fx)), max(0.0, min(1.0, fy))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        h = self.hit_test_handle(event.position())
        if h >= 0:
            self.handle_pos = h
            if self.cropping:
                pass
            else:
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
            self.cropping = False
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self.dragging and self.item_start:
            p = self.page_rect()
            pw, ph = self.paper_size_px()
            dx = (pos.x() - self.drag_start.x()) / p.width() * pw
            dy = (pos.y() - self.drag_start.y()) / p.height() * ph
            item = self.items[self.selected_idx]
            item.x = max(0, min(pw - item.w, self.item_start.x + dx))
            item.y = max(0, min(ph - item.h, self.item_start.y + dy))
            self.item_changed.emit(); self.update()
        elif self.cropping and self.item_start and self.handle_pos >= 0:
            item = self.items[self.selected_idx]
            fx, fy = self._crop_handle_to_fraction(item, pos.x(), pos.y())
            hp = self.handle_pos
            if hp in (0, 3, 6):
                item.crop_l = fx
            elif hp in (1, 2, 7):
                item.crop_r = fx
            if hp in (0, 1, 4):
                item.crop_t = fy
            elif hp in (2, 3, 5):
                item.crop_b = fy
            self.item_changed.emit(); self.update()
        elif self.resizing and self.item_start:
            px, py = self.to_page_coords(pos)
            item = self.items[self.selected_idx]
            start = self.item_start
            hp = self.handle_pos
            if hp in (0, 3, 6):
                nx = min(px, start.x + start.w - MIN_ITEM_SIZE)
                item.x = max(0, nx)
                item.w = max(MIN_ITEM_SIZE, start.x + start.w - nx)
            elif hp in (1, 2, 7):
                item.w = max(MIN_ITEM_SIZE, px - start.x)
            if hp in (0, 1, 4):
                ny = min(py, start.y + start.h - MIN_ITEM_SIZE)
                item.y = max(0, ny)
                item.h = max(MIN_ITEM_SIZE, start.y + start.h - ny)
            elif hp in (2, 3, 5):
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
            over_item = self.find_item_at(pos) >= 0
            self.setCursor(Qt.CrossCursor if self.hover_handle >= 0 else
                          Qt.OpenHandCursor if over_item else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.dragging = self.resizing = self.rotating = False
        self.item_start = None; self.handle_pos = -1
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        if self.selected_idx >= 0 and event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y() / 120.0
            item = self.items[self.selected_idx]
            s = 1.0 + delta * 0.05
            cx, cy = item.x + item.w / 2, item.y + item.h / 2
            item.w *= s; item.h *= s
            item.x = cx - item.w / 2; item.y = cy - item.h / 2
            self.item_changed.emit(); self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        page = self.page_rect()
        painter.setPen(QPen(QColor(110, 110, 110), 2))
        painter.setBrush(QBrush(self.bg_color))
        painter.drawRect(page)
        painter.setClipRect(page)
        for item in sorted(self.items, key=lambda it: it.z):
            if not item.visible or not HAS_PIL:
                continue
            try:
                pil = Image.open(item.path)
                if pil.mode == 'RGBA':
                    bg = Image.new('RGBA', pil.size, (255, 255, 255, 255))
                    pil = Image.alpha_composite(bg, pil)
                elif pil.mode not in ('RGB', 'RGBA'):
                    pil = pil.convert('RGBA')
            except Exception:
                continue
            cl, ct, cr, cb = item.crop_rect()
            ow, oh = pil.size
            cx1, cx2 = int(cl * ow), int(cr * ow)
            cy1, cy2 = int(ct * oh), int(cb * oh)
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
            painter.restore()

        painter.setClipRect(QRectF(0, 0, self.width(), self.height()))

        if 0 <= self.selected_idx < len(self.items):
            item = self.items[self.selected_idx]
            if self.cropping:
                rect = self.item_widget_rect(item)
                cl, ct, cr, cb = item.crop_rect()
                inner = QRectF(
                    rect.x() + rect.width() * cl,
                    rect.y() + rect.height() * ct,
                    rect.width() * (cr - cl),
                    rect.height() * (cb - ct))
                painter.setBrush(QBrush(QColor(0, 0, 0, 100)))
                painter.setPen(Qt.NoPen)
                painter.drawRect(page)
                painter.setCompositionMode(QPainter.CompositionMode_Clear)
                painter.drawRect(inner)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                painter.setPen(QPen(QColor(0, 200, 60), 2, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(inner)
                for ci in (0, 1, 2, 3):
                    h = self._crop_handle_positions(item)[ci]
                    painter.setBrush(QBrush(QColor(0, 200, 60)))
                    painter.setPen(QPen(Qt.white, 1))
                    painter.drawRect(QRectF(h.x() - 5, h.y() - 5, 10, 10))
            else:
                rect = self.item_widget_rect(item)
                painter.setPen(QPen(QColor(0, 120, 255), 2, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect)
                for idx, pt in self.get_handles(item).items():
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
            cx1, cx2 = max(0, int(cl * ow)), min(ow, int(cr * ow))
            cy1, cy2 = max(0, int(ct * oh)), min(oh, int(cb * oh))
            if cx2 <= cx1 or cy2 <= cy1:
                continue
            cropped = pil.crop((cx1, cy1, cx2, cy2))
            cropped = cropped.resize((max(1, int(item.w)), max(1, int(item.h))),
                                     Image.LANCZOS)
            if item.rotation != 0:
                cropped = cropped.rotate(item.rotation, expand=True,
                                        resample=Image.BICUBIC,
                                        fillcolor=(255, 255, 255, 0))
            pp = (max(0, int(item.x)), max(0, int(item.y)))
            if cropped.mode == 'RGBA':
                img.paste(cropped, pp, cropped.split()[3])
            else:
                img.paste(cropped, pp)
        return img

    def clear_page(self):
        self.items = []
        self.selected_idx = -1
        self.cropping = False
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
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Документ: {num_pages} стр."))
        self.all_pages = QCheckBox("Все страницы (новые)")
        self.all_pages.setChecked(True)
        layout.addWidget(self.all_pages)
        self.first_page = QCheckBox("Только первую на текущую")
        layout.addWidget(self.first_page)
        self.all_current = QCheckBox("Все на текущую")
        layout.addWidget(self.all_current)
        self.all_pages.toggled.connect(lambda: (self.first_page.setChecked(False), self.all_current.setChecked(False)))
        self.first_page.toggled.connect(lambda: (self.all_pages.setChecked(False), self.all_current.setChecked(False)))
        self.all_current.toggled.connect(lambda: (self.all_pages.setChecked(False), self.first_page.setChecked(False)))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def mode(self):
        if self.first_page.isChecked():
            return "first"
        if self.all_current.isChecked():
            return "all_current"
        return "all"


class PrintStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Print Studio v3.1")
        self.setMinimumSize(1100, 700)
        self.conn = None
        self.page_idx = 0
        self.pages = [PageCanvas()]
        self.converter = None
        self.setup_ui()
        self.connect_cups()
        self.current_page().item_changed.connect(self._on_item)

    def current_page(self):
        return self.pages[self.page_idx]

    def _on_item(self):
        pass

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        ml = QHBoxLayout(central)
        ml.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(380)
        left = QWidget()
        left.setMinimumWidth(340)
        lo = QVBoxLayout(left)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.setSpacing(8)

        g = QGroupBox("Файлы")
        gl = QVBoxLayout(g); gl.setSpacing(4)
        r = QHBoxLayout()
        self.add_btn = QPushButton("Добавить")
        self.add_btn.clicked.connect(self._add_file)
        self.add_multi_btn = QPushButton("+Несколько")
        self.add_multi_btn.clicked.connect(self._add_files)
        r.addWidget(self.add_btn); r.addWidget(self.add_multi_btn)
        gl.addLayout(r)
        self.del_btn = QPushButton("Удалить")
        self.del_btn.clicked.connect(lambda: self.current_page().delete_selected())
        gl.addWidget(self.del_btn)
        lo.addWidget(g)

        g = QGroupBox("Слой")
        gl = QVBoxLayout(g); gl.setSpacing(4)
        r = QHBoxLayout()
        self.up_btn = QPushButton("▲"); self.up_btn.clicked.connect(lambda: self.current_page().move_selected_up())
        self.down_btn = QPushButton("▼"); self.down_btn.clicked.connect(lambda: self.current_page().move_selected_down())
        r.addWidget(self.up_btn); r.addWidget(self.down_btn)
        gl.addLayout(r)
        r = QHBoxLayout()
        self.rot_l = QPushButton("↺ -90"); self.rot_l.clicked.connect(lambda: self.current_page().rotate_selected(-90))
        self.rot_r = QPushButton("↻ +90"); self.rot_r.clicked.connect(lambda: self.current_page().rotate_selected(90))
        r.addWidget(self.rot_l); r.addWidget(self.rot_r)
        gl.addLayout(r)
        r = QHBoxLayout()
        self.flip_h = QPushButton("↔ Гор."); self.flip_h.clicked.connect(lambda: self.current_page().flip_selected_h())
        self.flip_v = QPushButton("↕ Верт."); self.flip_v.clicked.connect(lambda: self.current_page().flip_selected_v())
        r.addWidget(self.flip_h); r.addWidget(self.flip_v)
        gl.addLayout(r)

        r = QHBoxLayout()
        self.crop_btn = QPushButton("Обрезать")
        self.crop_btn.setCheckable(True)
        self.crop_btn.clicked.connect(self._toggle_crop)
        self.apply_crop_btn = QPushButton("Применить")
        self.apply_crop_btn.clicked.connect(lambda: self.current_page().apply_crop())
        self.apply_crop_btn.setEnabled(False)
        self.apply_crop_btn.setStyleSheet("QPushButton:enabled{background:#e8f5e9;font-weight:bold}")
        r.addWidget(self.crop_btn); r.addWidget(self.apply_crop_btn)
        gl.addLayout(r)

        self.reset_crop_btn = QPushButton("Сброс обрезки")
        self.reset_crop_btn.clicked.connect(lambda: self.current_page().reset_crop())
        gl.addWidget(self.reset_crop_btn)
        lo.addWidget(g)

        g = QGroupBox("Страницы")
        gl = QVBoxLayout(g); gl.setSpacing(4)
        r = QHBoxLayout()
        self.prev_btn = QPushButton("◀"); self.prev_btn.clicked.connect(self._prev_page)
        self.page_label = QLabel("1 / 1"); self.page_label.setAlignment(Qt.AlignCenter)
        self.next_btn = QPushButton("▶"); self.next_btn.clicked.connect(self._next_page)
        r.addWidget(self.prev_btn); r.addWidget(self.page_label); r.addWidget(self.next_btn)
        gl.addLayout(r)
        r = QHBoxLayout()
        self.add_page_btn = QPushButton("+ Стр."); self.add_page_btn.clicked.connect(self._add_page)
        self.del_page_btn = QPushButton("− Стр."); self.del_page_btn.clicked.connect(self._del_page)
        r.addWidget(self.add_page_btn); r.addWidget(self.del_page_btn)
        gl.addLayout(r)
        self.dup_page_btn = QPushButton("Копировать страницу")
        self.dup_page_btn.clicked.connect(self._dup_page)
        gl.addWidget(self.dup_page_btn)
        lo.addWidget(g)

        g = QGroupBox("Принтер")
        gl = QVBoxLayout(g); gl.setSpacing(4)
        r = QHBoxLayout()
        self.printer_combo = QComboBox()
        self.refresh_btn = QPushButton("↻"); self.refresh_btn.clicked.connect(self._refresh_printers)
        r.addWidget(self.printer_combo, 1); r.addWidget(self.refresh_btn)
        gl.addLayout(r)
        lo.addWidget(g)

        g = QGroupBox("Печать")
        gl = QFormLayout(g); gl.setSpacing(4)
        self.copies_spin = QSpinBox(); self.copies_spin.setRange(1, 999); self.copies_spin.setValue(1)
        gl.addRow("Копии:", self.copies_spin)
        self.orient_combo = QComboBox()
        for k, v in ORIENTATIONS.items():
            self.orient_combo.addItem(v, k)
        gl.addRow("Ориент.:", self.orient_combo)
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(PAPER_SIZES); self.paper_combo.setCurrentText("A4")
        self.paper_combo.currentTextChanged.connect(self._on_paper)
        gl.addRow("Бумага:", self.paper_combo)
        self.color_combo = QComboBox()
        for k, v in COLOR_MODES.items():
            self.color_combo.addItem(v, k)
        gl.addRow("Цвет:", self.color_combo)
        self.qual_combo = QComboBox()
        for k, v in QUALITY_PRESETS.items():
            self.qual_combo.addItem(v, k)
        gl.addRow("Качество:", self.qual_combo)
        self.dup_combo = QComboBox()
        for k, v in DUPLEX_MODES.items():
            self.dup_combo.addItem(v, k)
        gl.addRow("Дуплекс:", self.dup_combo)
        lo.addWidget(g)

        self.print_btn = QPushButton("🖨  Напечатать")
        self.print_btn.setMinimumHeight(44)
        self.print_btn.setStyleSheet(
            "QPushButton{background:#4CAF50;color:white;font-size:14px;"
            "font-weight:bold;border-radius:6px;padding:8px}"
            "QPushButton:hover{background:#45a049}"
            "QPushButton:disabled{background:#ccc}"
        )
        self.print_btn.clicked.connect(self._print)
        lo.addWidget(self.print_btn)

        self.status_label = QLabel("Готово. Добавьте файлы (изобр., PDF, Excel, Word...)")
        self.status_label.setWordWrap(True)
        lo.addWidget(self.status_label)
        lo.addStretch()

        scroll.setWidget(left)

        canvas_scroll = QScrollArea()
        canvas_scroll.setWidgetResizable(True)
        self.stack = QWidget()
        self.stack_layout = QVBoxLayout(self.stack)
        self.stack_layout.setContentsMargins(0, 0, 0, 0)
        self.stack_layout.addWidget(self.current_page())
        canvas_scroll.setWidget(self.stack)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(canvas_scroll)
        splitter.setSizes([380, 720])
        ml.addWidget(splitter)

    def _toggle_crop(self, checked):
        page = self.current_page()
        page.cropping = checked
        self.apply_crop_btn.setEnabled(checked)
        page.update()

    def _on_paper(self, text):
        self.current_page().paper = text
        self.current_page().update()

    def _switch_page(self, idx):
        if idx == self.page_idx:
            return
        old = self.current_page()
        self.stack_layout.removeWidget(old); old.hide()
        old.item_changed.disconnect()
        self.page_idx = idx
        new = self.current_page()
        self.stack_layout.addWidget(new); new.show()
        new.item_changed.connect(self._on_item)
        self.page_label.setText(f"{self.page_idx+1} / {len(self.pages)}")
        self.crop_btn.setChecked(False)
        self.apply_crop_btn.setEnabled(False)

    def _prev_page(self):
        if self.page_idx > 0:
            self._switch_page(self.page_idx - 1)

    def _next_page(self):
        if self.page_idx < len(self.pages) - 1:
            self._switch_page(self.page_idx + 1)

    def _add_page(self):
        p = PageCanvas()
        p.paper = self.paper_combo.currentText()
        p.item_changed.connect(self._on_item)
        self.pages.append(p)
        self._switch_page(len(self.pages) - 1)

    def _del_page(self):
        if len(self.pages) <= 1:
            return
        self.stack_layout.removeWidget(self.current_page())
        self.current_page().hide()
        del self.pages[self.page_idx]
        self.page_idx = min(self.page_idx, len(self.pages) - 1)
        new = self.current_page()
        self.stack_layout.addWidget(new); new.show()
        new.item_changed.connect(self._on_item)
        self.page_label.setText(f"{self.page_idx+1} / {len(self.pages)}")

    def _dup_page(self):
        src = self.current_page()
        p = PageCanvas()
        p.paper = src.paper; p.bg_color = src.bg_color
        p.items = [it.copy() for it in src.items]
        p.item_changed.connect(self._on_item)
        self.pages.append(p)
        self._switch_page(len(self.pages) - 1)

    def _add_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл", "",
            "Всё (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif *.webp "
            "*.pdf *.xlsx *.xls *.docx *.doc *.pptx *.ppt *.odt *.ods *.odp *.rtf *.csv);;"
            "Изображения (*.png *.jpg *.jpeg *.bmp *.tiff *.gif *.webp);;"
            "PDF (*.pdf);;"
            "Office (*.xlsx *.xls *.docx *.doc *.pptx *.ppt *.odt *.ods *.odp *.rtf *.csv);;"
            "Все файлы (*)"
        )
        if path:
            self._import(path)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы", "",
            "Всё (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif *.webp "
            "*.pdf *.xlsx *.xls *.docx *.doc *.pptx *.ppt *.odt *.ods *.odp *.rtf *.csv);;"
            "Изображения (*.png *.jpg *.jpeg *.bmp *.tiff *.gif *.webp);;"
            "PDF (*.pdf);;"
            "Office (*.xlsx *.xls *.docx *.doc *.pptx *.ppt *.odt *.ods *.odp *.rtf *.csv);;"
            "Все файлы (*)"
        )
        for path in paths:
            self._import(path)

    def _import(self, path):
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
        self.converter.finished.connect(lambda pages: self._import_done(path, pages))
        self.converter.error.connect(self._import_err)
        self.converter.start()

    def _import_done(self, path, pages):
        self.progress_dlg.close()
        if not pages:
            self.status_label.setText(f"Пусто: {Path(path).name}")
            return
        if len(pages) == 1:
            self.current_page().add_image_path(pages[0])
            self.status_label.setText(f"Добавлено: {Path(path).name}")
            return
        dlg = ImportDialog(len(pages), self)
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
                self._add_page()
                self.current_page().add_image_path(p)
        self.status_label.setText(f"Импорт: {Path(path).name} ({len(pages)} стр.)")

    def _import_err(self, msg):
        self.progress_dlg.close()
        QMessageBox.warning(self, "Ошибка импорта", msg)
        self.status_label.setText(f"Ошибка: {msg[:80]}")

    def _connect_cups(self):
        self.connect_cups()

    def connect_cups(self):
        if HAS_CUPS:
            try:
                self.conn = cups.Connection()
                self._refresh_printers()
            except Exception:
                self.conn = None
        else:
            self.conn = None

    def _refresh_printers(self):
        self.printer_combo.clear()
        if not self.conn:
            self.printer_combo.addItem("CUPS не доступен"); return
        try:
            ps = self.conn.getPrinters()
            if not ps:
                self.printer_combo.addItem("— Нет принтеров —"); return
            for n in sorted(ps.keys()):
                self.printer_combo.addItem(n, n)
        except Exception:
            self.printer_combo.addItem("— Ошибка —")

    def _build_opts(self):
        o = {}
        orient = self.orient_combo.currentData()
        if orient:
            o["orientation-requested"] = str(orient)
        o["PageSize"] = self.paper_combo.currentText()
        o["print-color-mode"] = "monochrome" if self.color_combo.currentData() == "grayscale" else "color"
        q = self.qual_combo.currentData()
        if q:
            o["print-quality"] = str(q)
        d = self.dup_combo.currentData()
        if d and d != "none":
            o["sides"] = d
        o["fit-to-page"] = "True"
        return o

    def _print(self):
        if not self.conn:
            QMessageBox.warning(self, "Ошибка", "CUPS не подключён.")
            return
        printer = self.printer_combo.currentData()
        if not printer:
            QMessageBox.warning(self, "Ошибка", "Выберите принтер.")
            return
        self.status_label.setText("Подготовка...")
        QApplication.processEvents()
        imgs = []
        for pg in self.pages:
            img = pg.page_to_image()
            if img is None:
                QMessageBox.critical(self, "Ошибка", "Pillow не установлен.")
                return
            imgs.append(img)
        opts = self._build_opts()
        copies = self.copies_spin.value()
        self.print_btn.setEnabled(False)
        self.worker = PrintWorker(self.conn, printer, imgs, opts, copies)
        self.worker.progress.connect(lambda m: self.status_label.setText(m))
        self.worker.finished.connect(self._print_done)
        self.worker.start()

    def _print_done(self, ok, msg):
        self.print_btn.setEnabled(True)
        self.status_label.setText(msg)
        if not ok:
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
