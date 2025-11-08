from QuickProject.Commander import Commander
from selenium import webdriver
from . import *
import time

app = Commander(executable_name)

_driver = None
_path = None
_data = None

def save():
    with open(_path, "w") as f:
        import json
        json.dump(_data, f, indent=4, ensure_ascii=False)

def getLocalDriver():
    global _driver

    if _driver is None:
        options = webdriver.ChromeOptions()
        # 设置PDF文件直接下载
        options.add_experimental_option(
            "prefs",
            {
                "plugins.always_open_pdf_externally": True,
                "download.default_directory": os.path.join(user_root, "Downloads"),
            },
        )

        _driver = webdriver.Chrome(options=options)
    return _driver

def closeLocalDriver():
    global _driver
    if _driver is not None:
        _driver.close()

        _driver = None

def parse_dois(papers: list):
    if not papers:
        return
    
    from selenium.webdriver.common.by import By
    driver = getLocalDriver()

    paper_404s = []

    QproDefaultStatus("Parse doi pages").start()

    for index, item in enumerate(papers):
        if 'abstract' in item['info']:
            continue
        doi = item['info']['ee'] # doi link
        # 2.1. get doi page, not wait for page load
        # driver.get(doi, wait_for_page_load=False)
        driver.execute_script(f"window.open('{doi}')")
        # close current tab
        driver.close()
        driver.switch_to.window(driver.window_handles[-1])
        current_url = driver.current_url

        QproDefaultStatus.update(f"Parse: {current_url}")
        # 2.2. check is ACM page
        if "dl.acm.org" in current_url:
            try:
                # 2.2.1. get abstract
                abstract = driver.find_element(By.CLASS_NAME, "abstractSection")
                # concat all paragraphs
                abstract = "\n".join(
                    [p.text.strip() for p in abstract.find_elements(By.TAG_NAME, "p")]
                )
            except:
                QproDefaultConsole.print(QproWarnString, f"False page: {current_url}")
                continue
        elif 'ieeexplore.ieee.org' in current_url: # IEEE
            # 2.2.2. get abstract
            abstract = driver.find_element(By.CLASS_NAME, 'abstract-text')
            abstract = abstract.text.strip()
        elif 'www.computer.org' in current_url:
            if 'Please accept our sincere apologies, but the page you are looking for could not be found.' in driver.page_source:
                QproDefaultConsole.print(QproErrorString, f"404 page: {current_url}")
                paper_404s.append(doi)
                continue
            abstract = driver.find_element(By.CLASS_NAME, 'article-content')
            abstract = abstract.text.strip()
        elif 'link.springer.com' in current_url:
            abstract = driver.find_element(By.ID, 'Abs1-content')
            abstract = abstract.text.strip()
        else:
            QproDefaultConsole.print(QproErrorString, f"Unknown page: {current_url}")
            continue
        item['info']['abstract'] = abstract
        if index % 10:
            save()
    for url in paper_404s:
        # remove 404 paper
        for _id, item in enumerate(papers):
            if item['info']['ee'] == url:
                i = _id
                break
        papers.pop(i)
    QproDefaultStatus.stop()

@app.command()
def deal(path: str, within_years: int = 0):
    """
    处理 dblp 搜索结果页面，生成每篇论文的摘要

    :param path: json file
    :param within_years: within years
    """
    global _path, _data
    _path = path

    with open(path, "r") as f:
        import json
        _data = json.load(f)
    
    # delete papers that are not within years
    delete = []
    import datetime
    current_year = datetime.datetime.now().year
    for item in _data['result']['hits']['hit']:
        if 'year' not in item['info']:
            if 'ee' in item['info']:
                delete.append(item['info']['ee'])
            else:
                QproDefaultConsole.print(QproErrorString, f"Unknown paper: {item['info']}")
            continue
        if within_years and int(item['info']['year']) < current_year - within_years:
            delete.append(item['info'].get('ee', 'NEED_DELETE'))
    for url in delete:
        for _id, item in enumerate(_data['result']['hits']['hit']):
            if item['info'].get('ee', 'NEED_DELETE') == url:
                i = _id
                break
        _data['result']['hits']['hit'].pop(i)
    
    save()
    parse_dois(_data['result']['hits']['hit'])
    save()
    closeLocalDriver()


