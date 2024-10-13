from dataclasses import dataclass
import numpy as np
import math
from shapely.geometry import Polygon
from geo_rasterize import rasterize

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QLineEdit, QStyledItemDelegate,
                             QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget, QLabel, QGridLayout, QTreeView,
                             QSpinBox, QSizePolicy)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot, Qt, QRectF
from PyQt6.QtCore import QPointF, QAbstractItemModel
import PyQt6

from .roi import PatternPolyLineROI, LiveRectangleROI, roi_style

from rich import print


def setHandleX(handle,display, x):
    current = display.mapToREALITY(handle)
    diff = QPointF(x-current.x(), 0)
    mappedPt = handle.mapToScene(diff)
    handle.movePoint(pos=mappedPt, finish=True)

def setPosHandleX(handle, display, rect, x):
    current = display.mapToREALITY(handle)
    rect.translate(x - current.x(),0)

def getHandleXdata(handle, display):
    return EditableShapeData(
        name = "x",
        obj = handle,
        setter = lambda handle, x: setHandleX(handle, display, x),
        getter = lambda handle: display.mapToREALITY(handle).x(),
        sigChanged = handle.xChanged
    )

def getPosHandleXdata(handle, display, rect):
    return EditableShapeData(
        name = "x",
        obj = handle,
        setter = lambda handle, x: setPosHandleX(handle, display, rect, x),
        getter = lambda handle: display.mapToREALITY(handle).x(),
        sigChanged = handle.xChanged
    )


def buildRectNode(display, rect, tree):
    sizeHandle, posHandle = rect.getHandles()[0], rect.getHandles()[1]

    sizeHandleData = ShapeData(
            name = "Size",
            obj = sizeHandle,
        ) 
    
    posHandleData = ShapeData(
            name = "Pos",
            obj = posHandle,
        ) 

    def getShapeData(rect):
        return ShapeData(
            name = "Rectangle",
            obj = rect,
        ) 
    node = ShapeDataNode(getShapeData(rect), tree)
    sizeNode = ShapeDataNode(sizeHandleData, node)
    sizeXNode = EditableShapeDataNode(getHandleXdata(sizeHandle,display), sizeNode)
    posNode = ShapeDataNode(posHandleData, node)
    posXNode = EditableShapeDataNode(getHandleXdata(posHandle,display), posNode)


def buildPolyNode(display, polygon, tree):
    shapeData = ShapeData(
            name = "Polygon",
            obj = polygon,
        ) 
    
    node = ShapeDataNode(shapeData, tree)

    for i, handle in enumerate(polygon.getHandles()):
        handleData = ShapeData(
            name = f"Point {i+1}",
            obj = handle
        )
        handleNode = ShapeDataNode(handleData, node)
        handleXNode = EditableShapeDataNode(getHandleXdata(handle, display), handleNode)

def buildNode(display, roi, tree):
    if isinstance(roi, LiveRectangleROI):
        buildRectNode(display, roi, tree)
    if isinstance(roi, PatternPolyLineROI):
        buildPolyNode(display, roi, tree)


@dataclass
class ShapeData:
    name: str
    obj: object

@dataclass
class EditableShapeData(ShapeData):
    setter: object #function
    getter: object #function
    sigChanged: pyqtSignal(object)
    def getval(self):
        return self.getter(self.obj)
    def setval(self, val:int):
        self.setter(self.obj, val)

class ShapeDataNode(QTreeWidgetItem):
    sigRequestSetWidget = pyqtSignal(QTreeWidgetItem, int, QWidget)
    def __init__(self, shapedata:ShapeData, *args, **kwargs):
        self.shapedata = shapedata
        super().__init__(*args, **kwargs)
        self.display()
    def display(self):
        self.setText(0, f"{self.shapedata.name}")
    def doubleClickResponse(self, column):
        print("clickclick")
    def selected(self):
        print("click")
    def unselected(self):
        print("unclick")


class EditableShapeDataNode(ShapeDataNode):
    def __init__(self, shapedata:EditableShapeData, *args, **kwargs):
        super().__init__(shapedata, *args, **kwargs)
        self.shapedata.sigChanged.connect(self.display)
    def display(self):
        super().display()
        self.setText(1, f"{self.shapedata.getval()}")
    def doubleClickResponse(self, column):
        if column == 1: #data column
            edit = QSpinBox()
            edit.setRange(0,511)
            edit.setSingleStep(1)
            def update():
                edit.setValue(int(self.shapedata.getval()))
            update()
            edit.valueChanged.connect(self.shapedata.setval)
            # self.shapedata.sigChanged.connect(update)
            return edit

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


if __name__ == "__main__":
    from .image_display import ImageDisplay
    app = pg.mkQApp()
    rect = LiveRectangleROI(512,512)
    poly = PatternPolyLineROI(512,512)
    tree = ShapeDataTree()
    image_display = ImageDisplay(1024, 1024)
    def setup(roi):
        image_display.setup_roi(roi)
        roi.maxBounds=None
        buildNode(image_display, roi, tree)
    setup(rect)
    setup(poly)
    image_display.show()
    tree.show()
    pg.exec()
