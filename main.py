import os
import re
import csv
import aiohttp
import asyncio
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from bs4 import BeautifulSoup
from urllib.parse import urljoin

app = FastAPI()

EMAIL_REGEX = re.compile(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}")
PHONE_REGEX = re.compile(r"(?:\+\d{1,3}[\s-]?)?(?:\(\d{1,4}\)[\s-]?)?\d{5,}[\d\s-]*")
JUNK_EMAIL_DOMAINS = {"sentry.wixpress.com", "sentry.io", "sentry-next.wixpress.com"}

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

async def fetch_html(session, url):
    try:
        async with session.get(url, timeout=10) as resp:
            return await resp.text(), str(resp.url)
    except:
        return None, url

def extract_contacts(html):
    if not html:
        return [], []

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    emails = {e for e in EMAIL_REGEX.findall(text) if e.split("@")[-1] not in JUNK_EMAIL_DOMAINS}
    phones = set()

    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if href.startswith("mailto:"):
            email = href[7:].split("?")[0]
            if email.split("@")[-1] not in JUNK_EMAIL_DOMAINS:
                emails.add(email.strip())
        elif href.startswith("tel:"):
            phones.add(href[4:].strip())

    for phone in PHONE_REGEX.findall(text):
        phones.add(phone.strip())

    return list(emails), list(phones)

async def find_contact_page(session, base_url, html):
    if not html:
        return base_url
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        if any(k in a["href"].lower() for k in ["contact", "contact-us"]):
            return urljoin(base_url, a["href"])
    return base_url

async def scrape_site(session, url):
    result = {"url": url, "emails": [], "phones": [], "error": None, "contact_page": None}

    html, final_url = await fetch_html(session, url)
    if not html:
        if url.startswith("http://"):
            result["error"] = "Site not reachable"
            return result
        https_url = url.replace("http://", "https://")
        html, final_url = await fetch_html(session, https_url)
        if not html:
            http_url = url.replace("https://", "http://")
            html, final_url = await fetch_html(session, http_url)
            if not html:
                result["error"] = "Site not reachable"
                return result

    contact_page = await find_contact_page(session, url, html)
    result["contact_page"] = contact_page
    emails1, phones1 = extract_contacts(html)

    if contact_page != final_url:
        html2, _ = await fetch_html(session, contact_page)
        emails2, phones2 = extract_contacts(html2)
        result["emails"] = list(set(emails1 + emails2))
        result["phones"] = list(set(phones1 + phones2))
    else:
        result["emails"] = emails1
        result["phones"] = phones1

    return result

async def extract_contacts_bulk(urls):
    os.makedirs("results", exist_ok=True)
    filename = f"results_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = os.path.join("results", filename)

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        results = []
        for url in urls:
            result = await scrape_site(session, url.strip())
            results.append(result)

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["URL", "Contact Page", "Emails", "Phones", "Error"])
        for r in results:
            writer.writerow([r["url"], r["contact_page"], ", ".join(r["emails"]), ", ".join(r["phones"]), r["error"] or ""])

    return filename

@app.get("/extract")
async def extract_single(url: str = Query(...)):
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        return await scrape_site(session, url)

class BulkInput(BaseModel):
    urls: list[str]

@app.post("/extract/bulk")
async def extract_bulk(data: BulkInput):
    filename = await extract_contacts_bulk(data.urls)
    return {"csv_url": f"/download/{filename}"}

@app.post("/extract/upload")
async def extract_from_file(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        return {"error": "Only CSV files supported."}
    try:
        df = pd.read_csv(file.file, header=None)
        filename = await extract_contacts_bulk(df[0].dropna().tolist())
        return {"csv_url": f"/download/{filename}"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/download/{filename}")
async def download_file(filename: str):
    path = os.path.join("results", filename)
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "File not found"})
    return FileResponse(path=path, filename=filename, media_type="text/csv")
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
