# -*- coding: utf-8 -*-
"""
AI行业变化雷达 Agent V3.5
V3 + 社区反馈摘要（触发式）+ 异常检测（是否触发重新评估）
依赖：feedparser，安装命令见文件末尾注释
"""

import re
import feedparser
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

# ———————— 三层信息源配置（可按需增删改）————————
# layer:
#   - official_model: 官方模型发布源
#   - dev_community : 开发者社区源
#   - industry      : 产业分析 / 科技媒体
RSS_FEEDS: List[Dict[str, str]] = [
    # 官方模型发布源
    {
        "name": "OpenAI Blog",
        "url": "https://openai.com/blog/rss.xml",
        "layer": "official_model",
    },
    {
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "layer": "official_model",
    },
    {
        "name": "Meta AI",
        "url": "https://ai.facebook.com/blog/rss/",
        "layer": "official_model",
    },
    {
        "name": "Anthropic",
        "url": "https://www.anthropic.com/news/rss",
        "layer": "official_model",
    },
    # 开发者社区源
    {
        "name": "Hacker News",
        "url": "https://news.ycombinator.com/rss",
        "layer": "dev_community",
    },
    {
        "name": "Reddit r/MachineLearning",
        "url": "https://www.reddit.com/r/MachineLearning/.rss",
        "layer": "dev_community",
    },
    {
        "name": "Reddit r/LocalLLaMA",
        "url": "https://www.reddit.com/r/LocalLLaMA/.rss",
        "layer": "dev_community",
    },
    # 产业分析源
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/tag/artificial-intelligence/feed/",
        "layer": "industry",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
        "layer": "industry",
    },
    {
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "layer": "industry",
    },
]


def parse_published_date(entry) -> Tuple[datetime, str]:
    """从 RSS 条目中解析发布日期，返回 (datetime 或 None, 显示用字符串)"""
    # 优先用 published，没有则用 updated
    time_struct = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    if time_struct is None:
        return None, "日期未知"
    try:
        dt = datetime(*time_struct[:6])
        return dt, dt.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        # 兜底：直接用原始字符串
        raw = getattr(entry, "published", None) or getattr(
            entry, "updated", None
        ) or "日期未知"
        return None, str(raw)


def classify_topic(title: str) -> str:
    """根据标题的关键词粗略判定主题分类（模型 / 算力 / 应用 / 监管 / 融资）"""
    t = title.lower()

    # 1. 模型
    model_keywords = [
        "model",
        "模型",
        "gpt",
        "llm",
        "llama",
        "gemini",
        "claude",
        "checkpoint",
        "weights",
        "pretrain",
        "pre-trained",
        "fine-tune",
        "fine tune",
        "inference",
    ]
    if any(k in t for k in model_keywords):
        return "模型"

    # 2. 算力 / 芯片 / 基础设施
    infra_keywords = [
        "gpu",
        "chip",
        "chips",
        "半导体",
        "nvidia",
        "amd",
        "intel",
        "算力",
        "compute",
        "datacenter",
        "data center",
        "accelerator",
        "cloud",
    ]
    if any(k in t for k in infra_keywords):
        return "算力"

    # 3. 监管 / 政策
    regulation_keywords = [
        "regulation",
        "regulatory",
        "policy",
        "policies",
        "law",
        "法律",
        "监管",
        "合规",
        "compliance",
        "guideline",
        "rules",
        "ban",
        "禁止",
        "欧盟",
        "eu",
        "白皮书",
        "安全框架",
    ]
    if any(k in t for k in regulation_keywords):
        return "监管"

    # 4. 融资 / 并购
    funding_keywords = [
        "融资",
        "funding",
        "raise",
        "raised",
        "round",
        "series a",
        "series b",
        "series c",
        "investment",
        "investor",
        "vc",
        "收购",
        "并购",
        "acquisition",
        "merger",
    ]
    if any(k in t for k in funding_keywords):
        return "融资"

    # 默认归为“应用”
    return "应用"


