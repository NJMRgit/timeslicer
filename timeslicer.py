import math
import os
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QGroupBox, QFormLayout, QLabel,
    QDoubleSpinBox, QRadioButton, QCheckBox,
    QSplitter, QGraphicsView, QGraphicsScene,
    QSlider, QStatusBar, QMessageBox, QFileDialog,
    QGraphicsPixmapItem, QAbstractSpinBox, QButtonGroup,
    QListWidget, QAbstractItemView, QListWidgetItem
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QImage, QColor, QDropEvent, QDragEnterEvent, QDragMoveEvent

DEG2RAD = 0.01745329251


class SliceProcessor(QThread):
    info = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    preview_ready = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.images = []
        self.blending = 0.25
        self.preview = True
        self.preview_image = QImage()
        self.reverse = False
        self.angle = 40.0
        self.shadow_mode = "none"
        self.shadow_alpha = 0.1
        self.thumbs = []

    def blend(self, pos):
        if self.blending < 0.01:
            return 1.0 if pos < 1 else 0.0
        s = 0.5 - (abs(pos) - 1) * (1.0 / (2.0 * self.blending))
        s = max(0.0, min(1.0, s))
        s /= math.sqrt(s * s + (1 - s) * (1 - s))
        return s

    def run(self):
        if not self.preview:
            self.info.emit("Started")

        if len(self.images) < 2:
            self.error.emit("Too few images!")
            return

        if self.preview:
            if not self.thumbs:
                for path in self.images:
                    im = QImage(path)
                    self.thumbs.append(im.scaled(1920, 1920, Qt.AspectRatioMode.KeepAspectRatio))
            thumb_size = self.thumbs[0].size()
            self.thumbs = [t.scaled(thumb_size, Qt.AspectRatioMode.IgnoreAspectRatio) for t in self.thumbs]
            output = QImage(thumb_size, QImage.Format.Format_RGB32)
        else:
            output = QImage(self.images[0])

        sn = math.sin(DEG2RAD * self.angle)
        cn = math.cos(DEG2RAD * self.angle)

        n = len(self.images)
        for p in range(n):
            pi = (n - p - 1) if self.reverse else p

            if self.preview:
                layer = self.thumbs[pi]
            else:
                layer = QImage(self.images[pi])
                if layer.size() != output.size():
                    layer = layer.scaled(output.size(), Qt.AspectRatioMode.IgnoreAspectRatio)

            for i in range(output.width()):
                for j in range(output.height()):
                    ox = i / output.width() - 0.5
                    oy = j / output.height() - 0.5

                    cx = cn * ox - sn * oy
                    t = cx + 0.5

                    b = 1.0
                    if pi == 0 and cx < -0.5:
                        pass
                    elif pi == n - 1 and cx > 0.5:
                        pass
                    else:
                        b = self.blend(2.0 * ((n - 1) * t - pi))

                    if b < 0.001:
                        continue

                    r = layer.pixelColor(i, j)
                    prev = output.pixelColor(i, j)

                    darken = 1.0
                    if self.shadow_mode != "none" and self.shadow_alpha > 0.01:
                        d = abs(b - 0.5)
                        if d < 0.5:
                            f = 1.0 - d / 0.5
                            if self.shadow_mode == "forward" and b < 0.5:
                                darken = 1.0 - f * self.shadow_alpha
                            elif self.shadow_mode == "backward" and b > 0.5:
                                darken = 1.0 - f * self.shadow_alpha

                    if darken < 1.0:
                        r = QColor(int(r.red() * darken), int(r.green() * darken), int(r.blue() * darken))

                    blended = QColor(
                        int(prev.red() * (1.0 - b) + r.red() * b),
                        int(prev.green() * (1.0 - b) + r.green() * b),
                        int(prev.blue() * (1.0 - b) + r.blue() * b)
                    )
                    output.setPixelColor(i, j, blended)

            if not self.preview:
                self.progress.emit(p)

            if self.isInterruptionRequested():
                return

        if self.preview:
            self.preview_image = output.copy()
            self.preview_ready.emit()

        if not self.preview:
            out_dir = os.path.expanduser("~/Pictures/timeslicer")
            os.makedirs(out_dir, exist_ok=True)
            output.save(os.path.join(out_dir, "time.jpg"), "jpg", 90)
            self.info.emit("Done!")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Time Slicer")
        self.resize(746, 525)
        self.setAcceptDrops(True)

        self.images = []
        self.processor = SliceProcessor()
        self._pending_update = False
        self._populating_list = False

        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(100)
        self.update_timer.timeout.connect(self.update_preview)

        self.processor.info.connect(self.on_info)
        self.processor.error.connect(self.on_error)
        self.processor.progress.connect(self.on_progress)
        self.processor.finished.connect(self.on_processor_finished)
        self.processor.preview_ready.connect(self.on_preview_ready)

        self._setup_ui()
        self.statusBar().showMessage("Time Slicer")

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(3, 3, 3, 3)

        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)

        self.preview_view = QGraphicsView()
        self.preview_view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.preview_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_view.setAcceptDrops(False)
        self.preview_view.installEventFilter(self)
        self.preview_scene = QGraphicsScene(self)
        self.preview_view.setScene(self.preview_scene)
        self.preview_item = QGraphicsPixmapItem()
        self.preview_scene.addItem(self.preview_item)
        self.preview_wait = QLabel("Please wait...", self.preview_view)
        self.preview_wait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_wait.setStyleSheet("background: palette(window); border: 1px solid palette(mid); padding: 8px;")
        self.preview_wait.adjustSize()
        self.preview_wait.hide()
        splitter.addWidget(self.preview_view)

        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(controls)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        # Section 1: Add files / folder buttons
        btn_widget = QWidget()
        btn_layout = QVBoxLayout(btn_widget)
        btn_layout.addStretch()
        btn_center = QVBoxLayout()
        btn_center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add_files_btn = QPushButton("Add files")
        self.add_files_btn.clicked.connect(self.on_add_files)
        btn_center.addWidget(self.add_files_btn)
        self.add_folder_btn = QPushButton("Add folder")
        self.add_folder_btn.clicked.connect(self.on_add_folder)
        btn_center.addWidget(self.add_folder_btn)
        btn_layout.addLayout(btn_center)
        btn_layout.addStretch()
        controls_layout.addWidget(btn_widget)

        # Section 2: Reorderable image list
        list_group = QGroupBox("Images")
        list_layout = QVBoxLayout(list_group)
        self.image_list = QListWidget()
        self.image_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.image_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.image_list.viewport().installEventFilter(self)
        list_layout.addWidget(self.image_list)
        controls_layout.addWidget(list_group)

        # Section 3: Mask settings
        mask_group = QGroupBox("Mask")
        mask_layout = QFormLayout(mask_group)
        mask_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.blending_spin = QDoubleSpinBox()
        self.blending_spin.setDecimals(2)
        self.blending_spin.setMaximum(1.0)
        self.blending_spin.setSingleStep(0.01)
        self.blending_spin.setValue(0.25)
        self.blending_spin.setMinimumWidth(80)
        self.blending_spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.blending_spin.setCorrectionMode(QAbstractSpinBox.CorrectionMode.CorrectToNearestValue)
        self.blending_spin.valueChanged.connect(self._something_changed)
        mask_layout.addRow("Blending:", self.blending_spin)

        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setSuffix("\u00b0")
        self.angle_spin.setMinimum(-90.0)
        self.angle_spin.setMaximum(90.0)
        self.angle_spin.setValue(40.0)
        self.angle_spin.valueChanged.connect(self._something_changed)
        mask_layout.addRow("Slice angle:", self.angle_spin)

        mask_layout.addRow("Drop shadow:", QLabel(""))
        self.shadow_group = QButtonGroup(self)
        self.shadow_none = QRadioButton("None")
        self.shadow_none.setChecked(True)
        self.shadow_group.addButton(self.shadow_none, 0)
        self.shadow_none.toggled.connect(self._on_shadow_toggled)
        mask_layout.addRow(self.shadow_none)
        self.shadow_forward = QRadioButton("Forward")
        self.shadow_group.addButton(self.shadow_forward, 1)
        self.shadow_forward.toggled.connect(self._something_changed)
        mask_layout.addRow(self.shadow_forward)
        self.shadow_backward = QRadioButton("Backward")
        self.shadow_group.addButton(self.shadow_backward, 2)
        self.shadow_backward.toggled.connect(self._something_changed)
        mask_layout.addRow(self.shadow_backward)

        self.shadow_alpha_spin = QDoubleSpinBox()
        self.shadow_alpha_spin.setMaximum(1.0)
        self.shadow_alpha_spin.setSingleStep(0.02)
        self.shadow_alpha_spin.setValue(0.1)
        self.shadow_alpha_spin.setEnabled(False)
        self.shadow_alpha_spin.valueChanged.connect(self._something_changed)
        mask_layout.addRow("Shadow alpha:", self.shadow_alpha_spin)

        self.reverse_check = QCheckBox("Reverse order")
        self.reverse_check.toggled.connect(self._on_reverse_toggled)
        mask_layout.addRow(self.reverse_check)

        controls_layout.addWidget(mask_group)

        # Section 4: Export
        export_widget = QWidget()
        export_layout = QVBoxLayout(export_widget)
        export_layout.addStretch()
        export_center = QVBoxLayout()
        export_center.setAlignment(Qt.AlignmentFlag.AlignCenter)

        qual_layout = QVBoxLayout()
        qual_label = QLabel("Quality:")
        qual_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qual_layout.addWidget(qual_label)
        quality_row = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(90)
        quality_row.addWidget(self.quality_slider)
        self.quality_value = QLabel("90")
        self.quality_value.setMinimumWidth(30)
        self.quality_slider.valueChanged.connect(lambda v: self.quality_value.setText(str(v)))
        quality_row.addWidget(self.quality_value)
        qual_layout.addLayout(quality_row)
        export_center.addLayout(qual_layout)

        self.progress_label = QLabel()
        font2 = self.progress_label.font()
        font2.setPointSize(10)
        self.progress_label.setFont(font2)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        export_center.addWidget(self.progress_label)

        self.run_button = QPushButton("Export")
        self.run_button.setMinimumSize(90, 40)
        font = self.run_button.font()
        font.setPointSize(12)
        self.run_button.setFont(font)
        self.run_button.clicked.connect(self.on_run)
        export_center.addWidget(self.run_button)

        export_layout.addLayout(export_center)
        export_layout.addStretch()
        controls_layout.addWidget(export_widget)

        self.setStatusBar(QStatusBar(self))

    def _on_shadow_toggled(self):
        self.shadow_alpha_spin.setEnabled(not self.shadow_none.isChecked())
        self._something_changed()

    def _something_changed(self):
        self.update_timer.start()

    def on_add_files(self):
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setNameFilter("Images (*.jpg *.jpeg *.png)")
        if dialog.exec():
            paths = [u.toLocalFile() for u in dialog.selectedUrls()]
            self.add_files(paths)

    def on_add_folder(self):
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        if dialog.exec():
            dir_path = dialog.selectedFiles()[0]
            supported = (".jpg", ".jpeg", ".png")
            entries = []
            for f in sorted(os.listdir(dir_path)):
                if f.lower().endswith(supported):
                    entries.append(os.path.join(dir_path, f))
            self.add_files(entries)

    def add_files(self, path_list):
        supported = {".jpg", ".jpeg", ".png"}
        added = 0
        for path in path_list:
            if os.path.splitext(path)[1].lower() in supported:
                self.images.append(path)
                added += 1
        self.images.sort()
        self._populate_image_list()
        self._something_changed()
        self.statusBar().showMessage(f"{added} new file(s) were added")

    def on_run(self):
        if len(self.images) < 2:
            QMessageBox.critical(self, "Time Slicer", "Too few images!")
            return
        if self.processor.isRunning():
            return
        self._sync_images_from_list()
        self.run_button.setEnabled(False)
        self._export_total = len(self.images)
        self.progress_label.setText("0%")
        self.processor.preview = False
        self.processor.images = self.images
        self.processor.thumbs = []
        self.processor.shadow_mode = "none"
        if self.shadow_forward.isChecked():
            self.processor.shadow_mode = "forward"
        elif self.shadow_backward.isChecked():
            self.processor.shadow_mode = "backward"
        self.processor.shadow_alpha = self.shadow_alpha_spin.value()
        self.processor.start()

    def on_progress(self, i):
        pct = int((i + 1) * 100 / self._export_total)
        self.progress_label.setText(f"{pct}%")

    def on_processor_finished(self):
        self.run_button.setEnabled(True)
        if not self.processor.preview:
            self.progress_label.setText("Done!")
        if self._pending_update:
            self._pending_update = False
            self.update_preview()

    def on_error(self, msg):
        self.progress_label.setText("Error")
        self.statusBar().showMessage(msg)
        QMessageBox.critical(self, "Time Slicer", msg)

    def on_info(self, msg):
        if msg == "Started":
            self.progress_label.setText("0%")
        elif msg == "Done!":
            self.progress_label.setText("Done!")

    def update_preview(self):
        if len(self.images) < 2:
            return
        if self.processor.isRunning():
            if self.processor.preview:
                self.processor.requestInterruption()
                self._pending_update = True
            return
        self._sync_images_from_list()
        self.processor.preview = True
        vp = self.preview_view
        self.preview_wait.move((vp.width() - self.preview_wait.width()) // 2, (vp.height() - self.preview_wait.height()) // 2)
        self.preview_wait.show()
        self.processor.images = self.images
        self.processor.angle = self.angle_spin.value()
        self.processor.reverse = self.reverse_check.isChecked()
        self.processor.blending = self.blending_spin.value()
        self.processor.shadow_mode = "none"
        if self.shadow_forward.isChecked():
            self.processor.shadow_mode = "forward"
        elif self.shadow_backward.isChecked():
            self.processor.shadow_mode = "backward"
        self.processor.shadow_alpha = self.shadow_alpha_spin.value()
        self.processor.start()

    def on_preview_ready(self):
        self.preview_wait.hide()
        pixmap = QPixmap.fromImage(self.processor.preview_image)
        self.preview_item.setPixmap(pixmap)
        self.preview_view.fitInView(self.preview_item, Qt.AspectRatioMode.KeepAspectRatio)

    def _populate_image_list(self):
        self._populating_list = True
        self.image_list.clear()
        paths = list(self.images)
        if self.reverse_check.isChecked():
            paths.reverse()
        for path in paths:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.image_list.addItem(item)
        self._populating_list = False

    def _sync_images_from_list(self):
        paths = []
        for i in range(self.image_list.count()):
            item = self.image_list.item(i)
            paths.append(item.data(Qt.ItemDataRole.UserRole))
        if self.reverse_check.isChecked():
            paths.reverse()
        self.images = paths

    def _on_list_reordered(self):
        if self._populating_list:
            return
        self._sync_images_from_list()
        self.processor.thumbs = []
        self._something_changed()

    def _on_reverse_toggled(self):
        self._populate_image_list()
        self._something_changed()

    def eventFilter(self, obj, event):
        if obj is self.preview_view and event.type() == event.Type.Resize:
            if hasattr(self, 'preview_wait'):
                self.preview_wait.move((self.preview_view.width() - self.preview_wait.width()) // 2, (self.preview_view.height() - self.preview_wait.height()) // 2)
            if self.preview_item.pixmap() and not self.preview_item.pixmap().isNull():
                self.preview_view.fitInView(self.preview_item, Qt.AspectRatioMode.KeepAspectRatio)
        if hasattr(self, 'image_list') and obj is self.image_list.viewport() and event.type() == event.Type.Drop:
            QTimer.singleShot(0, self._on_list_reordered)
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent):
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls()]
            self.add_files(paths)
            event.acceptProposedAction()


if __name__ == "__main__":
    a = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(a.exec())
