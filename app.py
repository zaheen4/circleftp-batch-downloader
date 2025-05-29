import subprocess
import os
import time
import sys
import pathlib  # For platform-independent file path handling
import json     # For application settings
import socket   # For internet connection check
import psutil   # For checking running processes

from bs4 import BeautifulSoup # HTML parsing
import customtkinter as ctk    # GUI framework
from customtkinter import filedialog # GUI file dialogs
from PIL import Image          # Icon handling
import threading               # For background tasks

# Selenium Imports - for browser automation
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# --- Base Directory Configuration (for .exe bundling) ---
if getattr(sys, 'frozen', False): # Running as a bundled exe
    BUNDLE_DIR = sys._MEIPASS
else: # Running as a .py script
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Configuration File for User Settings ---
# Stored in user's home directory for persistence.
CONFIG_DIR = os.path.join(os.path.expanduser('~'), 'CircleFTPDownloaderConfig')
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# --- Resource Directories ---
DRIVER_DIR = os.path.join(BUNDLE_DIR, "drivers")
ASSETS_DIR = os.path.join(BUNDLE_DIR, "assets")

CHROMEDRIVER_PATH = os.path.join(DRIVER_DIR, "chromedriver.exe")
GECKODRIVER_PATH = os.path.join(DRIVER_DIR, "geckodriver.exe")
EDGEDRIVER_PATH = os.path.join(DRIVER_DIR, "msedgedriver.exe")

# --- Utility Functions ---
def is_connected_to_internet(host="8.8.8.8", port=53, timeout=3):
    """Checks for an active internet connection."""
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False

# --- Selenium HTML Fetching ---
def get_full_html_content_selenium(url, browser_type, log_callback, progress_callback=None):
    """Fetches HTML from a URL or local file using Selenium."""
    url_to_load = url
    is_local_file = False

    # Determine if input is a local file path and convert to URI if so
    if not (url.startswith('http://') or url.startswith('https://') or url.startswith('file:///')):
        if os.path.exists(url):
            is_local_file = True
            try:
                url_to_load = pathlib.Path(url).as_uri()
            except Exception as e:
                log_callback(f"Error converting local path to URI: {e}. Trying original path.")
    elif url.startswith('file:///'):
        is_local_file = True

    if is_local_file:
        log_callback(f"Loading local HTML: {url_to_load}")
    else:
        log_callback(f"Fetching web URL via {browser_type}: {url_to_load}")

    if progress_callback: progress_callback(0.05)
    driver = None
    try:
        # WebDriver setup (service, options) based on browser_type
        service = None
        options = None

        if browser_type.lower() == 'chrome':
            service = ChromeService(executable_path=CHROMEDRIVER_PATH)
            options = webdriver.ChromeOptions()
        elif browser_type.lower() == 'firefox':
            service = FirefoxService(executable_path=GECKODRIVER_PATH)
            options = webdriver.FirefoxOptions()
            options.add_argument("-headless") # Firefox needs this specific argument for headless
        elif browser_type.lower() == 'edge':
            service = EdgeService(executable_path=EDGEDRIVER_PATH)
            options = webdriver.EdgeOptions()
        else:
            log_callback(f"ERROR: Unsupported browser: {browser_type}.")
            return None

        # Common headless options for Chrome and Edge
        if options and browser_type.lower() != 'firefox':
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--log-level=3")
            options.add_argument("--disable-logging")

        # Initialize WebDriver
        if browser_type.lower() == 'chrome':
            driver = webdriver.Chrome(service=service, options=options)
        elif browser_type.lower() == 'firefox':
            driver = webdriver.Firefox(service=service, options=options)
        elif browser_type.lower() == 'edge':
            driver = webdriver.Edge(service=service, options=options)

        driver.get(url_to_load)
        if progress_callback: progress_callback(0.15)

        # Wait for the main download section to ensure page is fully loaded,
        # but skip this for local files as content is assumed static.
        if not is_local_file:
            wait = WebDriverWait(driver, 20) # 20-second timeout
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "section.bg-light.mt-2.rounded.p-2.w-75.mx-auto"))
            )
            log_callback("Main download section loaded.")
        else:
            log_callback("Local file loaded; skipping dynamic element wait.")

        if progress_callback: progress_callback(0.8)
        full_html = driver.page_source
        log_callback("Successfully fetched/loaded full HTML.")
        if progress_callback: progress_callback(1.0)
        return full_html

    except FileNotFoundError as e:
        log_callback(f"ERROR: WebDriver for {browser_type} not found at '{e.filename}'. Check 'drivers' folder.")
        if progress_callback: progress_callback(0)
        return None
    except TimeoutException:
        log_callback(f"ERROR: Timeout waiting for download section on {url_to_load}.")
        if is_local_file: log_callback("For local files, section might be missing or JS-dependent.")
        if progress_callback: progress_callback(0)
        return None
    except WebDriverException as e:
        log_callback(f"ERROR: Selenium WebDriver failed for {browser_type} with {url_to_load}: {e}")
        if "net::ERR_FILE_NOT_FOUND" in str(e).lower():
            log_callback(f"Hint: Local file path '{url}' might be incorrect.")
        if progress_callback: progress_callback(0)
        return None
    except Exception as e:
        log_callback(f"Unexpected error during Selenium fetching for {url_to_load}: {e}")
        if progress_callback: progress_callback(0)
        return None
    finally:
        if driver:
            driver.quit() # Ensure browser closes

