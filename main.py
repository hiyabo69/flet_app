import flet as ft
import aiohttp
import os
import traceback
import sys
import asyncio
import subprocess
import platform
import ast
import shutil
from pathlib import Path
from hiyabocut import unshort
import base64
from bs4 import BeautifulSoup
import json
from threading import Event
from plyer import notification

file_path= Path.home() / "Downloads"

headers = {"User-Agent":"Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"}

filename_counters = {}

def get_config_file():
    """Obtiene la ruta del archivo de configuración dependiendo del sistema operativo."""
    return Path.home() / ".downloader_config.json"

    
def save_download_path(path):
    """Guarda la ruta de descarga en un archivo JSON."""
    config_file = get_config_file()
    try:
        with open(config_file, "w") as file:
            json.dump({"download_path": str(path)}, file)
        print(f"Configuración guardada en: {config_file}")
    except Exception as e:
        print(f"Error al guardar la configuración: {e}")

def load_download_path():
    """Carga la ruta de descarga desde el archivo JSON."""
    config_file = get_config_file()
    if config_file.exists():
        try:
            with open(config_file, "r") as file:
                config = json.load(file)
                return Path(config.get("download_path", ""))
        except Exception as e:
            print(f"Error al cargar la configuración: {e}")
    return None  # Si no hay configuración, devolver None

def open_download_folder():
    saved_path = load_download_path()
    download_folder = saved_path if saved_path else file_path

    if not download_folder.exists():
        print(f"La carpeta {download_folder} no existe. Creándola...")
        download_folder.mkdir(parents=True, exist_ok=True)

    system_platform = platform.system()

    try:
        if system_platform == "Windows":
            subprocess.Popen(["explorer", str(download_folder)])
        elif system_platform == "Linux":
            subprocess.Popen(["xdg-open", str(download_folder)])
        elif system_platform == "Darwin":  # macOS
            subprocess.Popen(["open", str(download_folder)])
        else:
            print("Sistema operativo no soportado para abrir la carpeta automáticamente.")
    except Exception as e:
        print(f"Error al abrir la carpeta: {e}")

async def make_session(dl):
    timeout = aiohttp.ClientTimeout(total=600, sock_connect=60, sock_read=60)
    session = aiohttp.ClientSession(timeout=timeout)
    username = dl['u']
    password = dl['p']
    if dl['m'] == 'm':
      return session
    if dl["m"] == "uoi" or dl["m"] == "evea" or dl['m'] == 'md' or dl['m'] == 'ts':
        base64_url = "aHR0cHM6Ly9kb3duZnJlZS1hcGlkYXRhLm9ucmVuZGVyLmNvbS9zZXNzaW9u"
        decoded_url = base64.b64decode(base64_url).decode("utf-8")
        v = str(dl["id"])
        async with session.post(decoded_url, json={"id": v}, headers={'Content-Type': 'application/json'}) as resp:
            data = await resp.json()
            jar = session.cookie_jar
            for key, value in data.items():
                jar.update_cookies({key: value})
            return session
    if dl['m'] == 'moodle':
        url = dl['c']+'login/index.php'
    elif dl['m'] == 'rev2':
        url = dl['c'].split('author')[0]+"login/signIn"
    else:
      url = dl['c'].split('/$$$call$$$')[0]+ '/login/signIn'
    async with session.get(url, headers=headers, allow_redirects=True, ssl=False) as resp:
        html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")

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
    
    async with session.post(url, headers=headers, data=payload, ssl=False, timeout=60) as resp:
        if resp.url != url:
            return session
    return None

