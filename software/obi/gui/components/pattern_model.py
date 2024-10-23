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
        if not (self.shapedata.name == "x") | (self.shapedata.name == "y"): 
            #don't label points w just x and y
            self.shapedata.obj.setToolTip(f"{self.shapedata.name}")
    def clickResponse(self, column):
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
        if hasattr(self, "remove"): ## callback to QTreeWidget.removeItemWidget
            if self.remove is not None:
                self.remove(self, 1)
                self.remove = None
    def clickResponse(self, column):
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
            select = lambda handle: HandleData.setHandlePen(handle, roi_style.HANDLE_HIGHLIGHT),
            deselect = lambda handle: HandleData.setHandlePen(handle, roi_style.HANDLE),
            setter = setter,
            getter = getter,
            sigChanged = sigChanged,
        )
    @staticmethod
    def getHandleXdata(handle, display):
        return HandleCoordData.getHandleData(handle, display,
            name = "x",
            setter = lambda handle, x: HandleCoordData.setHandleX(handle, display, x),
            getter = lambda handle: display.mapToREALITY(handle).x(),
            sigChanged = handle.xChanged,
        )
    @staticmethod
    def getHandleYdata(handle, display):
        return HandleCoordData.getHandleData(handle, display,
            name = "y",
            setter = lambda handle, y: HandleCoordData.setHandleY(handle, display, y),
            getter = lambda handle: display.mapToREALITY(handle).y(),
            sigChanged = handle.yChanged,
        )



class ROIDataNode(ShapeDataNode):
    def __init__(self, roi, tree):
        shapeData = ShapeData.from_roi(roi)
        super().__init__(shapeData, tree)
        self.current_handles = {}
        self.setup()
        roi.sigRegionChanged.connect(self.setup)
    def setup(self):
        roi = self.shapedata.obj
        changed = False
        for i, handle in enumerate(roi.getHandles()):
            if not handle in self.current_handles.keys():
                handleData = HandleData.from_handle(handle, name = f"Point {i+1}")
                handleNode = ShapeDataNode(handleData)
                self.current_handles.update({handle:handleNode})
                handleXNode = EditableShapeDataNode(HandleCoordData.getHandleXdata(handle, roi.display), handleNode)
                handleYNode = EditableShapeDataNode(HandleCoordData.getHandleYdata(handle, roi.display), handleNode)
                def remove():
                    self.takeChild(i)
                handle.sigRemoveRequested.connect(remove)
                self.insertChild(i, handleNode)
                changed = True
        if changed:
            self.renumerate()
    def renumerate(self):
        for i in range(self.childCount()):
            self.child(i).setText(0, f"Point {i+1}")
    

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
        widget = itm.clickResponse(column)
        if isinstance(widget, QWidget): #response could be None
            self.setItemWidget(itm, column, widget)
            itm.remove = lambda itm, column: self.removeItemWidget(itm, column)
    def addROI(self, roi):
        node = ROIDataNode(roi, self)
        def remove():
            self.invisibleRootItem().removeChild(node)
        roi.sigRemoveRequested.connect(remove)


class ShapePalette(QVBoxLayout):
    def __init__(self):
        super().__init__()
        self.rect_btn = QPushButton("Rectangle")
        self.poly_btn = QPushButton("Polygon")
        self.tree = ShapeDataTree()

        shapes = QHBoxLayout()
        shapes.addWidget(self.rect_btn)
        shapes.addWidget(self.poly_btn)
        self.addLayout(shapes)
        self.addWidget(self.tree)


if __name__ == "__main__":
    from .image_display import ImageDisplay
    app = pg.mkQApp()
    rect = LiveRectangleROI(512,512)
    poly = PatternPolyLineROI(512,512)
    palette = ShapePalette()
    image_display = ImageDisplay(1024, 1024)
    def setup(roi):
        image_display.setup_roi(roi)
        palette.tree.addROI(roi)
        roi.sigRasterizeRequested.connect(image_display.setOverlay)
        roi.sigRegionChanged.connect(image_display.setOverlay)
        
    setup(rect)
    setup(poly)
    image_display.show()
    w = QWidget()
    w.setLayout(palette)
    w.show()
    pg.exec()
