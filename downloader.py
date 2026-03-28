"""
Syosetu (小説家になろう) 章节正文下载器
作者：fishundbug

使用方式：运行脚本后，按提示输入正文页面链接即可下载。
链接格式示例：https://ncode.syosetu.com/n8611bv/561/
输出文件名示例：N8611BV-561.txt
"""

import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path


def parse_filename_from_url(url: str) -> str:
    """
    从 URL 中提取 ncode 和章节号，拼接为大写文件名。
    例：https://ncode.syosetu.com/n8611bv/561/ → N8611BV-561.txt
    """
    match = re.search(r"ncode\.syosetu\.com/([^/]+)/(\d+)", url)
    if not match:
        raise ValueError(f"无法从链接中解析出 ncode 和章节号：{url}")
    ncode = match.group(1).upper()
    chapter = match.group(2)
    return f"{ncode}-{chapter}.txt"


def _extract_text_from_div(div) -> str:
    """从一个包含 <p> 段落的 div 中提取纯文本，保留换行。"""
    lines = []
    for p in div.find_all("p"):
        text = p.get_text()
        lines.append(text)
    return "\n".join(lines)


def fetch_chapter(url: str) -> tuple[str, str]:
    """
    请求页面并提取章节标题、正文和后记。
    返回 (标题, 完整文本)。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")

    # 提取章节标题
    title_tag = soup.select_one("h1.p-novel__title")
    title = title_tag.get_text(strip=True) if title_tag else "无标题"

    # 提取正文区域（排除后记，只匹配不带 --afterword 的）
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

    # 如果存在后记，追加在正文后面，用分隔线隔开
    if afterword_div:
        afterword_text = _extract_text_from_div(afterword_div)
        body_text += "\n\n" + "*" * 48 + "\n\n" + afterword_text

    return title, body_text


def main():
    print("=" * 50)
    print("  Syosetu 章节下载器")
    print("  输入 q 或 quit 退出")
    print("=" * 50)

    # 输出目录：脚本所在文件夹下的 output 子目录
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    while True:
        print()
        url = input("请输入正文页面链接：").strip()

        if url.lower() in ("q", "quit", "exit"):
            print("已退出。")
            break

        if not url:
            continue

        try:
            filename = parse_filename_from_url(url)
            print(f"  文件名：{filename}")
            print(f"  正在下载……")

            title, body = fetch_chapter(url)

            # 写入文件：标题 + 空行 + 正文
            out_path = output_dir / filename
            out_path.write_text(f"{title}\n\n{body}", encoding="utf-8")

            print(f"  ✓ 下载完成 → {out_path}")

        except Exception as e:
            print(f"  ✗ 下载失败：{e}")


if __name__ == "__main__":
    main()
