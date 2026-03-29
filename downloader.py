"""
Syosetu (小説家になろう) 章节下载器
作者：fishundbug

用法：
  交互模式：python downloader.py
  命令行模式：python downloader.py <URL> [-m 1|2] [-r 起-止] [--no-delay]

示例：
  python downloader.py https://ncode.syosetu.com/n8611bv/ -m 1 -r 10-50 --no-delay
"""

import argparse
import re
import shlex
import time
import random
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urljoin

# 每次请求之间的随机延迟范围（秒）
DELAY_MIN = 0.5
DELAY_MAX = 1.0

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

    # 提取正文区域
    # 按 HTML 原始顺序遍历所有 div，保留网页显示顺序
    # 正文主体（无 -- 修饰符）直接输出，其他区域用分隔线隔开
    body_divs = soup.select("div.js-novel-text.p-novel__text")

    if not body_divs:
        raise RuntimeError("未找到正文区域（div.js-novel-text.p-novel__text）")

    parts = []
    for div in body_divs:
        # 每个不同区域之间插入分隔线
        if parts:
            parts.append("*" * 48)

        parts.append(_extract_text_from_div(div))

    body_text = "\n\n".join(parts)

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
        else:
            current_url = None

    return novel_title, chapter_urls


def _parse_range(range_str: str, total: int) -> list[int]:
    """
    解析多段下载范围字符串，返回 0-based 索引列表（去重、排序）。
    支持格式：1-5,9,25-40
    """
    indices = set()
    for segment in range_str.split(","):
        segment = segment.strip()
        if not segment:
            continue
        range_match = re.match(r"(\d+)\s*[-~]\s*(\d+)$", segment)
        single_match = re.match(r"(\d+)$", segment)
        if range_match:
            start = max(1, int(range_match.group(1)))
            end = min(total, int(range_match.group(2)))
            indices.update(range(start - 1, end))  # 转为 0-based
        elif single_match:
            num = int(single_match.group(1))
            if 1 <= num <= total:
                indices.add(num - 1)
        else:
            print(f"  无法识别的片段: {segment}，已跳过。")

    if not indices:
        print("  未解析到有效范围，将下载全部。")
        return list(range(total))

    return sorted(indices)


def download_novel_batch(
    novel_url: str,
    output_dir: Path,
    mode: str | None = None,
    range_str: str | None = None,
    delay: bool | None = None,
):
    """
    整本下载小说。
    参数均为 None 时进入交互模式，否则跳过对应提示。
    """
    # 第一步：获取章节列表
    print("  正在获取章节列表……")
    novel_title, chapter_urls = fetch_novel_chapter_links(novel_url)

    if not chapter_urls:
        print("  ✗ 未找到任何章节链接。")
        return

    total = len(chapter_urls)
    print(f"\n  书名：{novel_title}")
    print(f"  共找到 {total} 个章节")

    # 第二步：确定下载参数
    # --- 保存方式 ---
    if mode is not None:
        merge_mode = (mode == "1")
    else:
        print()
        print("  请选择保存方式：")
        print("    [1] 合并为单个 TXT 文件")
        print("    [2] 每章单独保存为一个 TXT 文件")
        choice = input("  请输入选项 (1/2)：").strip()
        if choice not in ("1", "2"):
            print("  无效选项，默认使用分章保存。")
            choice = "2"
        merge_mode = (choice == "1")

    # --- 下载范围 ---
    if range_str is not None:
        selected_indices = _parse_range(range_str, total)
    else:
        print(f"\n  下载范围（共 {total} 章）：")
        range_input = input("  直接回车下载全部，或输入范围（如 1-5,9,25-40）：").strip()
        if range_input:
            selected_indices = _parse_range(range_input, total)
        else:
            selected_indices = list(range(total))

    selected_urls = [chapter_urls[i] for i in selected_indices]
    selected_total = len(selected_urls)
    print(f"  将下载 {selected_total} 章")

    # --- 随机延迟开关 ---
    if delay is not None:
        use_delay = delay
    else:
        delay_input = input("\n  启用随机延迟？(Y/n，默认启用)：").strip().lower()
        use_delay = delay_input not in ("n", "no")

    if use_delay:
        print(f"  已启用随机延迟（{DELAY_MIN}~{DELAY_MAX}s）")
    else:
        print("  已关闭随机延迟（全速下载）")

    # 第三步：逐章下载
    ncode_match = re.search(r"syosetu\.com/([^/]+)", novel_url)
    ncode = ncode_match.group(1).upper() if ncode_match else "UNKNOWN"

    if merge_mode:
        # 合并模式：所有章节写入同一个文件
        safe_title = _sanitize_filename(novel_title)
        out_path = output_dir / f"{safe_title}.txt"
        print(f"\n  将合并保存至：{out_path}")
        print()

        merged_parts = []
        for i, ch_url in enumerate(selected_urls, 1):
            print(f"  [{i}/{selected_total}] 正在下载……", end="", flush=True)
            try:
                title, body = fetch_chapter(ch_url)
                merged_parts.append(f"{'═' * 48}\n{title}\n{'═' * 48}\n\n{body}")
                print(f" ✓ {title}")
            except Exception as e:
                print(f" ✗ 失败：{e}")
                merged_parts.append(f"{'═' * 48}\n[下载失败] {ch_url}\n{'═' * 48}")

            if use_delay and i < selected_total:
                _random_delay()

        header = f"{novel_title}\n{'─' * 48}\n\n"
        out_path.write_text(header + "\n\n".join(merged_parts), encoding="utf-8")
        print(f"\n  ✓ 全部完成！已保存至 → {out_path}")

    else:
        # 分章模式：每章一个文件
        safe_title = _sanitize_filename(novel_title)
        novel_dir = output_dir / safe_title
        novel_dir.mkdir(exist_ok=True)
        print(f"\n  将保存至文件夹：{novel_dir}")
        print()

        for i, ch_url in enumerate(selected_urls, 1):
            ch_match = re.search(r"/(\d+)/?$", ch_url)
            ch_num = ch_match.group(1) if ch_match else str(i)

            print(f"  [{i}/{selected_total}] 正在下载……", end="", flush=True)
            try:
                title, body = fetch_chapter(ch_url)
                filename = f"{ncode}-{ch_num}.txt"
                file_path = novel_dir / filename
                file_path.write_text(f"{title}\n\n{body}", encoding="utf-8")
                print(f" ✓ {title}")
            except Exception as e:
                print(f" ✗ 失败：{e}")

            if use_delay and i < selected_total:
                _random_delay()

        print(f"\n  ✓ 全部完成！已保存至 → {novel_dir}")


