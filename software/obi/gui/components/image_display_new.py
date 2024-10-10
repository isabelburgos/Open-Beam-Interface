import logging
import math
from shapely.geometry import Polygon
from geo_rasterize import rasterize

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

import PyQt6
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow,
                             QMessageBox, QPushButton,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox, QSizePolicy)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot as Slot, Qt, QRectF, QPointF

logger = logging.getLogger()

from PyQt6 import QtGui

from rich import print

# from .roi import LiveRectangleROI, PatternPolyLineROI, MeasureLine, ParallelMeasureLines


class ScanFrameDisplay(pg.ImageItem):
    def __init__(self):
        super().__init__(border='w',axisOrder="row-major")
    def set_img(self, image: np.array(np.uint8)):
        
        y_height, x_width = image.shape
        super().setImage(image, rect = (0,0, x_width, y_height), autoLevels=False)



class ImageDisplay(pg.GraphicsLayoutWidget):
    _logger = logger.getChild("ImageDisplay")
    def __init__(self, y_height, x_width, invertY=True, invertX=False):
        super().__init__()
        self.y_height = y_height
        self.x_width = x_width

        self.image_view = self.addViewBox(invertY = invertY, invertX=invertX)
        ## lock the aspect ratio so pixels are always square
        self.image_view.setAspectLocked(True)
        
        self.live_img = ScanFrameDisplay()
        self.live_img.setImage(np.full((y_height, x_width), 0, np.uint8), rect = (0,0,x_width, y_height), autoLevels=False, autoHistogramRange=True)
        self.image_view.addItem(self.live_img)

        self.data = np.zeros(shape = (y_height, x_width))

        # Contrast/color control
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.live_img)
        #self.hist.disableAutoHistogramRange()
        self.addItem(self.hist)

        self.hist.setLevels(min=0,max=255)

    def setup_roi(self, roi:pg.ROI):
        self.rois.append(roi)
        self.image_view.addItem(roi)
        roi.maxBounds = roi.getbounds(self.x_width, self.y_height)
        roi.setZValue(10)  # make sure ROI is drawn above image
        self.sigROIAdded.emit(roi)
    
    def mapToREALITY(self, obj): #absolute position in frame coordinates, which correspond to real scan pixels
        return self.live_img.mapFromScene(obj.scenePos())

    def setImage(self, image: np.array(np.uint8)):
        ## image must be 2D np.array of np.uint8
        y_height, x_width = image.shape
        self.live_img.setImage(image, rect = (0,0, x_width, y_height), autoLevels=False)
        self.setRange(y_height, x_width)
        self.data = image
        
    def setRange(self, y_height, x_width):
        if (x_width != self.x_width) | (y_height != self.y_height):
            # if not self.roi == None:
            #     self.roi.maxBounds = self.roi.getbounds(self.x_width, self.y_height)
            # #self.image_view.setRange(QtCore.QRectF(0, 0, x_width, y_height))
            self.x_width = x_width
            self.y_height = y_height
            if x_width >= y_height:
                self.image_view.setLimits(maxXRange=1.2*x_width)
            else:
                self.image_view.setLimits(maxYRange=1.2*y_height)
            self.image_view.autoRange()
            # self.sigResolutionChanged.emit((y_height,x_width))
    
    def showTest(self):
        array = np.random.randint(0, 255,size = (2*self.y_height, 2*self.x_width))
        array = array.astype(np.uint8)
        self.setImage(array)


if __name__ == "__main__":
    app = pg.mkQApp()
    image_display = ImageDisplay(512, 512)
    image_display.showTest()
    image_display.show()
    pg.exec()