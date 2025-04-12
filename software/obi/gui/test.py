import asyncio
from PyQt6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from .qtasync import QtAsyncRunner, asyncSlot

class MyWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qt + asyncio + @asyncSlot")

        self.button = QPushButton("Click me")
        self.button.clicked.connect(self.on_click)

        layout = QVBoxLayout()
        layout.addWidget(self.button)
        self.setLayout(layout)

    @asyncSlot()
    async def on_click(self):
        self.button.setText("Working...")
        await asyncio.sleep(2)
        self.button.setText("Done!")

async def main():
    qt = QtAsyncRunner()
    qt.start()

    win = MyWindow()
    win.show()

    await asyncio.sleep(10)
    await qt.stop()

asyncio.run(main())