def estimate_change_level(title: str, layer: str) -> str:
    """根据标题关键词 + 信息源层级估算“变化级别”（重大/中等/噪音）"""
    t = title.lower()

    major_keywords = [
        "重大",
        "重磅",
        "breakthrough",
        "突破",
        "state-of-the-art",
        "sota",
        "new generation",
        "新一代",
        "largest",
        "biggest",
        "史上",
        "首个",
        "first",
        "record",
        "纪录",
        "融资",
        "funding",
        "acquisition",
        "收购",
        "并购",
    ]
    medium_keywords = [
        "launch",
        "发布",
        "announces",
        "announce",
        "unveil",
        "upgrade",
        "升级",
        "preview",
        "beta",
        "general availability",
        "ga",
        "支持",
        "integration",
        "集成",
    ]

    # 官方模型源 + 强关键词 → 重大
    if layer == "official_model" and any(k in t for k in major_keywords):
        return "重大"

    # 标题本身很“重磅” → 重大
    if any(k in t for k in major_keywords):
        return "重大"

    # 有发布/升级类关键词 → 中等
    if any(k in t for k in medium_keywords):
        return "中等"

    # 开发者社区里被讨论的新工具/新库 → 中等
    dev_signals = ["show hn", "ask hn", "[d]", "[p]", "github", "paper"]
    if layer == "dev_community" and any(k in t for k in dev_signals):
        return "中等"

    return "噪音"


def estimate_community_heat(title: str, layer: str) -> str:
    """社区热度（高/中/低），RSS 多数没有评论/点赞，就用标题 + 来源层级做启发式估计"""
    t = title.lower()
    score = 0

    # 开发者社区本身就更偏“热议”
    if layer == "dev_community":
        score += 1

    # HN / Reddit 典型高热度信号
    if "show hn" in t or "ask hn" in t:
        score += 2
    if "github" in t or "paper" in t or "implementation" in t:
        score += 1

    # 带有“爆火/热议/viral/trending”等词
    hot_keywords = ["爆火", "热议", "viral", "trending", "热门", "must read", "🔥"]
    if any(k in t for k in hot_keywords):
        score += 2

    if score >= 3:
        return "高"
    if score >= 1:
        return "中"
    return "低"


def compute_importance_score(
    topic: str, change_level: str, community_heat: str, layer: str
) -> int:
    """综合打分：重要度 1-5"""
    score = 1  # 底线分

    # 变化级别权重最大
    if change_level == "重大":
        score += 3
    elif change_level == "中等":
        score += 1

    # 社区热度加成
    if community_heat == "高":
        score += 1
    elif community_heat == "中":
        score += 0  # 可以视需要调整

    # 官方模型层 + 模型/算力类 → 额外加权
    if layer == "official_model" and topic in ("模型", "算力"):
        score += 1

    # 截断到 1-5 区间
    return max(1, min(5, score))


# ———————— V3.5 模块 1：社区反馈摘要（触发式）————————


def extract_first_3_english_words(title: str) -> str:
    """从标题提取前 3 个英文单词，用于 RSS 搜索关键词"""
    words = re.findall(r"[a-zA-Z]+", title)
    return " ".join(words[:3]) if words else ""


def fetch_community_titles(keyword_query: str, max_per_feed: int = 8) -> List[str]:
    """用关键词请求 HN / Reddit 搜索 RSS，返回社区标题列表（仅标题文本）"""
    if not keyword_query.strip():
        return []
    q = quote_plus(keyword_query.strip())
    titles = []
    headers = {"User-Agent": "AI-News-Agent/3.5"}

    # Hacker News 搜索 RSS
    try:
        hn_url = f"https://hnrss.org/newest?q={q}"
        parsed = feedparser.parse(hn_url, request_headers=headers)
        for e in (parsed.entries or [])[:max_per_feed]:
            t = (e.get("title") or "").strip()
            if t:
                titles.append(t)
    except Exception:
        pass

    # Reddit 搜索 RSS
    try:
        reddit_url = f"https://www.reddit.com/search.rss?q={q}&sort=new"
        parsed = feedparser.parse(reddit_url, request_headers=headers)
        for e in (parsed.entries or [])[:max_per_feed]:
            t = (e.get("title") or "").strip()
            if t:
                titles.append(t)
    except Exception:
        pass

    return titles


