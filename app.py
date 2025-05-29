import subprocess
import os
import time
import sys
import tempfile
import pathlib

import socket # For internet connection check
import psutil # For checking running processes

from bs4 import BeautifulSoup
import customtkinter as ctk
from PIL import Image
import threading

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


# --- Configuration ---
# IMPORTANT: Replace this with the actual path to your idman.exe
IDM_PATH = r"C:\Program Files (x86)\Internet Download Manager\idman.exe"

# --- WebDriver Paths Configuration ---
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

DRIVER_DIR = os.path.join(BUNDLE_DIR, "drivers")
ASSETS_DIR = os.path.join(BUNDLE_DIR, "assets")

CHROMEDRIVER_PATH = os.path.join(DRIVER_DIR, "chromedriver.exe")
GECKODRIVER_PATH = os.path.join(DRIVER_DIR, "geckodriver.exe")
EDGEDRIVER_PATH = os.path.join(DRIVER_DIR, "msedgedriver.exe")

# --- Global variable to hold the selected browser type ---
selected_browser_type = "chrome" # Default selection


# --- Utility Functions for Checks ---
def is_connected_to_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False

def is_idm_running():
    for proc in psutil.process_iter(['name']):
        if proc.info['name'].lower() == 'idman.exe':
            return True
    return False

def launch_idm():
    if not is_idm_running():
        try:
            subprocess.Popen(IDM_PATH, creationflags=subprocess.DETACHED_PROCESS, close_fds=True)
            time.sleep(1) # Give IDM a moment to initialize
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False
    return True


# --- Helper Function: Get Full HTML Content using Selenium ---
def get_full_html_content_selenium(url, browser_type, log_callback,progress_callback=None):
    # MODIFICATION START
    url_to_load = url
    is_local_file = False

    # Check if the URL is a local file path
    if not (url.startswith('http://') or url.startswith('https://') or url.startswith('file:///')):
        if os.path.exists(url):
            is_local_file = True
            try:
                url_to_load = pathlib.Path(url).as_uri() # Convert system path to file:/// URI
            except Exception as e:
                log_callback(f"Error converting local path to URI: {e}. Trying to load directly.")
                url_to_load = url 
    elif url.startswith('file:///'):
        log_callback(f"Attempting to load local HTML file (URI provided): {url_to_load}")
        is_local_file = True 
    # MODIFICATION END

    if is_local_file:
        log_callback(f"Attempting to load local HTML file: {url_to_load}")
    else:
        log_callback(f"Opening headless {browser_type} with Selenium to fetch web URL: {url_to_load}")


    if progress_callback:
        progress_callback(0.05) # Indicate start of HTML fetching
    driver = None

    try:
        service = None
        options = None

        if browser_type.lower() == 'chrome':
            service = ChromeService(executable_path=CHROMEDRIVER_PATH)
            options = webdriver.ChromeOptions()
        elif browser_type.lower() == 'firefox':
            service = FirefoxService(executable_path=GECKODRIVER_PATH)
            options = webdriver.FirefoxOptions()
            options.add_argument("-headless")
        elif browser_type.lower() == 'edge':
            service = EdgeService(executable_path=EDGEDRIVER_PATH)
            options = webdriver.EdgeOptions()
        else:
            log_callback(f"ERROR: Unsupported browser type: {browser_type}.")
            return None

        if options and browser_type.lower() != 'firefox':
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--log-level=3")
            options.add_argument("--disable-logging")

        if browser_type.lower() == 'chrome':
            driver = webdriver.Chrome(service=service, options=options)
        elif browser_type.lower() == 'firefox':
            driver = webdriver.Firefox(service=service, options=options)
        elif browser_type.lower() == 'edge':
            driver = webdriver.Edge(service=service, options=options)

        driver.get(url_to_load)

        if progress_callback:
            progress_callback(0.15)

        wait = WebDriverWait(driver, 20)


        # MODIFICATION START: Conditional WebDriverWait
        if not is_local_file: # Only wait for dynamic elements if it's a web URL
            wait = WebDriverWait(driver, 20)
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "section.bg-light.mt-2.rounded.p-2.w-75.mx-auto"))
            )
            log_callback("Main download section loaded in browser. Extracting HTML.")
        else:
            log_callback("Local file loaded. Assuming content is static. Extracting HTML.")
        # MODIFICATION END


        if progress_callback:
            progress_callback(0.8) # Increased from 0.4, assuming this is a significant part of this function's work

        full_html = driver.page_source
        log_callback("Successfully fetched/loaded full HTML.")
        if progress_callback:
            progress_callback(1.0) # HTML fetching phase complete (1.0 for this function's scope)

        return full_html

    except FileNotFoundError as e: # This is for WebDriver executable
        log_callback(f"ERROR: WebDriver for {browser_type} not found at '{e.filename}'.")
        if progress_callback: progress_callback(0)
        return None
    except TimeoutException:
        log_callback(f"ERROR: Timeout waiting for the download section to appear on {url_to_load}.")
        log_callback("For local files, this section might be missing or not dynamically loaded.")
        if progress_callback: progress_callback(0)
        return None
    except WebDriverException as e:
        log_callback(f"ERROR: Selenium WebDriver failed for {browser_type} with {url_to_load}: {e}")
        # MODIFICATION START: Add hint for local file not found
        if "net::ERR_FILE_NOT_FOUND" in str(e) or "unknown error: net::ERR_FILE_NOT_FOUND" in str(e).lower():
            log_callback(f"Hint: The local file path '{url}' might be incorrect or not accessible by the browser driver.")
        # MODIFICATION END
        if progress_callback: progress_callback(0)
        return None
    except Exception as e:
        log_callback(f"An unexpected error occurred during HTML fetching for {url_to_load}: {e}")
        if progress_callback: progress_callback(0)
        return None
    finally:
        if driver:
            driver.quit()

# --- Function: Extract Download Links from HTML ---
def extract_download_links_from_html(html_content, log_callback):
    log_callback("Parsing HTML for download links...")



    # --- TEMPORARY DEBUG ---
    # print("----------- HTML CONTENT RECEIVED BY BeautifulSoup -----------")
    # print(html_content[:5000]) # Print the first 5000 characters to check
    # with open("debug_html_output.html", "w", encoding="utf-8") as f:
    #     f.write(html_content)
    # log_callback("Saved received HTML to debug_html_output.html")
    # print("--------------------------------------------------------------")
    # --- END TEMPORARY DEBUG ---


    soup = BeautifulSoup(html_content, 'html.parser')
    download_urls = []
    download_section = soup.find('section', class_='bg-light mt-2 rounded p-2 w-75 mx-auto')
    if not download_section:
        log_callback("WARNING: 'download_section' was not found. HTML structure might have changed or not be present in the local file.")
        return []
    links = download_section.find_all('a', class_='btn btn-success', href=True)
    if not links:
        log_callback("WARNING: No 'btn btn-success' download links found in the section.")
        return []
    for link in links:
        url = link['href']
        if url:
            download_urls.append(url)
    log_callback(f"Found {len(download_urls)} potential download links.")
    return list(set(download_urls))


