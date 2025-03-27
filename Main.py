import sys
import json
import time
import threading
import requests  # Para manejar solicitudes HTTP a dispositivos eSCL
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QMessageBox, QDialog
)
from PyQt5.QtGui import QPixmap, QImage, QMovie
from PyQt5.QtCore import Qt, QTimer, QMetaObject, Q_ARG, pyqtSlot
from zeroconf import ServiceBrowser, Zeroconf


DEVICE_FILE = "devices.json"  # Archivo para guardar los dispositivos detectados


class ScannerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.initZeroConf()
        self.loadDevices()

    def initUI(self):
        # Configuración de la ventana principal
        self.setWindowTitle("Aplicación de Escaneo")
        self.setGeometry(100, 100, 800, 500)

        # Layout principal
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Zona de previsualización (izquierda)
        self.preview_label = QLabel("Previsualización")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("border: 2px solid black;")
        layout.addWidget(self.preview_label)

        # Botones y lista de dispositivos (derecha)
        button_layout = QVBoxLayout()
        self.scan_devices_button = QPushButton("Escanear Dispositivos")
        self.devices_combo = QComboBox()
        self.scan_button = QPushButton("Escanear Documento")
        self.view_button = QPushButton("Visualizar Escaneo")
        self.save_button = QPushButton("Guardar como PDF")
        button_layout.addWidget(self.scan_devices_button)
        
        button_layout.addWidget(self.devices_combo)
        button_layout.addWidget(self.scan_button)
        #button_layout.addWidget(self.view_button)
        button_layout.addWidget(self.save_button)
        layout.addLayout(button_layout)

        # Conectar botones a funciones
        self.scan_devices_button.clicked.connect(self.scanNetworkDevices)
        self.scan_button.clicked.connect(self.scanDocument)
        self.view_button.clicked.connect(self.viewScannedDocument)
        self.save_button.clicked.connect(self.saveAsPDF)

        # Variables para almacenar la imagen escaneada y dispositivos
        self.scanned_image = None
        self.devices = []

    def initZeroConf(self):
        # Inicializar ZeroConf para descubrir dispositivos en la red
        self.zeroconf = Zeroconf()
        self.listener = MyListener(self)
        self.browser_ipp = ServiceBrowser(self.zeroconf, "_ipp._tcp.local.", self.listener)  # eSCL

    def loadDevices(self):
        # Cargar dispositivos desde el archivo JSON
        try:
            with open(DEVICE_FILE, "r") as file:
                self.devices = json.load(file)
                for device in self.devices:
                    self.devices_combo.addItem(f"{device['name']} ({device['type']})")
        except FileNotFoundError:
            self.devices = []

    def saveDevices(self):
        # Guardar dispositivos en el archivo JSON
        with open(DEVICE_FILE, "w") as file:
            json.dump(self.devices, file, indent=4)

    def scanNetworkDevices(self):
        # Mostrar ventana de espera mientras se escanean dispositivos
        dialog = ScanDialog(self)
        dialog.exec_()

        # Agregar dispositivos encontrados al desplegable
        self.devices_combo.clear()
        for device in self.devices:
            self.devices_combo.addItem(f"{device['name']} ({device['type']})")

    def scanDocument(self):
        # Escanear el documento
        selected_index = self.devices_combo.currentIndex()
        if selected_index == -1:
            QMessageBox.warning(self, "Error", "No se ha seleccionado ningún dispositivo.")
            return

        selected_device = self.devices[selected_index]
        if selected_device["type"] != "eSCL":
            QMessageBox.warning(self, "Error", "El dispositivo seleccionado no es compatible con eSCL.")
            return

        print(f"Escaneando con el dispositivo: {selected_device['name']} ({selected_device['type']})")

        # Mostrar ventana de espera mientras se realiza el escaneo
        dialog = ScanWaitDialog(self, selected_device)
        dialog.exec_()

    def viewScannedDocument(self):
        # Mostrar la imagen escaneada en la etiqueta de previsualización
        if self.scanned_image is None:
            QMessageBox.warning(self, "Error", "No hay ninguna imagen escaneada para visualizar.")
            return

        # Convertir QImage a QPixmap
        pixmap = QPixmap.fromImage(self.scanned_image)

        # Ajustar el pixmap al tamaño del área de previsualización manteniendo la relación de aspecto
        scaled_pixmap = pixmap.scaled(
            self.preview_label.size(),  # Tamaño del área de previsualización
            Qt.KeepAspectRatio,        # Mantener la relación de aspecto
            Qt.SmoothTransformation    # Usar una transformación suave para escalar
        )

        # Establecer el pixmap escalado en la etiqueta de previsualización
        self.preview_label.setPixmap(scaled_pixmap)

    def saveAsPDF(self):
        # Guardar la imagen escaneada como un archivo PDF
        if self.scanned_image is None:
            QMessageBox.warning(self, "Error", "No hay ninguna imagen escaneada para guardar.")
            return

        # Seleccionar ubicación para guardar el archivo PDF
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(self, "Guardar como PDF", "", "PDF Files (*.pdf)", options=options)

        if not file_path:
            return  # El usuario canceló la operación

        # Crear un archivo PDF con la imagen escaneada
        from reportlab.pdfgen import canvas
        from PIL import Image
        import tempfile
        import os

        temp_file_name = None  # Inicializar la variable para el archivo temporal

        try:
            # Guardar QImage como un archivo temporal
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_file_name = temp_file.name
                self.scanned_image.save(temp_file_name, "PNG")  # Guardar QImage como PNG

            # Abrir el archivo temporal con Pillow
            pil_image = Image.open(temp_file_name)

            # Crear el PDF
            pdf = canvas.Canvas(file_path)
            pdf.drawImage(temp_file_name, 0, 0, width=pil_image.width, height=pil_image.height)
            pdf.save()

            QMessageBox.information(self, "Éxito", f"El archivo PDF se guardó correctamente en: {file_path}")
        except Exception as e:
            # Mostrar un mensaje de error si ocurre un problema
            QMessageBox.critical(self, "Error", f"No se pudo guardar el archivo PDF: {str(e)}")
        finally:
            # Eliminar el archivo temporal si existe
            if temp_file_name and os.path.exists(temp_file_name):
                os.remove(temp_file_name)

    def closeEvent(self, event):
        # Cerrar ZeroConf al salir y guardar dispositivos
        self.zeroconf.close()
        self.saveDevices()
        event.accept()

    @pyqtSlot(QImage)
    def updatePreview(self, scanned_image):
        # Actualizar la previsualización con la imagen escaneada
        self.scanned_image = scanned_image
        self.viewScannedDocument()

    @pyqtSlot(str)
    def showError(self, error_message):
        QMessageBox.critical(self, "Error de escaneo", error_message)


class ScanDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Escaneando dispositivos...")
        self.setModal(True)
        self.setGeometry(200, 200, 400, 300)

        # Layout principal
        layout = QVBoxLayout(self)

        # GIF de espera
        self.gif_label = QLabel(self)
        self.gif_label.setAlignment(Qt.AlignCenter)
        self.movie = QMovie("loading.gif")  # Asegúrate de tener un archivo GIF llamado "loading.gif"
        self.gif_label.setMovie(self.movie)
        self.movie.start()
        layout.addWidget(self.gif_label)

        # Botones
        button_layout = QHBoxLayout()
        self.close_button = QPushButton("Cerrar")
        self.wait_button = QPushButton("Esperar")
        button_layout.addWidget(self.close_button)
        button_layout.addWidget(self.wait_button)
        layout.addLayout(button_layout)

        # Conectar botones
        self.close_button.clicked.connect(self.reject)
        self.wait_button.clicked.connect(self.waitForScan)

        # Simular escaneo
        QTimer.singleShot(5000, self.finishScan)  # Simular un escaneo de 5 segundos

    def waitForScan(self):
        # Mantener la ventana abierta
        pass

    def finishScan(self):
        # Simular dispositivos encontrados
        self.parent().devices = [
            {"name": "HP_OfficeJet_Pro", "type": "eSCL", "address": "192.168.1.100:631"},
            {"name": "Canon_MX920", "type": "WSD", "address": "192.168.1.101:80"}
        ]
        QMessageBox.information(self, "Escaneo completado", "Se encontraron dispositivos en la red.")
        self.accept()