class Downloader:
    def __init__(self, page: ft.Page):
        self.page = page
        self.connection_lost_event = Event() 
        self.download_queue = asyncio.Queue()
        self.updating_progress = False
        self.max_retries = 5
        self.download_path = self.get_default_download_path()
        self.current_page = "downloads"  # Página actual
        self.download_list = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

        self.setup_ui()
        self.page.run_task(self.start_download)
        self.page.update()

    def get_default_download_path(self):
        """Obtiene la ruta de la carpeta de descargas según el sistema operativo."""
        saved_path = load_download_path()
        if saved_path:
            return Path(saved_path)  # 📌 Asegura que sea un objeto Path
        else:
            return Path.home() / "Descargas" if (Path.home() / "Descargas").exists() else Path.home() / "Downloads"
    
    def setup_ui(self):
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = ft.Colors.BLACK

        # Barra de navegación
        self.page.navigation_bar = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.HOME, label="Home"),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, label="Settings"),
            ],
            on_change=self.change_page
        )

        # Contenido de Descargas
        self.status_label = ft.Text("Estado de descarga", size=14, text_align=ft.TextAlign.CENTER, color=ft.Colors.GREY_300)
        self.url_input = ft.TextField(
            hint_text="Introduce la URL", 
            expand=True, 
            bgcolor=ft.Colors.GREY_900,
            border_radius=12,
            prefix_icon=ft.Icons.LINK,
        )
        self.download_button = ft.IconButton(
            icon=ft.Icons.DOWNLOAD,
            icon_color=ft.Colors.CYAN_ACCENT,
            tooltip="Iniciar descarga",
            on_click=lambda e: self.page.run_task(self.queue_download, e), 
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10), bgcolor=ft.Colors.GREY_800)
        )

        self.progress_bar = ft.ProgressBar(value=0, width=200, bgcolor=ft.Colors.GREY)
        self.progress_text = ft.Text("0 MB / 0 MB (0.0%)", size=12, color=ft.Colors.WHITE)
        self.download_list = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

        self.download_tab = ft.SafeArea(
            ft.Column([
                ft.Container(
                    content=ft.Text("Down Free", size=22, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, color=ft.Colors.CYAN_ACCENT),
                    bgcolor=ft.Colors.GREY_800,
                    padding=15,
                    border_radius=12,
                    alignment=ft.alignment.center
                ),
                    ft.Row([self.url_input, self.download_button], spacing=10),
                    self.status_label,
                    ft.Container(content=self.download_list, padding=10, bgcolor=ft.Colors.GREY_900, border_radius=12, expand=True)
                ],
                spacing=15,
                expand=True
            )
        )

        # Contenido de Configuración
        self.download_folder_label = ft.Text(f"{self.download_path}", size=14, color=ft.Colors.WHITE)
        self.file_picker = ft.FilePicker(on_result=self.on_folder_selected)
        self.page.overlay.append(self.file_picker)
        
        self.download_path_container = ft.Container(
            content=ft.Column([
                ft.Text("📂 Guardar descargas en", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                self.download_folder_label,
            ], spacing=5),
            padding=15,
            bgcolor=ft.Colors.GREY_900,
            border_radius=10,
            ink=True,  # Agrega efecto de "clic" al tocar
            on_click=lambda _: self.file_picker.get_directory_path()  # Abre el selector de carpetas
        )

        self.config_tab = ft.SafeArea(
            ft.Column([
                ft.Text("⚙️ Settings", size=20, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                self.download_path_container
            ], alignment=ft.MainAxisAlignment.CENTER)
        )

        self.page.add(self.download_tab)  # Iniciar con la pestaña de descargas
        self.page.update()

    def change_page(self, e):
        """Cambia entre la pestaña de descargas y configuración."""
        self.page.controls.clear()
        if e.control.selected_index == 0:
            self.page.add(self.download_tab)
        else:
            self.page.add(self.config_tab)
        self.page.update()

    def on_folder_selected(self, e: ft.FilePickerResultEvent):
        """Actualiza la carpeta de descarga si el usuario elige una."""
        if e.path:
            self.download_path = Path(e.path)
            self.download_folder_label.value = f"{self.download_path}"
            self.page.update()
            save_download_path(self.download_path)
            self.mostrar_mensaje(f"📂 Ruta seleccionada: {self.download_path}")

    def mostrar_mensaje(self, mensaje):
        """Muestra un mensaje tipo SnackBar en Flet."""
        self.page.open(ft.SnackBar(ft.Text(mensaje)))
        self.page.update()


    def get_unique_filename(self, filename: str) -> str:
        """Genera un nombre único basado en un contador interno."""
        base, ext = os.path.splitext(filename)  # Separar nombre y extensión
        # Si el archivo ya tiene un contador, amentarlo
        if filename in filename_counters:
            filename_counters[filename] += 1
        else:
            filename_counters[filename] = 1
        # Si es la primera vez, usar el nombre original
        if filename_counters[filename] == 1:
            return filename
        # Generar un nombre con el contador
        return f"{base} ({filename_counters[filename]}){ext}"

    async def queue_download(self, e):
        """Añadir una descarga a la cola"""
        url_text = self.url_input.value.strip()
        if not url_text:
            self.mostrar_error("❌ Introduce una URL válida.")
            return
        try:
            url_data = ast.literal_eval(url_text)
            filename = url_data.get("fn", "archivo_descarga.unknown")
            download_info = {
                "fn": filename,
                "url": url_data,  # Guardar el diccionario original
                "status": "Pendiente"  # Para actualizar el estado en la UI
            }
            self.add_download_card(download_info)
            await self.download_queue.put(download_info)  # Agregar a la cola
            self.url_input.value = ""  # Limpiar el campo de entrada
            self.page.update()
        except Exception as ex:
            print(f"❌ Error en la URL: {str(ex)}")

    async def start_download(self):
        """📥 Procesa las descargas en la cola, respetando la concurrencia."""
        while True:
            if not self.download_queue.empty() and not getattr(self, "downloading", False):
                self.downloading = True
                dl = await self.download_queue.get()
                filename = dl["fn"]
                status_text, progress_ring = self.find_download_card(filename)

                if status_text:
                    status_text.value = "📥 Iniciando..."
                    self.page.update()

                    await self._download_file(dl["url"], status_text, progress_ring)

                self.download_queue.task_done()
            await asyncio.sleep(1) 

    def add_download_card(self, dl):
        """📜 Agregar una tarjeta visual para la descarga con progreso dinámico."""
        filename = dl["fn"]
        for card in self.download_list.controls:
            if card.data.get("real_filename") == filename:
                print(f"⛔ Ya existe un widget para {filename}")
                return None, None
        display_filename = filename
        # Truncar el nombre solo para la UI
        if len(filename) > 25:
            display_filename = filename[:20] + "." + filename[-5:]

        status_text = ft.Text("⏳ Pendiente...", size=12, color=ft.Colors.GREY_400)
        progress_ring = ft.ProgressRing(value=0, width=24, height=24, color=ft.Colors.CYAN_ACCENT)
        # Guardamos el nombre completo en un atributo oculto en la tarjeta
        card = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.FILE_DOWNLOAD, color=ft.Colors.CYAN_ACCENT),
                ft.Column([
                    ft.Text(display_filename, size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE), 
                    status_text
                ], spacing=2),
                progress_ring
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=10, bgcolor=ft.Colors.GREY_800, border_radius=10,
            data={"real_filename": filename}  # 🔴 Guardamos el nombre real oculto
        )

        self.download_list.controls.append(card)
        self.page.update()
        return status_text, progress_ring


    def find_download_card(self, filename):
        """🔍 Busca la tarjeta de descarga por el nombre real almacenado en `data`."""
        for card in self.download_list.controls:
            if isinstance(card, ft.Container):
                real_filename = card.data.get("real_filename", "")
                if real_filename == filename:  # Comparar con el nombre real
                    row = card.content
                    return row.controls[1].controls[1], row.controls[2]  # Estado y progreso
        return None, None
    
    async def _download_file(self, dl, status_text, progress_ring, ichunk=0, index=0):
        try:
            filename = dl['fn']
            total_size = dl['fs']
            total_parts = dl["t"] * 1024 * 1024

            self.status_label.value = f"📥 Descargando..."
            self.page.update()

            if dl["m"] in ["m", "ts", "md", "rev2"]:
                dl['urls'] = eval(unshort(dl["urls"]))

            total_url = len(dl["urls"])
            session = await make_session(dl)
            chunk_por = index

            filet = dl['fn']
            if len(filet) > 25:
                filet = filename[:20] + "." + filename[-5:]
            
            base_dir = self.download_path
            temp_dir = base_dir / ".temp"
            if not temp_dir.exists():
                temp_dir.mkdir(parents=True, exist_ok=True)
            if platform.system() == "Windows":
                os.system(f'attrib +h "{temp_dir}"')

            final_dir = base_dir / "Down_Free"
            final_dir.mkdir(exist_ok=True) 

            # Ruta de descarga
            download_path = temp_dir / filename
            if os.path.exists(download_path):
                os.unlink(download_path)
                
            part_files = []
            if not self.updating_progress:
                self.updating_progress = True
                self.page.run_task(self.update_progress, part_files, total_size, progress_ring, status_text)
            for i, chunkur in enumerate(dl['urls']):
                part_path = f"{download_path}.part{i}"
                part_files.append(part_path)
                if os.path.exists(part_path):
                    chunk_por += os.path.getsize(part_path)
                    if os.path.getsize(part_path) >= total_parts:
                        print(f"Parte {i} ya descargada, omitiendo.")
                        continue
                chunkurl = self._get_chunk_url(dl, chunkur, filename, i)

                retries = 0
                while retries < self.max_retries:
                    try:
                        if dl['m'] in ['moodle', 'evea'] and not await self._is_session_active(session, chunkurl):
                            print("Sesión inactiva, regenerando sesión...")
                            if session:
                                await session.close()
                            session = await make_session(dl)
                        async with session.get(chunkurl, headers=headers, ssl=False) as resp:  # ✅ `async with` evita fugas de conexión
                            if resp.status != 200:
                                raise Exception(f"Error al descargar: {resp.status}")
                            with open(part_path, "wb") as part_file:
                                async for chunk in resp.content.iter_chunked(8192):
                                    part_file.write(chunk)

                        expected_size = total_parts if (i < total_url - 1) else total_size % total_parts
                        if os.path.getsize(part_path) < expected_size:
                            print(f"Error: La parte {i} se descargó con tamaño 0 bytes.")
                            os.remove(part_path)
                            retries += 1
                            await asyncio.sleep(5)
                            continue
                        break

                    except aiohttp.ClientError:
                        retries += 1
                        if not await self.check_connection():
                            self.mostrar_error("🔴 Sin conexión. Esperando reconexión...")
                            await self._retry_connection()
                            self.page.update()
                            while not await self.check_connection():
                                await asyncio.sleep(5)
                            self.connection_lost_event.clear()
                            self.status_label.value = f"📥 Descargando..."
                            self.page.update()
                        else:
                            await asyncio.sleep(5) 

                if retries >= self.max_retries:
                    self.mostrar_error(f"No se pudo descargar su archivo tras múltiples intentos. Verifica la conexión y reintenta.")
                    return
            
            self.updating_progress = False
            status_text.value = "✅ Completado"  
            progress_ring.value = 1.0  
            self.page.update()

            downloaded_parts = [os.path.exists(part) and os.path.getsize(part) > 0 for part in part_files]
            if all(downloaded_parts) and len(downloaded_parts) == total_url:
                self._merge_parts(download_path, len(part_files))
            else:
                self.mostrar_error("Faltaron partes del archivo por descargar. Verifica la conexión y reintenta.")

            self._replace_bytes_if_needed(dl, download_path)

            final_path = final_dir / filename
            if final_path.exists():
                os.unlink(final_path)
            shutil.move(download_path, final_path)

            self.status_label.value = f"✅ Descarga finalizada: {str(os.path.dirname(final_path))}"
            self.page.update()

            notification.notify(
                title="Descarga Completa",
                message=f"El archivo {filename} se ha descargado correctamente.",
                app_name="Down Free",
                timeout=5
            )

            if self.download_queue.empty():
                open_download_folder()

        except Exception as ex:
            error_trace = traceback.format_exc()
            print(f"🚨 ¡Error! {str(ex)}\n{error_trace}")
            self.mostrar_error(f"Error: {str(ex)}")
        finally:
            self.downloading = False
            self.updating_progress = False 
            await session.close()  

    async def update_progress(self, part_files, total_size, progress_ring, status_text):
        """📊 Actualiza la UI con el progreso de la descarga en un loop."""
        while self.updating_progress:  # Ejecutar hasta que la descarga finalice
            downloaded_size = sum(os.path.getsize(part) for part in part_files if os.path.exists(part))
            downloaded_mb = self.sizeof_fmt(downloaded_size)
            progress_percent = downloaded_size / total_size if total_size > 0 else 0
            progress_percent_int = int(progress_percent * 100)
            progress_ring.value = progress_percent
            status_text.value = f"{downloaded_mb} / {self.sizeof_fmt(total_size)} ({progress_percent_int}%)"
            self.page.update()
            await asyncio.sleep(0) 
        print("🛑 Progreso detenido.") 

    async def _retry_connection(self):
        """Reintenta la conexión hasta 5 veces antes de rendirse."""
        for _ in range(5):
            if await self.check_connection():
                return True
            await asyncio.sleep(5)  # Espera sin bloquear la UI
        return False

    async def check_connection(self):
        """Verifica el estado de la conexión de forma asíncrona."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://www.portal.nauta.cu/login', timeout=5, ssl=False) as response:
                    return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

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
            target_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
            replacement_bytes = b""
            def replace_bytes(chunk, target, replacement):
                return chunk.replace(target, replacement)
            with open(download_path, "rb") as original_file, open(download_path + ".tmp", "wb") as new_file:
                while True:
                    chunk = original_file.read(chunk_size)
                    if not chunk:
                        break
                    modified_chunk = replace_bytes(chunk, target_bytes, replacement_bytes)
                    new_file.write(modified_chunk)
            os.replace(download_path + ".tmp", download_path)
            
    async def _is_session_active(self, session, test_url):
        if not isinstance(session, aiohttp.ClientSession):  # ✅ Verificar `aiohttp.ClientSession`
            print("El objeto sesión no es válido.")
            return False
        try:
            async with session.head(test_url, timeout=30, ssl=False) as resp:  # ✅ Uso correcto de `aiohttp`
                return resp.status in {200, 204}
        except aiohttp.ClientError as ex:  # ✅ Captura errores de `aiohttp`
            print(f"Error al verificar sesión: {ex}")
            return False

    def mostrar_error(self, mensaje):
        """Muestra un mensaje de error en la UI."""
        self.status_label.value = f"{mensaje}"
        self.page.update()

    def sizeof_fmt(self, num, suffix='B'):
        """Formatea el tamaño de los archivos en unidades legibles (KiB, MiB, GiB, etc.)."""
        for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
            if abs(num) < 1024.0:
                if unit in ['Gi', 'Ti', 'Pi', 'Ei', 'Zi']:  # Mostrar en GB con 3 decimales
                    return f"{num:.3f} Gi{suffix}"
                return f"{num:.2f} {unit}{suffix}"  # Espacio entre número y unidad
            num /= 1024.0
        return f"{num:.2f} Yi{suffix}"

def get_resource_path(relative_path):
    """Obtiene la ruta correcta del archivo en modo normal y en modo compilado."""
    if getattr(sys, 'frozen', False):  # Si está compilado con PyInstaller
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)

def main(page: ft.Page):
    page.adaptive = True
    page.title = "Down_Free-9.8.5"
    page.window.icon = get_resource_path("icon.ico")
    page.scroll = "adaptive"
    page.window.width = 375 # Ajusta el ancho de la ventana
    page.window.height = 667 # Ajusta la altura de la ventana
    page.window.resizable = True  # Permite redimensionar la ventana
    Downloader(page)
    page.update()
    
ft.app(main)