def generate_community_feedback_summary(community_titles: List[str]) -> Dict[str, str]:
    """根据社区标题关键词简单规则生成：主要赞点、主要质疑、是否认为有突破性"""
    praise_keywords = [
        "great", "amazing", "impressive", "strong", "good", "best", "love", "推荐",
        "好用", "强", "厉害", "突破", "breakthrough", "improved", "better", "fast",
        "easy", "simple", "clean", "solid", "works well", "excited",
    ]
    doubt_keywords = [
        "overhyped", "overrated", "concern", "issue", "problem", "bad", "weak",
        "质疑", "问题", "局限", "expensive", "cost", "risk", "worry", "not sure",
        "meh", "disappoint", "missing", "lack", "still", "yet",
    ]
    text = " ".join(t.lower() for t in community_titles)
    praise_count = sum(1 for k in praise_keywords if k in text)
    doubt_count = sum(1 for k in doubt_keywords if k in text)

    if praise_count > doubt_count:
        breakthrough = "是"
    elif doubt_count > praise_count:
        breakthrough = "否"
    else:
        breakthrough = "观点分歧"

    # 用关键词命中生成一句话描述
    praise_line = "性能与易用性获认可、讨论热度高。" if praise_count > 0 else "（暂无明确赞点）"
    doubt_line = "成本与落地效果存疑、部分认为被高估。" if doubt_count > 0 else "（暂无明确质疑）"
    if not community_titles:
        praise_line = "（未获取到社区讨论）"
        doubt_line = "（未获取到社区讨论）"
        breakthrough = "—"

    return {
        "主要赞点": praise_line,
        "主要质疑": doubt_line,
        "是否认为有突破性": breakthrough,
    }


def add_community_feedback_if_triggered(news_item: Dict) -> None:
    """若满足触发条件则拉取社区讨论并写入 community_feedback 摘要（就地修改）"""
    if (
        news_item.get("layer") != "official_model"
        or news_item.get("topic") != "模型"
        or news_item.get("change_level") != "重大"
    ):
        news_item["community_feedback"] = None
        return
    keyword = extract_first_3_english_words(news_item.get("title") or "")
    titles = fetch_community_titles(keyword)
    news_item["community_feedback"] = generate_community_feedback_summary(titles)


# ———————— V3.5 模块 2：异常检测（是否触发重新评估）————————


def normalize_keyword_for_similarity(title: str) -> str:
    """用于“相似关键词”比对：取标题前 3 个英文词并小写"""
    words = re.findall(r"[a-zA-Z]+", title.lower())
    return " ".join(words[:3]) if words else ""


def should_trigger_re_eval(
    item: Dict, all_news_with_ts: List[Dict], now: Optional[datetime] = None
) -> bool:
    """
    是否触发重新评估：Yes/No 对应 True/False。
    规则 1：official_model + 重大 + community_heat=高
    规则 2：topic=算力 + 重大 + 标题含 funding/$/billion/融资
    规则 3：24 小时内 ≥3 个不同源讨论相似关键词
    """
    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=24)
    title = (item.get("title") or "").lower()
    layer = item.get("layer")
    topic = item.get("topic")
    change = item.get("change_level")
    heat = item.get("community_heat")
    src = item.get("source")

    # 规则 1
    if layer == "official_model" and change == "重大" and heat == "高":
        return True

    # 规则 2
    if topic == "算力" and change == "重大":
        if any(k in title for k in ["funding", "$", "billion", "融资"]):
            return True

    # 规则 3：24h 内 ≥3 个不同源有相似关键词
    key = normalize_keyword_for_similarity(item.get("title") or "")
    if not key:
        return False
    sources_with_same_key = set()
    for n in all_news_with_ts:
        ts = n.get("_ts")
        if ts is None or ts < cutoff:
            continue
        other_key = normalize_keyword_for_similarity(n.get("title") or "")
        if other_key == key:
            sources_with_same_key.add(n.get("source"))
    if len(sources_with_same_key) >= 3:
        return True

    return False


