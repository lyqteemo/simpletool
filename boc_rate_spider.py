import base64
import logging
import os
import re
import time
from datetime import datetime, timedelta

import ddddocr
import pandas
import requests
from lxml import etree

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置信息
BASE_URL = "https://srh.bankofchina.com/search/whpj/"
CAPTCHA_URL = BASE_URL + "CaptchaServlet.jsp"
SEARCH_URL = BASE_URL + "search_cn.jsp"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0"

def get_captcha():
    """获取验证码"""
    response = requests.get(CAPTCHA_URL)
    response.raise_for_status()
    token = response.headers.get("token")
    with open("captcha.png", "wb") as f:
        f.write(base64.b64decode(response.content))
    return token

def get_captcha_char(ocr: ddddocr.DdddOcr):
    """解析验证码"""
    with open("captcha.png", "rb") as f:
        image = f.read()
    result = ocr.classification(image)
    logging.info(f"验证码识别结果: {result}")
    return result

def query_data(
    start_date: str,
    end_date: str,
    token: str,
    captcha_char: str,
    paramtk: str,
    page,
    is_first: bool = False,
):
    """
    :param start_date: 开始日期
    :param end_date: 结束日期
    :param token: token 随验证码同时生成的token,包含其过期时间
    :param captcha_char: 验证码
    :param paramtk: paramtk  查询翻页时的token,包含过期时间
    :param page: 页码
    :param is_first: 是否是第一次请求
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if is_first:
        data = {
            "erectDate": start_date,
            "nothing": end_date,
            "pjname": "美元",
            "head": "head_620.js",
            "bottom": "bottom_591.js",
            "first": 1,
            "token": token,
            "captcha": captcha_char,
        }
    else:
        data = {
            "erectDate": start_date,
            "nothing": end_date,
            "page": page,
            "pjname": "美元",
            "head": "head_620.js",
            "bottom": "bottom_591.js",
            "paramtk": paramtk,
            "token": token,
        }
    logging.debug(f"请求体: {data}")
    
    error = None
    paramtk = None
    m_nRecordCount = 0
    content = []
    try:
        response = requests.post(SEARCH_URL, headers=headers, data=data)
        response.raise_for_status()
        html_content = response.text.replace("GBK", "UTF-8").replace("\n", "").replace("\r", "").replace("\t", "")
        if "验证码错误" in html_content:
            error = "验证码错误"
        elif "验证码已过期" in html_content:
            error = "验证码已过期"
        else:
            paramtk = re.findall('paramtk" value="(.*?)">', html_content)
            paramtk = paramtk[0] if paramtk else None
            m_nRecordCount = re.findall("m_nRecordCount = (\d+);", html_content)
            m_nRecordCount = int(m_nRecordCount[0]) if m_nRecordCount else 0
            content = parse_html(html_content)
            logging.info(f"page: {page}, m_nRecordCount: {m_nRecordCount}, content count: {len(content)}")
    except requests.RequestException as e:
        logging.error(f"HTTP 请求失败: {e}")
        error = "HTTP 请求失败"
    return error, paramtk, m_nRecordCount, content


def parse_html(html_content):
    html = etree.HTML(html_content)
    data = []

    for row in html.xpath("//div[@class='BOC_main publish']//table//tr")[:-1]:
        if row.xpath("./th"):  # Skip header row
            continue
        item = {
            "货币名称": row.xpath("./td[1]/text()")[0].strip(),
            "现汇买入价": row.xpath("./td[2]/text()")[0].strip(),
            "现钞买入价": row.xpath("./td[3]/text()")[0].strip(),
            "现汇卖出价": row.xpath("./td[4]/text()")[0].strip(),
            "现钞卖出价": row.xpath("./td[5]/text()")[0].strip(),
            "中行折算价": row.xpath("./td[6]/text()")[0].strip(),
            "发布时间": row.xpath("./td[7]/text()")[0].strip(),
        }
        data.append(item)
    return data

def work_on(start_date, end_date):
    ocr = ddddocr.DdddOcr(show_ad=False)
    paramtk = ""
    token = ""
    captcha_str = ""
    contents = []
    logging.info(f"获取第1页数据")
    while True:
        token = get_captcha()  # 获取验证码token
        captcha_str = get_captcha_char(ocr)  # 获取验证码字符
        error, paramtk, record_count, content = query_data(
            start_date, end_date, token, captcha_str, "", 1, True
        )
        if error:
            logging.error(error)
        else:
            if content:
                contents.extend(content)
            break
        logging.info("5s后重试获取")
        time.sleep(5)
    
    page = 2
    while True:
        logging.info(f"获取第{page}页数据")
        error, paramtk, record_count, content = query_data(
            start_date, end_date, token, captcha_str, paramtk, page, False
        )
        if record_count <= 20:
            break
        if error:
            logging.error(error)
        else:
            if content:
                contents.extend(content)
            if page * 20 < record_count:
                page += 1
            else:
                break
    df = pandas.DataFrame(contents)
    print(df.head())
    if os.path.exists("captcha.png"):
        os.remove("captcha.png")

if __name__ == "__main__":
    start_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    work_on(start_date, end_date)
