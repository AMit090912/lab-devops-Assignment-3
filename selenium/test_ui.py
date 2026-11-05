"""Automated browser tests for the Lab 3 app (Selenium + pytest).

Run:  pytest selenium/test_ui.py -v
Env:  APP_URL (default http://localhost:5000), HEADLESS=0 to watch the browser.
"""

import json
import os
import time

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

APP_URL = os.getenv("APP_URL", "http://localhost:5000").rstrip("/")


@pytest.fixture(scope="module")
def driver():
    options = webdriver.ChromeOptions()
    if os.getenv("HEADLESS", "1") == "1":
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    drv = webdriver.Chrome(options=options)  # Selenium Manager downloads the matching driver
    yield drv
    drv.quit()


def test_homepage_loads(driver):
    driver.get(APP_URL)
    assert "Lab 3 DevOps Demo App" in driver.title
    WebDriverWait(driver, 10).until(EC.text_to_be_present_in_element((By.ID, "health-status"), "healthy"))


def test_add_item(driver):
    driver.get(APP_URL)
    name = f"selenium-item-{int(time.time())}"
    driver.find_element(By.ID, "item-name").send_keys(name)
    driver.find_element(By.ID, "add-item").click()
    WebDriverWait(driver, 10).until(EC.text_to_be_present_in_element((By.ID, "item-list"), name))


def test_empty_item_shows_validation_error(driver):
    driver.get(APP_URL)
    driver.find_element(By.ID, "item-name").clear()
    driver.find_element(By.ID, "add-item").click()
    message = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.ID, "form-message")))
    assert "enter an item name" in message.text.lower()


def test_feature_flag_banner_matches_flag_state(driver):
    """The banner shown in the UI must match what the flag API says for this user."""
    driver.get(f"{APP_URL}/api/flags")
    flags = json.loads(driver.find_element(By.TAG_NAME, "body").text)

    driver.get(APP_URL)
    for flag, element_id in (("new_ui_banner", "new-ui-banner"), ("discount_banner", "discount-banner")):
        present = len(driver.find_elements(By.ID, element_id)) > 0
        assert present == flags[flag]["enabled"], f"{flag}: UI={present} API={flags[flag]['enabled']}"
