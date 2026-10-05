import subprocess
import time, random, string
import json, os, csv
import requests, shutil
import websocket
from datetime import datetime
import requests
from itertools import cycle
from glob import glob
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from ftplib import FTP
import pymysql
from dotenv import load_dotenv


import asyncio
import nodriver as uc
from color_matcher import FBMarketplaceColorMatcher

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
FTP_USER = os.getenv("FTP_USER")
FTP_PWD = os.getenv("FTP_PWD")
X_API_KEY = os.getenv("X_API_KEY")


PROFILE_PATH = f"C:\\temp\\profile-josh"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROGRESS_FILE = "progress.json"



class Client:
    OPENAI_API_KEY = openai_api_key
    def __init__(self):
        self.build_logger()
        self.load_progress()
        self.connected = False
        self.color_matcher = FBMarketplaceColorMatcher(self.OPENAI_API_KEY, logger=self.logger)


    def kill_chrome(self):
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True
        )

        for line in result.stdout.splitlines():
            if ":9222" in line and "LISTENING" in line:
                parts = line.split()
                pid = parts[-1]

                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                return True

        return False


    def load_progress(self):
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                self.progress = json.load(f)
        else:
            self.progress = {
                "created": 0,
                "updated": 0,
                "deleted": 0,
                "renewed": 0,
            }
            self.save_progress()

        return self.progress


    def save_progress(self, progress=None):
        if progress is not None:
            self.progress = progress

        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.progress, f, indent=4)


    def increment_created(self):
        self.progress["created"] += 1
        self.save_progress()


    def increment_updated(self):
        self.progress["updated"] += 1
        self.save_progress()


    def increment_deleted(self):
        self.progress["deleted"] += 1
        self.save_progress()


    def increment_renewed(self):
        self.progress["renewed"] += 1
        self.save_progress()

    def reset_progress(self):
        self.progress = {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "renewed": 0,
        }
        self.save_progress()

    def load_listings(self):
        self.remove_old_feed_files()
        ftp = FTP('ftp.theinternetcarlot.com')
        ftp.set_pasv(True)
        ftp.login(FTP_USER, FTP_PWD)
        files = ftp.nlst('/uploads/')
        files = [item for item in files if 'NOWCOM_InRecon' not in item]
        dated_files = []
        for filename in files:
            date_str = filename.split('NOWCOM')[-1].split('.txt')[0]
            file_date = datetime.strptime(date_str, "%m%d%y")
            dated_files.append((file_date, filename))

        # Get the latest file
        if dated_files:
            latest_file = max(dated_files, key=lambda x: x[0])[1]
        else:
            ftp.quit()

        with open(latest_file.split('/')[-1], 'wb') as f:
            ftp.retrbinary(f"RETR {latest_file}", f.write)

        ftp.quit()

        with open(latest_file.split('/')[-1], mode='r', newline='') as file:
          reader = csv.reader(file, delimiter='|')
          rows = [row for row in reader]
        self.listings = [dict(zip(rows[0], row)) for row in rows[1:]]
        self.listings_dict = {listing['Vin']: listing for listing in self.listings}

    def remove_old_feed_files(self):
        files = glob('*.txt')
        for file in files:
            os.remove(file)

    def build_logger(self):
        LOG_DIR = Path("logs")
        LOG_DIR.mkdir(exist_ok=True)

        self.logger = logging.getLogger("app")
        if self.logger.handlers:
            return
        self.logger.setLevel(logging.INFO)

        handler = RotatingFileHandler(
            LOG_DIR / "app.log",
            maxBytes=1 * 1024 * 1024,  # Rotate every 1 MB
            backupCount=4,             # Keep app.log + 4 backups = 5 MB total
            encoding="utf-8",
        )

        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s"
            )
        )

        self.logger.addHandler(handler)

        # Optional: also log to the console
        console = logging.StreamHandler()
        console.setFormatter(handler.formatter)
        self.logger.addHandler(console)


    def launch_browser(self):
        self.kill_chrome()
        time.sleep(5)
        self.logger.info('Launching browser instance...')
        try:
            subprocess.Popen([
                CHROME_PATH,
                "--remote-debugging-port=9222",
                f"--user-data-dir={PROFILE_PATH}",
                "--no-first-run",
                "--headless=new",
                "--remote-allow-origins=http://localhost:9222",
                # f"--proxy-server=http://{proxy}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self.logger.error(f'Failed to launch browser instance. Error: {str(e)}')

    def get_vehicle_colors(self, vin):
        self.logger.info(f'Getting vehicle colors for vin: {vin}')
        url = f'https://dashboard.theinternetcarlot.com/api/v1/vehicle-specs/{vin}'
        r = requests.get(url, headers={'X-API-KEY': X_API_KEY})
        vehicle = r.json()['data']['vehicle']
        return (vehicle['exterior_color'], vehicle['interior_color'])


    async def select_combobox_option(self, field_name, value):
        return await self.fb_tab.evaluate(f"""
        (async () => {{

            const combo = [...document.querySelectorAll('label[role="combobox"]')]
                .find(e =>
                    e.innerText.trim().toLowerCase().includes(
                        {field_name.lower()!r}
                    )
                );

            if (!combo)
                return false;

            combo.click();

            await new Promise(resolve => setTimeout(resolve, 500));

            const option = [
                ...document.querySelectorAll(
                    'div[aria-label="Select an option"] div[aria-selected]'
                )
            ].find(el =>
                el.innerText.trim().toLowerCase() ===
                {value.lower()!r}
            );

            if (!option)
                return false;

            option.click();

            return true;

        }})();
        """)


    async def wait_for_listings(self, timeout=10):
        self.logger.info('Waiting for the listings to load...')
        end_time = time.time() + timeout

        while time.time() < end_time:

            # Listings are present
            listings = await self.tab.select_all(
                "div.row.card div.card-body div.row.align-items-center"
            )

            if listings:
                return listings

            # "Showing 0 of 0"
            elems = await self.tab.select_all(
                "div.listingAssistantGrid div.font-small.text-black.text-uppercase.fw-bold"
            )

            for elem in elems:
                if "showing 0 of 0" in ' '.join(elem.text_all.strip().lower().split()):
                    return []

            await asyncio.sleep(0.25)

        raise TimeoutError("Timed out waiting for listings.")

    async def wait_for_elements(self, selector, timeout=20):
        end_time = time.time() + timeout

        while time.time() < end_time:
            elems = await self.tab.select_all(selector)

            if elems:
                return elems

            await asyncio.sleep(0.5)

        raise TimeoutError(f"Timed out waiting for '{selector}'.")

    async def connect(self):
        self.logger.info('Establishing nodriver connection...')
        try:
            self.browser = await uc.start(
                browser_executable_path=None,   # Don't launch Chrome
                host="127.0.0.1",
                port=9222
            )
            self.tab = self.browser.tabs[0]
            self.tab = await self.browser.get("https://www.myaccountcenter.com/Social/FacebookListings")
            await self.wait_for_listings()
        except Exception as err:
            self.logger.error(f'Failed to establish nodriver connection. Error: {str(err)}')
            return
        self.connected = True

    async def get_filtered_listings(self, text):
        retries = 0
        while True:
            self.logger.info(f'Filtering out "{text.upper()}" listings...')
            await self.tab.reload()
            await self.delay(2, 3)
            await self.wait_for_listings()
            dropdown = await self.tab.select('div#chassisBlazorDropdown.dropdown_ListingStatus')
            await dropdown.scroll_into_view()
            await self.delay(2, 3)
            await dropdown.mouse_click()
            await self.delay(2, 3)
            options = await dropdown.query_selector_all('li')
            for option in options:
                if option.text.strip().lower() == text.lower():
                    await self.delay(2, 3)
                    await option.scroll_into_view()
                    await option.mouse_click()
            await self.delay(2, 3)
            try:
                listings = await self.wait_for_listings()
                return listings
            except Exception as e:
                self.logger.error(f'{str(e)}')
                retries += 1
                if retries == 10:
                    self.logger.info('Max retries reached while loading the listings...')
                    return []




    async def delay(self, minimum=1, maximum=2):
        await asyncio.sleep(random.uniform(minimum, maximum))

    # async def click_button(self, text):
    #     buttons = await self.tab.select_all("button")

    #     for button in buttons:
    #         if button.text.strip().lower() == text.lower():
    #             await button.click()
    #             return True

    #     return False

    async def create_listings(self):
        self.logger.info('Creating listings...')
        while self.progress['created'] < 25:
            listings = await self.get_filtered_listings('Not Listed')
            # listings = await self.wait_for_listings()
            if not listings:
                print('No more listings available.')
                break
            # for listing in listings:
            vin = listings[0].text_all.split('VIN: ')[-1].split()[0].strip()
            self.logger.info(f'Creating listing for VIN: {vin}')
            exterior_color = self.listings_dict[vin]['ExteriorColor']
            interior_color = self.listings_dict[vin]['Interior']
            if not exterior_color or not interior_color:
                self.logger.warning(f'No vehicle colors were found for vin: {vin}.')
                continue

            buttons = await listings[0].query_selector_all('button')
            for button in buttons:
                if button.text.strip().lower() == 'start listing':
                    await button.scroll_into_view()
                    await self.delay(1, 2)
                    await button.click()
                    await self.delay(3, 5)
                    break

            await self.browser.update_targets()
            try:
                self.fb_tab = self.browser.tabs[1]
            except:
                self.logger.warning(f'New tab not opened while creating a new listing for VIN: {vin}')
                break
            await self.delay(30, 35)
            await self.select_combobox_option('exterior color', self.color_matcher.get_matched_color(exterior_color))
            await self.delay(2, 3)
            await self.select_combobox_option('interior color', self.color_matcher.get_matched_color(interior_color))
            await self.delay(2, 3)
            await self.select_combobox_option('vehicle condition', 'excellent')
            await self.delay(2, 3)
            next_btn = await self.fb_tab.select('div[aria-label="Next"]')
            await next_btn.click()
            await self.delay(5, 10)
            publish_btn = await self.fb_tab.select('div[aria-label="Publish"]')
            await next_btn.click()
            await self.delay(15, 20)
            await self.fb_tab.close()
            await self.delay(3, 5)
            self.increment_created()
            self.logger.info(f'{self.progress['created']} listing(s) posted successfully.')
                    
            # if self.progress['created'] == 25:
            #     break


    async def update_listings(self):
        self.logger.info('Updating listings...')
        # self.logger.info('Getting listings with changed price or mileage...')
        # changed_vins = self.get_changed_listings()
        # self.logger.info(f'{len(changed_vins)} listing(s) need to be updated...')
        while True:
            listings = await self.get_filtered_listings('Update')
            # listings = await self.wait_for_listings()
            if not listings:
                self.logger.info('No more listings to update.')
                break
            for listing in listings:
                vin = listing.text_all.split('VIN: ')[-1].split()[0].strip()
                self.logger.info(f'Updating listing with VIN: {vin}')
                buttons = await listing.query_selector_all('button')
                for button in buttons:
                    if button.text.strip().lower() == 'update listing':
                        await button.scroll_into_view()
                        await self.delay(1, 2)
                        await button.click()
                        await self.delay(3, 5)
                        break
                await self.browser.update_targets()
                try:
                    self.fb_tab = self.browser.tabs[1]
                except:
                    self.logger.warning(f'New tab not opened while updating Listing for VIN: {vin}.')
                    break
                await self.delay(30, 35)
                button = await self.fb_tab.select('div[aria-label*="Update" i]')
                await button.click()
                await self.delay(15, 20)
                await self.fb_tab.close()
                await self.delay(3, 5)
                self.increment_updated()

    async def reset_started_listings(self):
        self.logger.info('Resetting "Started" listings to "Not Listed"')
        # self.logger.info('Getting listings with changed price or mileage...')
        # changed_vins = self.get_changed_listings()
        # self.logger.info(f'{len(changed_vins)} listing(s) need to be updated...')
        while True:
            listings = await self.get_filtered_listings('Started')
            # await self.update_filter('Started')
            # listings = await self.wait_for_listings()
            if not listings:
                self.logger.info('No more "Started" listings...')
                break
            for listing in listings:
                vin = listing.text_all.split('VIN: ')[-1].split()[0].strip()
                dropdown_btn = await listing.query_selector('button[aria-label*="Edit Menu" i]')
                if dropdown_btn:
                    await dropdown_btn.scroll_into_view()
                    await self.delay(1, 2)
                    await dropdown_btn.click()
                    await self.delay(2, 3)
                    dropdown_items = await listing.query_selector_all('button.dropdown-item')
                    for dropdown_item in dropdown_items:
                        if 'Reset to Not Listed'.lower() in dropdown_item.text_all.lower():
                            await dropdown_item.scroll_into_view()
                            await self.delay(1, 2)
                            await dropdown_item.click()
                            await self.delay(2, 3)
                            break
                    buttons = await self.tab.select_all('button')
                    for button in buttons:
                        if button.text.strip().lower() == "yes, reset status":
                            self.logger.info(f'Status changed to "Not Listed" for VIN: {vin}')
                            await button.click()
                            await self.delay(2, 3)
                            break

    async def delete_listings(self):
        self.logger.info('Deleting listings...')
        while True:
            listings = await self.get_filtered_listings('Need to Delete')
            # listings = await self.wait_for_listings()
            if not listings:
                self.logger.info('No more listings to delete.')
                break
            for _ in range(len(listings)):
                # listings = await self.wait_for_listings()
                vin = listings[0].text_all.split('VIN: ')[-1].split()[0].strip()
                self.logger.info(f'Deleting listing with VIN: {vin}')

                el = await listings[0].query_selector('div.fw-bold.text-primary.text-nowrap.lh-sm')
                if el:
                    listing_title = el.text_all

                el = await listings[0].query_selector('a[href*="/item/" i]')
                if el:
                    listing_id_ac = el.attrs['href'].split('/item/')[1].strip('/')

                buttons = await listings[0].query_selector_all('button')
                for button in buttons:
                    if button.text.strip().lower() == 'delete listing':
                        await button.scroll_into_view()
                        await self.delay(1, 2)
                        await button.click()
                        await self.delay(3, 5)
                        break
                await self.browser.update_targets()
                try:
                    self.fb_tab = self.browser.tabs[1]
                except:
                    break
                await self.fb_tab.get(f'https://www.facebook.com/marketplace/you/selling?title_search={listing_title}')
                await self.delay(10, 15)
                elems = await self.fb_tab.select_all(f'div[aria-label="Collection of your marketplace items"] div[aria-label*="More options"]')
                elems = elems[::2]
                for elem_btn in elems:
                    await elem_btn.scroll_into_view()
                    await self.delay()
                    await elem_btn.click()
                    await self.delay(3, 5)
                    elem = await self.fb_tab.select('div[aria-label="More options for listing" i] a[href*="/item/" i]')
                    listing_id_fb = elem.attrs['href'].split('/item/')[1].strip('/')
                    if listing_id_fb == listing_id_ac:
                        del_btn = None
                        options = await self.fb_tab.select_all('div[aria-label="More options for listing" i] div[role="menuitem"')
                        for option in options:
                            if option.text_all.strip().lower() == 'delete listing':
                                del_btn = option
                                break
                        if del_btn:
                            await del_btn.click()
                            await self.delay(3, 5)
                            elems = await self.fb_tab.select_all('div[aria-label="Delete"]')
                            if len(elems) > 1:
                                await elems[1].click()
                            else:
                                await elems[0].click()
                        break
                    await elem_btn.click()
                    await self.delay(3, 5)


                await self.delay(2, 3)
                await self.fb_tab.close()
                await self.delay(2, 3)
                buttons = await self.tab.select_all('button')
                for button in buttons:
                    if button.text.strip().lower() == "yes, it's removed":
                        await button.click()
                        break
                await self.delay(3, 5)
                self.increment_deleted()

    async def renew_listings(self):
        self.logger.info('Renewing listings...')

        while True:
            self.fb_tab = await self.browser.get('https://www.facebook.com/marketplace/selling/renew_listings/?is_routable_dialog=true', new_tab=True)
            await self.delay(5, 10)

            elems = await self.fb_tab.select_all('div[aria-label="Renew"]')

            if not elems:
                self.logger.info('No more listings to be renewed.')
                await self.delay(1, 2)
                await self.fb_tab.close()
                return

            for idx, elem in enumerate(elems):
                await elem.scroll_into_view()
                await self.delay(1, 2)
                await elem.click()
                await self.delay(3, 5)
                self.increment_renewed()
            await self.fb_tab.close()
            await self.delay(1, 2)
            

    async def main(self):
        self.build_logger()
        while True:
            try:
                self.load_listings()
                self.launch_browser()
                await self.connect()
                if not self.connected:
                    continue
                await self.delete_listings()
                await self.renew_listings()
                await self.update_listings()
                await self.reset_started_listings()
                await self.create_listings()
                self.logger.info('Closing browser instance...')
                try:
                    await self.tab.close()
                    await self.browser.stop()
                except:
                    pass
                self.reset_progress()
                break
            except Exception as e:
                self.logger.error(str(e))


if __name__ == '__main__':
    client = Client()
    uc.loop().run_until_complete(client.main())