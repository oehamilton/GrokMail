import sys
import subprocess
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget
from PyQt6.QtGui import QIcon

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SARA AI Companion")
        self.setGeometry(100, 100, 300, 200)  # x, y, width, height
        #set title color and background color
        # Set stylesheet for the main window and button
        self.setStyleSheet("""
            QMainWindow { 
                background-color: #2c3e50;
            }
            QPushButton {
                background-color: #3498db;
                color: #ffffff;
                border: none;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #1abc9c;
            }
            QPushButton:focus {
                outline: none;
            }
            QPushButton:disabled {
                background-color: #7f8c8d;
                color: #bdc3c7;
            }
            QPushButton:disabled:hover {
                background-color: #7f8c8d;
            }
        """)
        # Set the window icon       
        icon_path = r"D:\CODE\GrokMail\src\icon.png"
        self.setWindowIcon(QIcon(icon_path))

        # Create a button
        button = QPushButton("Scan Emails")
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
            # Use the full path to the venv's Python interpreter
            python_path = sys.executable  # Gets the current Python interpreter (e.g., venv's python.exe)
            script_path = r"src\\grok4Mail.py"
            result = subprocess.run([python_path, script_path], capture_output=True, text=True, encoding='utf-8')
            #result = subprocess.run(['D:\\CODE\\SpaceDebris\\venv\\Scripts\\python.exe', 'D:\\CODE\\GrokMail\\src\\grok4Mail.py'], capture_output=True, text=True)
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