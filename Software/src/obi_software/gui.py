import threading
from queue import Queue, Empty, Full
import argparse
import pathlib
import tomllib
import asyncio
import sys
import pyqtgraph as pg
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, 
                             QMessageBox, QPushButton,
                             QVBoxLayout, QWidget, QLabel, QGridLayout,
                             QSpinBox)
from PyQt6 import QtCore

import qasync
from qasync import asyncSlot, asyncClose, QApplication, QEventLoop

from .beam_interface import *
from .ui_interface import *
from .threads import *
from .gui_modules.image_display import ImageDisplay
from .gui_modules.settings import SettingBox, SettingBoxWithDefaults

parser = argparse.ArgumentParser()
parser.add_argument('--config_path', required=True, 
                    type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
                    help='path to microscope.toml')
parser.add_argument("port")
parser.add_argument('--debug',action='store_true')
args = parser.parse_args()
print(f"loading config from {args.config_path}")



class Settings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.rx = SettingBoxWithDefaults("X Resolution",128, 16384, 512, ["512","1024", "2048", "4096", "8192", "16384", "Custom"])
        self.addLayout(self.rx)
        self.ry = SettingBoxWithDefaults("Y Resolution",128, 16384, 512, ["512","1024", "2048", "4096", "8192", "16384", "Custom"])
        self.addLayout(self.ry)
        self.dwell = SettingBoxWithDefaults("Dwell Time",0, 65536, 2, ["1","2", "8", "16", "32", "Custom"])
        self.addLayout(self.dwell)
        self.single_capture_btn = QPushButton("Single Capture")
        self.addWidget(self.single_capture_btn)
        self.live_capture_btn = QPushButton("Start Live Scan")
        self.live_capture_btn.setCheckable(True)
        self.addWidget(self.live_capture_btn)
        self.save_btn = QPushButton("Save Image")
        self.addWidget(self.save_btn)
    def disable_input(self):
        self.rx.spinbox.setEnabled(False)
        self.ry.spinbox.setEnabled(False)
        self.dwell.spinbox.setEnabled(False)
        self.single_capture_btn.setEnabled(False)
    def enable_input(self):
        self.rx.spinbox.setEnabled(True)
        self.ry.spinbox.setEnabled(True)
        self.dwell.spinbox.setEnabled(True)
        self.single_capture_btn.setEnabled(True)

def si_prefix(distance:float):
    if 1 >= distance > pow(10, -3):
        return f"{distance*pow(10,3):.5f} mm"
    if pow(10, -3) >= distance > pow(10, -6):
        return f"{distance*pow(10,6):.5f} µm"
    if pow(10, -6) >= distance > pow(10, -9):
        return f"{distance*pow(10,9):.5f} nm"
    else:
        return f"{distance:.5f} m"

