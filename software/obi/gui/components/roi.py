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
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot, Qt, QRectF, QSizeF
from PyQt6.QtCore import QPointF


class roi_style:
    BORDER = pg.mkPen(color = "#00ff00", width = 2)
    BORDER_HOVER = pg.mkPen(color = "#00ff00", width = 4)
    HANDLE = pg.mkPen(color = "#00ff00", width = 5)
    HANDLE_HOVER = pg.mkPen(color = "#00ff00", width = 8) 

class MeasureLine(pg.LineSegmentROI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs,
        pen = roi_style.BORDER,
        handlePen = roi_style.HANDLE)
    @staticmethod
    def parse_points(points):
        x1 = points[0][1].x()
        y1 = points[0][1].y()
        x2 = points[1][1].x()
        y2 = points[1][1].y()
        return (x1, y1), (x2, y2)
    @property
    def local_endpoints(self):
        points = self.getLocalHandlePositions()
        return self.parse_points(points)
    @property
    def scene_endpoints(self):
        points = self.getSceneHandlePositions()
        return self.parse_points(points)
    @staticmethod
    def length_angle(p1, p2):
        d = math.sqrt(pow(p1[0] - p2[0],2) + pow(p1[1] - p2[1],2))
        if p2[0] != p1[0]:
            m = (p2[1] - p1[1])/(p2[0] - p1[0])
            a = math.degrees(math.atan(m))
        else:
            a = 0
        return d, a


class ParallelMeasureLines(pg.GraphicsObject):
    sigRegionChanged = pyqtSignal(float)
    def __init__(self, x_width, y_height):
        super().__init__()
        start  = [.25*x_width, .25*y_height]
        end = [start[0] + .25*x_width, start[1]]

        self.lines = pg.LinearRegionItem(values=(start[0], end[0]), movable=False)
        self.lines.setParentItem(self)
        self.line = MeasureLine(positions = (start,end))
        self.line.setParentItem(self)

        self.line.sigRegionChanged.connect(self.fn)

    def fn(self):
        ## TODO: make this more straightforward with QTransforms
        p1, p2 = self.line.local_endpoints
        d, a = self.line.length_angle(p1, p2)

        s1, s2 = self.line.scene_endpoints
        image_view = self.parentItem().parentItem()
        tr = image_view.mapViewToScene(QPointF(0,0))
        tx, ty = tr.x(), tr.y()
        tr_s1 = [s1[0]-tx, s1[1]-ty]
        tr_s2 = [s2[0]-tx, s2[1]-ty]

        d_s, a_s = self.line.length_angle(s1, s2)
        scale = d/d_s
        tr_s_s1 = [tr_s1[0]*scale, tr_s1[1]*scale]
        tr_s_s2 = [tr_s2[0]*scale, tr_s2[1]*scale]

        p1, p2 = tr_s_s1, tr_s_s2

        self.lines.setTransformOriginPoint(*p1)
        self.lines.setRotation(a)

        # map to the coordinate system of the linear region
        if p2[0] >= p1[0]:
            p_rot = [p1[0] + d, p1[1]]
        elif p2[0] < p1[0]: # if the lines are swapped
            p_rot = [p1[0] - d, p1[1]]
        
        self.lines.setRegion([p1, p_rot])
        self.sigRegionChanged.emit(d)

class LiveRectangleROI(pg.ROI):
    def __init__(self, x_width, y_height):
        super().__init__(
            [int(.25*x_width), int(.25*y_height)], #upper left corner
            [int(.5*x_width), int(.5*y_height)], #size
            pen = roi_style.BORDER, 
            hoverPen = roi_style.BORDER_HOVER, 
            handlePen=roi_style.HANDLE,
            handleHoverPen=roi_style.HANDLE_HOVER,
            scaleSnap = True, 
            translateSnap = True,
            maxBounds = QtCore.QRectF(0, 0, x_width, y_height)
        )
        self.addScaleHandle([1, 1], [0, 0])
        self.addScaleHandle([0, 0], [1, 1])

    def getbounds(self, x_width, y_height):
        return QtCore.QRectF(0, 0, x_width, y_height)


class PatternPolyLineROI(pg.PolyLineROI):
    sigRasterizeRequested = pyqtSignal(object) #see self.requestRasterize()
    def __init__(self, x_width, y_height):
        ul = [int(.25*x_width), int(.25*y_height)]
        size = [int(.5*x_width), int(.5*y_height)]
        super().__init__(
            [
                ul, ## upper left
                [ul[0]+size[0], ul[1]], ## upper right
                [ul[0]+size[0], ul[1] + size[1]], #lower right
                [ul[0], ul[1]+size[1]] #lower left
            ],
            pen = roi_style.BORDER, 
            hoverPen = roi_style.BORDER_HOVER, 
            handlePen=roi_style.HANDLE, 
            handleHoverPen=roi_style.HANDLE_HOVER, 
            scaleSnap = True, 
            translateSnap = True, 
            closed=True,
            removable=True
        )

    def getbounds(self, x_width, y_height):
        ## TODO: why is the coordinate system like this?
        return QtCore.QRectF(0, 0, x_width, y_height)

    def stateRect(self, state):
        minX, minY, maxX, maxY = Polygon(self.asPoints(state['pos'])).bounds
        ## remember, y axis is inverted and starts at the top, x axis starts at the left
        topLeft = QPointF(minX, minY)
        bottomRight = QPointF(maxX, maxY)
        return QRectF(topLeft, bottomRight)

    def checkPointMove(self, handle, pos, modifiers):
        if not Polygon(self.asPoints()).is_simple:
            handle.sigRemoveRequested.emit(handle)
        if self.maxBounds is not None:
            if not self.maxBounds.contains(self.mapFromScene(pos)):
                return False
        # something with this doesn't work quite right
        # remove the handle if the move is out of line
        # otherwise, the handle gets "stuck"
        return True
    
    def asPoints(self, pos=None): ## halfway deprecated...
        if pos == None:
            pos = self.pos()
        ox, oy = pos.x(), pos.y()
        # ox, oy = 0,0
        handles = self.getHandles()
        points = []
        for handle in handles:
            pos = handle.pos()
            points.append((pos.x()+ox, pos.y()+oy))
        return points
    
    def absolutePoints(self, display): #ImageDisplay
        positions = [display.mapToREALITY(handle) for handle in self.getHandles()] # [QPoint]
        coords = [(pos.x(), pos.y()) for pos in positions] # [(x: int, y:int)]
        return coords

    def rasterize(self, display) -> np.ndarray:
        polygon = Polygon(self.absolutePoints(display))
        return rasterize([polygon], [255], (display.x_width, display.y_height), dtype='uint8')
    
    def requestRasterize(self):
        #workaround to let QTreeWidgetItem trigger this signal when a shape node is clicked
        self.sigRasterizeRequested.emit(self)
    