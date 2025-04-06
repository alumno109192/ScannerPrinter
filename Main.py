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
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scanner_app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DEVICE_FILE = "devices.json"  # Archivo para guardar los dispositivos detectados


class ScannerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.initZeroConf()
        self.loadDevices()

        # Verificar actualizaciones al iniciar la aplicación
        self.checkForUpdates()

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
        self.update_button = QPushButton("Buscar Actualizaciones")
        button_layout.addWidget(self.scan_devices_button)
        
        button_layout.addWidget(self.devices_combo)
        button_layout.addWidget(self.scan_button)
        #button_layout.addWidget(self.view_button)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.update_button)
        layout.addLayout(button_layout)

        # Conectar botones a funciones
        self.scan_devices_button.clicked.connect(self.scanNetworkDevices)
        self.scan_button.clicked.connect(self.scanDocument)
        self.view_button.clicked.connect(self.viewScannedDocument)
        self.save_button.clicked.connect(self.saveAsPDF)
        self.update_button.clicked.connect(self.checkForUpdates)

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
        if self.scanned_image is None:
            QMessageBox.warning(self, "Error", "No hay ninguna imagen escaneada para guardar.")
            return

        try:
            options = QFileDialog.Options()
            file_path, _ = QFileDialog.getSaveFileName(self, "Guardar como PDF", "", "PDF Files (*.pdf)", options=options)

            if not file_path:
                return

            # Importar librerías necesarias
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.utils import ImageReader
            from PIL import Image
            import tempfile
            import os

            temp_file_name = None

            # Crear un directorio temporal si no existe
            temp_dir = tempfile.gettempdir()
            temp_file_name = os.path.join(temp_dir, "temp_scan.png")

            logger.debug(f"Guardando imagen temporal en: {temp_file_name}")
            # Guardar QImage como archivo temporal
            if not self.scanned_image.save(temp_file_name, "PNG"):
                raise Exception("Error al guardar imagen temporal")

            # Abrir y procesar la imagen con PIL
            with Image.open(temp_file_name) as pil_image:
                # Obtener dimensiones
                img_width, img_height = pil_image.size
                
                logger.debug(f"Dimensiones originales de imagen: {img_width}x{img_height}")
                
                # Calcular dimensiones para el PDF (en puntos)
                aspect = img_height / float(img_width)
                
                # Usar un tamaño fijo de página A4
                pdf_width = 595  # Ancho A4 en puntos (8.27 × 11.69 pulgadas)
                pdf_height = pdf_width * aspect

                logger.debug(f"Dimensiones calculadas PDF: {pdf_width}x{pdf_height}")

                try:
                    # Crear el PDF con tamaño personalizado
                    c = canvas.Canvas(file_path, pagesize=(pdf_width, pdf_height))
                    
                    # Dibujar la imagen usando todo el espacio disponible
                    c.drawImage(temp_file_name, 0, 0, width=pdf_width, height=pdf_height)
                    c.save()
                    
                    logger.info(f"PDF guardado exitosamente en: {file_path}")
                    QMessageBox.information(self, "Éxito", f"El archivo PDF se guardó correctamente en:\n{file_path}")
                
                except Exception as pdf_error:
                    logger.error(f"Error al crear PDF: {str(pdf_error)}")
                    QMessageBox.critical(self, "Error", f"Error al crear el PDF: {str(pdf_error)}")
                    return

        except Exception as e:
            logger.error(f"Error general al guardar PDF: {str(e)}")
            QMessageBox.critical(self, "Error", f"No se pudo guardar el archivo PDF:\n{str(e)}")
        
        finally:
            # Limpiar archivo temporal
            try:
                if temp_file_name and os.path.exists(temp_file_name):
                    os.remove(temp_file_name)
                    logger.debug("Archivo temporal eliminado correctamente")
            except Exception as cleanup_error:
                logger.error(f"Error al eliminar archivo temporal: {str(cleanup_error)}")

    def checkForUpdates(self):
        try:
            # URL del archivo version.json en tu repositorio
            version_url = "https://raw.githubusercontent.com/tu-usuario/tu-repositorio/main/version.json"

            # Descargar la información de la versión
            response = requests.get(version_url)
            if response.status_code != 200:
                raise Exception("No se pudo verificar la versión más reciente.")

            # Leer la versión más reciente
            latest_version_info = response.json()
            latest_version = latest_version_info["version"]
            download_url = latest_version_info["download_url"]

            # Comparar con la versión actual
            current_version = "1.0.0"  # Cambia esto por la versión actual de tu aplicación
            if latest_version != current_version:
                # Mostrar un mensaje al usuario
                reply = QMessageBox.question(
                    self,
                    "Actualización disponible",
                    f"Hay una nueva versión disponible ({latest_version}). ¿Deseas descargarla?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    # Abrir el enlace de descarga en el navegador
                    import webbrowser
                    webbrowser.open(download_url)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo verificar actualizaciones: {str(e)}")

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