import flet as ft
import requests
import os
import time
import shutil
import platform
import asyncio
import ast
from pathlib import Path
from hiyabocut import unshort
import base64
from bs4 import BeautifulSoup
import json
from threading import Event

try:
    import android
    from android.permissions import request_permissions, Permission
    from android.storage import primary_external_storage_path

except ImportError:
    android = None

headers = {"User-Agent":"Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"}

def make_session(dl):
    session = requests.Session()
    username = dl['u']
    password = dl['p']
    if dl['m'] == 'm':
      return session
    if dl["m"] == "uoi" or dl["m"] == "evea" or dl['m'] == 'md' or dl['m'] == 'ts':
        base64_url = "aHR0cHM6Ly9kb3duZnJlZS1hcGlkYXRhLm9ucmVuZGVyLmNvbS9zZXNzaW9u"
        decoded_url = base64.b64decode(base64_url).decode("utf-8")
        v = str(dl["id"])
        resp = requests.post(decoded_url,json={"id":v},headers={'Content-Type':'application/json'})
        data = json.loads(resp.text)
        print("Esta es su data", data)
        session.cookies.update(data)
        return session
    if dl['m'] == 'moodle':
        url = dl['c']+'login/index.php'
    elif dl['m'] == 'rev2':
        url = dl['c'].split('author')[0]+"login/signIn"
    else:
      url = dl['c'].split('/$$$call$$$')[0]+ '/login/signIn'
    resp = session.get(url,headers=headers,allow_redirects=True,verify=False)
    soup = BeautifulSoup(resp.text, "html.parser")
    if dl['m'] == 'moodle':
      try:
        token = soup.find("input", attrs={"name": "logintoken"})["value"]
        payload = {"anchor": "",
        "logintoken": token,
        "username": username,
        "password": password,
        "rememberusername": 1}
      except:
        payload = {"anchor": "",
        "username": username,
        "password": password,
        "rememberusername": 1}
    elif dl['m'] == 'rev2':
        payload = {"source":"",
                   "username":username,
                   "password":password,
                   "remember":"1"}
    else:
      try:
          csrfToken = soup.find('input',{'name':'csrfToken'})['value']
          payload = {}
          payload['csrfToken'] = csrfToken
          payload['source'] = ''
          payload['username'] = username
          payload['password'] = password
          payload['remember'] = '1'
      except Exception as ex:
          print(ex)
    
    resp = session.post(url,headers=headers,data=payload,verify=False,timeout=60)
    if resp.url!=url:
        return session
    return None

