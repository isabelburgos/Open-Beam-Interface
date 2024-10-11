import numpy as np
import math
from shapely.geometry import Polygon
from geo_rasterize import rasterize

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QLineEdit, QStyledItemDelegate,
                             QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget, QLabel, QGridLayout, QMenu,
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
        handle.sigClicked.connect(self.mouse)
        super().__init__(*args, **kwargs)
        self.setText(0, "x")
        handle.xChanged.connect(self.display)
    def display(self):
        self.setText(1, f"{self.handle.x()}")
    def mouse(self, ev):
        print("Hello")
        print(ev)
        print(f"{ev.scenePos()=}")
    def doubleClickResponse(self, column):
        if column == 1: #data column
            edit = QSpinBox()
            edit.setRange(0,511)
            edit.setSingleStep(1)
            def moveHandle(x):
                pt = QPointF(x, self.handle.y())
                mappedPt = self.handle.mapToScene(self.handle.mapFromParent(pt))
                self.handle.movePoint(pos=mappedPt, finish=True)
            edit.valueChanged.connect(moveHandle)
            return edit
    def set_handle_pen(self, pen):
        self.handle.pen = pen
        self.handle.currentPen = self.handle.pen
        self.handle.update()
    def selected(self):
        self.set_handle_pen(self.highlight_pen)
        self.parent().selected()
    def unselected(self):
        self.set_handle_pen(roi_style.HANDLE)

class PolygonPointNode(ShapeDataNode):
    highlight_pen = pg.mkPen(color = "#ffffff", width = 8) 
    def __init__(self, handle, num: int, *args, **kwargs):
        self.handle = handle
        handle.sigRemoveRequested.connect(self.remove)
        super().__init__(*args, **kwargs)
        self.setText(0, f"Point {num}")
        self.handle.setToolTip(f"Point {num}")
    def display(self):
        xnode = XCoordNode(self.handle, self)
    def set_handle_pen(self, pen):
        self.handle.pen = pen
        self.handle.currentPen = self.handle.pen
        self.handle.update()
    def selected(self):
        self.set_handle_pen(self.highlight_pen)
        self.parent().selected()
    def unselected(self):
        self.set_handle_pen(roi_style.HANDLE)
    def remove(self):
        p = self.parent()
        p.removeChild(self)
        p.renumerate()

class ROIShapeNode(ShapeDataNode):
    strname = "Shape"
    def __init__(self, roi: pg.ROI, num: int, *args, **kwargs):
        self.roi = roi
        super().__init__(*args, **kwargs)
        self.setText(0, f"{self.strname} {num}")
        self.roi.setToolTip(f"{self.strname} {num}")
    def selected(self):
        self.roi.setMouseHover(True)
        self.roi.requestRasterize()
    def unselected(self):
        self.roi.setMouseHover(False)
        
class PolygonShapeNode(ROIShapeNode):
    strname = "Polygon"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    def display(self):
        # self.takeChildren()
        existing_handles = [self.child(i).handle for i in range(self.childCount())]
        for i, handle in enumerate(self.roi.getHandles()):
            if not handle in existing_handles:
                handlenode = PolygonPointNode(handle, i+1)
                self.insertChild(i, handlenode)
        self.renumerate()
    def renumerate(self):
        for i in range(self.childCount()):
            self.child(i).setText(0, f"Point {i+1}")


class RectShapeNode(ROIShapeNode):
    strname = "Rectangle"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    def display(self):
        size, pos = self.roi.getHandles()
        posnode = QTreeWidgetItem(self)
        posnode.setText(0, "Position")
        posxnode = XCoordNode(pos, posnode)
        sizenode = QTreeWidgetItem(self)
        sizenode.setText(0, "Size")
        sizexnode = XCoordNode(size, sizenode)


class ShapeDataTree(QTreeWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setColumnCount(2)
        self.itemDoubleClicked.connect(self.clickedItem)
        self.currentItemChanged.connect(self.changedItem)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.openMenu)
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
    def openMenu(self, position):
        menu = QMenu()

        indexes = self.selectedIndexes()
        children = []
        for index in indexes:
            child = self.itemFromIndex(index)
            children.append(child)
        print(children)
        node = children[0]
        remove = menu.addAction("Remove")
        if isinstance(node, ROIShapeNode):
            remove.triggered.connect(node.roi._emitRemoveRequest)
        if isinstance(node, PolygonPointNode):
            removeAllowed = all(r.checkRemoveHandle(self) for r in node.handle.rois)
            if removeAllowed:
                remove.triggered.connect(node.handle.removeClicked)
            else:
                remove.setEnabled(False)
        
        menu.exec(self.viewport().mapToGlobal(position))


class PatternTypes(QVBoxLayout):
    sigROIRequested = pyqtSignal(PyQt6.sip.wrappertype) #Ask to place a new ROI on ImageDisplay
    sigRasterizeRequested = pyqtSignal(object)
    node_mapping = {
        PatternPolyLineROI: PolygonShapeNode,
        LiveRectangleROI: RectShapeNode
    }
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

        self.shapes = {
            PatternPolyLineROI: [],
            LiveRectangleROI: []
        }
    
    def emit_ROI(self, roi_class:PyQt6.sip.wrappertype):
        self.sigROIRequested.emit(roi_class)
    
    @Slot(pg.ROI)
    def receive_ROI(self, roi: pg.ROI):
        node = self.create_node(roi)
        self.sigRasterizeRequested.emit(roi)
        roi.sigRegionChanged.connect(self.sigRasterizeRequested)
        roi.sigRasterizeRequested.connect(self.sigRasterizeRequested)
        roi.sigRegionChanged.connect(node.display)

    def create_node(self, roi):
        roitype = type(roi)
        nodes = self.shapes.get(roitype)
        nodetype = self.node_mapping.get(roitype)
        node = nodetype(roi, len(nodes) + 1, self.tree)
        self.shapes.update({roitype:nodes + [node]})
        return node

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