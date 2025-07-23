import sys
import subprocess
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt Script Runner")
        self.setGeometry(100, 100, 300, 200)  # x, y, width, height

        # Create a button
        button = QPushButton("Run SARA AI Companion")
        button.clicked.connect(self.run_script)

        # Set up layout
        layout = QVBoxLayout()
        layout.addWidget(button)

        # Create central widget and set layout
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def run_script(self):
        try:
            # Replace 'your_script.py' with the path to your script
            # Added full path to the Python executable and script so the installed Python environment and modules are used
            result = subprocess.run(['D:\\CODE\\SpaceDebris\\venv\\Scripts\\python.exe', 'D:\\CODE\\GrokMail\\src\\grok4Mail.py'], capture_output=True, text=True)
            print("Script Output:", result.stdout)
            if result.stderr:
                print("Script Error:", result.stderr)
        except Exception as e:
            print("Error running script:", e)

# Create and run the application
app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec())