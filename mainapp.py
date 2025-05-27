import subprocess
import os
import time
import sys
import tempfile

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
    """
    Checks if there's an active internet connection by trying to connect
    to a well-known host (Google's DNS server by default).
    """
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False

def is_idm_running():
    """Checks if idman.exe process is currently running."""
    for proc in psutil.process_iter(['name']):
        if proc.info['name'].lower() == 'idman.exe':
            return True
    return False

def launch_idm():
    """Launches IDM if it's not already running."""
    if not is_idm_running():
        try:
            subprocess.Popen(IDM_PATH, creationflags=subprocess.DETACHED_PROCESS, close_fds=True)
            return True
        except FileNotFoundError:
            return False # IDM path is wrong or not found
        except Exception:
            return False
    return True # IDM was already running or successfully launched




# --- Helper Function: Get Full HTML Content using Selenium ---
def get_full_html_content_selenium(url, browser_type, log_callback,progress_callback=None):
    log_callback(f"Opening headless {browser_type} with Selenium to fetch: {url}")
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
            options.add_argument("-headless")   # Firefox uses -headless argument
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

        driver.get(url)


        if progress_callback:
            progress_callback(0.15) # Indicate page loaded, waiting for elements


        wait = WebDriverWait(driver, 20)
        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "section.bg-light.mt-2.rounded.p-2.w-75.mx-auto"))
        )
        log_callback("Main download section loaded in browser. Extracting HTML.")
        if progress_callback:
            progress_callback(0.4) # Indicate element found, now getting source

        full_html = driver.page_source
        log_callback("Successfully fetched full HTML via Selenium.")
        if progress_callback:
            progress_callback(0.5) # HTML fetching phase complete

        return full_html

    except FileNotFoundError as e:
        log_callback(f"ERROR: WebDriver for {browser_type} not found at '{e.filename}'.")
        log_callback("Make sure the correct WebDriver executable is downloaded and placed in the 'drivers' subfolder.")
        if progress_callback: progress_callback(0) # Reset on error
        return None
    except TimeoutException:
        log_callback(f"ERROR: Timeout waiting for the download section to appear on {url}.")
        log_callback("The page might be taking too long to load, or the CSS selector is incorrect.")
        if progress_callback: progress_callback(0) # Reset on error
        return None
    except WebDriverException as e:
        log_callback(f"ERROR: Selenium WebDriver failed for {browser_type}: {e}")
        log_callback(f"This could be due to a version mismatch between {browser_type} browser and its WebDriver, or other browser issues.")
        if progress_callback: progress_callback(0) # Reset on error
        return None
    except Exception as e:
        log_callback(f"An unexpected error occurred during Selenium fetching for {browser_type}: {e}")
        if progress_callback: progress_callback(0) # Reset on error
        return None
    finally:
        if driver:
            driver.quit()

# --- Function: Extract Download Links from HTML ---
def extract_download_links_from_html(html_content, log_callback):
    log_callback("Parsing HTML for download links...")
    soup = BeautifulSoup(html_content, 'html.parser')
    download_urls = []

    download_section = soup.find('section', class_='bg-light mt-2 rounded p-2 w-75 mx-auto')

    if not download_section:
        log_callback("WARNING: 'download_section' was not found by BeautifulSoup. HTML structure might have changed.")
        return []

    links = download_section.find_all('a', class_='btn btn-success', href=True)

    if not links:
        log_callback("WARNING: No 'btn btn-success' download links found within the identified section.")
        return []

    for link in links:
        url = link['href']
        if url:
            download_urls.append(url)

    log_callback(f"Found {len(download_urls)} potential download links.")
    return list(set(download_urls))