# --- HTML Parsing ---
def extract_download_links_from_html(html_content, log_callback):
    """Extracts download URLs from the provided HTML content."""
    log_callback("Parsing HTML for download links...")
    soup = BeautifulSoup(html_content, 'html.parser')
    download_urls = []
    
    # Specific selector for the download links section on the target site
    download_section = soup.find('section', class_='bg-light mt-2 rounded p-2 w-75 mx-auto')
    if not download_section:
        log_callback("WARNING: Download section not found. HTML structure might have changed.")
        return []
    
    # Specific selector for the download anchor tags
    links = download_section.find_all('a', class_='btn btn-success', href=True)
    if not links:
        log_callback("WARNING: No download links (<a> tags with 'btn-success') found in section.")
        return []
        
    for link in links:
        url = link['href']
        if url:
            download_urls.append(url)
            
    log_callback(f"Found {len(download_urls)} potential download links.")
    return list(set(download_urls)) # Return unique links

# --- IDM Integration ---
def initiate_idm_direct_downloads(urls, idm_exec_path, log_callback, count_progress_callback=None):
    """Sends a list of URLs to IDM for downloading."""
    if not urls:
        log_callback("No URLs provided to IDM for this batch.")
        if count_progress_callback: count_progress_callback(0)
        return 0

    log_callback(f"Sending {len(urls)} links to IDM for this batch...")
    successfully_sent_count = 0
    for i, url in enumerate(urls):
        # IDM command-line arguments: /d <URL> /n (no questions) /q (add to queue) /s (start queue)
        command = [idm_exec_path, '/d', url, '/n', '/q', '/s']
        try:
            # Using os.path.basename to log a cleaner version of the URL
            log_callback(f"[{i+1}/{len(urls)}] Sending: {os.path.basename(url.split('?')[0])}")
            subprocess.run(command, creationflags=subprocess.CREATE_NO_WINDOW) # Hide console window
            time.sleep(0.5) # Brief pause to avoid overwhelming IDM
            successfully_sent_count += 1
            if count_progress_callback:
                count_progress_callback(successfully_sent_count)
        except FileNotFoundError:
            log_callback(f"ERROR: IDM executable not found at '{idm_exec_path}'. Aborting batch.")
            break # Stop processing this batch if IDM path is wrong
        except Exception as e:
            log_callback(f"ERROR sending {os.path.basename(url.split('?')[0])} to IDM: {e}")
            
    log_callback(f"Sent {successfully_sent_count}/{len(urls)} requests to IDM for this batch.")
    return successfully_sent_count

