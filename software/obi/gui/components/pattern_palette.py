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
    sigRequestSetWidget = pyqtSignal(QTreeWidgetItem, int, QWidget)
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
    highlight_pen = pg.mkPen(color = "#ffffff", width = 8) 
    def __init__(self, handle, *args, **kwargs):
        self.handle = handle
        super().__init__(*args, **kwargs)
        self.setText(0, "x")
        handle.xChanged.connect(self.display)
    def display(self):
        self.setText(1, f"{self.handle.x()}")
    def doubleClickResponse(self, column):
        if column == 1: #data column
            edit = QSpinBox()
            edit.setRange(0,511)
            edit.setSingleStep(1)
            def moveHandle(x):
                print(dir(self.handle))
                print(f"{self.handle.pos()=}")
                print(f"{self.handle.scenePos()=}")
                print(f"{self.handle.viewPos()=}")
                # self.handle.movePoint((self.handle.scenePos().y(), x), finish=True)
                self.handle.setX(x)
            edit.valueChanged.connect(moveHandle)
            return edit
    def set_handle_pen(self, pen):
        self.handle.pen = pen
        self.handle.currentPen = self.handle.pen
        self.handle.update()
    def selected(self):
        self.set_handle_pen(self.highlight_pen)
    def unselected(self):
        self.set_handle_pen(roi_styles.HANDLE)



class PolygonPointNode(ShapeDataNode):
    highlight_pen = pg.mkPen(color = "#ffffff", width = 8) 
    def __init__(self, handle, num: int, *args, **kwargs):
        self.handle = handle
        super().__init__(*args, **kwargs)
        self.setText(0, f"Point {num}")
    def display(self):
        xnode = XCoordNode(self.handle, self)
    def set_handle_pen(self, pen):
        self.handle.pen = pen
        self.handle.currentPen = self.handle.pen
        self.handle.update()
    def selected(self):
        self.set_handle_pen(self.highlight_pen)
    def unselected(self):
        self.set_handle_pen(roi_styles.HANDLE)

class PolygonShapeNode(ShapeDataNode):
    def __init__(self, roi: PatternPolyLineROI, *args, **kwargs):
        self.roi = roi
        super().__init__(*args, **kwargs)
        self.setText(0, "Polygon")
    def display(self):
        # self.takeChildren()
        #existing_handles = [self.child(i).handle for i in range(self.childCount())]
        for i, handle in enumerate(self.roi.getHandles()):
            #if not handle in existing_handles:
            handlenode = PolygonPointNode(handle, i+1, self)

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
        widget = itm.doubleClickResponse(column)
        if isinstance(widget, QWidget): #response could be None
            self.setItemWidget(itm,column,widget)


class PatternTypes(QVBoxLayout):
    sigROIRequested = pyqtSignal(PyQt6.sip.wrappertype) #Ask to place a new ROI on ImageDisplay
    sigRasterizeRequested = pyqtSignal(object)
    def __init__(self):
        super().__init__()
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
        print(dir(node))
        self.sigRasterizeRequested.emit(roi)
        roi.sigRegionChanged.connect(self.sigRasterizeRequested)
        roi.sigRegionChanged.connect(node.display)

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