class ImageData(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.mag = SettingBox("Magnification",1, 1000000, 1)
        self.addLayout(self.mag)
        self.measure_btn = QPushButton("Measure")
        self.measure_btn.setCheckable(True)
        self.addWidget(self.measure_btn)
        self.measure_length = QLabel("      ")
        self.addWidget(self.measure_length)
class DebugSettings(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCheckable(True)
        self.addWidget(self.connect_btn)
        self.sync_btn = QPushButton("Sync")
        self.latency = SettingBox("Latency",0, pow(2,28), pow(2,16))
        self.addLayout(self.latency)
        self.freescan_btn = QPushButton("Free Scan")
        self.addWidget(self.freescan_btn)
        self.interrupt_btn = QPushButton("Interrupt")
        self.addWidget(self.interrupt_btn)

class Window(QVBoxLayout):
    def __init__(self,iface, frame_queue, debug=False):
        super().__init__()
        self.debug = debug
        self.config = tomllib.load(open(args.config_path, "rb") )
        self.iface = iface
        self.frame_queue = frame_queue
        self.settings = Settings()
        self.addLayout(self.settings)
        self.settings.single_capture_btn.clicked.connect(self.capture_single_frame)
        # self.settings.live_capture_btn.clicked.connect(self.capture_live)
        self.settings.save_btn.clicked.connect(self.save_image)
        self.image_display = ImageDisplay(512,512)
        self.addWidget(self.image_display)
        self.image_data = ImageData()
        self.addLayout(self.image_data)
        self.image_data.measure_btn.clicked.connect(self.toggle_measure)
        if self.debug:
            self.debug_settings = DebugSettings()
            self.addLayout(self.debug_settings)
            self.debug_settings.connect_btn.clicked.connect(self.toggle_connection)
            self.debug_settings.sync_btn.clicked.connect(self.request_sync)
            self.debug_settings.freescan_btn.clicked.connect(self.free_scan)
            self.debug_settings.interrupt_btn.clicked.connect(self.interrupt)

    @property
    def parameters(self):
        x_res = self.settings.rx.getval()
        y_res = self.settings.ry.getval()
        dwell = self.settings.dwell.getval()
        if self.debug:
            latency = self.debug_settings.latency.getval()
        else:
            latency = 65536
        return x_res, y_res, dwell, latency
    
    def toggle_measure(self):
        if self.image_data.measure_btn.isChecked():
            self.image_display.add_line()
            self.image_display.line.sigRegionChanged.connect(self.measure)
            self.image_data.mag.spinbox.valueChanged.connect(self.measure)
            self.settings.rx.spinbox.valueChanged.connect(self.measure)
            self.settings.ry.spinbox.valueChanged.connect(self.measure)
            self.measure()
        else:
            self.image_display.remove_line()
            self.image_data.measure_length.setText("      ")
            self.image_data.mag.spinbox.valueChanged.disconnect(self.measure)
            self.settings.rx.spinbox.valueChanged.disconnect(self.measure)
            self.settings.ry.spinbox.valueChanged.disconnect(self.measure)

    def get_pixel_size(self):
        mag = self.image_data.mag.getval()
        cal = self.config["mag_cal"]
        cal_factor = cal["m_per_FOV"]
        full_fov_pixels = max(self.settings.rx.getval(), self.settings.ry.getval())
        pixel_size = cal_factor/mag/full_fov_pixels
        return pixel_size

    def measure(self):
        if not self.image_display.line == None:
            pixel_size = self.get_pixel_size()
            line_length = self.image_display.get_line_length()
            line_actual_size = line_length*pixel_size
            self.image_data.measure_length.setText(si_prefix(line_actual_size))
        

    def display_image(self, array, y_ptr):
        x_width, y_height = array.shape
        print(array)
        print(f"{array.shape=}")
        try:
            self.image_display.setImage(y_height, x_width, array, y_ptr)
        except Exception as e:
            print(f"display error: {e}")
    
    def display_frame(self):
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(1)
    
    def update_frame(self):
        if not self.frame_queue.empty():
            frame = self.frame_queue.get()
            array = frame.as_uint8()
            x_width, y_height = array.shape
            self.image_display.setImage(y_height, x_width, array, frame.y_ptr)
            print(array)
            print(f"{array.shape=}")
            self.frame_queue.task_done()
        self.display_frame()



    def save_image(self):
        self.fb.current_frame.saveImage_tifffile()

    def capture_single_frame(self):
        x_range, y_range, dwell, latency = self.parameters
        # frame = self.iface.capture_frame(x_range, y_range, dwell)
        # self.display_image(frame.as_uint8(), frame.y_ptr)
        threading.Thread(target = self.iface.capture_frame_rolling, args=[x_range, y_range, dwell]).start()
        # self.display_image(frame.as_uint8(), frame.y_ptr)
        self.display_frame()
        # threading.Thread(target = self.iface.abort.set).start()
        # print("aborted from gui")



    #### Debug settings
    @asyncSlot()
    async def toggle_connection(self):
        if self.debug_settings.connect_btn.isChecked():
            await self.conn._connect()
            self.debug_settings.connect_btn.setText("Disconnect")
        else:
            self.conn._disconnect()
            self.debug_settings.connect_btn.setText("Connect")

    @asyncSlot()
    async def request_sync(self):
        await self.conn._synchronize()

    @asyncSlot()
    async def free_scan(self):
        x_range, y_range, dwell, latency = self.parameters
        await self.fb.set_ext_ctrl(1)
        async for frame in self.fb.free_scan(x_range, y_range, dwell=dwell, latency=latency):
            print("Got frame")
            self.display_image(frame.as_uint8())
        print("Concluded gui.free_scan")


def run_gui_thread(in_queue, out_queue):
    print("run gui thread")
    loop = asyncio.new_event_loop()
    frame_queue = Queue()
    worker = UIThreadWorker(in_queue, out_queue, loop)
    iface = OBIInterface(worker, frame_queue)

    app = QApplication(sys.argv)

    # event_loop = QEventLoop(app)
    # asyncio.set_event_loop(event_loop)

    # app_close_event = asyncio.Event()
    # app.aboutToQuit.connect(app_close_event.set)

    w = QWidget()
    window = Window(iface=iface, debug=args.debug, frame_queue=frame_queue)
    w.setLayout(window)
    print("show window!")
    w.show()
    pg.exec()

    # with event_loop:
    #     event_loop.run_until_complete(app_close_event.wait())


def run_gui():
    ui_to_con = Queue()
    con_to_ui = Queue()

    # ui = threading.Thread(target = run_gui_thread, args = [con_to_ui, ui_to_con])
    con = threading.Thread(target = conn_thread, args = [ui_to_con, con_to_ui])

    # ui.start()
    con.start()
    run_gui_thread(con_to_ui, ui_to_con)
    

if __name__ == "__main__":
    run_gui()