# --- Function: Initiate Direct Download for Each URL using IDM CLI ---
# Modified to call count_progress_callback with the number of items processed in this call
def initiate_idm_direct_downloads(urls, idm_exec_path, log_callback, count_progress_callback=None):
    if not urls:
        log_callback("No URLs provided for download to IDM in this batch.")
        if count_progress_callback:
            count_progress_callback(0) # Report 0 items processed
        return 0 # Return count of processed items

    log_callback(f"Initiating {len(urls)} direct downloads in this batch via IDM...")
    successfully_sent_count = 0
    for i, url in enumerate(urls):
        command = [idm_exec_path, '/d', url, '/n', '/q', '/s']
        try:
            log_callback(f"[{i+1}/{len(urls)}] Sending: {os.path.basename(url.split('?')[0])}")
            subprocess.run(command, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(0.5) # Small delay between sending commands to IDM
            successfully_sent_count += 1
            if count_progress_callback:
                count_progress_callback(successfully_sent_count) # Report cumulative success within this batch
        except FileNotFoundError:
            log_callback(f"ERROR: IDM executable not found at '{idm_exec_path}'. Skipping remaining in batch.")
            break
        except Exception as e:
            log_callback(f"ERROR: Failed to send {os.path.basename(url.split('?')[0])} to IDM: {e}")
            # Optionally, still call progress callback if partial success is okay for the count
            # if count_progress_callback: count_progress_callback(successfully_sent_count)
    log_callback(f"Sent {successfully_sent_count}/{len(urls)} requests to IDM for this batch.")
    return successfully_sent_count


# --- GUI Application Class ---
class DownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("CircleFTP Batch Downloader")
        self.geometry("600x580") # Increased height for batch size input
        self.grid_columnconfigure(0, weight=1)
        # self.grid_rowconfigure(5, weight=1) # Adjusted later for new layout

        self.selected_browser_button = None
        self.browser_button_default_color = ("#3B8ED0", "#1F6AA5")

        # --- Batch processing state variables ---
        self.all_extracted_urls = []
        self.current_url_index = 0
        self.initial_fetch_done = False


        # --- URL Section ---
        self.url_frame = ctk.CTkFrame(self)
        self.url_frame.grid(row=0, column=0, padx=20, pady=(10,5), sticky="ew")
        self.url_frame.grid_columnconfigure(0, weight=1)
        self.url_label = ctk.CTkLabel(self.url_frame, text="Content Page URL:")
        self.url_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.url_entry = ctk.CTkEntry(self.url_frame, placeholder_text="http://new.circleftp.net/content/00000", height=35)
        self.url_entry.grid(row=1, column=0, padx=(10, 3), pady=(5,10), sticky="ew")
        self.paste_icon = self.load_icon("paste_icon2.png", size=(24, 24))
        self.paste_button = ctk.CTkButton(self.url_frame, text="", image=self.paste_icon, height=35 ,width=40, command=self.paste_from_clipboard)
        self.paste_button.grid(row=1, column=1, padx=(3, 10), pady=(5,10))

        # --- Browser Selection Section ---
        self.browser_frame = ctk.CTkFrame(self)
        self.browser_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        self.browser_frame.grid_columnconfigure((0,1,2), weight=1)
        self.browser_label = ctk.CTkLabel(self.browser_frame, text="Choose Browser:")
        self.browser_label.grid(row=0, column=0, columnspan=3, padx=10, pady=5, sticky="w")
        browser_icon_size = 35
        self.chrome_icon = self.load_icon("chrome_icon.png", size=(browser_icon_size, browser_icon_size))
        self.firefox_icon = self.load_icon("firefox_icon.png", size=(browser_icon_size, browser_icon_size))
        self.edge_icon = self.load_icon("edge_icon.png", size=(browser_icon_size, browser_icon_size))
        browser_button_height = 70
        self.chrome_button = ctk.CTkButton(self.browser_frame, text="Chrome", image=self.chrome_icon, compound="top", command=lambda: self.select_browser("chrome"), fg_color=self.browser_button_default_color,height=browser_button_height)
        self.chrome_button.grid(row=1, column=0, padx=(15, 10), pady=(8, 15), sticky="ew")
        self.firefox_button = ctk.CTkButton(self.browser_frame, text="Firefox", image=self.firefox_icon, compound="top", command=lambda: self.select_browser("firefox"), fg_color=self.browser_button_default_color,height=browser_button_height)
        self.firefox_button.grid(row=1, column=1, padx=10, pady=(8, 15), sticky="ew")
        self.edge_button = ctk.CTkButton(self.browser_frame, text="Edge", image=self.edge_icon, compound="top", command=lambda: self.select_browser("edge"), fg_color=self.browser_button_default_color,height=browser_button_height)
        self.edge_button.grid(row=1, column=2, padx=(10, 15), pady=(8, 15), sticky="ew")
        self.select_browser("chrome", initial_setup=True)


        # --- Batch Size Section ---
        self.batch_frame = ctk.CTkFrame(self)
        self.batch_frame.grid(row=2, column=0, padx=20, pady=(5,5), sticky="ew")
        # Configure columns for label, entry, and slider
        self.batch_frame.grid_columnconfigure(0, weight=0) # Label
        self.batch_frame.grid_columnconfigure(1, weight=0) # Entry
        self.batch_frame.grid_columnconfigure(2, weight=1) # Slider (to take remaining space)

        self.batch_label = ctk.CTkLabel(self.batch_frame, text="Batch size:")
        self.batch_label.grid(row=0, column=0, padx=(10,5), pady=5, sticky="w")

        self.batch_size_entry = ctk.CTkEntry(self.batch_frame, placeholder_text="e.g., 5", width=70) # Adjusted width
        self.batch_size_entry.grid(row=0, column=1, padx=(0,10), pady=5, sticky="w")
        self.batch_size_entry.insert(0, "5") # Default batch size

        # Variable to link slider and potentially entry (though entry is prime for validation)
        self.batch_slider_var = ctk.IntVar(value=5)
        self.batch_slider = ctk.CTkSlider(
            self.batch_frame,
            from_=1,
            to=16, # Common upper limit for slider; entry can accept higher values
            number_of_steps=15, # (to - from_)
            variable=self.batch_slider_var, # Link to the IntVar
            command=self._update_batch_entry_from_slider # Update entry when slider moves
        )
        self.batch_slider.grid(row=0, column=2, padx=(0, 10), pady=5, sticky="ew")
        self.batch_slider.set(5) # Ensure slider visual matches the default

        # Bind entry modification to update slider (optional, for better sync)
        self.batch_size_entry.bind("<FocusOut>", self._update_slider_from_batch_entry_event)
        self.batch_size_entry.bind("<Return>", self._update_slider_from_batch_entry_event)

        # --- Start Button ---
        self.start_button = ctk.CTkButton(self, text="Start Download", command=self.handle_start_or_continue, height=40)
        self.start_button.grid(row=3, column=0, padx=20, pady=(8, 12), sticky="ew") # Row updated

        # --- Log Textbox ---
        logbox_font = ("Consolas", 12)
        self.log_textbox = ctk.CTkTextbox(self, width=500, height=150, font=logbox_font)
        self.log_textbox.grid(row=4, column=0, padx=20, pady=10, sticky="nsew") # Row updated
        self.log_textbox.insert("end", "Welcome to CircleFTP Batch Downloader!\n")
        self.log_textbox.configure(state="disabled")
        self.grid_rowconfigure(4, weight=1) # Make log textbox row expandable

        # --- Progress Bar and Clear Log Button ---
        self.bottom_controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_controls_frame.grid(row=5, column=0, padx=(22, 20), pady=(0,10), sticky="ew") # Row updated
        self.bottom_controls_frame.grid_columnconfigure(0, weight=1)
        self.bottom_controls_frame.grid_columnconfigure(1, weight=0)
        self.progress_bar = ctk.CTkProgressBar(self.bottom_controls_frame, mode="determinate", height=12)
        self.progress_bar.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="ew")
        self.progress_bar.set(0)
        self.clear_log_button = ctk.CTkButton(self.bottom_controls_frame, text="Clear Log", command=self.clear_log, width=100)
        self.clear_log_button.grid(row=0, column=1, padx=(10,0), pady=0, sticky="e")


    def clear_log(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        self.log_message("Log cleared.")

    def load_icon(self, icon_filename, size=(32, 32)):
        try:
            image_path = os.path.join(ASSETS_DIR, icon_filename)
            image = Image.open(image_path)
            # Image.LANCZOS is deprecated, use Image.Resampling.LANCZOS
            image = image.resize(size, Image.Resampling.LANCZOS)
            return ctk.CTkImage(light_image=image, dark_image=image, size=size)
        except FileNotFoundError:
            self.log_message(f"ERROR: Icon '{icon_filename}' not found at '{image_path}'.")
            return None
        except Exception as e:
            self.log_message(f"ERROR loading icon '{icon_filename}': {e}")
            return None

    def paste_from_clipboard(self):
        try:
            clipboard_content = self.clipboard_get()
            self.url_entry.delete(0, ctk.END)
            self.url_entry.insert(0, clipboard_content)
            self.log_message("Pasted URL from clipboard.")
        except ctk.TclError:
            self.log_message("ERROR: Could not access clipboard.")

    def select_browser(self, browser_name, initial_setup=False):
        global selected_browser_type
        default_fg_color = ctk.ThemeManager.theme["CTkButton"]["fg_color"]
        hover_fg_color = ctk.ThemeManager.theme["CTkButton"]["hover_color"]
        self.chrome_button.configure(fg_color=default_fg_color)
        self.firefox_button.configure(fg_color=default_fg_color)
        self.edge_button.configure(fg_color=default_fg_color)
        if browser_name == "chrome":
            self.chrome_button.configure(fg_color=hover_fg_color)
            selected_browser_type = "chrome"
        elif browser_name == "firefox":
            self.firefox_button.configure(fg_color=hover_fg_color)
            selected_browser_type = "firefox"
        elif browser_name == "edge":
            self.edge_button.configure(fg_color=hover_fg_color)
            selected_browser_type = "edge"
        if not initial_setup:
            self.log_message(f"Selected browser: {browser_name.capitalize()}")

    def log_message(self, message):
        self.after(0, lambda: self._update_log_textbox(message))

    def _update_log_textbox(self, message):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _update_progress_bar(self, value):
        self.after(0, lambda: self.progress_bar.set(value))


    def _set_ui_state_processing(self, is_processing):
        if is_processing:
            self.start_button.configure(state="disabled", text="Working...")
            self.paste_button.configure(state="disabled")
            self.chrome_button.configure(state="disabled")
            self.firefox_button.configure(state="disabled")
            self.edge_button.configure(state="disabled")
            self.url_entry.configure(state="disabled")
            self.batch_size_entry.configure(state="disabled")
            self.clear_log_button.configure(state="disabled")
        else: # Resetting or enabling for next step
            # Specific button text and states will be set by the calling logic
            self.paste_button.configure(state="normal")
            self.chrome_button.configure(state="normal")
            self.firefox_button.configure(state="normal")
            self.edge_button.configure(state="normal")
            self.url_entry.configure(state="normal")
            self.batch_size_entry.configure(state="normal") # Usually enabled unless mid-total-process
            self.clear_log_button.configure(state="normal")


    def handle_start_or_continue(self):
        
        url = self.url_entry.get().strip()
        if not self.initial_fetch_done and not url : # Only check URL if it's the very first start
            self.log_message("Please enter a URL first!")
            return

        try:
            batch_size_str = self.batch_size_entry.get()
            if not batch_size_str:
                self.log_message("ERROR: Batch size cannot be empty.")
                return
            batch_size = int(batch_size_str)
            if batch_size <= 0:
                self.log_message("ERROR: Batch size must be a positive number.")
                return
        except ValueError:
            self.log_message("ERROR: Invalid batch size. Please enter a number.")
            return

        self._set_ui_state_processing(True)

        if not self.initial_fetch_done: # Corresponds to "Start Download"
            self.log_message("\n--- Starting Download Process ---")
            self.current_url_index = 0
            self.all_extracted_urls = []
            self._update_progress_bar(0)
            thread = threading.Thread(target=self._initial_fetch_and_first_batch_thread, args=(url, batch_size))
        else: # Corresponds to "Continue"
            self.log_message(f"\n--- Continuing with next batch ({batch_size} links) ---")
            thread = threading.Thread(target=self._send_batch_thread, args=(batch_size,))
        
        thread.daemon = True
        thread.start()

    def _initial_fetch_and_first_batch_thread(self, url_or_path, batch_size):
        # --- Pre-checks ---
        # Pre-checks for IDM are always needed
        self.log_message("Performing pre-flight checks for IDM...")
        if not os.path.exists(IDM_PATH):
            self.log_message(f"ERROR: IDM executable not found at '{IDM_PATH}'.")
            self.after(0, self._reset_ui_after_error, "Start Download")
            return
        if not launch_idm():
            self.log_message("ERROR: Could not launch IDM.")
            self.after(0, self._reset_ui_after_error, "Start Download")
            return
        self.log_message("IDM is running or launched successfully.")

        # --- MODIFICATION START: Conditional Internet Check ---
        is_web_url = url_or_path.startswith('http://') or url_or_path.startswith('https://')
        if is_web_url:
            self.log_message("Checking internet connection for web URL...")
            if not is_connected_to_internet():
                self.log_message("ERROR: No active internet connection for web URL.")
                self.after(0, self._reset_ui_after_error, "Start Download")
                return
            self.log_message("Internet connection verified for web URL.")
        else:
            self.log_message("Skipping internet check for local file path.")
        # --- MODIFICATION END ---

        
        # --- Fetch HTML (0% to 40% of progress) ---
        def selenium_progress_update(p_val): # p_val is 0.0 to 1.0 for selenium's task
            self.after(0, lambda: self._update_progress_bar(p_val * 0.40))

        html_content = get_full_html_content_selenium(url_or_path, selected_browser_type, self.log_message, selenium_progress_update)
        if not html_content:
            self.log_message("Failed to retrieve HTML content. Cannot proceed.")
            self.after(0, self._reset_ui_after_error, "Start Download")
            return
        self.after(0, lambda: self._update_progress_bar(0.40)) # Ensure it's at 40%

        # --- Extract Links (40% to 50% of progress) ---
        self.log_message("Extracting links...")
        self.all_extracted_urls = extract_download_links_from_html(html_content, self.log_message)
        self.after(0, lambda: self._update_progress_bar(0.50)) # At 50% after extraction

        if not self.all_extracted_urls:
            self.log_message("No download links were extracted from the provided URL.")
            self.after(0, self._reset_ui_after_error, "Start Download")
            return

        self.log_message(f"\nSuccessfully extracted {len(self.all_extracted_urls)} total download URLs.")
        for dl_url in self.all_extracted_urls:
             self.log_message(f"- {os.path.basename(dl_url.split('?')[0])}")

        self.initial_fetch_done = True # Mark that initial fetch is complete
        self.current_url_index = 0    # Reset index for sending

        # --- Send First Batch ---
        self._send_batch_thread(batch_size, is_first_batch=True)


    def _send_batch_thread(self, batch_size, is_first_batch=False):
        start_idx = self.current_url_index
        end_idx = min(start_idx + batch_size, len(self.all_extracted_urls))
        urls_to_send_this_batch = self.all_extracted_urls[start_idx:end_idx]

        if not urls_to_send_this_batch:
            if not is_first_batch : # Avoid double message if no links found initially
                 self.log_message("No more links to send in this batch or all links processed.")
            if self.current_url_index >= len(self.all_extracted_urls) and self.all_extracted_urls:
                 self.log_message("All download links have been sent to IDM.")
            self.after(0, self._finalize_all_downloads)
            return

        # --- Send to IDM (50% to 100% of progress overall) ---
        # links_processed_before_this_batch accounts for links sent in *previous* batches
        links_processed_before_this_batch = start_idx 
        total_links_overall = len(self.all_extracted_urls)

        def idm_item_processed_callback(items_done_in_current_idm_call):
            # items_done_in_current_idm_call is the count of links processed by *this specific IDM call for the current batch*
            total_links_sent_for_idm_phase = links_processed_before_this_batch + items_done_in_current_idm_call
            # The IDM sending phase constitutes 50% of the total progress bar (0.5 to 1.0)
            progress_for_idm_phase = (total_links_sent_for_idm_phase / total_links_overall) * 0.5
            overall_progress = 0.5 + progress_for_idm_phase # Add the 0.5 from fetch/extract phase
            self.after(0, lambda: self._update_progress_bar(min(overall_progress, 1.0)))

        initiate_idm_direct_downloads(urls_to_send_this_batch, IDM_PATH, self.log_message, idm_item_processed_callback)
        
        self.current_url_index = end_idx # Update main index

        # Ensure progress bar reflects completion of this batch
        final_progress_for_idm_phase = (self.current_url_index / total_links_overall) * 0.5
        final_overall_progress = 0.5 + final_progress_for_idm_phase
        self.after(0, lambda: self._update_progress_bar(min(final_overall_progress, 1.0)))


        if self.current_url_index < total_links_overall:
            self.log_message(f"Batch of {len(urls_to_send_this_batch)} links sent. {total_links_overall - self.current_url_index} links remaining.")
            self.after(0, lambda: self.start_button.configure(text="Continue", state="normal"))
            self.after(0, lambda: self.batch_size_entry.configure(state="normal")) # Allow changing batch size
            self.after(0, lambda: self.clear_log_button.configure(state="normal"))
            # Keep URL and browser selection disabled until fully reset
            self.after(0, lambda: self.paste_button.configure(state="disabled"))
            self.after(0, lambda: self.chrome_button.configure(state="disabled"))
            self.after(0, lambda: self.firefox_button.configure(state="disabled"))
            self.after(0, lambda: self.edge_button.configure(state="disabled"))
            self.after(0, lambda: self.url_entry.configure(state="disabled"))


        else:
            self.log_message("All download links have been sent to IDM.")
            self.after(0, self._finalize_all_downloads)


    def _reset_ui_after_error(self, button_text="Start Download"):
        self.log_message("\n--- Process Interrupted or Failed ---")
        self._update_progress_bar(0)
        self._set_ui_state_processing(False) # Re-enables most controls
        self.start_button.configure(text=button_text, state="normal")
        # Reset state variables
        self.all_extracted_urls = []
        self.current_url_index = 0
        self.initial_fetch_done = False


    def _finalize_all_downloads(self):
        self.log_message("\n--- All Batches Processed or Process Ended ---")
        # Set progress to full only if links were extracted AND all were processed
        if self.all_extracted_urls and self.current_url_index >= len(self.all_extracted_urls):
            self.after(0, lambda: self._update_progress_bar(1.0))
        else: # Handles cases like no links found, or process reset before completion
            self.after(0, lambda: self._update_progress_bar(0.0))

            
        self._set_ui_state_processing(False) # Re-enables most controls
        self.start_button.configure(text="Start Download", state="normal")
        # Reset state variables for a completely new run
        self.all_extracted_urls = []
        self.current_url_index = 0
        self.initial_fetch_done = False

    
    def _update_batch_entry_from_slider(self, value_from_slider):
        # value_from_slider is a float, convert to int for batch size
        int_value = int(round(value_from_slider)) # Round to nearest int
        current_entry_text = self.batch_size_entry.get()
        
        # Update entry only if the integer value is different to avoid flicker/loops
        # and to ensure that if entry had a value > slider_max, it's not overwritten by slider
        if current_entry_text != str(int_value):
            self.batch_size_entry.delete(0, ctk.END)
            self.batch_size_entry.insert(0, str(int_value))

    def _update_slider_from_batch_entry_event(self, event=None): # event arg for bindings
        try:
            entry_val_str = self.batch_size_entry.get()
            if not entry_val_str: # Handle empty entry case
                # Optionally set slider to a default or min value, or do nothing here
                # and let the main validation in handle_start_or_continue catch it.
                # For instance, reset slider to its current var value if entry is invalidly cleared
                self.batch_slider_var.set(self.batch_slider_var.get()) # No change if empty or invalid
                return

            entry_val = int(entry_val_str)
            slider_min = self.batch_slider.cget("from_")
            slider_max = self.batch_slider.cget("to")

            # If entry value is within slider range, update slider
            if slider_min <= entry_val <= slider_max:
                if self.batch_slider_var.get() != entry_val:
                    self.batch_slider_var.set(entry_val)
            # If entry value is outside, clamp slider to its boundaries if you want it to reflect that
            # Or, just let the entry hold the "master" value and slider shows max/min
            elif entry_val < slider_min:
                 if self.batch_slider_var.get() != slider_min:
                    self.batch_slider_var.set(slider_min)
            elif entry_val > slider_max:
                 if self.batch_slider_var.get() != slider_max:
                    self.batch_slider_var.set(slider_max)

        except ValueError:
            # If entry is not a valid integer, user might be typing.
            # We can optionally revert the entry to the slider's last valid integer value
            # or simply do nothing and let the main validation on "Start/Continue" handle it.
            # For now, let's make it less intrusive and not auto-correct the entry here.
            # If an invalid char is typed, it won't update the slider.
            # On FocusOut/Return, if it's still invalid, the main validation will catch it.
            pass

# --- Main application entry point ---
if __name__ == "__main__":
    os.makedirs(DRIVER_DIR, exist_ok=True) # Ensure driver dir exists
    os.makedirs(ASSETS_DIR, exist_ok=True) # Ensure assets dir exists

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    app = DownloaderApp()
    app.mainloop()