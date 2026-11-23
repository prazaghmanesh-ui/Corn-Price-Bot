import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import pytz
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os

# پیکربندی لاگ‌گیری
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# تنظیمات ایمیل (بهتر است این مقادیر را از Environment Variables بخوانید)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "your_email@gmail.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "your_app_password")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "receiver@company.com")

def get_cbi_exchange_rates():
    """دریافت نرخ ارز رسمی از بانک مرکزی (CBI)"""
    logging.info("Fetching exchange rates from CBI...")
    rates = {'USD': None, 'RUB': None}
    try:
        # در سیستم‌های واقعی ممکن است نیاز به استفاده از API های معتبر یا پارس کردن دقیق سایت CBI باشد.
        # در اینجا به عنوان نمونه از ساختار عمومی سایت استفاده می‌کنیم
        url = "https://www.cbi.ir/exrates/rates_fa.aspx"
        response = requests.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # پیدا کردن ردیف‌های دلار و روبل (این بخش بسته به تغییرات قالب CBI ممکن است نیاز به آپدیت داشته باشد)
        rows = soup.find_all('tr')
        for row in rows:
            text = row.get_text()
            if 'دلار آمریکا' in text:
                tds = row.find_all('td')
                if len(tds) >= 2:
                    rates['USD'] = float(tds[2].text.strip().replace(',', ''))
            elif 'روبل روسیه' in text:
                tds = row.find_all('td')
                if len(tds) >= 2:
                    rates['RUB'] = float(tds[2].text.strip().replace(',', ''))
        
        # مقادیر پیش‌فرض در صورت عدم پاسخگویی سایت
        if not rates['USD']: rates['USD'] = 420000.0 # ریال (مثال نرخ رسمی/نیما)
        if not rates['RUB']: rates['RUB'] = 4500.0   # ریال (مثال نرخ رسمی)
        logging.info(f"CBI Rates - USD: {rates['USD']} IRR, RUB: {rates['RUB']} IRR")
    except Exception as e:
        logging.error(f"Error fetching CBI rates: {e}")
    return rates

def get_damparvar_prices():
    """استخراج قیمت ذرت از سایت ایران دامپرور"""
    logging.info("Fetching prices from Iran Damparvar...")
    data = {'min': None, 'max': None, 'avg': None, 'date': None, 'currency': 'IRR/kg'}
    try:
        url = "https://irandamparvar.ir/توسعه-و-تجارت-بازرگانی/نهاده-های-دامی/"
        response = requests.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # جستجو برای کلیدواژه ذرت در جداول
        tables = soup.find_all('table')
        for table in tables:
            if 'ذرت' in table.text:
                rows = table.find_all('tr')
                for row in rows:
                    if 'ذرت' in row.text:
                        cols = row.find_all('td')
                        if len(cols) >= 3:
                            data['min'] = float(re.sub(r'[^\d]', '', cols[1].text))
                            data['max'] = float(re.sub(r'[^\d]', '', cols[2].text))
                            data['avg'] = (data['min'] + data['max']) / 2
                            data['date'] = datetime.now(pytz.timezone('Asia/Tehran')).strftime('%Y-%m-%d')
                            break
    except Exception as e:
        logging.error(f"Error fetching Iran Damparvar: {e}")
    return data

def get_itpnews_prices():
    """استخراج قیمت ذرت از داشبورد ITPNews"""
    logging.info("Fetching prices from ITP News...")
    data = {'price': None, 'date': None, 'currency': 'IRR/kg'}
    try:
        # خواندن از جدول اصلی که معمولاً رندر شده است
        url = "https://price.itpnews.com/"
        response = requests.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        rows = soup.find_all('tr')
        for row in rows:
            if 'ذرت' in row.text and 'کنجاله' not in row.text:
                cols = row.find_all('td')
                if len(cols) >= 5:
                    price_str = cols[4].text.strip().replace(',', '')
                    data['price'] = float(price_str) if price_str.isdigit() else None
                    data['date'] = cols[1].text.strip()
                    break
    except Exception as e:
        logging.error(f"Error fetching ITP News: {e}")
    return data

