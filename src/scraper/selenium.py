from __future__ import annotations
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

class Browser:
    def __init__(self):
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
        options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
        
        self.driver = webdriver.Chrome(options=options)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def get(self, url: str) -> None:
        self.driver.get(url)

    def wait_for_page(self, timeout: int = 10) -> None:
        WebDriverWait(self.driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

    def close(self) -> None:
        self.driver.quit()