@app.command()
def ai_auto_detect(path: str, content: str):
    """
    使用 GPT-3 来判断论文摘要是否符合内容要求

    :param path: json file
    :param content: content
    """
    from QuickStart_Rhy.API.GPT import ChatGPT
    from QuickStart_Rhy.apiTools import translate
    import re

    global _path, _data

    _path = path

    with open(_path, "r") as f:
        import json
        _data = json.load(f)
    
    trend_threshold = 40
    delete = []
    QproDefaultStatus("GPT-3 自动判断").start()
    for item in _data['result']['hits']['hit']:
        if 'abstract' not in item['info']:
            continue # no abstract
        if 'abstract-check' in item['info'] and 'abstract-gpt' in item['info'] and 'trend' in item['info']:
            continue # already detect
        if 'ee' not in item['info']:
            delete.append(item['info']['ee'])
            continue # no ee

        QproDefaultStatus.update(f"识别: {item['info']['title']}")
        if 'abstract-check' not in item['info']:
            check = ChatGPT(f"请判断下述论文摘要与\"{content}\"的相关程度, 给出0到100之间的分数, 0表示毫无关系, 100表示密切相关:\n{item['info']['abstract']}\n\n")
            res = ''
            for item in check:
                res = item
            check = res
            item['info']['abstract-check'] = check
        else:
            check = item['info']['abstract-check']
        QproDefaultConsole.print(QproInfoString, f"GPT 相关性判断: [bold green]{check}[/]")
        # trend = %f分
        match_strings = [r"\d+\.?\d*分", r"\d+\.?\d*的高分", r"\d+\.?\d*的分数", r"\d+\.?\d*的得分", r"\d+\.?\d*的评分", r"\d+\.?\d*分数", r"\d+\.?\d*得分", r"\d+\.?\d*评分", r"分数.*?\d+\.?\d*", r"得分.*?\d+\.?\d*", r"评分.*?\d+\.?\d*", r"\d+\.?\d*"]
        trend = []
        for match_string in match_strings:
            trend = re.findall(match_string, check)
            if trend:
                break
        if not trend:
            QproDefaultConsole.print(QproWarnString, f"未识别评分, 跳过论文")
            continue
        trend = [re.findall(r"\d+\.?\d*", i)[0] for i in trend]
        trend = float(trend[0])
        item['info']['trend'] = trend
        if trend is not None:
            if trend < trend_threshold: # delete paper
                QproDefaultConsole.print(QproWarnString, f"识别评分: {trend}, 删除论文")
                continue
            else:
                QproDefaultConsole.print(QproInfoString, f"识别评分: {trend}, 保留论文")
        else:
            QproDefaultConsole.print(QproWarnString, f"trend: None")
        QproDefaultConsole.print('-' * QproDefaultConsole.width)
        save()
    QproDefaultStatus.stop()
    for item in _data['result']['hits']['hit']:
        if 'trend' in item['info'] and item['info']['trend'] < trend_threshold:
            delete.append(item['info']['ee'])
    for url in delete:
        for _id, item in enumerate(_data['result']['hits']['hit']):
            if item['info']['ee'] == url:
                i = _id
                break
        _data['result']['hits']['hit'].pop(i)
    save()
    QproDefaultStatus("GPT-3 自动总结").start()
    for item in _data['result']['hits']['hit']:
        if not item['info'].get('abstract-zh'):
            while True:
                try:
                    QproDefaultStatus.update(f"翻译: {item['info']['title']}")
                    abstract = translate(item['info']['abstract'])
                    if abstract is not None:
                        break
                    QproDefaultConsole.print(QproErrorString, "Translate failed, retry...")
                except Exception as e:
                    QproDefaultConsole.print(QproErrorString, e)
                finally:
                    time.sleep(3)
            item['info']['abstract-zh'] = abstract
        QproDefaultStatus.update(f"GPT-3 总结: {item['info']['title']}")
        if 'abstract-gpt' not in item['info']:
            item['info']['abstract-gpt'] = ChatGPT(f"请帮我将如下论文摘要用100字以内的中文概括:\n{item['info']['abstract-zh']}\n\n", True, True)
        QproDefaultConsole.print(QproInfoString, f"GPT-3 总结: [bold green]{item['info']['abstract-gpt']}[/]")
        save()
    QproDefaultStatus.stop()


# 统计
@app.command()
def stat(ls: list, disable_cur_year: bool = False):
    """
    统计当前数据
    """
    import datetime

    ls = [i for i in ls if i.endswith(".json")]
    cur_year = str(datetime.datetime.now().year)

    ss = set()
    for i in ls:
        with open(os.path.join(os.getcwd(), i), "r") as f:
            import json
            data = json.load(f)
        # total += len(data['result']['hits']['hit'])
        for item in data['result']['hits']['hit']:
            if 'ee' not in item['info']:
                continue
            if item['info']['year'] == cur_year and disable_cur_year:
                continue
            ss.add(item['info']['ee'])
    QproDefaultConsole.print(QproInfoString, f"Total: {len(ss)}")
    return len(ss), cur_year


