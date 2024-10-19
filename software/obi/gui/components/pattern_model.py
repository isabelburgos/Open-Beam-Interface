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


def buildNode(display, roi, tree):
    def setHandlePos(handle, diff):
        mappedPt = handle.mapToScene(diff)
        handle.movePoint(pos=mappedPt, finish=True)

    def setHandleX(handle,display, x):
        current = display.mapToREALITY(handle)
        diff = QPointF(x-current.x(), 0)
        setHandlePos(handle, diff)
        
    def setHandleY(handle,display, y):
        current = display.mapToREALITY(handle)
        diff = QPointF(0, y-current.y())
        setHandlePos(handle, diff)
    
    def setHandlePen(handle, pen):
        handle.pen = pen
        handle.currentPen = handle.pen
        handle.update()

    def getHandleData(handle, display, *, name, setter, getter, sigChanged):
        return EditableShapeData(
            name = name,
            obj = handle,
            select = lambda handle: setHandlePen(handle, roi_style.HANDLE_HIGHLIGHT),
            deselect = lambda handle: setHandlePen(handle, roi_style.HANDLE),
            setter = setter,
            getter = getter,
            sigChanged = sigChanged,
        )

    def getHandleXdata(handle, display):
        return getHandleData(handle, display,
            name = "x",
            setter = lambda handle, x: setHandleX(handle, display, x),
            getter = lambda handle: display.mapToREALITY(handle).x(),
            sigChanged = handle.xChanged,
        )
    
    def getHandleYdata(handle, display):
        return getHandleData(handle, display,
            name = "y",
            setter = lambda handle, y: setHandleY(handle, display, y),
            getter = lambda handle: display.mapToREALITY(handle).y(),
            sigChanged = handle.yChanged,
        )

    node = ROIDataNode(roi, tree)


@dataclass
class ShapeData:
    name: str
    obj: object
    select: object #function
    deselect: object #function
    def toggleSelected(self, selected:True):
        if selected:
            self.select(self.obj)
        else:
            self.deselect(self.obj)
    @classmethod
    def from_roi(cls, roi):
        name = "Shape"
        if isinstance(roi, LiveRectangleROI):
            name = "Rectangle"
        if isinstance(roi, PatternPolyLineROI):
            name = "Polygon"
        return cls(
            name = name,
            obj = roi, 
            select=lambda roi:roi.requestRasterize(), 
            deselect=lambda roi: print("nothing")) 

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
    def __init__(self, shapedata:ShapeData, *args, **kwargs):
        self.shapedata = shapedata
        super().__init__(*args, **kwargs)
        self.display()
    def display(self):
        self.setText(0, f"{self.shapedata.name}")
    def doubleClickResponse(self, column):
        print("clickclick")
    def selected(self):
        self.shapedata.toggleSelected(True)
    def unselected(self):
        self.shapedata.toggleSelected(False)

class EditableShapeDataNode(ShapeDataNode):
    def __init__(self, shapedata:EditableShapeData, *args, **kwargs):
        super().__init__(shapedata, *args, **kwargs)
        self.shapedata.sigChanged.connect(self.display)
    def display(self):
        super().display()
        self.setText(1, f"{int(self.shapedata.getval())}")
        if hasattr(self, "remove"):
            if self.remove is not None:
                self.remove(self, 1)
                self.remove = None
    def doubleClickResponse(self, column):
        if column == 1: #data column
            edit = QSpinBox()
            # edit.setRange(0,511)
            edit.setSingleStep(1)
            edit.setValue(int(self.shapedata.getval()))
            edit.valueChanged.connect(self.shapedata.setval)
            return edit
    def unselected(self):
        self.display()
        super().unselected()
    def selected(self):
        pass

class HandleDataNode(ShapeDataNode):
    def __init__(self, handleData, node):
        super().__init__(handleData, node)


class HandleData(ShapeData):
    @staticmethod
    def setHandlePen(handle, pen):
        handle.pen = pen
        handle.currentPen = handle.pen
        handle.update()

    @classmethod
    def from_handle(cls, handle, name):
        return cls(
            name = name,
            obj = handle,
            select = lambda handle: self.setHandlePen(handle, roi_style.HANDLE_HIGHLIGHT),
            deselect = lambda handle: self.setHandlePen(handle, roi_style.HANDLE)
            )

class HandleCoordData(EditableShapeData):
    @staticmethod
    def setHandlePos(handle, diff):
        mappedPt = handle.mapToScene(diff)
        handle.movePoint(pos=mappedPt, finish=True)
    @staticmethod
    def setHandleX(handle,display, x):
        current = display.mapToREALITY(handle)
        diff = QPointF(x-current.x(), 0)
        setHandlePos(handle, diff)
    @staticmethod
    def setHandleY(handle,display, y):
        current = display.mapToREALITY(handle)
        diff = QPointF(0, y-current.y())
        setHandlePos(handle, diff)
    
    @staticmethod
    def getHandleData(handle, display, *, name, setter, getter, sigChanged):
        return EditableShapeData(
            name = name,
            obj = handle,
            select = lambda handle: setHandlePen(handle, roi_style.HANDLE_HIGHLIGHT),
            deselect = lambda handle: setHandlePen(handle, roi_style.HANDLE),
            setter = setter,
            getter = getter,
            sigChanged = sigChanged,
        )
    @staticmethod
    def getHandleXdata(handle, display):
        return getHandleData(handle, display,
            name = "x",
            setter = lambda handle, x: setHandleX(handle, display, x),
            getter = lambda handle: display.mapToREALITY(handle).x(),
            sigChanged = handle.xChanged,
        )
    @staticmethod
    def getHandleYdata(handle, display):
        return getHandleData(handle, display,
            name = "y",
            setter = lambda handle, y: setHandleY(handle, display, y),
            getter = lambda handle: display.mapToREALITY(handle).y(),
            sigChanged = handle.yChanged,
        )



class ROIDataNode(ShapeDataNode):
    def __init__(self, roi, tree):
        shapeData = ShapeData.from_roi(roi)
        super().__init__(shapeData, tree)
        self.setup()
    def setup(self):
        roi = self.shapedata.obj
        for i, handle in enumerate(roi.getHandles()):
            handleData = HandleData.from_handle(handle, name = f"Point {i+1}")
            handleNode = HandleDataNode(handleData, self)
            handleXNode = EditableShapeDataNode(HandleCoordData.getHandleXdata(handle, display), handleNode)
            handleYNode = EditableShapeDataNode(HandleCoordData.getHandleYdata(handle, display), handleNode)

    

class ShapeDataTree(QTreeWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setColumnCount(2)
        # self.itemDoubleClicked.connect(self.clickedItem)
        self.itemClicked.connect(self.clickedItem)
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
            self.setItemWidget(itm, column, widget)
            itm.remove = lambda itm, column: self.removeItemWidget(itm, column)


if __name__ == "__main__":
    from .image_display import ImageDisplay
    app = pg.mkQApp()
    rect = LiveRectangleROI(512,512)
    poly = PatternPolyLineROI(512,512)
    tree = ShapeDataTree()
    image_display = ImageDisplay(1024, 1024)
    def setup(roi):
        image_display.setup_roi(roi)
        roi.sigRasterizeRequested.connect(image_display.setOverlay)
        roi.sigRegionChanged.connect(image_display.setOverlay)
        buildNode(image_display, roi, tree)
    setup(rect)
    setup(poly)
    image_display.show()
    tree.show()
    pg.exec()
