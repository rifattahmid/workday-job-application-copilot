from scraper import scrape_workday
from generator import generate_application

url = input("Paste Workday URL: ")

data = scrape_workday(url)

data["company"] = input("Enter Company Name: ")

generate_application(data)