@app.command()
def draw(title: str, ls: list, disable_cur_year: bool = False):
    # draw trend
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    import matplotlib
    import numpy as np

    ls = [i for i in ls if i.endswith(".json")]
    keywords = set([i.split('-')[0] for i in ls])
    QproDefaultConsole.print(QproInfoString, f"Keywords: {keywords}")
    total_num, cur_year = app.real_call('stat', ls, disable_cur_year)

    fm.fontManager.addfont('/Users/lianhaocheng/Library/Fonts/微软雅黑.ttf')

    # 设置字体名称，注意这里不是路径
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei']
    matplotlib.rcParams['axes.unicode_minus'] = False

    year_set = set()
    paper_set = set()
    count_year = {}

    for i in ls:
        with open(os.path.join(os.getcwd(), i), "r") as f:
            import json
            data = json.load(f)
        for item in data['result']['hits']['hit']:
            if 'ee' not in item['info'] or item['info']['ee'] in paper_set:
                continue
            # 依据venue和year统计
            if item['info']['venue'] not in count_year:
                count_year[item['info']['venue']] = {}
            if item['info']['year'] == cur_year and disable_cur_year:
                continue
            if item['info']['year'] not in count_year[item['info']['venue']]:
                count_year[item['info']['venue']][item['info']['year']] = 0
            count_year[item['info']['venue']][item['info']['year']] += 1
            paper_set.add(item['info']['ee'])
            year_set.add(item['info']['year'])
    # count_year = sorted(count_year.items(), key=lambda x: x[0])
    # 画堆叠柱状图
    years = sorted(list(year_set), key=lambda x: int(x))
    venues = list(count_year.keys())
    venues.sort()
    bottom = np.zeros(len(years))
    for i, venue in enumerate(venues):
        ls = [count_year[venue].get(year, 0) for year in years]
        plt.bar(years, ls, bottom=bottom, label=venue)
        bottom += np.array(ls)
    plt.xlabel('年份', fontsize=16)
    plt.ylabel('数量', fontsize=16)
    # int yticks
    plt.yticks([i for i in range(0, int(max(bottom)) + 1, 5)], fontsize=16)
    plt.xticks(fontsize=16)
    plt.legend(loc='best', fontsize=16)
    plt.title(f'{title}: {total_num}', fontsize=16)
    plt.tight_layout()
    plt.savefig('trend.svg', format='svg')
    # plt.show()

@app.command()
def table(name: str, paths: list):
    """
    json 转 table

    :param path: json file
    """
    import re
    with open(f'{name}.md', 'w', encoding='utf-8') as f:
        f.write(f"|年份|会议|论文标题|摘要|\n")
        f.write(f"|---|---|---|---|\n")
        total_data = []
        for path in paths:
            with open(path, "r") as jf:
                import json
                data = json.load(jf)    
            total_data += data['result']['hits']['hit']
        # sorted(total_data, key=lambda x: -x['info']['trend'])
        writed = set()
        for item in total_data:
            if item['info']['ee'] in writed:
                continue
            check = item['info'].get('abstract-gpt', '').replace('\n', ' ')
            if not check:
                check = item['info'].get('abstract', '').replace('\n', ' ')
            bib = item['info'].get('bib', '')
            if isinstance(item['info']['authors']['author'], dict):
                author = item['info']['authors']['author']['text']
            else:
                author = item['info']['authors']['author'][0]['text']
            if not bib or not author:
                continue
            # parse citation from bib
            citation = re.findall(r'@.*?{(.*?),', bib)[0]
            citation = "\\cite{" + citation + "}"
            bib = author + "等人" + check + citation
            # f.write(f"|{item['info']['year']}|{item['info']['venue']}|[{item['info']['title']}]({item['info']['ee']})|{item['info'].get('trend', '')}|{bib}|\n")
            f.write(f"|{item['info']['year']}|{item['info']['venue']}|[{item['info']['title']}]({item['info']['ee']})|{bib}|\n")
            writed.add(item['info']['ee'])


