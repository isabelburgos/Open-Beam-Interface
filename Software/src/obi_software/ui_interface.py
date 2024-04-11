from .beam_interface import *
from .threads import conn_thread, UIThreadWorker
from queue import Queue
class ExternalBeamCtrl:
    def __init__(self, beam_type: BeamType, worker: UIThreadWorker):
        self.beam_type = beam_type
        self.worker = worker
        self._in_control = False

    @property
    def in_control(self):
        # True if OBI board is electrically 
        # connected to X, Y, and Video signals
        return self._in_control
    
    def enable(self):
        self.worker.xchg(ExternalCtrlCommand(enable=1, beam_type=self.beam_type))
        self._in_control = True
    
    def disable(self):
        self.worker.xchg(ExternalCtrlCommand(enable=0, beam_type=self.beam_type))
        self._in_control = False

class Frame:
    def __init__(self, x_resolution, y_resolution):
        self._x_count = x_resolution
        self._y_count = y_resolution
        self.canvas = np.zeros(shape = self.np_shape, dtype = np.uint16)
        self.y_ptr = 0

    @property
    def pixels(self):
        return self._x_count * self._y_count

    @property
    def np_shape(self):
        return self._y_count, self._x_count

    def fill(self, pixels: array.array):
        assert len(pixels) == self.pixels, f"expected {self.pixels}, got {len(pixels)}"
        self.canvas = np.array(pixels, dtype = np.uint16).reshape(self.np_shape)
    
    def fill_lines(self, pixels: array.array):
        print(f"{len(pixels)=}")
        assert len(pixels)%self._x_count == 0, f"invalid shape: {len(pixels)} is not a multiple of {self._x_count}"
        fill_y_count = int(len(pixels)/self._x_count)
        print(f"starting with {self.y_ptr=}")
        print(f"{fill_y_count=}")
        if (fill_y_count == self._y_count) & (self.y_ptr == 0):
            self.fill(pixels)
        elif self.y_ptr + fill_y_count <= self._y_count:
            self.canvas[self.y_ptr:self.y_ptr + fill_y_count] = np.array(pixels, dtype = np.uint16).reshape(fill_y_count, self._x_count)
            self.y_ptr += fill_y_count
            if self.y_ptr == self._y_count:
                print("Rolling over")
                self.y_ptr == 0
        elif self.y_ptr + fill_y_count > self._y_count:
            print(f"{self.y_ptr} + {fill_y_count} > {self._y_count}")
            remaining_lines = self._y_count - self.y_ptr
            remaining_pixel_count = remaining_lines*self._x_count
            remaining_pixels = pixels[:remaining_pixel_count]
            print(f"{remaining_lines=}")
            self.canvas[self.y_ptr:self._y_count] = np.array(remaining_pixels, dtype = np.uint16).reshape(remaining_lines, self._x_count)
            rewrite_lines = fill_y_count - remaining_lines
            rewrite_pixels = pixels[remaining_pixel_count:]
            print(f"{rewrite_lines=}")
            self.canvas[:rewrite_lines] = np.array(rewrite_pixels, dtype = np.uint16).reshape(rewrite_lines, self._x_count)
            self.y_ptr = rewrite_lines
        print(f"ending with {self.y_ptr=}")

    def opt_chunk_size(self, dwell):
        FPS = 30
        DWELL_NS = 125
        s_per_frame = 1/FPS
        dwells_per_frame = s_per_frame/(DWELL_NS*pow(10,-9)*dwell)
        if dwells_per_frame > self.pixels:
            return self.pixels
        else:
            lines_per_chunk = dwells_per_frame//self._x_count
            return int(self._x_count*lines_per_chunk)

    def as_uint16(self):
        return np.left_shift(self.canvas, 2)

    def as_uint8(self):
        return np.right_shift(self.canvas, 6).astype(np.uint8)

    def saveImage_tifffile(self):
        img_name = "saved" + datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        tifffile.imwrite(f"{img_name}_16bit.tif", self.as_uint16(), shape = self.np_shape, dtype = np.uint16)
        tifffile.imwrite(f"{img_name}_8bit.tif", self.as_uint8(), shape = self.np_shape, dtype = np.uint8)
        print(f"{img_name}")
    

class OBIInterface:
    def __init__(self, worker: UIThreadWorker):
        self.worker = worker
        self.e_beam = ExternalBeamCtrl(BeamType.Electron, self.worker)
    
    def transfer_scan_cmd(self, command:Command, beam: ExternalBeamCtrl):
        if not beam.in_control:
            beam.enable()
        worker.xchg(command)
        beam.disable()

    def set_full_resolution(self, x_resolution, y_resolution):
        full_fov_pixels = max(x_resolution, y_resolution)
        step_size = int((16384/full_fov_pixels)*256)
        x_range = DACCodeRange(0, x_resolution, step_size)
        y_range = DACCodeRange(0, y_resolution, step_size)
        self.worker.xchg(RasterRegionCommand(x_range=x_range, y_range=y_range))
    
    def capture_pixel_run(self, dwell, length):
        return self.worker.xchg(RasterPixelRunCommand(dwell=dwell, length=length))
    
    def capture_frame(self, x_resolution, y_resolution, dwell):
        self.set_full_resolution(x_resolution, y_resolution)
        frame = Frame(x_resolution, y_resolution)
        pixels_per_chunk = frame.opt_chunk_size(dwell)
        pixels_left = frame.pixels
        while pixels_left > pixels_per_chunk:
            lines = self.capture_pixel_run(dwell, pixels_per_chunk)
            frame.fill(lines)
            pixels_left -= pixels_per_chunk
        last_lines = self.capture_pixel_run(dwell, pixels_left)
        frame.fill(last_lines)
        return frame



def main():
    ui_to_con = Queue()
    con_to_ui = Queue()

    def ui_thread(in_queue, out_queue):
        loop = asyncio.new_event_loop()
        worker = UIThreadWorker(in_queue, out_queue, loop)
        iface = OBIInterface(worker)
        iface.capture_frame(1024, 2048, 2)

    ui = threading.Thread(target = ui_thread, args = [con_to_ui, ui_to_con])
    con = threading.Thread(target = conn_thread, args = [ui_to_con, con_to_ui])

    ui.start()
    con.start()

if __name__=="__main__":
    main()