class Downloader:
    def __init__(self, page: ft.Page):
        self.page = page
        self.download_queue = asyncio.Queue()
        self.pause_event = Event()
        self.stop_event = Event()
        self.downloading = False 
        self.max_retries = 5

        # UI
        self.status_label = ft.Text("Estado de descarga", size=14, text_align=ft.TextAlign.CENTER)
        self.url_input = ft.TextField(hint_text="URL de Descarga", expand=True)
        self.pause_button = ft.ElevatedButton("Pausar", on_click=self.pause_download, disabled=True)
        self.resume_button = ft.ElevatedButton("Reanudar", on_click=self.resume_download, disabled=True)
        self.progress_bar = ft.ProgressBar(value=0, width=150)
        self.progress_text = ft.Text("0 MB / 0 MB (0.0%)", size=12)
        self.download_list = ft.Column(scroll=ft.ScrollMode.ALWAYS, expand=True)

        # Estructura de la interfaz
        self.page.add(
            ft.Column([
                ft.Container(
                    content=ft.Text("📥 Down Free", size=22, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    bgcolor=ft.Colors.BLUE_GREY_900,
                    padding=10,
                    border_radius=10
                ),
                ft.Row([
                    self.url_input,
                    ft.IconButton(ft.Icons.DOWNLOAD, on_click=self.queue_download)
                ], spacing=10, alignment=ft.MainAxisAlignment.CENTER),
                ft.Row([
                    self.pause_button,
                    self.resume_button
                ], spacing=10, alignment=ft.MainAxisAlignment.CENTER),
                ft.Column([
                    self.progress_bar,
                    self.progress_text
                ], alignment=ft.MainAxisAlignment.CENTER),
                self.status_label,
                ft.Container(content=self.download_list, expand=True)
            ], spacing=15, expand=True, alignment=ft.MainAxisAlignment.CENTER)
        )

        self.page.update()
        self.page.run_task(self.start_download)

        if self.is_android():
            self.request_android_permissions()
            self.page.run_task(self.request_ignore_battery_optimizations)

    def is_android(self):
        """Detecta si la aplicación se ejecuta en Android."""
        return android is not None and platform.system() == "Linux"

    def mostrar_mensaje(self, mensaje):
        """Muestra un mensaje tipo SnackBar en Flet."""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(mensaje),
            duration=2000
        )
        self.page.snack_bar.open = True
        self.page.update()

    def request_android_permissions(self):
        """Solicita permisos en Android."""
        if self.is_android():
            permissions = [Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE]
            request_permissions(permissions, self.on_permission_callback)

    def on_permission_callback(self, permissions, results):
        if all(results):
            self.mostrar_mensaje("✅ Permisos otorgados")
        else:
            self.mostrar_mensaje("❌ Permisos no otorgados")

    async def request_ignore_battery_optimizations(self):
        """Solicita que la app se excluya de optimización de batería en Android."""
        if self.is_android():
            try:
                context = PythonActivity.mActivity
                package_name = context.getPackageName()
                pm = context.getSystemService(Context.POWER_SERVICE)

                if not pm.isIgnoringBatteryOptimizations(package_name):
                    intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                    intent.setData(Uri.parse(f"package:{package_name}"))
                    context.startActivity(intent)

                self.mostrar_mensaje("⚡ Solicitud de optimización de batería enviada")
            except Exception as e:
                self.mostrar_mensaje(f"⚠ Error: {str(e)}")

    async def queue_download(self, e):    # 🔹 'e' es el evento, no la URL
        url_text = self.url_input.value.strip()  # 📌 Obtiene el texto de la entrada
        if not url_text:
            self.mostrar_error("❌ Introduce una URL válida.")
            return
        try:
            url = ast.literal_eval(url_text)  # 🔹 Convierte la cadena a un diccionario
            file_status = self.add_download(url["fn"])   # 📌 Agregar nombre del archivo a la lista UI
            url["status_text"] = file_status 
            await self.download_queue.put(url) 
            self.url_input.value = ""  # Limpiar campo
            self.page.update()
        except Exception as ex:
            self.mostrar_error(f"❌ Error en la URL: {str(ex)}")

    async def start_download(self):
        while True:
            if not self.downloading and not self.download_queue.empty():
                self.downloading = True 
                dl = await self.download_queue.get()  # 🔹 Esperar una nueva descarga
                filet = dl['fn']
                if len(filet) > 25:
                    filet = filet[:20] + "." + filet[-5:]
                if "status_text" in dl:
                    dl["status_text"].value = f"📂 {filet} - Descargando..."
                    dl["status_text"].update()  # 🔹 Forzar actualización
                    self.page.update()
                self.pause_button.disabled = False
                self.resume_button.disabled = True
                self.page.update()
                await self._download_file(dl)  # 🔹 Descargar el archivo
                self.download_queue.task_done()  # 🔹 Marcar como completada
                self.downloading = False 
                self.pause_button.disabled = True
                self.resume_button.disabled = True
                self.page.update()
            await asyncio.sleep(1)   

    async def _download_file(self, dl, ichunk=0, index=0):
        try:
            filename = dl['fn']
            self.status_label.value = f"📥 Descargando: {filename}"
            self.page.update()
            total_size = dl['fs']
            total_parts = dl["t"] * 1024 * 1024

            if dl["m"] in ["m", "ts", "md", "rev2"]:
                dl['urls'] = eval(unshort(dl["urls"]))

            total_url = len(dl["urls"])
            session = make_session(dl)
            chunk_por = index
            filet = dl['fn']

            if len(filet) > 25:
                filet = filename[:20] + "." + filename[-5:]
            
            # Ruta de descarga
            if android:
                download_path = os.path.join(primary_external_storage_path(), "Download", filename)
            else:
                download_path = os.path.join(str(Path.home()), "Downloads", filename)

            if os.path.exists(download_path):
                os.unlink(download_path)

            part_files = []

            for i, chunkur in enumerate(dl['urls']):
                part_path = f"{download_path}.part{i}"
                part_files.append(part_path)

                if os.path.exists(part_path):
                    chunk_por += os.path.getsize(part_path)
                    if os.path.getsize(part_path) >= total_parts:
                        print(f"Parte {i} ya descargada, omitiendo.")
                        continue

                chunkurl = self._get_chunk_url(dl, chunkur, filename, i)

                start_time = time.time() 

                retries = 0
                while retries < self.max_retries:
                    try:
                        if dl['m'] in ['moodle', 'evea'] and not self._is_session_active(session, chunkurl):
                            print("Sesión inactiva, regenerando sesión...")
                            session = make_session(dl)

                        with open(part_path, "wb") as part_file:
                            resp = session.get(chunkurl, headers=headers, stream=True, verify=False)
                            resp.raise_for_status()
                            downloaded = 0

                            for chunk in resp.iter_content(chunk_size=8192):
                                if self.pause_event.is_set():
                                    self.status_label.value = 'Descarga pausada... esperando reanudación'
                                    self.page.update()
                                    while self.pause_event.is_set():
                                        await asyncio.sleep(0.1)

                                    if not self._is_session_active(session, chunkurl):
                                        print("Sesión inactiva, regenerando sesión...")
                                        session = make_session(dl)

                                if self.stop_event.is_set():
                                    return

                                downloaded += len(chunk)
                                chunk_por = sum(
                                    os.path.getsize(f"{download_path}.part{j}") for j in range(i)
                                ) + downloaded
                                elapsed_time = time.time() - start_time     
                                progress = chunk_por / total_size 
                                downloaded_mb = chunk_por / (1024 * 1024) 
                                total_mb = total_size / (1024 * 1024)           
                                part_file.write(chunk)
                                self.update_download(filename, progress, downloaded_mb, total_mb)
                                await asyncio.sleep(0)

                        expected_size = total_parts if (i < total_url - 1) else total_size % total_parts

                        if os.path.getsize(part_path) < expected_size:
                            print(f"Error: La parte {i} se descargó con tamaño 0 bytes.")
                            os.remove(part_path)
                            retries += 1
                            await asyncio.sleep(5)
                            continue

                        break

                    except requests.exceptions.RequestException:
                        self.connection_lost_event.set()
                        if not self._retry_connection():
                            retries += 1
                            await asyncio.sleep(12)
                            if not self._is_session_active(session, chunkurl):
                                print("Sesión inactiva, regenerando sesión...")
                                session = make_session(dl)
                            continue

                if retries >= self.max_retries:
                    self.mostrar_error(f"No se pudo completar la parte {i + 1} tras múltiples intentos.")
                    return

            downloaded_parts = [os.path.exists(part) and os.path.getsize(part) > 0 for part in part_files]
            if all(downloaded_parts) and len(downloaded_parts) == total_url:
                self._merge_parts(download_path, len(part_files))
            else:
                self.mostrar_error("Faltaron partes del archivo por descargar. Verifica la conexión y reintenta.")

            self._replace_bytes_if_needed(dl, download_path)

            if android:
                try:
                    destination_file = os.path.join(primary_external_storage_path(), "Download", filename)
                    if os.path.exists(destination_file):
                        os.unlink(destination_file)
                    shutil.move(download_path, destination_file)
                    print("Archivo guardado en la carpeta Download")
                except Exception as ex:
                    print(f"Archivo guardado en {str(download_path)}")

            self.complete_download(filet)

        except Exception as ex:
            print(f"¡Error! {str(ex)}")
            self.mostrar_error("Error de conexión: No se pudo conectar al servidor.")

    def _merge_parts(self, output_path, num_parts):
        """Une todas las partes descargadas en un único archivo."""
        try:
            with open(output_path, "wb") as final_file:
                for i in range(num_parts):
                    part_path = f"{output_path}.part{i}"
                    if not os.path.exists(part_path):
                        print(f"Parte faltante: {part_path}. No se puede completar la unión.")
                        return
                    with open(part_path, "rb") as part_file:
                        while chunk := part_file.read(8192):
                            final_file.write(chunk)
                    os.remove(part_path)  # Eliminar la parte una vez unida
            print(f"Descarga completada y unida: {output_path}")
            self.status_label.value = f"✅ Descarga finalizada: {output_path}"
            self.page.update()
        except Exception as e:
            print(f"Error al unir las partes: {e}")

    def _get_chunk_url(self, dl, chunkur, filename, i):
        """Obtiene la URL del chunk basado en el modo de descarga."""
        if dl['m'] in ['m', 'ts', 'md', 'rev2']:
            return chunkur
        elif dl["m"] == "uoi":
            return chunkur + "/.file"
        elif dl['m'] in ['moodle', 'evea']:
            draftid, fileid = chunkur.split(":")
            return f"{dl['c']}draftfile.php/{draftid}/user/draft/{fileid}/{filename.replace(' ', '%2520')}-{i}.zip"
        else:
            return dl['c'].split('^')[0] + chunkur + dl['c'].split('^')[1]

    def _replace_bytes_if_needed(self, dl, download_path):
        """Elimina ciertos bytes no deseados en algunos archivos."""
        if dl["m"] not in ["uoi", "m", "moodle", "evea", "ts"]:
            chunk_size = 1024 * 1024
            target_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01..."
            replacement_bytes = b""

            def replace_bytes(chunk, target, replacement):
                return chunk.replace(target, replacement)

            with open(download_path, "rb") as original_file, open(download_path + ".tmp", "wb") as new_file:
                while chunk := original_file.read(chunk_size):
                    new_file.write(replace_bytes(chunk, target_bytes, replacement_bytes))

            os.replace(download_path + ".tmp", download_path)
            
    def _is_session_active(self, session, test_url):
        if not isinstance(session, requests.Session):
            print("El objeto sesión no es válido.")
            return False
        try:
            # Realizar una solicitud HEAD para verificar la conexión
            resp = session.head(test_url, timeout=30, verify=False)
            # Si el estado es 200, 204, o similar, la sesión está activa
            return resp.status_code in {200, 204}  # Incluye códigos comunes de éxito
        except requests.exceptions.RequestException as ex:
            print(f"Error al verificar sesión: {ex}")
            return False

    def pause_download(self, e):
        self.pause_event.set()
        self.pause_button.disabled = True
        self.resume_button.disabled = False
        self.status_label.value = "Descarga pausada"
        self.page.update()

    def resume_download(self, e):
        self.pause_event.clear()
        self.pause_button.disabled = False
        self.resume_button.disabled = True
        self.status_label.value = "Descarga reanudada"
        self.page.update()

    def add_download(self, filename):
        """Muestra en la UI que un archivo ha sido agregado a la cola."""
        filet = filename
        if len(filet) > 25:
            filet = filename[:20] + "." + filename[-5:]
        file_status = ft.Text(f"📂 {filet} - Conectando...", size=16)
        self.download_list.controls.append(file_status)
        self.page.update()
        return file_status

    def update_download(self, filename, progress, downloaded_mb, total_mb):
        """Actualiza el estado de descarga con progreso y velocidad."""
        percentage = progress * 100
        self.progress_bar.value = progress
        self.progress_text.value = f"{downloaded_mb:.2f} MB / {total_mb:.2f} MB ({percentage:.2f}%)"
        self.status_label.value = f"📥 {filename}  {percentage:.2f}%"
        self.page.update()

    def complete_download(self, filename):
        """Marca la descarga como finalizada en la UI."""
        for text_control in self.download_list.controls:
            if text_control.value.startswith(f"📂 {filename}"):
                text_control.value = f"📂 {filename} - ✅Descarga Finalizada"
                text_control.update()
                self.page.update()  # 🔹 Asegurar actualización en Flet
                return

    def mostrar_error(self, mensaje):
        """Muestra un mensaje de error en la UI."""
        self.status_label.value = f"❌ {mensaje}"
        self.page.update()

import sys

def main(page: ft.Page):
    page.on_close = lambda _: sys.exit(0)  # Cierra la app correctamente
    page.title = "Down Free"
    page.scroll = "adaptive"
    page.update()
    Downloader(page)

ft.app(target=main)
