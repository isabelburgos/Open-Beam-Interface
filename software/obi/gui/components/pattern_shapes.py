import numpy as np
import math
from shapely.geometry import Polygon
from geo_rasterize import rasterize

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow,
                             QMessageBox, QPushButton,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QSizePolicy)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot, Qt, QRectF
from PyQt6.QtCore import QPointF
import PyQt6

from .roi import PatternPolyLineROI, LiveRectangleROI

class ROITypeButton(QPushButton):
    sigROIRequested = pyqtSignal(PyQt6.sip.wrappertype)
    def __init__(self, name: str, roi_class: pg.ROI):
        super().__init__(name)
        self.roi_class = roi_class
        self.clicked.connect(self.emit_ROI)
    def emit_ROI(self):
        self.sigROIRequested.emit(self.roi_class)

class PatternTypes(QHBoxLayout):
    sigROIRequested = pyqtSignal(PyQt6.sip.wrappertype)
    sigROIAdded = pyqtSignal(pg.ROI)
    def __init__(self):
        super().__init__()
        self.tree = pg.DataTreeWidget()
        self.sigROIAdded.connect(self.recieve_ROI)

        def add(btn:ROITypeButton):
            self.addWidget(btn)
            btn.sigROIRequested.connect(self.emit_ROI)
        
        add(ROITypeButton("Rectangle", LiveRectangleROI))
        add(ROITypeButton("Polygon", PatternPolyLineROI))
        self.addWidget(self.tree)
    
    def emit_ROI(self, roi_class:PyQt6.sip.wrappertype):
        self.sigROIRequested.emit(roi_class)
        self.fakeadd(roi_class)
    
    def recieve_ROI(self, roi: pg.ROI):
        self.tree.setData(roi)
    
    def fakeadd(self, roi_class:PyQt6.sip.wrappertype):
        roi = roi_class(512, 512)
        self.sigROIAdded.emit(roi)

if __name__ == "__main__":
    app = pg.mkQApp()
    w = QWidget()
    w.setLayout(PatternTypes())
    w.show()
    pg.exec()