def _sanitize_filename(name: str) -> str:
    """移除文件名中的非法字符。"""
    # Windows 文件名禁止字符：\ / : * ? " < > |
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()


# ─── 主程序 ──────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="Syosetu 章节下载器 — 支持单章下载与整本批量下载",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用示例:\n"
            "  downloader.py                                 进入交互模式\n"
            "  downloader.py <URL>                           整本下载(交互设置)\n"
            "  downloader.py <URL> -m 1                      合并为单文件\n"
            "  downloader.py <URL> -m 2 -r 10-50 --no-delay  分章+指定范围+全速\n"
            "  downloader.py <URL>/5/                        单章下载\n"
            "\n"
            "不传任何参数时进入交互模式, 交互模式中同样支持附加参数。"
        ),
    )
    parser.add_argument("url", nargs="?", default=None,
                        metavar="URL", help="小说目录页或章节页链接")
    parser.add_argument("-m", "--mode", choices=["1", "2"], metavar="N",
                        help="保存方式: 1=合并单文件, 2=分章保存")
    parser.add_argument("-r", "--range", dest="range_str", metavar="A-B",
                        help="下载范围, 如 1-5,9,25-40")
    parser.add_argument("--no-delay", action="store_true",
                        help="关闭随机延迟, 全速下载")
    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    # 输出目录：脚本所在文件夹下的 output 子目录
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    if args.url:
        # 命令行模式：直接执行
        try:
            if is_single_chapter_url(args.url):
                download_single_chapter(args.url, output_dir)
            else:
                # 有任一参数指定时，直接传入跳过交互
                delay = (not args.no_delay) if (args.no_delay or args.mode or args.range_str) else None
                download_novel_batch(
                    args.url, output_dir,
                    mode=args.mode,
                    range_str=args.range_str,
                    delay=delay,
                )
        except Exception as e:
            print(f"  ✗ 操作失败：{e}")
    else:
        # 交互模式
        print("=" * 50)
        print("  Syosetu 章节下载器")
        print("  支持单章下载 / 整本下载")
        print("=" * 50)
        print()
        print("  用法：直接输入 URL，或附加参数：")
        print("    <URL>                    交互式设置")
        print("    <URL> -m 1               合并为单文件")
        print("    <URL> -m 2               分章保存")
        print("    <URL> -r 1-5,9,25-40     指定下载范围")
        print("    <URL> --no-delay         关闭随机延迟")
        print("    <URL> -m 1 -r 10-50 --no-delay  组合使用")
        print()
        print("  输入 q 或 quit 退出")

        while True:
            print()
            user_input = input(">>> ").strip()

            if user_input.lower() in ("q", "quit", "exit"):
                print("已退出。")
                break

            if not user_input:
                continue

            # 将用户输入拆分为参数列表，复用 argparse 解析
            try:
                tokens = shlex.split(user_input)
            except ValueError:
                tokens = user_input.split()

            try:
                iargs = parser.parse_args(tokens)
            except SystemExit:
                # argparse 遇到无效参数会调用 sys.exit，捕获后继续
                continue

            if not iargs.url:
                print("  请输入 URL。")
                continue

            try:
                if is_single_chapter_url(iargs.url):
                    download_single_chapter(iargs.url, output_dir)
                else:
                    has_params = iargs.no_delay or iargs.mode or iargs.range_str
                    delay = (not iargs.no_delay) if has_params else None
                    download_novel_batch(
                        iargs.url, output_dir,
                        mode=iargs.mode,
                        range_str=iargs.range_str,
                        delay=delay,
                    )
            except Exception as e:
                print(f"  ✗ 操作失败：{e}")


if __name__ == "__main__":
    main()
