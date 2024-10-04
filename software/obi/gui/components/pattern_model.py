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

class m(QAbstractItemModel):
    def __init__(self):
        super().__init__()
    def data(self, index, role):
        return "text"
    def columnCount(self, index):
        return 1
    def rowCount(self, index):
        return 1


if __name__ == "__main__":
    from .image_display import ImageDisplay
    app = pg.mkQApp()
    mm = m()
    tree = QTreeView()
    tree.setModel(mm)
    tree.show()
    pg.exec()
