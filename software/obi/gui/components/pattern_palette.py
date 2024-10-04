import numpy as np
import math
from shapely.geometry import Polygon
from geo_rasterize import rasterize

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QLineEdit, QStyledItemDelegate,
                             QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QSizePolicy)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot, Qt, QRectF
from PyQt6.QtCore import QPointF
import PyQt6

from .roi import PatternPolyLineROI, LiveRectangleROI, roi_style

from rich import print



class ROITypeButton(QPushButton):
    sigROIRequested = pyqtSignal(PyQt6.sip.wrappertype)
    def __init__(self, name: str, roi_class: pg.ROI):
        super().__init__(name)
        self.roi_class = roi_class
        self.clicked.connect(self.emit_ROI)
    def emit_ROI(self):
        self.sigROIRequested.emit(self.roi_class)

class ShapeDataNode(QTreeWidgetItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.display()
    def doubleClickResponse(self, column):
        print("clickclick")
    def selected(self):
        print("click")
    def unselected(self):
        print("unclick")

class XCoordNode(ShapeDataNode):
    def __init__(self, handle, *args, **kwargs):
        self.handle = handle
        super().__init__(*args, **kwargs)
        self.setText(0, "x")
    def display(self):
        self.setText(1, f"{self.handle.x()}")
    def doubleClickResponse(self, column):
        if column == 1: #data column
            edit = QSpinBox()
            edit.setRange(0,511)
            edit.setSingleStep(1)
            edit.valueChanged.connect(itm.handle.setY)
            self.setItemWidget(itm,column,edit)

class PolygonPointNode(ShapeDataNode):
    def __init__(self, handle, *args, **kwargs):
        self.handle = handle
        super().__init__(*args, **kwargs)
        self.setText(0, "Point")
    def display(self):
        xnode = XCoordNode(self.handle, self)

class PolygonShapeNode(ShapeDataNode):
    def __init__(self, roi: PatternPolyLineROI, *args, **kwargs):
        self.roi = roi
        super().__init__(*args, **kwargs)
        self.setText(0, "Polygon")
    def display(self):
        for i, handle in enumerate(self.roi.getHandles()):
            handlenode = PolygonPointNode(handle, self)


class ShapeDataTree(QTreeWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setColumnCount(2)
        self.itemDoubleClicked.connect(self.clickedItem)
        self.currentItemChanged.connect(self.changedItem)
    def changedItem(self, current, previous):
        print(f"changed, {current=}, {previous=}")
        if previous is not None:
            previous.unselected()
        if current is not None:
            current.selected()
    def clickedItem(self, itm, column):
        print(f"clicked {itm=}, {column=}")
        itm.doubleClickResponse(column)


class PatternTypes(QVBoxLayout):
    sigROIRequested = pyqtSignal(PyQt6.sip.wrappertype) #Ask to place a new ROI on ImageDisplay
    sigRasterizeRequested = pyqtSignal(pg.ROI)
    def __init__(self):
        super().__init__()
        # self.trees = QVBoxLayout()
        # self.trees.addWidget(QLabel("Patterns"))
        self.tree = ShapeDataTree()

        btns = QHBoxLayout()
        self.addLayout(btns)
        def add(btn:ROITypeButton):
            btns.addWidget(btn)
            btn.sigROIRequested.connect(self.emit_ROI)
        
        add(ROITypeButton("Rectangle", LiveRectangleROI))
        add(ROITypeButton("Polygon", PatternPolyLineROI))
        self.addWidget(self.tree)
    
    def emit_ROI(self, roi_class:PyQt6.sip.wrappertype):
        self.sigROIRequested.emit(roi_class)
    
    @Slot(pg.ROI)
    def receive_ROI(self, roi: pg.ROI):
        node = PolygonShapeNode(roi, self.tree)
        p =  QStyledItemDelegate()
        node.setItemDelegate(p)
        
        # w = QWidget()
        # w.setLayout(panel)
        # pp = QTreeWidgetItem(poly)
        # pp.setExpanded(True)
        # self.trees.setHeaderItem(poly)
        # self.trees.setItemWidget(pp, 0, w)
        # # self.addLayout(panel)
        # panel.sigRasterizeRequested.connect(self.sigRasterizeRequested)
        self.sigRasterizeRequested.emit(roi)

    def connect(self, display): #ImageDisplay
        self.sigROIRequested.connect(display.addROI)
        display.sigROIAdded.connect(self.receive_ROI)
        self.sigRasterizeRequested.connect(display.setOverlay)



if __name__ == "__main__":
    from .image_display import ImageDisplay
    app = pg.mkQApp()
    v = ImageDisplay(512,512)
    p = PatternTypes()
    p.connect(v)
    p.addWidget(v)
    w = QWidget()
    w.setLayout(p)
    w.show()
    pg.exec()