def fetch_one_feed(feed_info: Dict[str, str]):
    """抓取单个 RSS 源，返回 (来源名, 层级, 条目列表)"""
    name = feed_info["name"]
    url = feed_info["url"]
    layer = feed_info["layer"]
    try:
        # 设置 User-Agent，避免部分源拒绝请求
        parsed = feedparser.parse(
            url,
            request_headers={"User-Agent": "AI-News-Agent/3.0"},
            
        )
    except Exception as e:
        print(f"  [跳过] {name}: 请求失败 ({e})", flush=True)
        return name, layer, []

    if getattr(parsed, "bozo", False) and not parsed.entries:
        print(f"  [跳过] {name}: 解析异常", flush=True)
        return name, layer, []

    items = []
    for entry in parsed.entries[:10]:  # 每个源最多取 10 条
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title:
            continue

        ts, date_str = parse_published_date(entry)

        # 主题分类
        topic = classify_topic(title)
        # 变化级别
        change_level = estimate_change_level(title, layer)
        # 社区热度
        community_heat = estimate_community_heat(title, layer)
        # 综合重要度评分
        importance = compute_importance_score(topic, change_level, community_heat, layer)

        items.append(
            {
                "title": title,
                "link": link,
                "published_date": date_str,
                "_ts": ts,
                "source": name,
                "layer": layer,
                "topic": topic,
                "change_level": change_level,
                "community_heat": community_heat,
                "importance": importance,
            }
        )
    return name, layer, items


def get_ai_news():
    """从配置的 RSS 源抓取新闻，做变化雷达标注 + V3.5 社区反馈与异常检测，再按重要度+时间排序"""
    all_news = []
    for feed in RSS_FEEDS:
        name, layer, items = fetch_one_feed(feed)
        all_news.extend(items)

    # 按重要度（高→低）、发布时间（新→旧）排序
    def sort_key(x):
        ts = x.get("_ts") or datetime.min
        return (-x["importance"], -(ts.timestamp()))

    all_news.sort(key=sort_key)

    # V3.5：社区反馈摘要（仅对 official_model + 模型 + 重大 触发）
    for n in all_news:
        add_community_feedback_if_triggered(n)

    # V3.5：异常检测（是否触发重新评估），需在去掉 _ts 前用全部条目做 24h 相似关键词统计
    now = datetime.utcnow()
    for n in all_news:
        n["re_eval"] = "Yes" if should_trigger_re_eval(n, all_news, now) else "No"

    # 去掉内部字段
    for n in all_news:
        n.pop("_ts", None)
    return all_news


def print_daily_report(news_list):
    """按“AI 行业变化雷达日报”格式打印（含 V3.5 社区反馈与是否重新评估）"""
    print("=" * 50)
    print("      AI 行业变化雷达日报")
    print("=" * 50)
    print()
    for i, news in enumerate(news_list, 1):
        print(f"【{i}】{news['title']}")
        print(f"来源：{news['source']} | 日期：{news['published_date']}")
        print(f"分类：{news['topic']}")
        print(f"变化级别：{news['change_level']}")
        print(f"社区热度：{news['community_heat']}")
        print(f"重要度：{news['importance']}/5")
        print(f"是否触发重新评估：{news.get('re_eval', 'No')}")
        cf = news.get("community_feedback")
        if cf:
            print("社区反馈摘要：")
            print(f"  主要赞点：{cf.get('主要赞点', '—')}")
            print(f"  主要质疑：{cf.get('主要质疑', '—')}")
            print(f"  是否认为有突破性：{cf.get('是否认为有突破性', '—')}")
        print(f"链接：{news['link']}")
        print()
    print("=" * 50)
    print("        — 雷达日报结束 —")
    print("=" * 50)


if __name__ == "__main__":
    # 1. 从 RSS 抓取新闻
    news = get_ai_news()
    # 2. 输出日报
    print_daily_report(news)

# 依赖安装（首次运行前执行一次）：
#   pip install feedparser
