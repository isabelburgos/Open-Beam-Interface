import numpy as np
import math
from shapely.geometry import Polygon
from geo_rasterize import rasterize

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QLineEdit,
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


# class CoordNode(QTreeWidgetItem):
#     def __init__(self, handle, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.handle = handle

# class XCoordNode(CoordNode):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.setText(0, "x")
#         self.updateField()
#         self.handle.xChanged.connect(self.updateField)
#     def updatePoint(self, value):
#         self.handle.setX(value)
#     def updateField(self):
#         self.setText(1, f"{self.handle.pos().x()}")

# class YCoordNode(CoordNode):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.setText(0, "y")
#         self.updateField()
#         self.handle.yChanged.connect(self.updateField)
#     def updatePoint(self, value):
#         self.handle.setY(value)
#     def updateField(self):
#         self.setText(1, f"{self.handle.pos().y()}")

class CoordDataTree(QTreeWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setColumnCount(3)
        self.setHeaderLabels(("ID", "x", "y"))
        self.itemDoubleClicked.connect(self.editItem)
        self.currentItemChanged.connect(self.highlightItem)
    def highlightItem(self,current, previous):
        print("highlight")
        highlight_pen = pg.mkPen(color = "#ffffff", width = 8) 
        def set_pen(handle, pen):
            handle.pen = pen
            handle.currentPen = handle.pen
            handle.update()
        if current is not None:
            set_pen(current.handle, highlight_pen)
        if previous is not None:
            if current.handle != previous.handle:
                set_pen(previous.handle, roi_style.HANDLE)
    def editItem(self, itm, column):
        if column > 0:
            edit = QSpinBox()
            edit.setRange(0,511)
            edit.setSingleStep(1)
            if column == 1: #x:
                edit.valueChanged.connect(itm.handle.setX)
            if column == 2: #y
                edit.valueChanged.connect(itm.handle.setY)
            self.setItemWidget(itm,column,edit)
        # if isinstance(itm, CoordNode):
        #     edit = QSpinBox()
        #     edit.setRange(0,511)
        #     edit.setSingleStep(1)
        #     edit.valueChanged.connect(itm.updatePoint)
        #     self.setItemWidget(itm,column,edit)



class PolygonROIPanel(QVBoxLayout):
    sigRasterizeRequested = pyqtSignal(pg.ROI)
    def __init__(self, roi:PatternPolyLineROI):
        super().__init__()
        self.roi = roi
        self.data = CoordDataTree()
        self.display()
        self.addWidget(self.data)
        self.roi.sigRegionChanged.connect(self.check_update_points)
    def display(self):
        self.data.clear()
        for i, handle in enumerate(self.roi.getHandles()):
            point = QTreeWidgetItem(self.data)
            point.handle = handle
            point.setText(0, f"Point {i+1}")
            point.setText(1, f"{handle.x()}")
            point.setText(2, f"{handle.y()}")
            handle.xChanged.connect(self.rasterize)
            handle.yChanged.connect(self.rasterize)
            # point = QTreeWidgetItem(self.data)
            # point.handle = handle
            # point.setText(0, f"Point {i+1}")
            # x_coord = XCoordNode(handle, point)
            # y_coord = YCoordNode(handle, point)
    def check_update_points(self):
        self.rasterize()
        if len(self.roi.getHandles()) != self.data.topLevelItemCount():
            self.display()
    def rasterize(self):
        self.sigRasterizeRequested.emit(self.roi)


class PROIPanel(QTreeWidgetItem):
    def __init__(self, roi:PatternPolyLineROI):
        super().__init__()
        self.roi = roi
        self.display()
        self.roi.sigRegionChanged.connect(self.check_update_points)
    def display(self):
        # self.data.clear()
        for i, handle in enumerate(self.roi.getHandles()):
            handle.xChanged.connect(self.rasterize)
            handle.yChanged.connect(self.rasterize)
            point = QTreeWidgetItem(self.data)
            point.handle = handle
            point.setText(0, f"Point {i+1}")
            x_coord = XCoordNode(handle, point)
            y_coord = YCoordNode(handle, point)
    def check_update_points(self):
        self.rasterize()
        if len(self.roi.getHandles()) != self.data.topLevelItemCount():
            self.display()
    def rasterize(self):
        self.sigRasterizeRequested.emit(self.roi)

class PatternTypes(QVBoxLayout):
    sigROIRequested = pyqtSignal(PyQt6.sip.wrappertype) #Ask to place a new ROI on ImageDisplay
    sigRasterizeRequested = pyqtSignal(pg.ROI)
    def __init__(self):
        super().__init__()
        # self.trees = QVBoxLayout()
        # self.trees.addWidget(QLabel("Patterns"))
        self.trees = QTreeWidget()

        btns = QHBoxLayout()
        self.addLayout(btns)
        def add(btn:ROITypeButton):
            btns.addWidget(btn)
            btn.sigROIRequested.connect(self.emit_ROI)
        
        add(ROITypeButton("Rectangle", LiveRectangleROI))
        add(ROITypeButton("Polygon", PatternPolyLineROI))
        self.addWidget(self.trees)
    
    def emit_ROI(self, roi_class:PyQt6.sip.wrappertype):
        self.sigROIRequested.emit(roi_class)
    
    @Slot(pg.ROI)
    def receive_ROI(self, roi: pg.ROI):
        poly = QTreeWidgetItem(self.trees)
        poly.setText(0, "Polygon")
        poly.setExpanded(True)
        panel = PolygonROIPanel(roi)
        panel.sigRasterizeRequested.connect(self.sigRasterizeRequested)
        w = QWidget()
        w.setLayout(panel)
        pp = QTreeWidgetItem(poly)
        pp.setExpanded(True)
        self.trees.setHeaderItem(poly)
        self.trees.setItemWidget(pp, 0, w)
        # self.addLayout(panel)
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