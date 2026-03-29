"""
Syosetu (小説家になろう) 章节下载器
作者：fishundbug

支持两种模式：
  1. 单章下载：输入章节页面链接（如 .../n8611bv/561/）
  2. 整本下载：输入小说目录页链接（如 .../n8611bv/）

整本下载时可选择：
  A) 合并为单个 TXT 文件
  B) 每章单独保存为一个 TXT 文件
"""

import re
import time
import random
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urljoin

# 每次请求之间的随机延迟范围（秒）
DELAY_MIN = 0.5
DELAY_MAX = 1.2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}


def _get_soup(url: str) -> BeautifulSoup:
    """请求页面并返回 BeautifulSoup 对象。"""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def _extract_text_from_div(div) -> str:
    """从一个包含 <p> 段落的 div 中提取纯文本，保留换行。"""
    lines = []
    for p in div.find_all("p"):
        text = p.get_text()
        lines.append(text)
    return "\n".join(lines)


def _random_delay():
    """在请求之间插入随机延迟，避免触发反爬。"""
    time.sleep(DELAY_MIN + random.random() * (DELAY_MAX - DELAY_MIN))


# ─── 判断链接类型 ─────────────────────────────────────────────

def is_single_chapter_url(url: str) -> bool:
    """判断 URL 是否指向单个章节（以数字路径结尾）。"""
    return bool(re.search(r"syosetu\.com/[^/]+/\d+/?$", url))


# ─── 单章下载（原有功能） ─────────────────────────────────────

def parse_filename_from_url(url: str) -> str:
    """
    从 URL 中提取 ncode 和章节号，拼接为大写文件名。
    例：https://ncode.syosetu.com/n8611bv/561/ → N8611BV-561.txt
    """
    match = re.search(r"syosetu\.com/([^/]+)/(\d+)", url)
    if not match:
        raise ValueError(f"无法从链接中解析出 ncode 和章节号：{url}")
    ncode = match.group(1).upper()
    chapter = match.group(2)
    return f"{ncode}-{chapter}.txt"


def fetch_chapter(url: str) -> tuple[str, str]:
    """
    请求页面并提取章节标题、正文和后记。
    返回 (标题, 完整文本)。
    """
    soup = _get_soup(url)

    # 提取章节标题
    title_tag = soup.select_one("h1.p-novel__title")
    title = title_tag.get_text(strip=True) if title_tag else "无标题"

    # 提取正文区域（区分正文和后记）
    body_divs = soup.select("div.js-novel-text.p-novel__text")
    main_div = None
    afterword_div = None
    for div in body_divs:
        classes = div.get("class", [])
        if "p-novel__text--afterword" in classes:
            afterword_div = div
        elif main_div is None:
            main_div = div

    if not main_div:
        raise RuntimeError("未找到正文区域（div.js-novel-text.p-novel__text）")

    body_text = _extract_text_from_div(main_div)

    # 如果存在后记，追加在正文后面
    if afterword_div:
        afterword_text = _extract_text_from_div(afterword_div)
        body_text += "\n\n" + "*" * 48 + "\n\n" + afterword_text

    return title, body_text


def download_single_chapter(url: str, output_dir: Path):
    """下载单个章节并保存为文件。"""
    filename = parse_filename_from_url(url)
    print(f"  文件名：{filename}")
    print(f"  正在下载……")

    title, body = fetch_chapter(url)

    out_path = output_dir / filename
    out_path.write_text(f"{title}\n\n{body}", encoding="utf-8")
    print(f"  ✓ 下载完成 → {out_path}")


# ─── 整本下载（新增功能） ─────────────────────────────────────

def fetch_novel_chapter_links(novel_url: str) -> tuple[str, list[str]]:
    """
    从小说目录页提取书名和所有章节的 URL。
    自动处理分页（通过"次へ"按钮逐页遍历）。
    返回 (书名, [章节URL列表])。
    """
    # 确保 URL 以 / 结尾
    if not novel_url.endswith("/"):
        novel_url += "/"

    chapter_urls = []
    novel_title = ""
    current_url = novel_url
    page_num = 1

    while current_url:
        print(f"  正在解析目录第 {page_num} 页……")
        soup = _get_soup(current_url)

        # 首页提取书名
        if not novel_title:
            title_tag = soup.select_one("h1.p-novel__title")
            novel_title = title_tag.get_text(strip=True) if title_tag else "未知书名"

        # 提取当前页所有章节链接
        for a_tag in soup.select("a.p-eplist__subtitle"):
            href = a_tag.get("href", "")
            if href:
                full_url = urljoin(current_url, href)
                chapter_urls.append(full_url)

        # 查找"下一页"链接
        next_link = soup.select_one("a.c-pager__item--next")
        if next_link:
            next_href = next_link.get("href", "")
            current_url = urljoin(current_url, next_href) if next_href else None
            page_num += 1
            _random_delay()
        else:
            current_url = None

    return novel_title, chapter_urls


