# 官方工具描述与 Schema 常量
# 对齐版本: tavily-mcp v0.2.4+

TAVILY_SEARCH_DESCRIPTION = "使用 Tavily AI 搜索引擎执行强大的网页搜索。返回相关的网页内容，支持自定义结果数量、内容类型和域名过滤。非常适合获取当前信息、新闻和详细的网页内容分析。"
TAVILY_EXTRACT_DESCRIPTION = "强大的网页内容提取工具，从指定 URL 获取并处理原始内容。非常适合数据采集、内容分析和研究任务。"
TAVILY_CRAWL_DESCRIPTION = "系统性地探索和爬取网站。从起始 URL 开始，像树一样扩展并遵循内部链接。可以控制深度、广度，并引导爬虫关注特定部分。"
TAVILY_MAP_DESCRIPTION = "创建网站 URL 的结构化地图。用于发现和分析站点结构、内容组织和导航路径。非常适合站点审计和内容发现。"

# 工具参数 Schema
TAVILY_SEARCH_SCHEMA = {
    "query": {"type": "string", "description": "搜索查询语句"},
    "search_depth": {
        "type": "string",
        "enum": ["basic", "advanced"],
        "description": "搜索深度。'basic' 速度较快，'advanced' 质量更高且包含更多上下文。"
    },
    "topic": {
        "type": "string",
        "enum": ["general", "news", "finance"],
        "description": "搜索主题类别。"
    },
    "days": {"type": "number", "description": "搜索过去几天内的新闻（仅在 topic 为 news 时有效）。"},
    "max_results": {"type": "number", "description": "返回的最大结果数（默认 5，最大 20）。"},
    "include_images": {"type": "boolean", "description": "是否在结果中包含相关图片。"},
    "include_answer": {"type": "boolean", "description": "是否包含由 AI 生成的简短回答。"},
    "include_raw_content": {"type": "boolean", "description": "是否包含网页的原始 HTML 内容。"},
    "include_domains": {"type": "array", "items": {"type": "string"}, "description": "要包含的特定域名列表。"},
    "exclude_domains": {"type": "array", "items": {"type": "string"}, "description": "要排除的特定域名列表。"},
    "time_range": {
        "type": "string",
        "enum": ["day", "week", "month", "year"],
        "description": "搜索的时间范围。"
    },
    "include_image_descriptions": {"type": "boolean", "description": "是否包含图片的文字描述。"}
}

TAVILY_EXTRACT_SCHEMA = {
    "urls": {"type": "array", "items": {"type": "string"}, "description": "要提取内容的 URL 列表。"},
    "extract_depth": {
        "type": "string",
        "enum": ["basic", "advanced"],
        "description": "提取深度。'advanced' 会尝试提取表格和更多细节。"
    },
    "include_images": {"type": "boolean", "description": "是否提取网页中的图片链接。"}
}

TAVILY_CRAWL_SCHEMA = {
    "url": {"type": "string", "description": "开始爬取的起始 URL。"},
    "max_depth": {"type": "number", "description": "爬取的最大深度。"},
    "max_breadth": {"type": "number", "description": "每层页面跟随的最大链接数。"},
    "limit": {"type": "number", "description": "停止前处理的总链接数限制。"},
    "instructions": {"type": "string", "description": "给爬虫的自然语言指令，用于引导其关注特定内容。"},
    "select_paths": {"type": "array", "items": {"type": "string"}, "description": "包含的路径模式（Regex）。"},
    "exclude_paths": {"type": "array", "items": {"type": "string"}, "description": "排除的路径模式（Regex）。"},
    "include_images": {"type": "boolean", "description": "是否在爬取结果中包含图片。"},
    "allow_external": {"type": "boolean", "description": "是否允许爬取外部域名的链接。"}
}

TAVILY_MAP_SCHEMA = {
    "url": {"type": "string", "description": "开始映射的起始 URL。"},
    "max_depth": {"type": "number", "description": "映射的最大深度。"},
    "limit": {"type": "number", "description": "发现的 URL 数量限制。"},
    "select_paths": {"type": "array", "items": {"type": "string"}, "description": "要包含的路径过滤。"}
}