class ScanWaitDialog(QDialog):
    def __init__(self, parent, device):
        super().__init__(parent)
        self.setWindowTitle("Escaneando documento...")
        self.setModal(True)
        self.setGeometry(200, 200, 400, 300)

        # Layout principal
        layout = QVBoxLayout(self)

        # GIF de espera
        self.gif_label = QLabel(self)
        self.gif_label.setAlignment(Qt.AlignCenter)
        self.movie = QMovie("loading.gif")  # Asegúrate de tener un archivo GIF llamado "loading.gif"
        self.gif_label.setMovie(self.movie)
        self.movie.start()
        layout.addWidget(self.gif_label)

        # Inicializar variables
        self.device = device
        self.parent = parent

        # Iniciar el escaneo en un hilo separado
        self.scan_thread = threading.Thread(target=self.startScan)
        self.scan_thread.start()

    def startScan(self):
        try:
            # Realizar una solicitud HTTP al dispositivo eSCL para iniciar el escaneo
            url = f"http://{self.device['address']}/eSCL/ScanJobs"
            headers = {"Content-Type": "application/xml"}
            body = """<scan:ScanJob xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">
                        <scan:InputSource>Platen</scan:InputSource>
                        <scan:DocumentFormat>image/jpeg</scan:DocumentFormat>
                      </scan:ScanJob>"""
            response = requests.post(url, headers=headers, data=body)

            if response.status_code != 201:
                raise Exception(f"Error al iniciar el escaneo: {response.status_code}")

            # Obtener la URL del trabajo de escaneo
            job_url = response.headers["Location"]

            # Agregar un tiempo de espera de 30 segundos antes de descargar la imagen
            time.sleep(30)

            # Descargar la imagen escaneada
            self.downloadScannedImage(job_url)
        except Exception as e:
            # Mostrar un mensaje de error si ocurre un problema
            QMetaObject.invokeMethod(self.parent, "showError", Qt.QueuedConnection, Q_ARG(str, str(e)))
        finally:
            # Cerrar el diálogo en el hilo principal
            QMetaObject.invokeMethod(self, "accept", Qt.QueuedConnection)

    def downloadScannedImage(self, job_url):
        try:
            # Descargar la imagen escaneada
            image_response = requests.get(f"{job_url}/NextDocument")
            if image_response.status_code != 200:
                raise Exception("Error al descargar la imagen escaneada.")

            # Convertir la imagen a QImage
            qimage = QImage()
            qimage.loadFromData(image_response.content)

            # Actualizar la previsualización en el hilo principal
            QMetaObject.invokeMethod(self.parent, "updatePreview", Qt.QueuedConnection, Q_ARG(QImage, qimage))
        except Exception as e:
            # Mostrar un mensaje de error si ocurre un problema
            QMetaObject.invokeMethod(self.parent, "showError", Qt.QueuedConnection, Q_ARG(str, str(e)))


class MyListener:
    def __init__(self, app):
        self.app = app

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            device_name = info.name.split(".")[0]
            device_address = f"{info.parsed_scoped_addresses()[0]}:{info.port}"
            device_type = "eSCL"

            # Evitar duplicados
            for device in self.app.devices:
                if device["name"] == device_name and device["type"] == device_type:
                    return

            # Agregar dispositivo a la lista
            new_device = {"name": device_name, "type": device_type, "address": device_address}
            self.app.devices.append(new_device)
            self.app.devices_combo.addItem(f"{device_name} ({device_type})")
            print(f"Dispositivo encontrado: {device_name} ({device_type}) - {device_address}")

    def remove_service(self, zeroconf, type, name):
        print(f"Dispositivo desconectado: {name}")

    def update_service(self, zeroconf, type, name):
        # Método vacío para manejar actualizaciones de servicios
        print(f"Servicio actualizado: {name}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScannerApp()
    window.show()
    sys.exit(app.exec_())