# --- Function: Initiate Direct Download for Each URL using IDM CLI ---
def initiate_idm_direct_downloads(urls, idm_exec_path, log_callback, progress_callback=None):
    if not urls:
        log_callback("No URLs provided for download to IDM.")
        if progress_callback: progress_callback(1.0) # Complete if no URLs
        return

    log_callback(f"\nInitiating {len(urls)} direct downloads via IDM...")

    # Calculate initial progress value after HTML phase (0.5)
    # Remaining 0.5 of progress bar will be for sending IDM links
    base_progress = 0.5
    progress_per_url = (1.0 - base_progress) / len(urls) if urls else 0

    for i, url in enumerate(urls):
        command = [
            idm_exec_path,
            '/d', url,
            '/n',
            '/q',
            '/s'
        ]

        try:
            log_callback(f"[{i+1}/{len(urls)}] Sending direct download for: {os.path.basename(url.split('?')[0])}")
            subprocess.run(command, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(0.5)

            if progress_callback:
                current_progress = base_progress + (i + 1) * progress_per_url
                progress_callback(current_progress) # Update progress bar

        except FileNotFoundError:
            log_callback(f"ERROR: IDM executable not found at '{idm_exec_path}'. Skipping remaining downloads.")
            if progress_callback: progress_callback(0) # Reset on error
            break
        except Exception as e:
            log_callback(f"ERROR: Failed to send direct download for {os.path.basename(url.split('?')[0])} to IDM: {e}")
            
            # Continue to next URL even if one fails
            if progress_callback: progress_callback(base_progress + (i + 1) * progress_per_url) # Still advance bar even on error for this link


    log_callback("\nAll download requests sent to IDM.")
    log_callback("Files should be starting in IDM according to its internal 'Save To' and concurrent download settings.")
    if progress_callback:
        progress_callback(1.0) # Ensure bar is full at the end

# --- GUI Application Class ---
class DownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("CircleFTP Batch Downloader")
        self.geometry("600x530")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        self.selected_browser_button = None

        # --- Custom Colors ---
        # Define a custom color for unselected buttons or a subtle highlight
        # This will be the default color for *unselected* browser buttons
        self.browser_button_default_color = ("#3B8ED0", "#1F6AA5") # Default CTkButton color (light/dark)
        # We will now use ctk.ThemeManager.theme["CTkButton"]["hover_color"] for the selected state.
        # So, you don't need a separate self.browser_button_selected_color anymore if you want it to match hover.

        # --- URL Section ---
        self.url_frame = ctk.CTkFrame(self)
        self.url_frame.grid(row=0, column=0, padx=20, pady=10, sticky="ew")
        self.url_frame.grid_columnconfigure(0, weight=1)

        self.url_label = ctk.CTkLabel(self.url_frame, text="Content Page URL:")
        self.url_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        #  URL entry 
        self.url_entry = ctk.CTkEntry(self.url_frame, placeholder_text="http://new.circleftp.net/content/00000", height=35) # Increased height
        self.url_entry.grid(row=1, column=0, padx=(10, 3), pady=(5,10), sticky="ew")

        # Load Paste icon
        self.paste_icon = self.load_icon("paste_icon2.png", size=(24, 24)) # Adjust size as needed for paste button
        self.paste_button = ctk.CTkButton(self.url_frame, text="", image=self.paste_icon, height=35 ,width=40, # Small width for icon button
                                           command=self.paste_from_clipboard)
        self.paste_button.grid(row=1, column=1, padx=(3, 10), pady=(5,10))


        # --- Browser Selection Section ---
        self.browser_frame = ctk.CTkFrame(self)
        self.browser_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        self.browser_frame.grid_columnconfigure((0,1,2), weight=1)

        self.browser_label = ctk.CTkLabel(self.browser_frame, text="Choose Browser:")
        self.browser_label.grid(row=0, column=0, columnspan=3, padx=10, pady=5, sticky="w")

        # Load browser icons
        browser_icon_size = 35
        self.chrome_icon = self.load_icon("chrome_icon.png", size=(browser_icon_size, browser_icon_size)) # Slightly larger icons for main buttons
        self.firefox_icon = self.load_icon("firefox_icon.png", size=(browser_icon_size, browser_icon_size))
        self.edge_icon = self.load_icon("edge_icon.png", size=(browser_icon_size, browser_icon_size))


        browser_button_height = 70
        self.chrome_button = ctk.CTkButton(self.browser_frame, text="Chrome", image=self.chrome_icon,
                                           compound="top", command=lambda: self.select_browser("chrome"),
                                           fg_color=self.browser_button_default_color,height=browser_button_height) # Apply default color
        self.chrome_button.grid(row=1, column=0, padx=(15, 10), pady=(8, 15), sticky="ew")

        self.firefox_button = ctk.CTkButton(self.browser_frame, text="Firefox", image=self.firefox_icon,
                                            compound="top", command=lambda: self.select_browser("firefox"),
                                            fg_color=self.browser_button_default_color,height=browser_button_height)
        self.firefox_button.grid(row=1, column=1, padx=10, pady=(8, 15), sticky="ew")

        self.edge_button = ctk.CTkButton(self.browser_frame, text="Edge", image=self.edge_icon,
                                         compound="top", command=lambda: self.select_browser("edge"),
                                         fg_color=self.browser_button_default_color,height=browser_button_height)
        self.edge_button.grid(row=1, column=2, padx=(10, 15), pady=(8, 15), sticky="ew")

        # Select Chrome by default on startup
        self.select_browser("chrome", initial_setup=True)

        # --- Start Button ---
        # Make Start button taller
        self.start_button = ctk.CTkButton(self, text="Start Download", command=self.start_download_process, height=40) # Increased height
        self.start_button.grid(row=2, column=0, padx=20, pady=(8, 12), sticky="ew")



        # --- Log Textbox ---

        logbox_font = ("Consolas", 12)
        self.log_textbox = ctk.CTkTextbox(self, width=500, height=150, font=logbox_font)
        self.log_textbox.grid(row=3, column=0, padx=20, pady=10, sticky="nsew")
        self.log_textbox.insert("end", "Welcome to CircleFTP Batch Downloader!\n")
        self.log_textbox.configure(state="disabled")



        #  --- Progress Bar and Clear Log Button (New Row) ---
        self.bottom_controls_frame = ctk.CTkFrame(self, fg_color="transparent") # Use transparent frame
        self.bottom_controls_frame.grid(row=4, column=0, padx=(22, 20), pady=(0,10), sticky="ew")
        self.bottom_controls_frame.grid_columnconfigure(0, weight=1) # Progress bar takes most space
        self.bottom_controls_frame.grid_columnconfigure(1, weight=0) # Clear button fixed size

        
        self.progress_bar = ctk.CTkProgressBar(self.bottom_controls_frame, mode="determinate", height=12)
        self.progress_bar.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="ew") # Placed in sub-frame, left side
        self.progress_bar.set(0)

        self.clear_log_button = ctk.CTkButton(self.bottom_controls_frame, text="Clear Log", command=self.clear_log, width=100) # Fixed width for button
        self.clear_log_button.grid(row=0, column=1, padx=(10,0), pady=0, sticky="e") # Placed in sub-frame, right side



    def clear_log(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end") # Delete all text
        self.log_textbox.configure(state="disabled")
        self.log_message("Log cleared.") # Add a message after clearing

    def load_icon(self, icon_filename, size=(32, 32)):
        """Loads an image icon from the assets folder and resizes it."""
        try:
            image_path = os.path.join(ASSETS_DIR, icon_filename)
            image = Image.open(image_path)
            image = image.resize(size, Image.LANCZOS)
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
            self.log_message("ERROR: Could not access clipboard. Clipboard might be empty or inaccessible.")

    def select_browser(self, browser_name, initial_setup=False):
        global selected_browser_type

        # Get the default and hover colors from the theme manager
        default_fg_color = ctk.ThemeManager.theme["CTkButton"]["fg_color"]
        hover_fg_color = ctk.ThemeManager.theme["CTkButton"]["hover_color"] # This is the key change!

        # Reset appearance of all browser buttons to default
        self.chrome_button.configure(fg_color=default_fg_color)
        self.firefox_button.configure(fg_color=default_fg_color)
        self.edge_button.configure(fg_color=default_fg_color)

        # Highlight the selected button using the hover color
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
        # Ensure progress bar updates on the main thread
        self.after(0, lambda: self.progress_bar.set(value))


    def start_download_process(self):
        url = self.url_entry.get().strip()
        if not url:
            self.log_message("Please enter a URL first!")
            return
        

        # --- Pre-checks ---
        self.log_message("Performing pre-flight checks...")
        if not is_connected_to_internet():
            self.log_message("ERROR: No active internet connection. Please check your network.")
            self._re_enable_buttons_after_error()
            return

        if not os.path.exists(IDM_PATH):
            self.log_message(f"ERROR: IDM executable not found at '{IDM_PATH}'. Please verify the path.")
            self._re_enable_buttons_after_error()
            return

        if not launch_idm(): # This function attempts to launch if not running
            self.log_message("ERROR: Could not launch IDM. Please ensure IDM is installed correctly.")
            self._re_enable_buttons_after_error()
            return
        else:
            self.log_message("IDM is running or launched successfully.")
            time.sleep(1) # Give IDM a moment to fully initialize if it just launched

        # Reset progress bar to 0 at the start of a new process
        self.progress_bar.set(0)



        self.start_button.configure(state="disabled", text="Working...")
        self.paste_button.configure(state="disabled")
        self.chrome_button.configure(state="disabled")
        self.firefox_button.configure(state="disabled")
        self.edge_button.configure(state="disabled")
        self.log_message("\n--- Starting Download Process ---")

        thread = threading.Thread(target=self._run_download_logic, args=(url,))
        thread.daemon = True
        thread.start()

    def _run_download_logic(self, url):
        try:
            global selected_browser_type

            os.makedirs(DRIVER_DIR, exist_ok=True)
            os.makedirs(ASSETS_DIR, exist_ok=True)

            html_content = get_full_html_content_selenium(url, selected_browser_type, self.log_message)

            if html_content:
                extracted_download_urls = extract_download_links_from_html(html_content, self.log_message)

                if extracted_download_urls:
                    self.log_message(f"\nFound {len(extracted_download_urls)} download URLs:")
                    for dl_url in extracted_download_urls:
                        self.log_message(f"- {os.path.basename(dl_url.split('?')[0])}")
                    # Pass the progress_callback to the IDM function
                    initiate_idm_direct_downloads(extracted_download_urls, IDM_PATH, self.log_message, self._update_progress_bar)

                else:
                    self.log_message("No download links were extracted from the provided URL.")
                    self._update_progress_bar(0) # Reset on no links
            else:
                self.log_message("Failed to retrieve HTML content. Cannot proceed.")
                self._update_progress_bar(0) # Reset on failure

        except Exception as e:
            self.log_message(f"An unexpected error occurred during processing: {e}")
            self._update_progress_bar(0) # Reset on unexpected error
        finally:
            self.log_message("\n--- Process Finished ---")
            self.after(0, self._enable_buttons)

            self._update_progress_bar(1.0) # Ensure bar is full at the very end regardless of outcome


    def _enable_buttons(self):
        self.start_button.configure(state="normal", text="Start Download")
        self.paste_button.configure(state="normal")
        self.chrome_button.configure(state="normal")
        self.firefox_button.configure(state="normal")
        self.edge_button.configure(state="normal")


    def _re_enable_buttons_after_error(self):
        """Helper to re-enable buttons after a pre-check failure."""
        self.after(0, self._enable_buttons) # Schedule on main thread
        self.start_button.configure(text="Start Download") # Reset text


# --- Main application entry point ---
if __name__ == "__main__":
    # if not os.path.exists(IDM_PATH):
    #     print(f"ERROR: IDM executable not found at '{IDM_PATH}'. Please verify the path and run this script from a console.")
    #     input("Press Enter to exit...")
    #     sys.exit(1)

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    app = DownloaderApp()
    app.mainloop()