# --- GUI Application Class ---
class DownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("CircleFTP Batch Downloader")
        
        # --- Window Sizing and Positioning ---
        app_width = 580
        app_height = 640 # Adjusted for new UI elements
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        # Position on the right side of the screen
        margin_right = 20 
        margin_top = 40   
        x_coordinate = max(screen_width - app_width - margin_right, 0)
        y_coordinate_centered = int((screen_height / 2) - (app_height / 2))
        y_coordinate = max(y_coordinate_centered, margin_top)
        if y_coordinate + app_height > screen_height: # Prevent going off bottom
            y_coordinate = max(screen_height - app_height - margin_top, margin_top)

        self.geometry(f"{app_width}x{app_height}+{x_coordinate}+{y_coordinate}")



        self.grid_columnconfigure(0, weight=1) # Main column expands

        # --- Internal State Variables ---
        self.selected_browser_button = None # Tracks the currently selected browser button
        self.browser_button_default_color = ("#3B8ED0", "#1F6AA5") # Standard CTk button color
        self.all_extracted_urls = []
        self.current_url_index = 0
        self.initial_fetch_done = False
        self.selected_browser_type = "chrome" # Default browser

        # --- Font Definitions ---
        default_font = ("", 14)
        ftp_url_font = ("", 13)
        idm_path_font = ("Tahoma", 12)
        idm_path_browse_font = ("", 13)
        start_button_font = ("Trebuchet MS", 16)
        abort_button_font = ("Trebuchet MS", 16)
        logbox_font = ("Consolas", 12)
        clear_log_text_font = ("", 11) 

        # --- UI Element Setup ---
        # URL Input Section
        self.url_frame = ctk.CTkFrame(self)
        self.url_frame.grid(row=0, column=0, padx=20, pady=(10,5), sticky="ew")
        self.url_frame.grid_columnconfigure(0, weight=1)  # URL entry expands
        self.url_frame.grid_columnconfigure(1, weight=0)  # Clear button
        self.url_frame.grid_columnconfigure(2, weight=0)  # Paste button


        self.url_label = ctk.CTkLabel(self.url_frame, text="CircleFTP URL:", font=default_font)
        self.url_label.grid(row=0, column=0, columnspan=3, padx=10, pady=5, sticky="w") # Span for clarity

        self.url_entry = ctk.CTkEntry(self.url_frame, placeholder_text="http://...", font=ftp_url_font, height=35)
        self.url_entry.grid(row=1, column=0, padx=(10, 3), pady=(5,10), sticky="ew")

        self.clear_icon = self.load_icon("backspace_icon.png", size=(25, 25)) # Using a backspace icon
        self.clear_url_button = ctk.CTkButton(self.url_frame, text="", image=self.clear_icon, height=35, width=40, command=self._clear_url_entry)
        self.clear_url_button.grid(row=1, column=1, padx=(3, 3), pady=(5,10))

        self.paste_icon = self.load_icon("paste_icon2.png", size=(24, 24))
        self.paste_button = ctk.CTkButton(self.url_frame, text="", image=self.paste_icon, height=35 ,width=40, command=self.paste_from_clipboard)
        self.paste_button.grid(row=1, column=2, padx=(0, 10), pady=(5,10))



        # Browser Selection Section
        self.browser_frame = ctk.CTkFrame(self)
        self.browser_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        self.browser_frame.grid_columnconfigure((0,1,2), weight=1) # Equal weight for browser buttons

        self.browser_label = ctk.CTkLabel(self.browser_frame, text="Choose Browser (for web URLs):", font=default_font)
        self.browser_label.grid(row=0, column=0, columnspan=3, padx=10, pady=5, sticky="w")

        browser_icon_size = 35
        browser_button_height = 70
        self.chrome_icon = self.load_icon("chrome_icon.png", size=(browser_icon_size, browser_icon_size))
        self.firefox_icon = self.load_icon("firefox_icon.png", size=(browser_icon_size, browser_icon_size))
        self.edge_icon = self.load_icon("edge_icon.png", size=(browser_icon_size, browser_icon_size))


        self.chrome_button = ctk.CTkButton(self.browser_frame, text="Chrome", font=default_font, image=self.chrome_icon, compound="top", command=lambda: self.select_browser("chrome"), fg_color=self.browser_button_default_color, height=browser_button_height)
        self.chrome_button.grid(row=1, column=0, padx=(15, 10), pady=(8, 15), sticky="ew")

        self.firefox_button = ctk.CTkButton(self.browser_frame, text="Firefox", font=default_font, image=self.firefox_icon, compound="top", command=lambda: self.select_browser("firefox"), fg_color=self.browser_button_default_color, height=browser_button_height)
        self.firefox_button.grid(row=1, column=1, padx=10, pady=(8, 15), sticky="ew")

        self.edge_button = ctk.CTkButton(self.browser_frame, text="Edge", font=default_font, image=self.edge_icon, compound="top", command=lambda: self.select_browser("edge"), fg_color=self.browser_button_default_color, height=browser_button_height)
        self.edge_button.grid(row=1, column=2, padx=(10, 15), pady=(8, 15), sticky="ew")
        # self.select_browser("chrome", initial_setup=True) # Called after loading config

        # IDM Path Configuration Section
        self.idm_frame = ctk.CTkFrame(self)
        self.idm_frame.grid(row=2, column=0, padx=20, pady=5, sticky="ew")
        self.idm_frame.grid_columnconfigure(1, weight=1) # Path entry expands

        self.idm_label = ctk.CTkLabel(self.idm_frame, text="IDM Path:", font=default_font)
        self.idm_label.grid(row=0, column=0, padx=(10,5), pady=5, sticky="w")

        self.idm_path_entry = ctk.CTkEntry(self.idm_frame, placeholder_text=r"C:\Program Files (x86)\Internet Download Manager\IDMan.exe", font=idm_path_font)
        self.idm_path_entry.grid(row=0, column=1, padx=(0,5), pady=5, sticky="ew")
        # self.idm_path_entry.insert(0, r"C:\Program Files (x86)\Internet Download Manager\idman.exe") # Default set by _load_config
        self.idm_path_entry.configure(state="disabled") 
        self.idm_browse_button = ctk.CTkButton(self.idm_frame, text="Browse...", font=idm_path_browse_font, command=self._browse_idm_path, width=80)
        self.idm_browse_button.grid(row=0, column=2, padx=(0,10), pady=5, sticky="e")



        # Batch Size Configuration Section
        self.batch_frame = ctk.CTkFrame(self)
        self.batch_frame.grid(row=3, column=0, padx=20, pady=(5,5), sticky="ew")
        self.batch_frame.grid_columnconfigure(2, weight=1) # Slider expands

        self.batch_label = ctk.CTkLabel(self.batch_frame, text="Batch Size:", font=default_font)
        self.batch_label.grid(row=0, column=0, padx=(10,5), pady=5, sticky="w")

        self.batch_size_entry = ctk.CTkEntry(self.batch_frame, placeholder_text="e.g., 5", width=70)
        self.batch_size_entry.grid(row=0, column=1, padx=(0,10), pady=5, sticky="w")
        # self.batch_size_entry.insert(0, "5") # Default set by _load_config

        self.batch_slider_var = ctk.IntVar(value=5) # Default for var
        self.batch_slider = ctk.CTkSlider(self.batch_frame, from_=1, to=16, number_of_steps=15, variable=self.batch_slider_var, command=self._update_batch_entry_from_slider)
        self.batch_slider.grid(row=0, column=2, padx=(0, 10), pady=5, sticky="ew")
        # self.batch_slider.set(5) # Set by _load_config via _update_slider_from_batch_entry_event

        self.batch_size_entry.bind("<FocusOut>", self._update_slider_from_batch_entry_event)
        self.batch_size_entry.bind("<Return>", self._update_slider_from_batch_entry_event)



        # Action Buttons Frame (Start/Continue, Abort)
        self.action_buttons_frame = ctk.CTkFrame(self, fg_color="transparent")

        self.action_buttons_frame.grid(row=4, column=0, padx=20, pady=(8, 12), sticky="ew")
        self.action_buttons_frame.grid_columnconfigure(0, weight=5) # Start/Continue button gets more space
        self.action_buttons_frame.grid_columnconfigure(1, weight=1) # Abort button

        self.start_button = ctk.CTkButton(self.action_buttons_frame, text="Start Download", font=start_button_font, command=self.handle_start_or_continue, height=40)
        self.start_button.grid(row=0, column=0, columnspan=2, padx=(0,0), pady=0, sticky="ew") # Initially spans both columns

        self.abort_button = ctk.CTkButton(self.action_buttons_frame, text="Abort", font=abort_button_font, command=self._abort_process, height=40, fg_color="firebrick", hover_color="#B22222")
        self.abort_button.grid_remove() # Initially hidden



        # Log Textbox
        self.log_textbox = ctk.CTkTextbox(self, width=500, height=150, font=logbox_font)
        self.log_textbox.grid(row=5, column=0, padx=20, pady=10, sticky="nsew")
        self.log_textbox.insert("end", "Welcome to CircleFTP Batch Downloader!\n")
        self.log_textbox.configure(state="disabled")
        self.grid_rowconfigure(5, weight=1) # Log textbox expands vertically



        # Bottom Controls (Progress Bar, Clear Log)
        self.bottom_controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_controls_frame.grid(row=6, column=0, padx=(22, 20), pady=(0,10), sticky="ew")
        self.bottom_controls_frame.grid_columnconfigure(0, weight=1) # Progress bar expands

        self.progress_bar = ctk.CTkProgressBar(self.bottom_controls_frame, mode="determinate", height=12)
        self.progress_bar.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="ew")
        self.progress_bar.set(0)

        self.clear_log_button = ctk.CTkButton(self.bottom_controls_frame, text="Clear Log", font=clear_log_text_font, command=self.clear_log, width=90)
        self.clear_log_button.grid(row=0, column=1, padx=(10,0), pady=0, sticky="e")



        # --- Final Setup ---
        self._load_config() # Load saved settings (this will set defaults if no config file)
        self.select_browser(self.selected_browser_type, initial_setup=True) # Now select after buttons are created and config loaded
        self.protocol("WM_DELETE_WINDOW", self.on_closing) # Save config on exit



    # --- App Methods ---
    def _abort_process(self):
        """Aborts the current batch download process."""
        self.log_message("\n--- Download Process Aborted by User ---")
        self._finalize_all_downloads() # Resets state and UI

    def _clear_url_entry(self):
        """Clears the URL entry field."""
        self.url_entry.delete(0, ctk.END)
        self.log_message("URL entry cleared.")

    def is_idm_running(self):
        """Checks if idman.exe process is currently running."""
        for proc in psutil.process_iter(['name']):
            if proc.info['name'].lower() == 'idman.exe':
                return True
        return False

    def launch_idm_with_path(self, idm_exec_path):
        """Launches IDM using the given path if it's not already running."""
        if not self.is_idm_running():
            try:
                subprocess.Popen(idm_exec_path, creationflags=subprocess.DETACHED_PROCESS, close_fds=True)
                time.sleep(1) # Give IDM a moment
                return True
            except FileNotFoundError:
                self.log_message(f"ERROR launching IDM: File not found at {idm_exec_path}")
                return False
            except Exception as e:
                self.log_message(f"ERROR launching IDM: {e}")
                return False
        return True

    def _browse_idm_path(self):
        """Opens a file dialog to select the IDMan.exe path."""
        filepath = filedialog.askopenfilename(
            title="Select IDMan.exe",
            filetypes=(("Executable files", "*.exe"), ("All files", "*.*"))
        )
        if filepath:
            self.idm_path_entry.configure(state="normal") # Enable to change
            self.idm_path_entry.delete(0, ctk.END)
            self.idm_path_entry.insert(0, filepath)
            self.idm_path_entry.configure(state="disabled") # Disable again
            self.log_message(f"IDM path set to: {filepath}")

    def _load_config(self):
        """Loads application settings from the config file."""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        default_idm_path = r"C:\Program Files (x86)\Internet Download Manager\IDMan.exe"
        default_browser = "chrome"
        default_batch_size = "5"

        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)

                idm_path = config.get("idm_path", default_idm_path)
                self.idm_path_entry.delete(0, ctk.END)
                self.idm_path_entry.insert(0, idm_path)

                self.url_entry.delete(0, ctk.END)
                self.url_entry.insert(0, config.get("last_url", ""))

                batch_size = str(config.get("batch_size", default_batch_size))
                self.batch_size_entry.delete(0, ctk.END)
                self.batch_size_entry.insert(0, batch_size)
                
                self.selected_browser_type = config.get("browser", default_browser)
                # self.select_browser(self.selected_browser_type) # Called after UI init

                self.log_message("Configuration loaded.")
            else:
                self.log_message("No config file found. Using defaults and creating one on exit.")
                # Set defaults in UI if no config file
                self.idm_path_entry.delete(0, ctk.END)
                self.idm_path_entry.insert(0, default_idm_path)
                self.batch_size_entry.delete(0, ctk.END)
                self.batch_size_entry.insert(0, default_batch_size)
                self.selected_browser_type = default_browser

            self._update_slider_from_batch_entry_event() # Sync slider with entry value

        except json.JSONDecodeError:
            self.log_message("ERROR: Config file corrupted. Using defaults.")
        except Exception as e:
            self.log_message(f"ERROR loading config: {e}. Using defaults.")
        # Fallback to ensure UI elements have some default if errors occur
        if not self.idm_path_entry.get(): self.idm_path_entry.insert(0, default_idm_path)
        if not self.batch_size_entry.get(): self.batch_size_entry.insert(0, default_batch_size)
        self._update_slider_from_batch_entry_event()


    def _save_config(self):
        """Saves current settings to the config file."""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        config = {
            "idm_path": self.idm_path_entry.get(),
            "last_url": self.url_entry.get(),
            "browser": self.selected_browser_type,
            "batch_size": self.batch_size_entry.get()
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=4)
            # self.log_message("Configuration saved.") # Optional: log on save
        except Exception as e:
            self.log_message(f"ERROR saving configuration: {e}")

    def on_closing(self):
        """Handles window close event: saves config and destroys window."""
        self._save_config()
        self.destroy()

    def clear_log(self):
        """Clears the log textbox."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        self.log_message("Log cleared.")

    def load_icon(self, icon_filename, size=(32, 32)):
        """Loads an image icon from the assets folder."""
        try:
            image_path = os.path.join(ASSETS_DIR, icon_filename)
            image = Image.open(image_path)
            image = image.resize(size, Image.Resampling.LANCZOS) # Updated resampling method
            return ctk.CTkImage(light_image=image, dark_image=image, size=size)
        except FileNotFoundError:
            self.log_message(f"ERROR: Icon '{icon_filename}' not found at '{image_path}'.")
        except Exception as e:
            self.log_message(f"ERROR loading icon '{icon_filename}': {e}")
        return None # Return None if loading fails

    def paste_from_clipboard(self):
        """Pastes content from clipboard to URL entry."""
        try:
            clipboard_content = self.clipboard_get()
            self.url_entry.delete(0, ctk.END)
            self.url_entry.insert(0, clipboard_content)
            self.log_message("Pasted from clipboard.")
        except ctk.TclError:
            self.log_message("ERROR: Could not access clipboard.")

    def select_browser(self, browser_name, initial_setup=False):
        """Handles browser selection button styling and updates selected browser type."""
        default_fg_color = ctk.ThemeManager.theme["CTkButton"]["fg_color"]
        hover_fg_color = ctk.ThemeManager.theme["CTkButton"]["hover_color"]
        
        buttons = [self.chrome_button, self.firefox_button, self.edge_button]
        for button in buttons: # Reset all buttons
            if hasattr(button, 'configure'): # Ensure button exists
                 button.configure(fg_color=default_fg_color)

        if browser_name == "chrome" and hasattr(self, 'chrome_button'):
            self.chrome_button.configure(fg_color=hover_fg_color)
            self.selected_browser_type = "chrome"
        elif browser_name == "firefox" and hasattr(self, 'firefox_button'):
            self.firefox_button.configure(fg_color=hover_fg_color)
            self.selected_browser_type = "firefox"
        elif browser_name == "edge" and hasattr(self, 'edge_button'):
            self.edge_button.configure(fg_color=hover_fg_color)
            self.selected_browser_type = "edge"
        
        if not initial_setup: # Don't log during initial setup before logbox might be ready
            self.log_message(f"Selected browser: {browser_name.capitalize()}.")


    def log_message(self, message):
        """Thread-safe logging to the GUI textbox."""
        self.after(0, lambda: self._update_log_textbox(message))

    def _update_log_textbox(self, message):
        """Internal method to update the log textbox (called by log_message)."""
        if hasattr(self, 'log_textbox'): # Ensure log_textbox exists
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", message + "\n")
            self.log_textbox.see("end") # Scroll to the end
            self.log_textbox.configure(state="disabled")

    def _update_progress_bar(self, value):
        """Thread-safe update of the progress bar."""
        self.after(0, lambda: self.progress_bar.set(value))

    def _set_ui_state_processing(self, is_processing):
        """Enables/disables UI elements based on processing state."""
        controls_to_disable = [
            self.paste_button, self.chrome_button, self.firefox_button,
            self.edge_button, self.url_entry, self.batch_size_entry,
            self.clear_log_button, self.idm_browse_button, self.idm_path_entry,
            self.batch_slider # Disable slider as well
        ]
        
        if is_processing:
            self.start_button.configure(state="disabled", text="Working...")
            for control in controls_to_disable:
                if hasattr(control, 'configure'): control.configure(state="disabled")
        else: # Resetting or enabling for next step
            # self.start_button state/text handled by caller
            for control in controls_to_disable:
                 if hasattr(control, 'configure'): control.configure(state="normal")
            # self.idm_path_entry.configure(state="disabled") # IDM path usually not editable during run

    def handle_start_or_continue(self):
        """Handles clicks on the 'Start Download' or 'Continue' button."""
        url_or_path = self.url_entry.get().strip()
        if not self.initial_fetch_done and not url_or_path:
            self.log_message("Please enter a URL or local file path first!")
            return

        try:
            batch_size_str = self.batch_size_entry.get()
            if not batch_size_str:
                self.log_message("ERROR: Batch size cannot be empty.")
                return
            batch_size = int(batch_size_str)
            if batch_size <= 0:
                self.log_message("ERROR: Batch size must be positive.")
                return
        except ValueError:
            self.log_message("ERROR: Invalid batch size. Please enter a number.")
            return
        
        # IDM Path check (moved here for both Start and Continue)
        idm_path_from_ui = self.idm_path_entry.get()
        if not idm_path_from_ui or not os.path.exists(idm_path_from_ui):
            self.log_message(f"ERROR: Invalid IDM path: '{idm_path_from_ui}'. Please set it correctly.")
            self._set_ui_state_processing(False) # Re-enable UI to fix path
            self.start_button.configure(state="normal", text="Start Download" if not self.initial_fetch_done else "Continue")
            return

        self._set_ui_state_processing(True)
        self.abort_button.grid_remove() # Always hide abort when initiating a process step
        self.start_button.grid_configure(columnspan=2, padx=(0,0)) # Main button takes full width

        if not self.initial_fetch_done:
            self.log_message("\n--- Starting Download Process ---")
            self.current_url_index = 0
            self.all_extracted_urls = []
            self._update_progress_bar(0)
            thread = threading.Thread(target=self._initial_fetch_and_first_batch_thread, args=(url_or_path, batch_size))
        else:
            self.log_message(f"\n--- Continuing with batch ({batch_size} links) ---")
            thread = threading.Thread(target=self._send_batch_thread, args=(batch_size,))
        
        thread.daemon = True # Allows main program to exit even if thread is running
        thread.start()

    def _initial_fetch_and_first_batch_thread(self, url_or_path, batch_size):
        """Thread worker for initial fetch and first batch processing."""
        idm_path_from_ui = self.idm_path_entry.get() # Already validated in handle_start_or_continue

        self.log_message(f"Performing IDM checks with path: {idm_path_from_ui}")
        if not self.launch_idm_with_path(idm_path_from_ui):
            self.log_message("ERROR: Could not launch or verify IDM.")
            self.after(0, self._reset_ui_after_error, "Start Download")
            return
        self.log_message("IDM is running or launched successfully.")

        is_web_url = url_or_path.startswith('http://') or url_or_path.startswith('https://')
        if is_web_url:
            self.log_message("Checking internet connection for web URL...")
            if not is_connected_to_internet():
                self.log_message("ERROR: No active internet connection.")
                self.after(0, self._reset_ui_after_error, "Start Download")
                return
            self.log_message("Internet connection verified.")
        else:
            self.log_message("Input is a local file path; skipping internet check.")
        
        def selenium_progress_update(p_val):
            self.after(0, lambda: self._update_progress_bar(p_val * 0.40)) # Fetching is 0-40% of total

        html_content = get_full_html_content_selenium(url_or_path, self.selected_browser_type, self.log_message, selenium_progress_update)
        if not html_content:
            self.log_message("Failed to retrieve/load HTML. Cannot proceed.")
            self.after(0, self._reset_ui_after_error, "Start Download")
            return
        self.after(0, lambda: self._update_progress_bar(0.40))

        self.log_message("Extracting links from HTML...")
        self.all_extracted_urls = extract_download_links_from_html(html_content, self.log_message)
        self.after(0, lambda: self._update_progress_bar(0.50)) # Extraction brings to 50%

        if not self.all_extracted_urls:
            self.log_message("No download links were extracted.")
            self.after(0, self._reset_ui_after_error, "Start Download")
            return

        self.log_message(f"\nSuccessfully extracted {len(self.all_extracted_urls)} total URLs.")
        # Optional: Log all extracted URLs if needed, can be verbose
        # for i, dl_url in enumerate(self.all_extracted_urls):
        # self.log_message(f"  {i+1}. {os.path.basename(dl_url.split('?')[0])}")

        self.initial_fetch_done = True
        self.current_url_index = 0
        self._send_batch_thread(batch_size, is_first_batch=True) # Proceed to send first batch

    def _send_batch_thread(self, batch_size, is_first_batch=False):
        """Thread worker for sending a batch of URLs to IDM."""
        idm_path_from_ui = self.idm_path_entry.get() # Already validated in handle_start_or_continue

        start_idx = self.current_url_index
        end_idx = min(start_idx + batch_size, len(self.all_extracted_urls))
        urls_to_send_this_batch = self.all_extracted_urls[start_idx:end_idx]

        if not urls_to_send_this_batch:
            # This case should ideally be caught if all_extracted_urls was empty earlier,
            # or if current_url_index >= len(all_extracted_urls)
            if self.initial_fetch_done and self.all_extracted_urls : # Only log this if fetch was done and there were URLs
                 self.log_message("All links from this session have been processed.")
            self.after(0, self._finalize_all_downloads)
            return
        
        links_processed_before_this_batch = start_idx 
        total_links_overall = len(self.all_extracted_urls)

        def idm_item_processed_callback(items_done_in_current_idm_call):
            total_links_sent_for_idm_phase = links_processed_before_this_batch + items_done_in_current_idm_call
            progress_for_idm_phase = (total_links_sent_for_idm_phase / total_links_overall) * 0.5 # Sending is 50-100%
            overall_progress = 0.5 + progress_for_idm_phase
            self.after(0, lambda: self._update_progress_bar(min(overall_progress, 1.0)))

        initiate_idm_direct_downloads(urls_to_send_this_batch, idm_path_from_ui, self.log_message, idm_item_processed_callback)
        self.current_url_index = end_idx

        # Final progress update after batch is sent
        final_progress_for_idm_phase = (self.current_url_index / total_links_overall) * 0.5
        final_overall_progress = 0.5 + final_progress_for_idm_phase
        self.after(0, lambda: self._update_progress_bar(min(final_overall_progress, 1.0)))

        if self.current_url_index < total_links_overall:
            self.log_message(f"Batch of {len(urls_to_send_this_batch)} links sent. {total_links_overall - self.current_url_index} remaining.")
            # Setup UI for "Continue" state
            self.after(0, lambda: self.start_button.configure(text="Continue", state="normal"))
            self.after(0, lambda: self.start_button.grid_configure(columnspan=1, padx=(0,5))) # Continue button takes 1st col
            self.after(0, lambda: self.abort_button.grid(row=0, column=1, padx=(5, 0), pady=0, sticky="ew")) # Show Abort
            self.after(0, lambda: self.abort_button.configure(state="normal"))
            
            # Re-enable only batch size and clear log for next step
            self.after(0, lambda: self.batch_size_entry.configure(state="normal"))
            self.after(0, lambda: self.batch_slider.configure(state="normal")) # Also re-enable slider
            self.after(0, lambda: self.clear_log_button.configure(state="normal"))
            
            # Keep others disabled
            self.after(0, lambda: self.paste_button.configure(state="disabled"))
            self.after(0, lambda: self.chrome_button.configure(state="disabled"))
            self.after(0, lambda: self.firefox_button.configure(state="disabled"))
            self.after(0, lambda: self.edge_button.configure(state="disabled"))
            self.after(0, lambda: self.url_entry.configure(state="disabled"))
            self.after(0, lambda: self.idm_path_entry.configure(state="disabled"))
            self.after(0, lambda: self.idm_browse_button.configure(state="disabled"))
        else:
            self.log_message("All download links have been sent to IDM.")
            self.after(0, self._finalize_all_downloads)

    def _reset_ui_after_error(self, button_text="Start Download"):
        """Resets UI after an error, allowing user to try again."""
        self.log_message("\n--- Process Failed or Interrupted ---")
        self._update_progress_bar(0)
        self._set_ui_state_processing(False) # Re-enables most input controls
        self.start_button.configure(text=button_text, state="normal")
        self.start_button.grid_configure(columnspan=2, padx=(0,0)) # Start button takes full width
        self.abort_button.grid_remove() # Hide abort button
        
        # Reset processing state variables
        self.all_extracted_urls = []
        self.current_url_index = 0
        self.initial_fetch_done = False

    def _finalize_all_downloads(self):
        """Finalizes the download process, resetting UI for a new operation."""
        self.log_message("\n--- All Batches Processed or Process Ended ---")
        if self.all_extracted_urls and self.current_url_index >= len(self.all_extracted_urls):
            self.after(0, lambda: self._update_progress_bar(1.0)) # Full progress if all completed
        else:
            self.after(0, lambda: self._update_progress_bar(0.0)) # Reset if not fully completed or aborted

        self._set_ui_state_processing(False) # Re-enables most input controls
        self.start_button.configure(text="Start Download", state="normal")
        self.start_button.grid_configure(columnspan=2, padx=(0,0)) # Start button takes full width
        self.abort_button.grid_remove() # Hide abort button

        # Reset processing state variables for a completely new run
        self.all_extracted_urls = []
        self.current_url_index = 0
        self.initial_fetch_done = False
    
    def _update_batch_entry_from_slider(self, value_from_slider):
        """Updates the batch size entry when the slider is moved."""
        int_value = int(round(value_from_slider))
        current_entry_text = self.batch_size_entry.get()
        if current_entry_text != str(int_value):
            self.batch_size_entry.delete(0, ctk.END)
            self.batch_size_entry.insert(0, str(int_value))

    def _update_slider_from_batch_entry_event(self, event=None):
        """Updates the slider position based on the batch size entry value."""
        try:
            entry_val_str = self.batch_size_entry.get()
            if not entry_val_str: # If entry is cleared, do nothing or reset slider
                # self.batch_slider_var.set(self.batch_slider.cget("from_")) # Option: reset to min
                return

            entry_val = int(entry_val_str)
            slider_min = self.batch_slider.cget("from_")
            slider_max = self.batch_slider.cget("to")

            if slider_min <= entry_val <= slider_max: # Value is within slider range
                if self.batch_slider_var.get() != entry_val:
                    self.batch_slider_var.set(entry_val)
            elif entry_val < slider_min: # Clamp to slider min
                if self.batch_slider_var.get() != slider_min: self.batch_slider_var.set(slider_min)
            elif entry_val > slider_max: # Clamp to slider max
                if self.batch_slider_var.get() != slider_max: self.batch_slider_var.set(slider_max)
        except ValueError:
            pass # Ignore if entry is not a valid integer (e.g., during typing)

# --- Main application entry point ---
if __name__ == "__main__":
    # Ensure necessary directories exist on startup
    os.makedirs(DRIVER_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    # Config directory is created in _load_config/_save_config

    ctk.set_appearance_mode("System") # Or "Light", "Dark"
    ctk.set_default_color_theme("blue") # Or "green", "dark-blue"

    app = DownloaderApp()
    app.mainloop()