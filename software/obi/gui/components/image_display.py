import datetime
import logging
import math

import numpy as np
import pyqtgraph as pg
from pyqtgraph.exporters import Exporter
from pyqtgraph.Qt import QtCore
from pyqtgraph.graphicsItems.TextItem import TextItem

import PyQt6
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow,
                             QMessageBox, QPushButton,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QSizePolicy)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot, Qt, QRectF

logger = logging.getLogger()

from PyQt6.QtCore import QPointF
from PyQt6 import QtGui

from rich import print

from .roi import LiveRectangleROI, PatternPolyLineROI, MeasureLine, ParallelMeasureLines


class ImageDisplay(pg.GraphicsLayoutWidget):
    _logger = logger.getChild("ImageDisplay")
    sigResolutionChanged = pyqtSignal(tuple)
    sigROIAdded = pyqtSignal(pg.ROI)
    def __init__(self, y_height, x_width, invertY=True, invertX=False):
        super().__init__()
        self.y_height = y_height
        self.x_width = x_width

        self.image_view = self.addViewBox(invertY = invertY, invertX=invertX)
        ## lock the aspect ratio so pixels are always square
        self.image_view.setAspectLocked(True)
        
        self.live_img = pg.ImageItem(border='w',axisOrder="row-major")
        self.live_img.setImage(np.full((y_height, x_width), 0, np.uint8), rect = (0,0,x_width, y_height), autoLevels=False, autoHistogramRange=True)
        self.image_view.addItem(self.live_img)

        self.overlay = pg.ImageItem(border='w',axisOrder="row-major")
        self.overlay.setOpacity(0.3)
        self.overlay.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)
        self.image_view.addItem(self.overlay)
        
        self.data = np.zeros(shape = (y_height, x_width))

        # Contrast/color control
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.live_img)
        #self.hist.disableAutoHistogramRange()
        self.addItem(self.hist)

        self.hist.setLevels(min=0,max=255)

        self.roi = None
        self.rois = []
        self.line = None
        self.measure_lines = ParallelMeasureLines(512, 512)

        ### reverse the default LUT
        # lut = []
        # for n in range(0, 256):
        #     lut.append([255-n,255-n,255-n])
        
        # lut = np.array(lut, dtype = np.uint8)
        # self.live_img.setLookupTable(lut)

        def show_all_maps(point):
            print(f"point = {point!r}")
            print(f"mapToView: {self.image_view.mapToView(point)}")
            print(f"mapFromView: {self.image_view.mapFromView(point)}")
            print(f"mapSceneToView: {self.image_view.mapSceneToView(point)}")
            print(f"mapViewToScene: {self.image_view.mapViewToScene(point)}")
            print(f"mapDeviceToView: {self.image_view.mapDeviceToView(point)}")
            print(f"mapViewToDevice: {self.image_view.mapViewToDevice(point)}")
            print("\n")
    
        #self.fitInView(QRectF(0,0,1,self.aspect), Qt.AspectRatioMode.KeepAspectRatio)
        #self.ensureVisible(self.live_img, xMargin=10, yMargin=20)
        
        
    @property
    def aspect(self):
        hint = super().sizeHint()
        height, width = hint.height(), hint.width()
        maxsize = max(height, width)
        histsize = self.hist.size()
        h_height, h_width = histsize.height(), histsize.width()
        return width/(width-h_width)

    def sizeHint(self):
        hint = super().sizeHint()
        height, width = hint.height(), hint.width()
        maxsize = max(height, width)
        return QtCore.QSize(int(maxsize*self.aspect), maxsize)
    def sizePolicy(self):
        policy = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum)
        policy.setWidthForHeight(True)
        return policy
    
    def setup_roi(self, roi:pg.ROI):
        self.rois.append(roi)
        self.image_view.addItem(roi)
        roi.maxBounds = QtCore.QRectF(0, 0, self.x_width, self.y_height)
        roi.setZValue(10)  # make sure ROI is drawn above image
        self.sigROIAdded.emit(roi)
    
    def mapToREALITY(self, obj): #absolute position in frame coordinates, which correspond to real scan pixels
        return self.live_img.mapFromScene(obj.scenePos())
    
    @Slot(PyQt6.sip.wrappertype)
    def addROI(self, roi_class):
        roi = roi_class(self.x_width, self.y_height)
        self.setup_roi(roi)

    def add_ROI(self):
        # Custom ROI for selecting an image region
        self.roi = LiveRectangleROI(self.x_width, self.y_height)
        self.setup_roi(self.roi)
    
    def add_image_ROI(self):
        from PIL import Image
        im = Image.open("/Users/isabelburgos/Open-Beam-Interface/software/obi/support/nanographs_logo.bmp")
        image_arr = np.asarray(im)
        self.add_ROI()
        self.img = pg.ImageItem(image_arr)
        self.img.setParentItem(self.roi)
    
    def add_polyline_ROI(self):
        roi = PatternPolyLineROI(self.x_width, self.y_height)
        self.setup_roi(roi)

    def add_line(self, start=None, end=None):
        if start == None:
            start  = [.25*self.x_width, .25*self.y_height]
        if end == None:
            end = [start[0] + .25*self.x_width, start[1]]
        border = pg.mkPen(color = "#00ff00", width = 2)
        self.line = pg.LineSegmentROI(positions = (start,end),
                        pen = border, handlePen=border,)
        self.image_view.addItem(self.line)
        self.line.setZValue(10)  # make sure line is drawn above image
    
    def add_double_lines(self):
        self.image_view.addItem(self.measure_lines)
        self.measure_lines.fn()
    
    def remove_double_lines(self):
        self.image_view.removeItem(self.measure_lines)
    
    @Slot(bool)
    def toggle_double_lines(self, enable:bool):
        if enable:
            self.add_double_lines()
        else:
            self.remove_double_lines()


    def remove_line(self):
        if not self.line == None:
            self.image_view.removeItem(self.line)
            self.line = None
    
    def get_line_length(self):
        # the pos() and size() functions for LinearROIRegion do not work
        p1, p2 = [point.pos() for point in self.line.endpoints]
        d = math.sqrt(pow(p1[0] - p2[0],2) + pow(p1[1] - p2[1],2))
        return d

    def remove_ROI(self):
        if not self.roi == None:
            self.image_view.removeItem(self.roi)
            self.roi = None

    def get_ROI(self):
        x_start, y_start = self.roi.pos() ## upper left corner
        x_count, y_count = self.roi.size()
        return int(x_start), int(x_count), int(y_start), int(y_count)
        
    def setOverlay(self, roi:pg.ROI):
        image = roi.rasterize(self)
        self.overlay.setImage(image)

    def setImage(self, image: np.array(np.uint8)):
        ## image must be 2D np.array of np.uint8
        y_height, x_width = image.shape
        self.live_img.setImage(image, rect = (0,0, x_width, y_height), autoLevels=False)
        self.setRange(y_height, x_width)
        self.data = image
        
    def setRange(self, y_height, x_width):
        if (x_width != self.x_width) | (y_height != self.y_height):
            if not self.roi == None:
                self.roi.maxBounds = self.roi.getbounds(self.x_width, self.y_height)
            #self.image_view.setRange(QtCore.QRectF(0, 0, x_width, y_height))
            self.x_width = x_width
            self.y_height = y_height
            if x_width >= y_height:
                self.image_view.setLimits(maxXRange=1.2*x_width)
            else:
                self.image_view.setLimits(maxYRange=1.2*y_height)
            self.image_view.autoRange()
            self.sigResolutionChanged.emit((y_height,x_width))
    
    def showTest(self):
        array = np.random.randint(0, 255,size = (2*self.y_height, 2*self.x_width))
        array = array.astype(np.uint8)
        self.setImage(array)

if __name__ == "__main__":
    app = pg.mkQApp()
    image_display = ImageDisplay(512, 512)
    image_display.showTest()
    #image_display.add_ROI()
    #image_display.remove_ROI()
    #image_display.add_double_lines()
    #image_display.add_image_ROI()
    image_display.add_polyline_ROI()
    image_display.show()
    pg.exec()