@app.command()
def dblp(keyword: str = '', is_exact: bool = False, venue: str = '', year: int = 0, journal: bool = False):
    """
    从dblp爬取数据

    :param keyword: 搜索关键词
    :param is_exact: 是否精确搜索
    :param venue: 会议名称
    :param year: 年份
    :param journal: 期刊
    """
    from urllib.parse import quote
    raw_title = keyword
    keyword = keyword
    if is_exact:
        keyword += '$'
    if journal:
        keyword += f' type:Journal_Articles:'
        keyword += f' streamid:journals/{journal}:'
    if venue:
        keyword += f' type:Conference_and_Workshop_Papers:'
        keyword += f' streamid:conf/{venue}:'
    if year:
        keyword += f' year:{year}:'

    # risc-v streamid:conf/micro: type:Conference_and_Workshop_Papers:&h=1000&format=json
    import requests
    
    root_domain = ['dblp.uni-trier.de', 'dblp.org']
    url_template = "https://{}/search/publ/api?q={}&h=1000&format=json"
    
    QproDefaultStatus("正在搜索...").start()
    for domain in root_domain:
        url = url_template.format(domain, quote(keyword))
        QproDefaultConsole.print(QproInfoString, url)
        while r := requests.get(url):
            if r.status_code == 200:
                break
            time.sleep(1)
        if 'Error 500: Internal Server Error' in r.text:
            QproDefaultStatus.stop()
            QproDefaultConsole.print(QproErrorString, "Error 500: Internal Server Error")
            return
        elif 'hit' not in r.json()['result']['hits']:
            QproDefaultConsole.print(QproWarnString, "Domain No result:", domain)
            continue
        else:
            break
    data = r.json()
    QproDefaultStatus("搜索完成").stop()
    if 'hit' not in data['result']['hits']:
        QproDefaultConsole.print(QproErrorString, "No result.")
        return
    if is_exact:
        delete = []
        # 首先删除没有 info->ee 的数据
        for item in data['result']['hits']['hit']:
            if 'ee' not in item['info']:
                delete.append(item['info']['title'])
        for i in delete:
            for _id, item in enumerate(data['result']['hits']['hit']):
                if item['info']['title'] == i:
                    index = _id
                    break
            data['result']['hits']['hit'].pop(index)
    
    file_name = raw_title # f"{raw_title}-{venue if venue else journal}"
    file_name += '-' if file_name else ''
    if venue or journal:
        file_name += venue if venue else journal
    file_name += '-' if file_name else ''
    if year:
        file_name += f"{year}"
    file_name += ".json"
    with open(file_name, "w") as f:
        import json
        json.dump(data, f, ensure_ascii=False, indent=4)


@app.command()
def remove_empty():
    """
    删除没有 info->ee 的数据
    """
    ls = os.listdir(os.getcwd())
    ls = [i for i in ls if i.endswith(".json")]
    for i in ls:
        with open(os.path.join(os.getcwd(), i), "r") as f:
            import json
            data = json.load(f)
        delete = []
        for item in data['result']['hits']['hit']:
            if 'ee' not in item['info']:
                delete.append(item['info']['title'])
        for d in delete:
            for _id, item in enumerate(data['result']['hits']['hit']):
                if item['info']['title'] == d:
                    index = _id
                    break
            data['result']['hits']['hit'].pop(index)
        if len(data['result']['hits']['hit']) == 0:
            os.remove(os.path.join(os.getcwd(), i))
            continue
        with open(os.path.join(os.getcwd(), i), "w") as f:
            import json
            json.dump(data, f, ensure_ascii=False, indent=4)


@app.command()
def get_bibtex(name: str, paths: list):
    """
    从 dblp 中获取 bibtex

    :param path: json file
    """
    global _path, _data
    
    import requests
    writed = set()
    with open(os.path.join(os.getcwd(), name + '.bib'), "w") as f:
        for path in paths:
            if not path.endswith(".json"):
                continue
            _path = path
            with open(_path, "r") as jf:
                import json
                _data = json.load(jf)
            for item in _data['result']['hits']['hit']:
                if 'ee' not in item['info'] or item['info']['ee'] in writed:
                    QproDefaultConsole.print(QproWarnString, f"跳过 {item['info']['title']}")
                    continue
                if not item['info'].get('bib'):
                    url = f"{item['info']['url']}.bib"
                    QproDefaultStatus("正在获取 bibtex...").start()
                    while r := requests.get(url):
                        if r.status_code == 200:
                            break
                        time.sleep(1)
                    if 'Error 500: Internal Server Error' in r.text:
                        QproDefaultConsole.print(QproErrorString, "Error 500: Internal Server Error")
                        return
                    QproDefaultStatus("获取 bibtex 完成").stop()
                    item['info']['bib'] = r.text
                    save()
                print(item['info']['bib'], file=f)
                writed.add(item['info']['ee'])


def main():
    """
    注册为全局命令时, 默认采用main函数作为命令入口, 请勿将此函数用作它途.
    When registering as a global command, default to main function as the command entry, do not use it as another way.
    """
    app()


if __name__ == "__main__":
    main()