def download_novel_batch(novel_url: str, output_dir: Path):
    """
    整本下载小说。
    先获取所有章节链接，再让用户选择保存方式，最后逐章下载。
    """
    # 第一步：获取章节列表
    print("  正在获取章节列表……")
    novel_title, chapter_urls = fetch_novel_chapter_links(novel_url)

    if not chapter_urls:
        print("  ✗ 未找到任何章节链接。")
        return

    print(f"\n  书名：{novel_title}")
    print(f"  共找到 {len(chapter_urls)} 个章节")

    # 第二步：让用户选择保存方式
    print()
    print("  请选择保存方式：")
    print("    [1] 合并为单个 TXT 文件")
    print("    [2] 每章单独保存为一个 TXT 文件")
    choice = input("  请输入选项 (1/2)：").strip()

    if choice not in ("1", "2"):
        print("  无效选项，默认使用分章保存。")
        choice = "2"

    merge_mode = (choice == "1")

    # 第三步：逐章下载
    # 提取 ncode 用于命名
    ncode_match = re.search(r"syosetu\.com/([^/]+)", novel_url)
    ncode = ncode_match.group(1).upper() if ncode_match else "UNKNOWN"

    if merge_mode:
        # 合并模式：所有章节写入同一个文件
        # 文件名使用书名（过滤非法字符）
        safe_title = _sanitize_filename(novel_title)
        out_path = output_dir / f"{safe_title}.txt"
        print(f"\n  将合并保存至：{out_path}")
        print()

        merged_parts = []
        for i, ch_url in enumerate(chapter_urls, 1):
            print(f"  [{i}/{len(chapter_urls)}] 正在下载……", end="", flush=True)
            try:
                title, body = fetch_chapter(ch_url)
                merged_parts.append(f"{'═' * 48}\n{title}\n{'═' * 48}\n\n{body}")
                print(f" ✓ {title}")
            except Exception as e:
                print(f" ✗ 失败：{e}")
                merged_parts.append(f"{'═' * 48}\n[下载失败] {ch_url}\n{'═' * 48}")

            if i < len(chapter_urls):
                _random_delay()

        # 写入文件
        header = f"{novel_title}\n{'─' * 48}\n\n"
        out_path.write_text(header + "\n\n".join(merged_parts), encoding="utf-8")
        print(f"\n  ✓ 全部完成！已保存至 → {out_path}")

    else:
        # 分章模式：每章一个文件，放在以书名命名的子文件夹中
        safe_title = _sanitize_filename(novel_title)
        novel_dir = output_dir / safe_title
        novel_dir.mkdir(exist_ok=True)
        print(f"\n  将保存至文件夹：{novel_dir}")
        print()

        for i, ch_url in enumerate(chapter_urls, 1):
            # 从 URL 提取章节号
            ch_match = re.search(r"/(\d+)/?$", ch_url)
            ch_num = ch_match.group(1) if ch_match else str(i)

            print(f"  [{i}/{len(chapter_urls)}] 正在下载……", end="", flush=True)
            try:
                title, body = fetch_chapter(ch_url)
                filename = f"{ncode}-{ch_num}.txt"
                file_path = novel_dir / filename
                file_path.write_text(f"{title}\n\n{body}", encoding="utf-8")
                print(f" ✓ {title}")
            except Exception as e:
                print(f" ✗ 失败：{e}")

            if i < len(chapter_urls):
                _random_delay()

        print(f"\n  ✓ 全部完成！已保存至 → {novel_dir}")


def _sanitize_filename(name: str) -> str:
    """移除文件名中的非法字符。"""
    # Windows 文件名禁止字符：\ / : * ? " < > |
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()


# ─── 主程序 ──────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  Syosetu 章节下载器")
    print("  支持单章下载 / 整本下载")
    print("  输入 q 或 quit 退出")
    print("=" * 50)

    # 输出目录：脚本所在文件夹下的 output 子目录
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    while True:
        print()
        url = input("请输入链接（章节页 或 小说目录页）：").strip()

        if url.lower() in ("q", "quit", "exit"):
            print("已退出。")
            break

        if not url:
            continue

        try:
            if is_single_chapter_url(url):
                # 单章模式
                download_single_chapter(url, output_dir)
            else:
                # 整本模式
                download_novel_batch(url, output_dir)
        except Exception as e:
            print(f"  ✗ 操作失败：{e}")


if __name__ == "__main__":
    main()