def get_telegram_quotes():
    """استخراج قیمت‌ها از کانال تلگرام"""
    logging.info("Fetching prices from Telegram channel...")
    url = "https://t.me/s/ThevanguardofKalaPanah"
    quotes = {'Brazil': [], 'Russia': []}
    
    try:
        response = requests.get(url, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        messages = soup.find_all('div', class_='tgme_widget_message_text')
        
        for msg in messages:
            text = msg.text
            # جستجوی الگوهای کوتاژ و قیمت (فرمت: عدد کوتاژ: قیمت)
            matches = re.finditer(r'(?:کوتاژ|شماره)?\s*(\d{7,8})\s*[:\-]\s*([\d,]+)', text)
            
            origin = None
            if 'برزیل' in text: origin = 'Brazil'
            elif 'روس' in text: origin = 'Russia'
            
            if origin:
                for match in matches:
                    quotation_id = match.group(1)
                    # اگر قیمت‌ها در تلگرام معمولاً تومان است، باید آن را به ریال یا تومان استاندارد کرد
                    raw_price = float(match.group(2).replace(',', ''))
                    
                    # تشخیص واحد (اغلب اگر قیمت زیر 100,000 باشد تومان است، اما برای احتیاط و دقت ثبت می‌کنیم)
                    unit = 'Toman' if raw_price < 100000 else 'IRR'
                    irr_price = raw_price * 10 if unit == 'Toman' else raw_price
                    
                    quotes[origin].append({
                        'quotation_id': quotation_id,
                        'price_irr': irr_price,
                        'price_toman': irr_price / 10,
                        'original_unit': unit
                    })
    except Exception as e:
        logging.error(f"Error fetching Telegram quotes: {e}")
    
    # محاسبه میانگین‌ها
    averages = {}
    for origin, q_list in quotes.items():
        if q_list:
            avg_irr = sum(q['price_irr'] for q in q_list) / len(q_list)
            averages[origin] = {'average_irr': avg_irr, 'average_toman': avg_irr / 10, 'count': len(q_list), 'quotes': q_list}
        else:
            averages[origin] = None
            
    return averages

def calculate_usd_prices(price_irr, rates):
    """محاسبه قیمت دلاری بر اساس دو متد مختلف"""
    # متد ۱: تبدیل مستقیم ریال به دلار بر اساس نرخ رسمی
    usd_method_1 = price_irr / rates['USD'] if rates['USD'] else 0
    
    # متد ۲: تبدیل ریال به روبل، سپس روبل به دلار جهانی (فرضیه کراس‌ریت)
    # نرخ برابری روبل به دلار جهانی به صورت ثابت فرض شده است (مثلاً 1 USD = 90 RUB) یا از محاسبه متقاطع
    cross_rate_rub_usd = 90.0 
    rub_value = price_irr / rates['RUB'] if rates['RUB'] else 0
    usd_method_2 = rub_value / cross_rate_rub_usd if rub_value else 0
    
    return round(usd_method_1, 4), round(usd_method_2, 4)

def generate_html_report(damparvar, itpnews, telegram, rates):
    """تولید قالب حرفه‌ای HTML به زبان فارسی"""
    tehran_tz = pytz.timezone('Asia/Tehran')
    report_date = datetime.now(tehran_tz).strftime('%Y-%m-%d %H:%M:%S')
    
    html = f"""
    <html dir="rtl" lang="fa">
    <head>
        <style>
            body {{ font-family: Tahoma, Arial, sans-serif; background-color: #f4f4f9; color: #333; }}
            .container {{ width: 80%; margin: 0 auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
            h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: right; }}
            th {{ background-color: #3498db; color: white; }}
            .note {{ font-size: 0.9em; color: #7f8c8d; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>گزارش روزانه قیمت ذرت دامی - {report_date}</h2>
            
            <h3>۱. نرخ ارز (بانک مرکزی)</h3>
            <table>
                <tr><th>ارز</th><th>نرخ (ریال)</th></tr>
                <tr><td>دلار آمریکا (USD)</td><td>{rates['USD']:,}</td></tr>
                <tr><td>روبل روسیه (RUB)</td><td>{rates['RUB']:,}</td></tr>
            </table>

            <h3>۲. قیمت‌ها از منابع مختلف</h3>
            <table>
                <tr>
                    <th>منبع</th>
                    <th>نوع ذرت</th>
                    <th>قیمت میانگین (تومان/کیلو)</th>
                    <th>معادل دلاری (متد ۱ - مستقیم)</th>
                    <th>معادل دلاری (متد ۲ - کراس‌ریت روبل)</th>
                </tr>
    """
    
    # اضافه کردن داده‌های دامپرور
    if damparvar['avg']:
        toman_price = damparvar['avg'] / 10
        usd1, usd2 = calculate_usd_prices(damparvar['avg'], rates)
        html += f"<tr><td>ایران دامپرور</td><td>نامشخص</td><td>{toman_price:,.0f} <br><span class='note'>(محاسبه شده از میانه کف و سقف)</span></td><td>${usd1}</td><td>${usd2}</td></tr>"

    # اضافه کردن داده‌های ITP News
    if itpnews['price']:
        toman_price = itpnews['price'] / 10
        usd1, usd2 = calculate_usd_prices(itpnews['price'], rates)
        html += f"<tr><td>ITP News</td><td>نامشخص</td><td>{toman_price:,.0f}</td><td>${usd1}</td><td>${usd2}</td></tr>"

    # اضافه کردن داده‌های تلگرام
    for origin in ['Brazil', 'Russia']:
        if telegram.get(origin):
            toman_price = telegram[origin]['average_toman']
            usd1, usd2 = calculate_usd_prices(telegram[origin]['average_irr'], rates)
            origin_fa = "برزیل" if origin == 'Brazil' else "روسیه"
            html += f"<tr><td>تلگرام (کالا پناه)</td><td>{origin_fa}</td><td>{toman_price:,.0f} <br><span class='note'>(میانگین {telegram[origin]['count']} کوتاژ)</span></td><td>${usd1}</td><td>${usd2}</td></tr>"

    html += """
            </table>
            <p class="note">متد ۱: تبدیل بر اساس نرخ مستقیم ریال به دلار بانک مرکزی.</p>
            <p class="note">متد ۲: تبدیل ریال به روبل و سپس محاسبه برابری روبل به دلار جهانی.</p>
        </div>
    </body>
    </html>
    """
    return html

def send_email(html_content):
    """ارسال ایمیل حاوی گزارش HTML"""
    logging.info("Sending email report...")
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"گزارش روزانه نهاده‌های دامی (ذرت) - {datetime.now(pytz.timezone('Asia/Tehran')).strftime('%Y-%m-%d')}"
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL

    part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        logging.info("Email sent successfully.")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

def main():
    logging.info("Starting Daily Corn Pricing Workflow...")
    rates = get_cbi_exchange_rates()
    damparvar = get_damparvar_prices()
    itpnews = get_itpnews_prices()
    telegram = get_telegram_quotes()
    
    report_html = generate_html_report(damparvar, itpnews, telegram, rates)
    send_email(report_html)
    logging.info("Workflow completed.")

if __name__ == "__main__":
    main()
